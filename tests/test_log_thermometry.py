import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from resonator_lab.thermometry import ThermometrySettings
from resonator_lab.log_thermometry import LSCILogReader
from resonator_lab.devices import create_temperature_devices
from resonator_lab import ExperimentConfig, SweepSettings, ResonatorPowerSweep, SimulatedVNA, iter_run


class LogThermometryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.local = datetime(2026, 11, 16, 12, 30)
        self.now = self.local.astimezone(timezone.utc) + timedelta(seconds=61)
        self.path = self.root / '26-11-16' / 'CH6 T 26-11-16.txt'
        self.path.parent.mkdir()
        self.row = '16-11-26,12:30:00,1.432770E-2\r\n'
        self.path.write_bytes(self.row.encode())
        self.settings = ThermometrySettings(backend='lsci_log', log_path=str(self.root))

    def reader(self):
        return LSCILogReader(self.settings, now=lambda: self.now)

    def test_photo_format_kelvin_timestamp_and_readonly(self):
        original = self.path.read_bytes()
        result = self.reader().read_snapshot()
        self.assertEqual(result['primary_kelvin'], .0143277)
        self.assertEqual(result['age_s'], 61)
        self.assertEqual(result['source_timestamp_utc'], self.local.astimezone(timezone.utc).isoformat())
        self.assertEqual(result['channels']['6']['source_line'], self.row.strip())
        self.assertEqual(original, self.path.read_bytes())
        self.assertFalse(result['simulated'])

    def test_partial_append_and_malformed_latest(self):
        with self.path.open('ab') as stream:
            stream.write(b'16-11-26,12:31:00,1.4')
        self.assertEqual(self.reader().read_snapshot()['age_s'], 61)
        with self.path.open('ab') as stream:
            stream.write(b'BAD\n')
        with self.assertRaisesRegex(ValueError, 'Invalid latest'):
            self.reader().read_snapshot()

    def test_stale_future_invalid_missing(self):
        self.now += timedelta(seconds=121)
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.reader().read_snapshot()
        self.now -= timedelta(seconds=190)
        with self.assertRaisesRegex(ValueError, 'future'):
            self.reader().read_snapshot()
        for value in ['nan', 'inf', '-1', '0']:
            self.path.write_text('16-11-26,12:30:00,' + value + '\n')
            with self.assertRaisesRegex(ValueError, 'Invalid latest'):
                self.reader().read_snapshot()
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.reader().read_snapshot()

    def test_rollover_and_wrong_quantity(self):
        other = self.root / '26-11-17'
        other.mkdir()
        (other / 'CH6 R 26-11-17.txt').write_text(self.row)
        self.assertEqual(self.reader().read_snapshot()['log_file'], str(self.path.resolve()))
        (other / 'CH6 T 26-11-17.txt').write_text('17-11-26,00:00:00,.02\n')
        self.now = datetime(2026, 11, 17).astimezone(timezone.utc)
        self.assertEqual(self.reader().read_snapshot()['primary_kelvin'], .02)
        self.settings.log_path = str(other / 'CH6 R 26-11-17.txt')
        with self.assertRaisesRegex(ValueError, 'not R/P'):
            self.reader().read_snapshot()

    def test_utf16_large_tail(self):
        self.path.write_bytes((self.row * 4000).encode('utf-16'))
        self.assertEqual(self.reader().read_snapshot()['primary_kelvin'], .0143277)

    def test_factory_no_controller_or_control_mode(self):
        cfg = ExperimentConfig(thermometry=self.settings)
        controller, reader = create_temperature_devices(cfg, SimulatedVNA())
        self.assertIsNone(controller)
        self.assertIsInstance(reader, LSCILogReader)
        cfg.temperature_mode = 'controlled'
        with self.assertRaisesRegex(ValueError, 'read-only'):
            create_temperature_devices(cfg, SimulatedVNA())

    def config(self):
        return ExperimentConfig(sweep=SweepSettings(points=11, settle_s=0), powers_dbm=[-40, -35],
                                temperatures_k=[None], thermometry=self.settings)

    def test_sweep_json_and_csv_provenance(self):
        path = ResonatorPowerSweep(SimulatedVNA(), temperature_reader=self.reader()).run(self.config(), self.root/'data')
        traces = list(iter_run(path))
        self.assertEqual(len(traces), 2)
        for trace in traces:
            self.assertEqual(trace.metadata['temperature_before_k'], .0143277)
            self.assertEqual(trace.metadata['temperature_snapshot_after']['age_s'], 61)
            self.assertIsNone(trace.metadata['temperature_target_k'])
        log = (path/'temperature_log.csv').read_text()
        self.assertIn('source_timestamp_utc,age_s,log_file,source_line', log)
        self.assertIn('CH6 T 26-11-16.txt', log)

    def test_stale_after_trace_saves_then_stops(self):
        vna = SimulatedVNA()
        acquire = vna.acquire
        def age_after_acquire(cancel):
            trace = acquire(cancel)
            self.now += timedelta(seconds=300)
            return trace
        vna.acquire = age_after_acquire
        runner = ResonatorPowerSweep(vna, temperature_reader=self.reader())
        with self.assertRaisesRegex(RuntimeError, 'trace saved'):
            runner.run(self.config(), self.root/'data')
        traces = list(iter_run(runner.last_run_path))
        self.assertEqual(len(traces), 1)
        self.assertIn('stale', traces[0].metadata['temperature_read_error_after'])
        self.assertEqual(json.loads((runner.last_run_path/'manifest.json').read_text())['status'], 'failed')

    def test_base_gui_log_config(self):
        from resonator_lab.gui import ResonatorApp
        app = object.__new__(ResonatorApp)
        app.power_only = True
        fields = dict(power_list='-40', backend='Simulator', resonator='R', start_ghz='6', stop_ghz='6.01',
            points='11', if_bandwidth_hz='100', averages='1', s_parameter='S21', timeout_s='30', settle_s='0',
            input_loss_db='', notes='', output_root='data', log_enabled='Yes', log_path=str(self.root),
            log_channel='6', log_max_age_s='180')
        app.vars = {key: SimpleNamespace(get=lambda value=value: value) for key, value in fields.items()}
        cfg = app.config()
        self.assertEqual(cfg.thermometry.backend, 'lsci_log')
        self.assertEqual(cfg.temperature_mode, 'fixed')
        self.assertEqual(cfg.temperatures_k, [None])
