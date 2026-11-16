"""Native Model 372 PID supervision; no Python heater-power PID is used.

Only the explicitly configured sample heater (output 0) is controlled. The
still/warmup outputs, scanner, thermometer calibration and excitation are not set.
"""
import copy
import math
import threading
import time
from collections import deque
from dataclasses import replace
from enum import IntEnum
from .instruments import Cancelled, check_cancel, SimulatedVNA
from .thermometry import LakeShore372Reader, ThermometrySettings, channel_id
from .storage import utc_now


def wait_for_stability(read_kelvin, target, tolerance, dwell_s, timeout_s, poll_s,
                       cancel, on_progress=None, clock=time.monotonic, wait=None,
                       cooling=False, heartbeat=None):
    """Require every sampled value in band for an uninterrupted dwell, >=3 samples.

    A bad/missing reading is an error, not evidence of stability. cooling=True
    accepts values <= base+tolerance, since the heater is OFF during cooldown.
    clock/wait injection makes time-based tests independent of wall time.
    """
    if any(not math.isfinite(x) or x <= 0 for x in (target, tolerance, dwell_s, timeout_s, poll_s)):
        raise ValueError('Stability parameters must be finite and positive.')
    if timeout_s < dwell_s or poll_s > dwell_s:
        raise ValueError('Require poll interval <= dwell <= timeout.')
    wait = wait or cancel.wait
    started = clock(); stable_since = None; count = 0
    while True:
        check_cancel(cancel)
        if heartbeat:
            heartbeat()
        if clock() - started > timeout_s:
            raise TimeoutError('Temperature did not stabilize before timeout.')
        value = float(read_kelvin())
        now = clock()
        if not math.isfinite(value) or value <= 0:
            raise ValueError('Invalid thermometer reading during stabilization.')
        if now - started > timeout_s:
            raise TimeoutError('Temperature read completed after stabilization timeout.')
        in_band = value <= target + tolerance if cooling else abs(value - target) <= tolerance
        if in_band:
            stable_since = now if stable_since is None else stable_since
            count += 1
        else:
            stable_since, count = None, 0
        stable_s = 0.0 if stable_since is None else now - stable_since
        if on_progress:
            on_progress({'kelvin': value, 'target_k': target, 'stable_s': stable_s,
                         'required_s': dwell_s, 'elapsed_s': now - started,
                         'samples_in_band': count, 'cooling': cooling})
        if stable_s >= dwell_s and count >= 3:
            return value
        remaining = timeout_s - (now - started)
        if remaining <= 0:
            raise TimeoutError('Temperature did not stabilize before timeout.')
        if wait(min(poll_s, remaining)):
            raise Cancelled('Stop requested during temperature stabilization.')


class LakeShore372PID(LakeShore372Reader):
    def __init__(self, thermometry, pid, tolerance_k=0.002, sensor=None, time_scale=1.0):
        pid.validate(hardware=True)
        super().__init__(thermometry, sensor)
        self.pid_settings = pid
        self.tolerance_k = tolerance_k
        self.target = None
        self.control_owned = False
        self.monitor_stop = threading.Event()
        self.cancel_event = threading.Event()
        self.monitor_thread = None
        self.monitor_error = None
        self.samples = deque(maxlen=20000)
        self.stable_since = None
        self.stable_samples = 0
        self.sample_callback = lambda snapshot: None
        self.progress_callback = lambda progress: None
        self.time_scale = time_scale
        self.is_simulated = False
        self.shutdown_report = None
        try:
            self._validate_feedback()
            self.effective_pid = self.sensor.get_heater_pid(0)
            for key in ('gain', 'integral', 'derivative'):
                if not math.isfinite(float(self.effective_pid[key])) or float(self.effective_pid[key]) < 0:
                    raise ValueError('Invalid existing PID settings; configure tuning in the lab.')
            if float(self.effective_pid['gain']) <= 0 and pid.gain is None:
                raise ValueError('Existing proportional gain is zero. Provide tuned PID settings.')
        except BaseException:
            super().close()
            raise

    def _validate_feedback(self):
        settings = self.sensor.get_heater_output_settings(0)
        selected = getattr(settings.input_channel, 'value', settings.input_channel)
        if channel_id(selected) != channel_id(self.settings.primary_channel):
            raise ValueError('The sample-heater feedback input does not match the selected primary thermometer. Configure it in the lab first.')
        if channel_id(self.settings.primary_channel) != 'A':
            active, auto = self.sensor.get_scanner_status()
            if auto or channel_id(active) != channel_id(self.settings.primary_channel):
                raise ValueError('PID with a measurement channel requires the scanner held on that primary input. Configure scanning in the lab; this application does not change it.')
        return settings

    def _range(self, code):
        return self.sensor.SampleHeaterOutputRange(code)

    def set_target(self, temperature_k):
        cfg = self.pid_settings
        if not math.isfinite(temperature_k) or not cfg.base_temperature_k <= temperature_k <= cfg.max_temperature_k:
            raise ValueError('Setpoint is outside configured base/ceiling limits.')
        self.check_monitor()
        with self.lock:
            settings = self._validate_feedback()
            self.control_owned = True  # all subsequent partial failures must attempt shutdown
            self.sensor.set_heater_output_range(0, self._range(0))
            self.sensor.set_manual_output(0, 0.0)
            self.sensor.set_setpoint_kelvin(0, temperature_k)
            if cfg.gain is not None:
                self.sensor.set_heater_pid(0, cfg.gain, cfg.integral, cfg.derivative)
            self.effective_pid = self.sensor.get_heater_pid(0)
            if cfg.gain is not None:
                for key in ('gain', 'integral', 'derivative'):
                    if not math.isclose(float(self.effective_pid[key]), getattr(cfg, key), rel_tol=1e-5, abs_tol=1e-6):
                        raise RuntimeError('Lake Shore did not accept PID ' + key)
            settings = copy.copy(settings)
            settings.output_mode = self.sensor.OutputMode.CLOSED_LOOP
            self.sensor.configure_heater(0, settings)
            self.sensor.set_heater_output_range(0, self._range(cfg.heater_range))
            actual_range = self.sensor.get_heater_output_range(0)
            actual_range = getattr(actual_range, 'value', actual_range)
            if int(actual_range) != cfg.heater_range:
                raise RuntimeError('Lake Shore heater range readback mismatch.')
            mode = self.sensor.get_heater_output_settings(0).output_mode
            if mode != self.sensor.OutputMode.CLOSED_LOOP:
                raise RuntimeError('Lake Shore did not enter closed-loop PID mode.')
            if not math.isclose(float(self.sensor.get_setpoint_kelvin(0)), temperature_k, rel_tol=1e-6, abs_tol=1e-8):
                raise RuntimeError('Lake Shore setpoint readback mismatch.')
            self.target = temperature_k
            self.samples.clear()
            self.stable_since = None
            self.stable_samples = 0

    def read_snapshot(self):
        with self.lock:
            snapshot = super().read_snapshot()
            snapshot['simulated'] = self.is_simulated
            actual_range = self.sensor.get_heater_output_range(0)
            actual_range = int(getattr(actual_range, 'value', actual_range))
            actual_mode = self.sensor.get_heater_output_settings(0).output_mode
            if self.control_owned:
                self._validate_feedback()
                if actual_range != self.pid_settings.heater_range or actual_mode != self.sensor.OutputMode.CLOSED_LOOP:
                    raise RuntimeError('Heater range/mode changed while PID control was active.')
                if not math.isclose(float(self.sensor.get_setpoint_kelvin(0)), self.target, rel_tol=1e-6, abs_tol=1e-8):
                    raise RuntimeError('Temperature setpoint changed externally during the run.')
            snapshot['pid'] = {'target_k': self.target,
                               'heater_range_readback': actual_range,
                               'output_mode_readback': int(getattr(actual_mode, 'value', actual_mode)), 'heater_output': 0,
                               'configured_range': self.pid_settings.heater_range,
                               'effective_pid': dict(self.effective_pid),
                               'control_owned': self.control_owned}
            value = snapshot['primary_kelvin']
            now = time.monotonic()
            self.samples.append((now, value))
            if self.control_owned and self.target is not None and abs(value - self.target) <= self.tolerance_k:
                self.stable_since = now if self.stable_since is None else self.stable_since
                self.stable_samples += 1
            else:
                self.stable_since, self.stable_samples = None, 0
            snapshot['stability'] = {'stable_s': 0 if self.stable_since is None else (now - self.stable_since) * self.time_scale,
                                     'required_s': self.pid_settings.dwell_s, 'tolerance_k': self.tolerance_k,
                                     'samples_in_band': self.stable_samples}
            return snapshot

    def read_temperature(self):
        snapshot = self.read_snapshot()
        self.sample_callback(snapshot)
        return snapshot['primary_kelvin']

    def wait_until_stable(self, tolerance_k, timeout_s, cancel):
        return self.ensure_stable_before_trace(tolerance_k, timeout_s, cancel)

    def ensure_stable_before_trace(self, tolerance_k, timeout_s, cancel):
        if self.target is None or not self.control_owned:
            raise ValueError('Set an active PID target before waiting for stability.')
        if tolerance_k != self.tolerance_k:
            with self.lock:
                self.stable_since, self.stable_samples = None, 0
                self.tolerance_k = tolerance_k
        started = time.monotonic()
        while True:
            check_cancel(cancel)
            self.check_monitor()
            value = self.read_temperature()
            elapsed = (time.monotonic() - started) * self.time_scale
            with self.lock:
                stable_s = 0 if self.stable_since is None else (time.monotonic() - self.stable_since) * self.time_scale
                count = self.stable_samples
            self.progress_callback({'kelvin': value, 'target_k': self.target, 'stable_s': stable_s,
                                    'required_s': self.pid_settings.dwell_s, 'elapsed_s': elapsed,
                                    'samples_in_band': count, 'cooling': False})
            if elapsed > timeout_s:
                raise TimeoutError('Temperature did not stabilize before timeout.')
            if stable_s >= self.pid_settings.dwell_s and count >= 3:
                return value
            if cancel.wait(min(self.pid_settings.poll_s, timeout_s - elapsed) / self.time_scale):
                raise Cancelled('Stop requested during temperature stabilization.')

    def start_monitor(self, on_sample, on_progress):
        self.sample_callback, self.progress_callback = on_sample, on_progress
        self.monitor_stop.clear()
        def monitor():
            while not self.monitor_stop.is_set():
                try:
                    if self.cancel_event.is_set() and self.control_owned:
                        self.disable_heating()
                    snapshot = self.read_snapshot()
                    self.sample_callback(snapshot)
                except Exception as exc:
                    self.monitor_error = '{}: {}'.format(type(exc).__name__, exc)
                    if self.control_owned:
                        try:
                            self.disable_heating()
                        except Exception as shutdown_error:
                            self.monitor_error += '; heater shutdown: ' + str(shutdown_error)
                    self.progress_callback({'error': self.monitor_error})
                    return
                self.monitor_stop.wait(max(0.01, self.pid_settings.poll_s / self.time_scale))
        self.monitor_thread = threading.Thread(target=monitor, name='Lake Shore temperature logger', daemon=False)
        self.monitor_thread.start()

    def check_monitor(self):
        if self.monitor_error:
            raise RuntimeError('Temperature logger failed: ' + self.monitor_error)

    def acquisition_summary(self, started_monotonic, ended_monotonic, target=None):
        with self.lock:
            values = [value for stamp, value in self.samples if started_monotonic <= stamp <= ended_monotonic]
        target = self.target if target is None else target
        return {'target_k': target, 'sample_count_during_acquisition': len(values),
                'minimum_k': min(values) if values else None,
                'maximum_k': max(values) if values else None,
                'samples_within_tolerance': all(abs(value - target) <= self.tolerance_k for value in values) if values else None,
                'monitor_error': self.monitor_error,
                'interpretation': 'Sampled temperatures, not a guarantee between readings.'}

    def disable_heating(self):
        """Best-effort every shutdown action, with readback; no still/warmup changes."""
        errors = []
        with self.lock:
            for operation in (lambda: self.sensor.set_heater_output_range(0, self._range(0)),
                              self._disable_mode,
                              lambda: self.sensor.set_manual_output(0, 0.0),
                              lambda: self.sensor.set_setpoint_kelvin(0, self.pid_settings.base_temperature_k)):
                try:
                    operation()
                except Exception as exc:
                    errors.append(str(exc))
            try:
                value = self.sensor.get_heater_output_range(0)
                if int(getattr(value, 'value', value)) != 0:
                    raise RuntimeError('Sample-heater range is not OFF.')
                if self.sensor.get_heater_output_settings(0).output_mode != self.sensor.OutputMode.OFF:
                    raise RuntimeError('PID output mode is not OFF.')
                if not math.isclose(float(self.sensor.get_setpoint_kelvin(0)), self.pid_settings.base_temperature_k, rel_tol=1e-6, abs_tol=1e-8):
                    raise RuntimeError('Base setpoint readback mismatch during shutdown.')
            except Exception as exc:
                errors.append(str(exc))
            if not errors:
                self.control_owned = False
            self.target = self.pid_settings.base_temperature_k
            self.shutdown_report = {'heater_output': 0, 'heater_and_pid_off_verified': not errors,
                                    'base_target_k': self.target, 'cooldown_confirmed': False,
                                    'shutdown_utc': utc_now(), 'errors': errors}
        if errors:
            raise RuntimeError('Temperature shutdown failed: ' + '; '.join(errors))
        return self.shutdown_report

    def _disable_mode(self):
        settings = copy.copy(self.sensor.get_heater_output_settings(0))
        settings.output_mode = self.sensor.OutputMode.OFF
        self.sensor.configure_heater(0, settings)

    def finish(self, cancel):
        self.disable_heating()
        cfg = self.pid_settings
        # PID stays OFF throughout passive cooldown. Values below base are acceptable.
        wait_for_stability(self.read_temperature, cfg.base_temperature_k, self.tolerance_k,
                           cfg.dwell_s, cfg.cooldown_timeout_s, cfg.poll_s, cancel,
                           self.progress_callback, clock=lambda: time.monotonic() * self.time_scale,
                           wait=lambda seconds: cancel.wait(seconds / self.time_scale), cooling=True,
                           heartbeat=self.check_monitor)
        self.shutdown_report.update(cooldown_confirmed=True, cooldown_confirmed_utc=utc_now())
        return dict(self.shutdown_report)

    def close(self):
        if self.closed:
            return
        errors = []
        self.monitor_stop.set()
        if self.monitor_thread:
            self.monitor_thread.join()  # serial calls have the configured finite I/O timeout
        if self.control_owned:
            try:
                self.disable_heating()
            except Exception as exc:
                errors.append(str(exc))
        try:
            super().close()
        except Exception as exc:
            errors.append(str(exc))
        if errors:
            raise RuntimeError('; '.join(errors))


class _SimulatedBridge:
    class OutputMode(IntEnum):
        OFF = 0
        CLOSED_LOOP = 5
    class SampleHeaterOutputRange(IntEnum):
        OFF = 0
        R1 = 1
    def __init__(self, vna, base):
        self.vna, self.base = vna, base
        self.setpoint, self.range = base, 0
        self.settings = type('HeaterSettings', (), {})()
        self.settings.input_channel = 'A'
        self.settings.output_mode = self.OutputMode.OFF
        self.pid = {'gain': 10.0, 'integral': 10.0, 'derivative': 0.0}
    def get_all_input_readings(self, channel):
        self.vna.temperature_k = self.setpoint if self.range else self.base
        return {'kelvin': self.vna.temperature_k, 'resistance': 1000.0, 'power': 1e-12, 'quadrature': 0.0}
    def get_reading_status(self, channel): return {'invalid': False}
    def get_scanner_status(self): return 1, False
    def get_heater_output_settings(self, output): return copy.copy(self.settings)
    def configure_heater(self, output, settings): self.settings = copy.copy(settings)
    def get_heater_pid(self, output): return dict(self.pid)
    def set_manual_output(self, output, value): self.manual_output = value
    def set_heater_pid(self, output, gain, integral, derivative): self.pid = dict(gain=gain, integral=integral, derivative=derivative)
    def set_setpoint_kelvin(self, output, value): self.setpoint = value
    def get_setpoint_kelvin(self, output): return self.setpoint
    def set_heater_output_range(self, output, value): self.range = int(value)
    def get_heater_output_range(self, output): return self.range
    def disconnect_usb(self): pass


class SimulatedPIDTemperature(LakeShore372PID):
    """Accelerated thermal supervisor demo, not a model for tuning a real fridge."""
    def __init__(self, vna, pid, tolerance_k):
        if not isinstance(vna, SimulatedVNA):
            raise ValueError('Simulated thermometry requires a simulated VNA.')
        synthetic = ThermometrySettings(backend='lakeshore372', com_port='SIMULATED', primary_channel='A', channels=['A'])
        synthetic_pid = replace(pid, heater_output=0, heater_range=1, heater_resistance_ohm=1.0,
                                max_heater_power_w=1.0, gain=None, integral=None, derivative=None)
        super().__init__(synthetic, synthetic_pid, tolerance_k, _SimulatedBridge(vna, pid.base_temperature_k), time_scale=3600.0)
        self.is_simulated = True
