"""Read the existing LSCI Reader daily temperature logs; never connect to instruments.

Observed format: 16-11-26,00:30:08,1.432770E-2 (day-month-year, local time, K).
A folder is re-scanned on every read to follow daily file rollover.
"""
import csv
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from .thermometry import TemperatureReader, channel_id, utc_now


class LSCILogReader(TemperatureReader):
    def __init__(self, settings, now=None):
        settings.validate()
        if settings.backend != 'lsci_log':
            raise ValueError('LSCILogReader requires the lsci_log backend.')
        self.settings = settings
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _select_file(self):
        path = Path(self.settings.log_path).expanduser()
        channel = channel_id(self.settings.log_channel)
        pattern = re.compile(r'CH' + re.escape(channel) + r' T (\d{2}-\d{2}-\d{2})(?:\.txt)?$', re.IGNORECASE)
        if path.is_file():
            if not pattern.fullmatch(path.name):
                raise ValueError('Select a CH{} T yy-mm-dd[.txt] temperature file, not R/P or pressure logs.'.format(channel))
            return path
        if not path.is_dir():
            raise FileNotFoundError('Temperature log path is unavailable: ' + str(path))
        candidates = []
        # CoolDownData root or one daily folder, as shown in the supplied photo.
        for item in list(path.glob('*')) + list(path.glob('*/*')):
            match = pattern.fullmatch(item.name)
            if match and item.is_file():
                try:
                    date = datetime.strptime(match.group(1), '%y-%m-%d')
                except ValueError:
                    continue
                candidates.append((date, item))
        if not candidates:
            raise FileNotFoundError('No CH{} T yy-mm-dd[.txt] logs found in {}'.format(channel, path))
        newest = max(date for date, _ in candidates)
        matches = [item for date, item in candidates if date == newest]
        if len(matches) != 1:
            raise ValueError('Multiple temperature files for the newest date; select the intended daily folder or file.')
        return matches[0]

    @staticmethod
    def _latest_line(path):
        # Bounded tail read. Discard any unfinished final record while LSCI is appending.
        with path.open('rb') as stream:
            prefix = stream.read(3)
            stream.seek(0, 2)
            size = stream.tell()
            start = max(0, size - 65536)
            if prefix[:2] in (b'\xff\xfe', b'\xfe\xff'):
                start -= start % 2
                encoding = 'utf-16-le' if prefix[:2] == b'\xff\xfe' else 'utf-16-be'
            else:
                encoding = 'utf-8-sig'
            stream.seek(start)
            raw = stream.read(65536)
        text = raw.decode(encoding).lstrip('\ufeff')
        lines = text.split('\n')
        if start:
            lines = lines[1:]
        lines = [line.strip() for line in lines[:-1] if line.strip()]
        if not lines:
            raise ValueError('Temperature log has no complete newline-terminated record: ' + str(path))
        return lines[-1]

    def read_snapshot(self):
        started = utc_now()
        path = self._select_file()
        line = self._latest_line(path)
        try:
            fields = next(csv.reader([line]))
            if len(fields) != 3:
                raise ValueError('Expected date,time,kelvin')
            local = datetime.strptime(fields[0].strip() + ',' + fields[1].strip(), '%d-%m-%y,%H:%M:%S')
            # astimezone() on a naive datetime uses this PC's local timezone for that date.
            source = local.astimezone().astimezone(timezone.utc)
            kelvin = float(fields[2])
            if not math.isfinite(kelvin) or kelvin <= 0:
                raise ValueError('Temperature must be finite and positive')
        except (ValueError, OverflowError) as exc:
            raise ValueError('Invalid latest temperature record in {}: {!r}: {}'.format(path, line, exc)) from exc
        observed = self.now()
        age = (observed - source).total_seconds()
        if age < -5:
            raise ValueError('Temperature log timestamp is in the future; check PC clock/timezone and log date.')
        if age > self.settings.log_max_age_s:
            raise ValueError('Temperature log is stale ({:.0f} s old; limit {:.0f} s): {}'.format(age, self.settings.log_max_age_s, path))
        channel = channel_id(self.settings.log_channel)
        record = {'kelvin': kelvin, 'read_ended_utc': observed.isoformat(),
                  'source_timestamp_utc': source.isoformat(), 'source_timestamp_local': local.isoformat(),
                  'age_s': age, 'log_file': str(path.resolve()), 'source_line': line}
        return dict(source='lsci_log', primary_channel=channel, primary_kelvin=kelvin,
                    started_utc=started, ended_utc=observed.isoformat(), simulated=False,
                    timestamp_basis='Log uses this PC local timezone; date format dd-mm-yy.',
                    channels={channel: record}, **record)

    def close(self):
        pass  # Each snapshot opens and immediately closes a read-only file handle.
