"""Unit-explicit, serializable experiment configuration and data."""
from dataclasses import dataclass, field, asdict
from typing import List, Optional
import math
import re
from decimal import Decimal, ROUND_FLOOR
import numpy as np
from .thermometry import ThermometrySettings, PIDSettings


def sequence(start, stop, count):
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError('Sequence count must be a positive integer.')
    if not all(math.isfinite(x) for x in (start, stop)):
        raise ValueError('Sequence endpoints must be finite.')
    if count == 1 and start != stop:
        raise ValueError('For one value, start and stop must match.')
    return np.linspace(start, stop, count).tolist()


def stepped_sequence(start, stop, step, max_values=100000):
    """Positive step magnitude, either direction; stop appears only if on the grid.

    Decimal arithmetic avoids losing an aligned endpoint to binary rounding.
    The returned explicit list is the authoritative acquisition schedule.
    """
    if not all(math.isfinite(x) for x in (start, stop, step)) or step <= 0:
        raise ValueError('Start/stop must be finite; step size must be finite and positive.')
    first, last, increment = (Decimal(str(x)) for x in (start, stop, step))
    intervals = int((abs(last - first) / increment).to_integral_value(rounding=ROUND_FLOOR))
    if intervals + 1 > max_values:
        raise ValueError('Temperature list exceeds {} entries; increase the step size.'.format(max_values))
    direction = 1 if last >= first else -1
    return [float(first + direction * i * increment) for i in range(intervals + 1)]


@dataclass
class SweepSettings:
    start_hz: float = 5.9297e9
    stop_hz: float = 5.9547e9
    points: int = 1001
    if_bandwidth_hz: float = 1000.0
    averages: int = 7
    s_parameter: str = 'S43'
    timeout_s: float = 1800.0
    settle_s: float = 0.2

    def validate(self):
        for name in ('start_hz', 'stop_hz', 'if_bandwidth_hz', 'timeout_s'):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(name + ' must be finite and positive.')
        if self.start_hz >= self.stop_hz:
            raise ValueError('Start frequency must be below stop frequency.')
        for name, minimum in (('points', 2), ('averages', 1)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError('{} must be an integer >= {}.'.format(name, minimum))
        if not re.fullmatch(r'S[1-4][1-4]', self.s_parameter):
            raise ValueError('Choose an S-parameter from S11 through S44.')
        if not math.isfinite(self.settle_s) or self.settle_s < 0:
            raise ValueError('Settling time must be finite and nonnegative.')


@dataclass
class ResonatorConfig:
    name: str
    sweep: SweepSettings = field(default_factory=SweepSettings)

    def validate(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError('Every resonator needs a nonempty name.')
        self.sweep.validate()

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        result = cls(name=data['name'], sweep=SweepSettings(**data.get('sweep', {})))
        result.validate()
        return result


@dataclass
class ExperimentConfig:
    resonator: str = 'Res1.1'  # legacy single-resonator API
    sweep: SweepSettings = field(default_factory=SweepSettings)
    powers_dbm: List[float] = field(default_factory=lambda: [-45., -40., -35.])
    temperatures_k: List[Optional[float]] = field(default_factory=lambda: [0.025])
    temperature_mode: str = 'fixed'  # fixed label, or controlled via injected controller
    temperature_tolerance_k: float = 0.002
    temperature_timeout_s: float = 1800.0
    input_loss_db: Optional[float] = None
    notes: str = ''
    thermometry: ThermometrySettings = field(default_factory=ThermometrySettings)
    pid: PIDSettings = field(default_factory=PIDSettings)
    batch_name: str = 'Resonator batch'
    resonators: List[ResonatorConfig] = field(default_factory=list)

    def validate(self):
        for resonator in self.resonator_plan:
            resonator.validate()
        names = [r.name.strip().casefold() for r in self.resonator_plan]
        if len(names) != len(set(names)):
            raise ValueError('Resonator names must be unique within the batch.')
        if self.resonators and not self.batch_name.strip():
            raise ValueError('Enter a batch name.')
        if self.thermometry.backend == 'lakeshore372':
            raise ValueError('Direct Lake Shore access is disabled. LSCI Reader owns the controller; logger integration is deferred.')
        self.thermometry.validate()
        if self.thermometry.backend == 'lsci_log' and self.temperature_mode != 'fixed':
            raise ValueError('LSCI logs are read-only; automatic temperature control is not available.')
        self.pid.validate(hardware=self.temperature_mode == 'controlled' and self.thermometry.backend == 'lakeshore372')
        if not self.resonators and not self.resonator.strip():
            raise ValueError('Enter a resonator name.')
        if not self.powers_dbm or not all(math.isfinite(x) for x in self.powers_dbm):
            raise ValueError('Provide at least one finite VNA power in dBm.')
        unknown_base = self.temperature_mode == 'fixed' and self.temperatures_k == [None]
        if not unknown_base and (not self.temperatures_k or not all(x is not None and math.isfinite(x) and x > 0 for x in self.temperatures_k)):
            raise ValueError('Temperatures must be finite and above 0 K.')
        if self.temperature_mode not in ('fixed', 'controlled'):
            raise ValueError('Temperature mode must be fixed or controlled.')
        if self.temperature_mode == 'fixed' and len(self.temperatures_k) != 1:
            raise ValueError('Fixed temperature mode requires exactly one temperature label.')
        for name in ('temperature_tolerance_k', 'temperature_timeout_s'):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(name + ' must be finite and positive.')
        if self.temperature_mode == 'controlled':
            if any(x < self.pid.base_temperature_k or x > self.pid.max_temperature_k for x in self.temperatures_k):
                raise ValueError('Setpoints must lie between the configured base and ceiling temperatures.')
            if self.temperature_timeout_s < self.pid.dwell_s:
                raise ValueError('Stabilization timeout must be at least the stability dwell.')
        if self.input_loss_db is not None and (not math.isfinite(self.input_loss_db) or self.input_loss_db < 0):
            raise ValueError('Input loss must be a finite, nonnegative value in dB.')

    @property
    def resonator_plan(self):
        """Order at one temperature. Legacy configs become a one-entry plan."""
        return self.resonators or [ResonatorConfig(self.resonator, self.sweep)]

    @property
    def total_traces(self):
        return len(self.temperatures_k) * len(self.resonator_plan) * len(self.powers_dbm)

    @property
    def run_name(self):
        return self.batch_name if self.resonators else self.resonator

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        data['sweep'] = SweepSettings(**data.get('sweep', {}))
        data['resonators'] = [ResonatorConfig.from_dict(r) for r in data.get('resonators', [])]
        data['thermometry'] = ThermometrySettings(**data.get('thermometry', {}))
        data['pid'] = PIDSettings(**data.get('pid', {}))
        config = cls(**data)
        config.validate()
        return config


@dataclass
class Trace:
    frequency_hz: np.ndarray
    s_complex: np.ndarray
    metadata: dict

    def validate(self):
        if self.frequency_hz.ndim != 1 or self.s_complex.shape != self.frequency_hz.shape:
            raise ValueError('Frequency and complex trace lengths do not match.')
        if len(self.frequency_hz) < 2 or not np.all(np.diff(self.frequency_hz) > 0):
            raise ValueError('Frequency axis must be strictly increasing.')
        if not np.all(np.isfinite(self.frequency_hz)) or not np.all(np.isfinite(self.s_complex)):
            raise ValueError('Instrument returned nonfinite trace data.')

    @property
    def magnitude_db(self):
        return 20 * np.log10(np.maximum(np.abs(self.s_complex), np.finfo(float).tiny))

    @property
    def phase_rad(self):
        return np.unwrap(np.angle(self.s_complex))
