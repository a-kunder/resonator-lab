"""Siglent adapter derived from the supplied siglentSNA5014a wrapper.

Only instrument communication lives here; no plotting or file I/O.
"""
from abc import ABC, abstractmethod
from dataclasses import asdict
import time
import numpy as np
from .model import Trace

DEFAULT_ADDRESS = ''  # Choose this installation's USB/TCPIP VISA address explicitly.


class Cancelled(Exception):
    pass


def check_cancel(cancel):
    if cancel.is_set():
        raise Cancelled('Stop requested.')


class VNA(ABC):
    @abstractmethod
    def configure(self, settings):
        """Return effective settings read back from instrument."""

    @abstractmethod
    def set_power(self, dbm):
        """Return actual source power in dBm."""

    @abstractmethod
    def set_output(self, enabled):
        pass

    @abstractmethod
    def acquire(self, cancel):
        """Return one completed Trace without starting another acquisition."""

    @abstractmethod
    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        try:
            self.set_output(False)
        finally:
            self.close()


class SiglentVNA(VNA):
    """Channel 1, linear frequency sweep; preserves loaded calibration.

    A grouped acquisition collects exactly the configured averaging count.
    *OPC? blocks until completion. Stop is cooperative between acquisitions;
    a blocked acquisition is bounded by timeout_s, not interrupted from another thread.
    """
    def __init__(self, address=DEFAULT_ADDRESS, resource_manager=None):
        if address.strip().upper().startswith(('ASRL', 'COM')):
            raise ValueError('Serial resources are not supported for this VNA. Select its USB/TCPIP address; LSCI Reader retains COM3.')
        self.rm = resource_manager
        self.owns_rm = resource_manager is None
        self.dev = None
        try:
            if self.rm is None:
                import pyvisa
                self.rm = pyvisa.ResourceManager()
            self.dev = self.rm.open_resource(address)
            self.dev.timeout = 5000
            self.dev.chunk_size = 1024 * 1024
            self.identity = self.dev.query('*IDN?').strip()
            if 'SIGLENT' not in self.identity.upper() or 'SNA' not in self.identity.upper():
                raise RuntimeError('Expected a Siglent SNA VNA; got ' + self.identity)
            self.address = address
        except BaseException:
            self.close()
            raise

    def write(self, command):
        self.dev.write(command)

    def query(self, command):
        return self.dev.query(command).strip()

    def check_errors(self):
        errors = []
        for _ in range(20):
            reply = self.query(':SYST:ERR?')
            if int(reply.split(',')[0]) == 0:
                break
            errors.append(reply)
        if errors:
            raise RuntimeError('VNA SCPI error: ' + '; '.join(errors))

    def configure(self, settings):
        settings.validate()
        self.settings = settings
        self.set_output(False)
        # Require the operator to resolve any pre-existing errors; do not hide them.
        self.check_errors()
        for command in (
            ':SENS1:SWE:MODE HOLD',
            ':SENS1:SWE:TYPE LIN',
            # Expand first so moving between disjoint windows cannot cross the old endpoint.
            ':SENS1:FREQ:STOP {}'.format(max(settings.stop_hz, float(self.query(':SENS1:FREQ:STOP?')))),
            ':SENS1:FREQ:STAR {}'.format(settings.start_hz),
            ':SENS1:FREQ:STOP {}'.format(settings.stop_hz),
            ':SENS1:SWE:POIN {}'.format(settings.points),
            ':SENS1:BAND {}'.format(settings.if_bandwidth_hz),
            ':SENS1:AVER:COUN {}'.format(settings.averages),
            ':SENS1:AVER {}'.format(int(settings.averages > 1)),
            ':TRIG:SEQ:SOUR BUS',
            ':FORM:DATA ASC',
        ):
            self.write(command)
        self.check_errors()
        self.effective = {
            'start_hz': float(self.query(':SENS1:FREQ:STAR?')),
            'stop_hz': float(self.query(':SENS1:FREQ:STOP?')),
            'points': int(float(self.query(':SENS1:SWE:POIN?'))),
            'if_bandwidth_hz': float(self.query(':SENS1:BAND?')),
            'averages': int(float(self.query(':SENS1:AVER:COUN?'))),
            'averaging_enabled': bool(int(self.query(':SENS1:AVER?'))),
            's_parameter': settings.s_parameter,
            'frequency_axis': 'linear axis reconstructed from instrument readbacks',
        }
        if self.effective['averages'] != settings.averages or self.effective['averaging_enabled'] != (settings.averages > 1):
            raise RuntimeError('VNA did not accept the requested averaging settings.')
        return dict(self.effective)

    def set_power(self, dbm):
        self.write(':SOUR1:POW {}'.format(dbm))
        self.check_errors()
        actual = float(self.query(':SOUR1:POW?'))
        if not np.isfinite(actual) or abs(actual - dbm) > 0.05:
            raise RuntimeError('VNA power readback {} dBm differs from requested {} dBm.'.format(actual, dbm))
        return actual

    def set_output(self, enabled):
        self.write(':OUTP {}'.format(int(enabled)))
        self.check_errors()
        if bool(int(self.query(':OUTP?'))) != bool(enabled):
            raise RuntimeError('VNA RF output did not reach requested state.')

    def acquire(self, cancel):
        check_cancel(cancel)
        old_timeout = self.dev.timeout
        self.dev.timeout = int(self.settings.timeout_s * 1000)
        try:
            # RAWD? explicitly addresses Sij; it does not require a display trace named Sij.
            # Stay in HOLD after completion, so continuous sweeps cannot overwrite data.
            self.write(':SENS1:AVER:CLE')
            self.write(':SENS1:SWE:GRO:COUN {}'.format(self.effective['averages']))
            self.write(':SENS1:SWE:MODE GRO')
            self.write(':TRIG:SEQ:SING')
            if int(self.query('*OPC?')) != 1:
                raise RuntimeError('VNA did not confirm acquisition completion.')
            self.write(':SENS1:SWE:MODE HOLD')
            self.check_errors()
            raw = np.asarray(self.dev.query_ascii_values(':SENS1:DATA:RAWD? ' + self.settings.s_parameter), dtype=float)
            self.check_errors()
            count = self.effective['points']
            if raw.ndim != 1 or len(raw) != 2 * count:
                raise ValueError('Expected {} real/imaginary pairs; received {} numbers.'.format(count, raw.size))
            trace = Trace(np.linspace(self.effective['start_hz'], self.effective['stop_hz'], count),
                          raw[::2] + 1j * raw[1::2], {'readout_command': ':SENS1:DATA:RAWD? ' + self.settings.s_parameter})
            trace.validate()
            return trace
        finally:
            self.dev.timeout = old_timeout

    def close(self):
        try:
            if self.dev is not None:
                self.dev.close()
        finally:
            self.dev = None
            if self.owns_rm and self.rm is not None:
                self.rm.close()
                self.rm = None


class SimulatedVNA(VNA):
    identity = 'SIMULATOR,ResonatorLab,0,1.0'
    address = 'simulation'

    def __init__(self, seed=1234):
        self.rng = np.random.RandomState(seed)
        self.temperature_k = 0.025
        self.power = -45.0
        self.output = False
        self.closed = False

    def configure(self, settings):
        settings.validate()
        self.settings = settings
        return dict(asdict(settings), frequency_axis='simulated linear axis')

    def set_power(self, dbm):
        self.power = dbm
        return dbm

    def set_output(self, enabled):
        self.output = enabled

    def acquire(self, cancel):
        if not self.output:
            raise RuntimeError('Simulated RF output is off.')
        if cancel.wait(0.15):
            raise Cancelled('Stop requested.')
        s = self.settings
        f = np.linspace(s.start_hz, s.stop_hz, s.points)
        center = (s.start_hz + s.stop_hz) / 2
        span = s.stop_hz - s.start_hz
        shift = span * (0.015 * np.tanh((self.power + 30) / 15) + 0.02 * self.temperature_k)
        linewidth = span / 35 * (1 + max(self.power + 30, 0) / 50 + self.temperature_k)
        z = (1 - 0.8 / (1 + 2j * (f - center - shift) / linewidth)) * np.exp(-2j * np.pi * (f - center) * 15e-9)
        noise = 0.003 * np.sqrt(s.if_bandwidth_hz / 1000 / s.averages) * 10 ** ((-35 - self.power) / 40)
        z += noise * (self.rng.randn(s.points) + 1j * self.rng.randn(s.points))
        trace = Trace(f, z, {})
        trace.validate()
        return trace

    def close(self):
        self.closed = True


class TemperatureController(ABC):
    """Implement this interface on the fridge computer, independently of the VNA.

    wait_until_stable must enforce a dwell/stability criterion, honor cancellation,
    and enforce its timeout. Return a measured temperature, never the setpoint.
    The adapter owns heater limits and its documented shutdown behavior.
    """
    @abstractmethod
    def set_target(self, temperature_k):
        pass

    @abstractmethod
    def wait_until_stable(self, tolerance_k, timeout_s, cancel):
        pass

    @abstractmethod
    def read_temperature(self):
        pass

    @abstractmethod
    def close(self):
        pass


class SimulatedTemperatureController(TemperatureController):
    def __init__(self, vna):
        if not isinstance(vna, SimulatedVNA):
            raise ValueError('Simulated temperature control requires a simulated VNA.')
        self.vna = vna

    def set_target(self, temperature_k):
        self.vna.temperature_k = temperature_k

    def wait_until_stable(self, tolerance_k, timeout_s, cancel):
        if cancel.wait(min(0.2, timeout_s)):
            raise Cancelled('Stop requested.')
        return self.read_temperature()

    def read_temperature(self):
        return self.vna.temperature_k

    def close(self):
        pass
