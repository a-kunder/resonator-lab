import json
import tempfile
import unittest
from resonator_lab import ExperimentConfig, SweepSettings, SimulatedVNA, ResonatorPowerSweep, iter_run
from resonator_lab.devices import create_temperature_devices
from resonator_lab.thermometry import ThermometrySettings


class BaseModeTests(unittest.TestCase):
    def test_base_power_sweep_without_claimed_temperature_or_controller(self):
        config = ExperimentConfig(sweep=SweepSettings(points=11, settle_s=0),
                                  powers_dbm=[-45, -40], temperatures_k=[None])
        vna = SimulatedVNA()
        controller, reader = create_temperature_devices(config, vna)
        self.assertIsNone(controller)
        self.assertIsNone(reader)
        with tempfile.TemporaryDirectory() as root:
            path = ResonatorPowerSweep(vna, controller, reader).run(config, root)
            self.assertEqual(json.loads((path / 'manifest.json').read_text())['status'], 'completed')
            traces = list(iter_run(path))
            self.assertEqual(len(traces), 2)
            for trace in traces:
                self.assertIsNone(trace.metadata['temperature_label_k'])
                self.assertIsNone(trace.metadata['temperature_before_k'])
                self.assertFalse(trace.metadata['temperature_logging_enabled'])

    def test_power_gui_ignores_thermal_settings_from_imported_profiles(self):
        from types import SimpleNamespace
        from resonator_lab.gui import ResonatorApp
        app = object.__new__(ResonatorApp)
        app.power_only = True
        fields = {'power_list': '-45, -40', 'backend': 'Siglent SNA5000A',
                  'resonator': 'Res1.1', 'start_ghz': '5.9297', 'stop_ghz': '5.9547',
                  'points': '10001', 'if_bandwidth_hz': '1000', 'averages': '7',
                  's_parameter': 'S43', 'timeout_s': '1800', 'settle_s': '.2',
                  'input_loss_db': '', 'notes': '', 'output_root': 'data', 'address': 'TEST',
                  'temperature_mode': 'Temperature × power sweep',
                  'temperature_source': 'Lake Shore 372', 'regulate': 'Yes'}
        app.vars = {key: SimpleNamespace(get=lambda value=value: value) for key, value in fields.items()}
        config = app.config()
        self.assertEqual(config.temperature_mode, 'fixed')
        self.assertEqual(config.temperatures_k, [None])
        self.assertEqual(config.thermometry.backend, 'none')

    def test_direct_lakeshore_route_is_blocked_to_preserve_lsci_ownership(self):
        config = ExperimentConfig(thermometry=ThermometrySettings(backend='lakeshore372'))
        with self.assertRaisesRegex(ValueError, 'LSCI Reader'):
            config.validate()
        with self.assertRaisesRegex(ValueError, 'ownership'):
            create_temperature_devices(config, SimulatedVNA())


if __name__ == '__main__':
    unittest.main()
