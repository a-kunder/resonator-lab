import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import numpy as np
from resonator_lab import ExperimentConfig, SweepSettings, SimulatedVNA, ResonatorPowerSweep, iter_run, Trace
from resonator_lab.thermometry import ThermometrySettings, PIDSettings, LakeShore372Reader
from resonator_lab.temperature_control import (wait_for_stability, LakeShore372PID,
                                               SimulatedPIDTemperature, _SimulatedBridge)
from resonator_lab.devices import create_temperature_devices, SimulatedTemperatureReader
from resonator_lab.instruments import Cancelled


class Clock:
    def __init__(self): self.now = 0
    def __call__(self): return self.now
    def wait(self, seconds): self.now += seconds; return False


class TemperatureTests(unittest.TestCase):
    def test_dwell_resets_after_any_excursion(self):
        clock = Clock(); readings = iter([.1, .1, .11] + [.1] * 20)
        progress = []
        value = wait_for_stability(lambda: next(readings), .1, .002, 600, 1800, 100,
                                  threading.Event(), progress.append, clock, clock.wait)
        self.assertEqual(value, .1)
        self.assertEqual(clock.now, 900)  # last excursion at t=200, dwell restarts t=300
        self.assertEqual(progress[-1]['stable_s'], 600)
        self.assertGreaterEqual(progress[-1]['samples_in_band'], 3)

    def test_bad_reading_never_counts_as_stability(self):
        for value in (float('nan'), 0, -1):
            clock = Clock()
            with self.assertRaises(ValueError):
                wait_for_stability(lambda: value, .1, .002, 600, 1800, 5,
                                   threading.Event(), clock=clock, wait=clock.wait)

    def test_stability_timeout_and_cancel(self):
        clock = Clock()
        with self.assertRaises(TimeoutError):
            wait_for_stability(lambda: .2, .1, .002, 600, 700, 100,
                               threading.Event(), clock=clock, wait=clock.wait)
        cancel = threading.Event(); cancel.set()
        with self.assertRaises(Cancelled):
            wait_for_stability(lambda: .1, .1, .002, 600, 700, 100, cancel)

    def test_passive_cooldown_accepts_below_base(self):
        clock = Clock()
        value = wait_for_stability(lambda: .015, .020, .002, 600, 1800, 100,
                                  threading.Event(), clock=clock, wait=clock.wait, cooling=True)
        self.assertEqual(value, .015)

    def test_hardware_pid_has_no_assumed_wiring_or_heater_limit(self):
        with self.assertRaises(ValueError): PIDSettings().validate(hardware=True)
        settings = PIDSettings(heater_output=0, heater_range=4, heater_resistance_ohm=50, max_heater_power_w=1e-6)
        with self.assertRaisesRegex(ValueError, 'above'):
            settings.validate(hardware=True)
        settings.max_heater_power_w = 50e-6
        settings.validate(hardware=True)

    def test_thermometry_requires_explicit_channel_and_connection(self):
        with self.assertRaises(ValueError): ThermometrySettings(backend='lakeshore372').validate()
        settings = ThermometrySettings(backend='lakeshore372', com_port='COM5', primary_channel='6', channels=['5'])
        with self.assertRaises(ValueError): settings.validate()

    def test_reader_saves_all_channels_and_does_not_set_heaters(self):
        class ReadOnlySensor:
            calls = []
            def get_all_input_readings(self, channel):
                self.calls.append(('read', channel))
                return dict(kelvin=.025, resistance=1000, power=1e-12, quadrature=.01)
            def get_reading_status(self, channel): return {'sensor_error': False}
            def get_scanner_status(self): return 5, True
            def disconnect_usb(self): self.calls.append(('disconnect',))
        sensor = ReadOnlySensor()
        settings = ThermometrySettings(backend='lakeshore372', com_port='COM5', primary_channel='6', channels=['5', '6'])
        reader = LakeShore372Reader(settings, sensor)
        snapshot = reader.read_snapshot(); reader.close()
        self.assertEqual(set(snapshot['channels']), {'5', '6'})
        self.assertEqual(snapshot['primary_kelvin'], .025)
        self.assertEqual(snapshot['channels']['6']['resistance_ohm'], 1000)
        self.assertTrue(snapshot['scanner']['auto_scan'])
        self.assertIsNone(snapshot['channels']['6']['sensor_conversion_time_utc'])
        self.assertEqual(sensor.calls, [('read', 5), ('read', 6), ('disconnect',)])

    def test_sensor_status_flags_are_rejected(self):
        vna = SimulatedVNA(); sensor = _SimulatedBridge(vna, .02)
        sensor.get_reading_status = lambda channel: {'sensor_error': True}
        settings = ThermometrySettings(backend='lakeshore372', com_port='COM5', primary_channel='A', channels=['A'])
        reader = LakeShore372Reader(settings, sensor)
        with self.assertRaisesRegex(ValueError, 'flags'): reader.read_snapshot()
        reader.close()

    def test_fixed_temperature_logs_measured_readings(self):
        with tempfile.TemporaryDirectory() as root:
            vna = SimulatedVNA(); reader = SimulatedTemperatureReader(vna, .031)
            cfg = ExperimentConfig(sweep=SweepSettings(points=11, settle_s=0), powers_dbm=[-30], temperatures_k=[.030])
            path = ResonatorPowerSweep(vna, temperature_reader=reader).run(cfg, root)
            trace = next(iter_run(path))
            self.assertEqual(trace.metadata['temperature_label_k'], .030)
            self.assertEqual(trace.metadata['temperature_before_k'], .031)
            self.assertEqual(trace.metadata['temperature_after_k'], .031)
            self.assertIn('SIM', trace.metadata['temperature_snapshot_before']['channels'])
            self.assertIsNone(trace.metadata['temperature_within_tolerance'])
            self.assertGreater(len((path / 'temperature_log.csv').read_text().splitlines()), 2)

    def test_post_acquisition_read_failure_still_saves_trace(self):
        class FailedReader:
            calls = 0
            closed = False
            def read_snapshot(self):
                self.calls += 1
                if self.calls == 2: raise OSError('serial cable disconnected')
                return {'primary_kelvin': .025, 'channels': {}, 'simulated': True}
            def close(self): self.closed = True
        with tempfile.TemporaryDirectory() as root:
            reader = FailedReader(); runner = ResonatorPowerSweep(SimulatedVNA(), temperature_reader=reader)
            cfg = ExperimentConfig(sweep=SweepSettings(points=11, settle_s=0), powers_dbm=[-30])
            with self.assertRaisesRegex(RuntimeError, 'trace saved'):
                runner.run(cfg, root)
            trace = next(iter_run(runner.last_run_path))
            self.assertIn('disconnected', trace.metadata['temperature_read_error_after'])
            self.assertEqual(len(trace.s_complex), 11)
            self.assertTrue(reader.closed)

    def test_native_controller_feedback_mismatch_rejected_before_heating(self):
        vna = SimulatedVNA(); sensor = _SimulatedBridge(vna, .02)
        sensor.settings.input_channel = 1
        thermal = ThermometrySettings(backend='lakeshore372', com_port='COM5', primary_channel='A', channels=['A'])
        pid = PIDSettings(heater_output=0, heater_range=1, heater_resistance_ohm=1, max_heater_power_w=1)
        with self.assertRaisesRegex(ValueError, 'feedback'):
            LakeShore372PID(thermal, pid, sensor=sensor)
        self.assertEqual(sensor.range, 0)

    def test_native_sequence_and_shutdown(self):
        vna = SimulatedVNA(); controller = SimulatedPIDTemperature(vna, PIDSettings(), .002)
        controller.set_target(.1)
        self.assertEqual(controller.sensor.settings.output_mode, controller.sensor.OutputMode.CLOSED_LOOP)
        self.assertEqual(controller.sensor.range, 1)
        self.assertEqual(controller.sensor.setpoint, .1)
        value = controller.wait_until_stable(.002, 1800, threading.Event())
        self.assertEqual(value, .1)
        report = controller.finish(threading.Event())
        self.assertTrue(report['cooldown_confirmed'])
        self.assertEqual(controller.sensor.range, 0)
        self.assertEqual(controller.sensor.settings.output_mode, controller.sensor.OutputMode.OFF)
        self.assertEqual(controller.sensor.setpoint, .020)
        controller.close()

    def test_native_monitor_turns_heater_off_on_sensor_failure(self):
        vna = SimulatedVNA(); controller = SimulatedPIDTemperature(vna, PIDSettings(), .002)
        controller.set_target(.1)
        controller.sensor.get_all_input_readings = lambda channel: {'kelvin': float('nan')}
        controller.start_monitor(lambda data: None, lambda data: None)
        controller.monitor_thread.join(timeout=2)
        self.assertFalse(controller.monitor_thread.is_alive())
        self.assertIsNotNone(controller.monitor_error)
        self.assertEqual(controller.sensor.range, 0)
        self.assertEqual(controller.sensor.settings.output_mode, controller.sensor.OutputMode.OFF)
        controller.close()

    def test_monitor_turns_heater_off_when_stop_requested(self):
        vna = SimulatedVNA(); controller = SimulatedPIDTemperature(vna, PIDSettings(), .002)
        controller.set_target(.1)
        controller.cancel_event.set()
        controller.start_monitor(lambda data: None, lambda data: None)
        deadline = time.monotonic() + 2
        while controller.control_owned and time.monotonic() < deadline: time.sleep(.01)
        self.assertFalse(controller.control_owned)
        self.assertEqual(controller.sensor.range, 0)
        controller.close()

    def test_factory_nested_sweep_metadata_and_cooldown(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = ExperimentConfig(sweep=SweepSettings(points=11, settle_s=0), powers_dbm=[-40, -30],
                                   temperatures_k=[.02, .1], temperature_mode='controlled')
            vna = SimulatedVNA(); controller, reader = create_temperature_devices(cfg, vna)
            path = ResonatorPowerSweep(vna, controller, reader).run(cfg, root)
            manifest = json.loads((path / 'manifest.json').read_text())
            self.assertEqual(manifest['status'], 'completed')
            self.assertEqual(len(list(iter_run(path))), 4)
            self.assertTrue(manifest['temperature_shutdown']['heater_and_pid_off_verified'])
            self.assertTrue(manifest['temperature_shutdown']['cooldown_confirmed'])
            self.assertEqual(controller.sensor.range, 0)
            self.assertEqual(controller.sensor.setpoint, .02)

    def test_stop_disables_heating_before_busy_vna_returns(self):
        class BusyVNA(SimulatedVNA):
            def acquire(self, cancel):
                cancel.set()
                deadline = time.monotonic() + 2
                while controller.control_owned and time.monotonic() < deadline:
                    time.sleep(.01)
                if controller.control_owned:
                    raise AssertionError('Heater remained enabled while VNA was busy.')
                return Trace(np.linspace(1, 2, 11), np.ones(11, dtype=complex), {})
        with tempfile.TemporaryDirectory() as root:
            cfg = ExperimentConfig(sweep=SweepSettings(points=11, settle_s=0), powers_dbm=[-30],
                                   temperatures_k=[.1], temperature_mode='controlled')
            vna = BusyVNA(); controller = SimulatedPIDTemperature(vna, cfg.pid, .002)
            path = ResonatorPowerSweep(vna, controller, controller).run(cfg, root)
            manifest = json.loads((path / 'manifest.json').read_text())
            self.assertEqual(manifest['status'], 'cancelled')
            self.assertEqual(len(list(iter_run(path))), 1)
            self.assertTrue(manifest['temperature_shutdown']['heater_and_pid_off_verified'])
            self.assertFalse(manifest['temperature_shutdown']['cooldown_confirmed'])

    def test_in_acquisition_excursion_is_flagged_even_if_endpoints_are_good(self):
        class ExcursionVNA(SimulatedVNA):
            def acquire(self, cancel):
                with controller.lock:
                    controller.samples.append((time.monotonic(), .110))
                time.sleep(.01)
                return Trace(np.linspace(1, 2, 11), np.ones(11, dtype=complex), {})
        with tempfile.TemporaryDirectory() as root:
            cfg = ExperimentConfig(sweep=SweepSettings(points=11, settle_s=0), powers_dbm=[-30],
                                   temperatures_k=[.1], temperature_mode='controlled')
            vna = ExcursionVNA(); controller = SimulatedPIDTemperature(vna, cfg.pid, .002)
            runner = ResonatorPowerSweep(vna, controller, controller)
            with self.assertRaisesRegex(RuntimeError, 'drifted'):
                runner.run(cfg, root)
            trace = next(iter_run(runner.last_run_path))
            self.assertAlmostEqual(trace.metadata['temperature_before_k'], .1)
            self.assertAlmostEqual(trace.metadata['temperature_after_k'], .1)
            self.assertFalse(trace.metadata['temperature_within_tolerance'])
            self.assertFalse(trace.metadata['temperature_acquisition_summary']['samples_within_tolerance'])
            self.assertEqual(controller.sensor.range, 0)

    def test_rolling_dwell_is_reused_but_any_excursion_resets_it(self):
        vna = SimulatedVNA(); controller = SimulatedPIDTemperature(vna, PIDSettings(), .002)
        controller.set_target(.1)
        controller.stable_since = time.monotonic() - 1
        controller.stable_samples = 5
        controller.ensure_stable_before_trace(.002, 1800, threading.Event())
        self.assertGreaterEqual(controller.stable_samples, 6)
        original = controller.sensor.get_all_input_readings
        controller.sensor.get_all_input_readings = lambda channel: dict(kelvin=.110)
        controller.read_snapshot()
        self.assertIsNone(controller.stable_since)
        self.assertEqual(controller.stable_samples, 0)
        controller.sensor.get_all_input_readings = original
        controller.ensure_stable_before_trace(.002, 1800, threading.Event())
        snapshot = controller.read_snapshot()
        self.assertGreaterEqual(snapshot['stability']['stable_s'], 600)
        controller.close()

    def test_old_schema_sample_is_still_readable(self):
        path = Path(__file__).resolve().parents[1] / 'examples' / 'sample_run'
        self.assertEqual(len(list(iter_run(path))), 3)


if __name__ == '__main__':
    unittest.main()
