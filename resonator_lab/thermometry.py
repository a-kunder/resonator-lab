"""Read-only Lake Shore thermometry, derived from the supplied Snoopy readout.

This module never writes heater, setpoint, scanner, excitation, or curve settings.
It deliberately does not assume Falkor has Snoopy's wiring or database.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import List
import math
import threading
from datetime import datetime, timezone


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def channel_id(value):
    text = str(value).strip().upper()
    if text == 'A':
        return 'A'
    if text.isdigit() and 1 <= int(text) <= 16:
        return str(int(text))
    raise ValueError('Thermometer channels must be 1–16 or A.')


@dataclass
class ThermometrySettings:
    backend: str = 'none'
    connection: str = 'serial'
    com_port: str = ''
    ip_address: str = ''
    tcp_port: int = 7777
    baud_rate: int = 57600
    io_timeout_s: float = 2.0
    primary_channel: str = ''
    channels: List[str] = field(default_factory=list)
    log_path: str = ''
    log_channel: str = '6'
    log_max_age_s: float = 180.0
    log_follow_daily: bool = True

    def validate(self):
        if self.backend not in ('none', 'lakeshore372', 'simulator', 'lsci_log'):
            raise ValueError('Unknown thermometry backend.')
        if self.backend == 'lsci_log':
            if not self.log_path.strip():
                raise ValueError('Choose the CoolDownData folder or a CH6 T log file.')
            channel_id(self.log_channel)
            if not isinstance(self.log_follow_daily, bool):
                raise ValueError('log_follow_daily must be true or false.')
            if not math.isfinite(self.log_max_age_s) or self.log_max_age_s <= 0:
                raise ValueError('Maximum log age must be finite and positive.')
            return
        if self.backend in ('none', 'simulator'):
            return
        if self.connection not in ('serial', 'tcp'):
            raise ValueError('Thermometry connection must be serial or tcp.')
        if self.connection == 'serial' and not self.com_port.strip():
            raise ValueError('Enter Falkor’s Lake Shore COM port.')
        if self.connection == 'tcp' and not self.ip_address.strip():
            raise ValueError('Enter the Lake Shore instrument IP address.')
        if not isinstance(self.tcp_port, int) or not 1 <= self.tcp_port <= 65535:
            raise ValueError('TCP port must be an integer from 1 to 65535.')
        if not isinstance(self.baud_rate, int) or self.baud_rate <= 0:
            raise ValueError('Baud rate must be a positive integer.')
        if not math.isfinite(self.io_timeout_s) or self.io_timeout_s <= 0:
            raise ValueError('Thermometry I/O timeout must be finite and positive.')
        primary = channel_id(self.primary_channel)
        channels = [channel_id(c) for c in self.channels]
        if not channels or primary not in channels:
            raise ValueError('Include the primary thermometer in the logged channel list.')
        if len(channels) != len(set(channels)):
            raise ValueError('Thermometer channel list contains duplicates.')

    def to_dict(self):
        return asdict(self)


class TemperatureReader(ABC):
    @abstractmethod
    def read_snapshot(self):
        """Return JSON-compatible per-channel readings, timestamps and primary_kelvin."""

    @abstractmethod
    def close(self):
        pass


class LakeShore372Reader(TemperatureReader):
    def __init__(self, settings, sensor=None):
        settings.validate()
        if settings.backend != 'lakeshore372':
            raise ValueError('LakeShore372Reader requires the lakeshore372 backend.')
        self.settings = settings
        self.lock = threading.RLock()
        self.sensor = sensor
        self.closed = False
        if self.sensor is None:
            try:
                from lakeshore import Model372
            except ImportError as exc:
                raise RuntimeError('Install the optional Lake Shore driver: python -m pip install "resonator-lab[temperature]"') from exc
            kwargs = {'timeout': settings.io_timeout_s}
            if settings.connection == 'serial':
                kwargs['com_port'] = settings.com_port
            else:
                kwargs.update(ip_address=settings.ip_address, tcp_port=settings.tcp_port)
            self.sensor = Model372(settings.baud_rate, **kwargs)

    def read_snapshot(self):
        with self.lock:
            return self._read_snapshot_locked()

    def _read_snapshot_locked(self):
        snapshot = {'source': 'lakeshore372', 'started_utc': utc_now(),
                    'primary_channel': channel_id(self.settings.primary_channel),
                    'channels': {}, 'connection': self.settings.to_dict(),
                    'freshness': 'Bridge readout; sensor conversion age is not provided or verified.',
                    'simulated': False}
        for name in self.settings.channels:
            name = channel_id(name)
            started = utc_now()
            reading = self.sensor.get_all_input_readings('A' if name == 'A' else int(name))
            kelvin = float(reading['kelvin'])
            if not math.isfinite(kelvin) or kelvin <= 0:
                raise ValueError('Invalid temperature from Lake Shore channel ' + name)
            if hasattr(self.sensor, 'get_reading_status'):
                flags = self.sensor.get_reading_status('A' if name == 'A' else int(name))
                if any(bool(v) for v in flags.values()):
                    raise ValueError('Lake Shore channel {} has measurement flags: {}'.format(name, flags))
            record = {'read_started_utc': started, 'read_ended_utc': utc_now(), 'kelvin': kelvin,
                      'sensor_conversion_time_utc': None}
            for source, target in [('resistance', 'resistance_ohm'), ('power', 'excitation_power_w'), ('quadrature', 'quadrature_ohm')]:
                value = reading.get(source)
                record[target] = float(value) if value is not None and math.isfinite(float(value)) else None
            snapshot['channels'][name] = record
        # Observe scanning without changing it. Reading stored channels does not force a fresh conversion.
        try:
            active, enabled = self.sensor.get_scanner_status()
            snapshot['scanner'] = {'active_channel': str(active), 'auto_scan': bool(enabled)}
        except Exception as exc:
            snapshot['scanner'] = None
            snapshot['scanner_query_error'] = str(exc)
        snapshot['primary_kelvin'] = snapshot['channels'][snapshot['primary_channel']]['kelvin']
        snapshot['ended_utc'] = utc_now()
        return snapshot

    def close(self):
        if not self.closed:
            self.closed = True
            if self.settings.connection == 'serial':
                self.sensor.disconnect_usb()
            else:
                self.sensor.disconnect_tcp()


# Full-scale sample-heater currents, Model 372 range codes. No range is selected by default.
SAMPLE_HEATER_CURRENTS_A = {1: 31.6e-6, 2: 100e-6, 3: 316e-6, 4: 1e-3,
                            5: 3.16e-3, 6: 10e-3, 7: 31.6e-3, 8: 100e-3}


@dataclass
class PIDSettings:
    heater_output: object = None
    heater_range: object = None
    heater_resistance_ohm: object = None
    max_heater_power_w: object = None
    base_temperature_k: float = 0.020
    max_temperature_k: float = 0.800
    dwell_s: float = 600.0
    poll_s: float = 5.0
    cooldown_timeout_s: float = 7200.0
    gain: object = None
    integral: object = None
    derivative: object = None

    def validate(self, hardware=False):
        for name in ('base_temperature_k', 'max_temperature_k', 'dwell_s', 'poll_s', 'cooldown_timeout_s'):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(name + ' must be finite and positive.')
        if self.base_temperature_k >= self.max_temperature_k:
            raise ValueError('Base temperature must be below the temperature ceiling.')
        if self.dwell_s < self.poll_s:
            raise ValueError('Stability dwell must be at least one polling interval.')
        values = (self.gain, self.integral, self.derivative)
        if any(x is not None for x in values):
            if any(x is None or not math.isfinite(x) or x < 0 for x in values) or self.gain <= 0:
                raise ValueError('Supply all P/I/D values (P > 0, I/D >= 0), or leave all blank to use existing tuning.')
        if hardware:
            if self.heater_output != 0:
                raise ValueError('Select the confirmed sample-heater output 0. Other outputs are not supported by this adapter.')
            if isinstance(self.heater_range, bool) or self.heater_range not in SAMPLE_HEATER_CURRENTS_A:
                raise ValueError('Select a confirmed sample-heater current range (code 1–8).')
            for name in ('heater_resistance_ohm', 'max_heater_power_w'):
                value = getattr(self, name)
                if value is None or not math.isfinite(value) or value <= 0:
                    raise ValueError('Enter the confirmed ' + name + '; Snoopy values are not assumed.')
            full_scale_power = SAMPLE_HEATER_CURRENTS_A[self.heater_range] ** 2 * self.heater_resistance_ohm
            if full_scale_power > self.max_heater_power_w:
                raise ValueError('Selected range permits {:.6g} W, above the entered heater-power limit.'.format(full_scale_power))
