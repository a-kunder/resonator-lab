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


class IncompleteLogError(ValueError):
    """The writer has not finished its first complete record yet."""


class LSCILogReader(TemperatureReader):
    def __init__(self, settings, now=None):
        settings.validate()
        if settings.backend != 'lsci_log':
            raise ValueError('LSCILogReader requires the lsci_log backend.')
        self.settings = settings
        self.now = now or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _filename_date(text):
        normalized = text.replace('_', '-')
        return datetime.strptime(normalized, '%Y-%m-%d' if len(normalized) == 10 else '%y-%m-%d')

    @classmethod
    def _is_daily_folder(cls, path):
        if not re.fullmatch(r'(?:\d{4}|\d{2})[-_]\d{2}[-_]\d{2}', path.name):
            return False
        try:
            cls._filename_date(path.name)
            return True
        except ValueError:
            return False

    def _select_record(self):
        path = Path(self.settings.log_path).expanduser()
        channel = channel_id(self.settings.log_channel)
        # LSCI installations differ in spacing: CH6 T26-11-17 and CH6 T 26-11-17.
        pattern = re.compile(r'CH\s*' + re.escape(channel) +
                             r'[ _-]*T[ _-]*((?:\d{4}|\d{2})[-_]\d{2}[-_]\d{2})(?:\.(?:txt|csv|log))?$', re.IGNORECASE)
        follow = self.settings.log_follow_daily
        file_match = pattern.fullmatch(path.name)
        if path.is_file():
            if not file_match:
                raise ValueError('Select a CH{} T temperature file, not R/P or pressure logs.'.format(channel))
            root = path.parent
            if not follow:
                return path, self._latest_line(path), root
        elif file_match and not path.exists():
            # A saved profile may name yesterday's file, already moved/deleted.
            if not follow:
                raise FileNotFoundError('Temperature log file is unavailable: ' + str(path))
            root = path.parent
        else:
            root = path
        if follow and self._is_daily_folder(root):
            root = root.parent
        if not root.is_dir():
            raise FileNotFoundError('Temperature log path is unavailable: ' + str(root))
        candidates = []
        paths = root.rglob('*') if follow else root.glob('*')
        for item in paths:
            match = pattern.fullmatch(item.name)
            if match and item.is_file():
                try:
                    date = self._filename_date(match.group(1))
                except ValueError:
                    continue
                candidates.append((date, item))
        if not candidates:
            raise FileNotFoundError('No CH{} T temperature logs found under {}. Expected e.g. CH{} T26-11-17.txt or CH{} T 26-11-17.txt.'.format(channel, root, channel, channel))
        incomplete = None
        for date in sorted({date for date, _ in candidates}, reverse=True):
            matches = [item for stamp, item in candidates if stamp == date]
            if len(matches) != 1:
                raise ValueError('Multiple temperature files for the newest usable date; select the intended file/folder and set Follow new daily folders to No.')
            selected = matches[0]
            try:
                return selected, self._latest_line(selected), root
            except IncompleteLogError as exc:
                # At midnight the new file can exist before the first full sample.
                # Previous-day data must still pass the normal timestamp age check.
                incomplete = exc
        raise incomplete

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
            raise IncompleteLogError('Temperature log has no complete newline-terminated record: ' + str(path))
        return lines[-1]

    def read_snapshot(self):
        started = utc_now()
        path, line, search_root = self._select_record()
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
                    log_search_root=str(search_root.resolve()), log_follow_daily=self.settings.log_follow_daily,
                    timestamp_basis='Log uses this PC local timezone; date format dd-mm-yy.',
                    channels={channel: record}, **record)

    def close(self):
        pass  # Each snapshot opens and immediately closes a read-only file handle.
