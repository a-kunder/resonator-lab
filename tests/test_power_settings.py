import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from resonator_lab import (ExperimentConfig, ResonatorConfig, PowerIFBandwidth, SweepSettings,
                           ResonatorPowerSweep, SimulatedVNA, SimulatedTemperatureController, iter_run, SiglentVNA)
from test_acquisition import FakeResource, FakeManager


def entry(name='A', base=300):
    return ResonatorConfig(name, SweepSettings(start_hz=100, stop_hz=200, points=5,
        if_bandwidth_hz=base, averages=2, settle_s=0), [PowerIFBandwidth(-45, 10), PowerIFBandwidth(-20, 1000)])


class GuardVNA(SimulatedVNA):
    def __init__(self):
        super().__init__()
        self.configurations = []
    def configure(self, settings):
        if self.output:
            raise AssertionError('IFBW must change with RF off')
        self.configurations.append(settings.if_bandwidth_hz)
        return super().configure(settings)


class PowerSettingTests(unittest.TestCase):
    def test_override_roundtrip_reordering_and_base_fallback(self):
        cfg = ExperimentConfig(resonators=[entry()], powers_dbm=[-20, -35, -45], temperatures_k=[None])
        loaded = ExperimentConfig.from_dict(cfg.to_dict())
        self.assertEqual([loaded.resonators[0].sweep_for_power(p).if_bandwidth_hz for p in loaded.powers_dbm], [1000, 300, 10])
        self.assertEqual(loaded.resonators[0].sweep.if_bandwidth_hz, 300)
        single = ExperimentConfig(powers_dbm=[-45], power_if_bandwidths=[PowerIFBandwidth(-45, 10)])
        self.assertEqual(ExperimentConfig.from_dict(single.to_dict()).resonator_plan[0].sweep_for_power(-45).if_bandwidth_hz, 10)

    def test_invalid_overrides_and_removed_power(self):
        for overrides in ([PowerIFBandwidth(-45, 0)], [PowerIFBandwidth(-45, float('nan'))],
                          [PowerIFBandwidth(float('inf'), 100)],
                          [PowerIFBandwidth(-45, 10), PowerIFBandwidth(-45, 100)]):
            cfg = ExperimentConfig(powers_dbm=[-45], resonators=[ResonatorConfig('A', power_if_bandwidths=overrides)])
            with self.assertRaises(ValueError): cfg.validate()
        cfg = ExperimentConfig(resonators=[entry()], powers_dbm=[-45])
        with self.assertRaisesRegex(ValueError, 'shared power list'): cfg.validate()

    def test_components_unknown_zero_legacy_and_conflicts(self):
        cfg = ExperimentConfig(room_temperature_attenuation_db=20, cold_attenuation_db=43)
        cfg.validate()
        self.assertEqual(cfg.total_input_loss_db, 63)
        self.assertEqual(ExperimentConfig.from_dict(cfg.to_dict()).total_input_loss_db, 63)
        cfg.cold_attenuation_db = None
        self.assertIsNone(cfg.total_input_loss_db)
        cfg.cold_attenuation_db = 0
        self.assertEqual(cfg.total_input_loss_db, 20)
        cfg.input_loss_db = 63
        with self.assertRaisesRegex(ValueError, 'not both'): cfg.validate()
        for value in [-1, float('nan'), float('inf')]:
            with self.assertRaises(ValueError): ExperimentConfig(cold_attenuation_db=value).validate()
        self.assertEqual(ExperimentConfig(input_loss_db=63).total_input_loss_db, 63)
        self.assertIsNone(ExperimentConfig().total_input_loss_db)

    def test_nested_batch_ifbw_and_attenuation_metadata(self):
        cfg = ExperimentConfig(resonators=[entry(), ResonatorConfig('B', SweepSettings(start_hz=300, stop_hz=400,
            points=7, if_bandwidth_hz=50, averages=3, settle_s=0))], powers_dbm=[-45, -35, -20],
            temperatures_k=[.02, .1], temperature_mode='controlled',
            room_temperature_attenuation_db=20, cold_attenuation_db=43, input_line='D', attenuation_notes='4K20 + CP3 + MXC20')
        vna = GuardVNA()
        with tempfile.TemporaryDirectory() as root:
            path = ResonatorPowerSweep(vna, SimulatedTemperatureController(vna)).run(cfg, root)
            traces = list(iter_run(path))
            self.assertEqual(len(traces), 12)
            self.assertEqual(vna.configurations, [10, 300, 1000, 50] * 2)
            for trace in traces:
                m = trace.metadata
                expected = [10, 300, 1000][m['power_index']] if m['resonator'] == 'A' else 50
                self.assertEqual(m['requested_settings']['if_bandwidth_hz'], expected)
                self.assertEqual(m['if_bandwidth_requested_hz'], expected)
                self.assertEqual(m['effective_settings']['if_bandwidth_hz'], expected)
                self.assertEqual(m['if_bandwidth_readback_hz'], expected)
                self.assertEqual(m['estimated_device_power_dbm'], m['vna_power_readback_dbm'] - 63)
                self.assertEqual(m['cold_attenuation_db'], 43)
                self.assertEqual(m['room_temperature_attenuation_db'], 20)
                self.assertEqual(m['input_line'], 'D')
                self.assertEqual(len(trace.frequency_hz), 5 if m['resonator'] == 'A' else 7)
            history = json.loads((path/'manifest.json').read_text())['configuration_history']
            self.assertEqual([item['power_index'] for item in history], [0, 1, 2, 0] * 2)
            self.assertFalse(vna.output)

    def test_reconfiguration_error_keeps_completed_data(self):
        class Failing(GuardVNA):
            def configure(self, settings):
                if settings.if_bandwidth_hz == 1000:
                    raise RuntimeError('Unsupported bandwidth')
                return super().configure(settings)
        cfg = ExperimentConfig(resonators=[entry()], powers_dbm=[-45, -20], temperatures_k=[None])
        vna = Failing(); runner = ResonatorPowerSweep(vna)
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError, 'Unsupported'): runner.run(cfg, root)
            self.assertEqual(len(list(iter_run(runner.last_run_path))), 1)
            self.assertFalse(vna.output)
            self.assertTrue(vna.closed)

    def test_missing_component_keeps_device_power_unknown_in_saved_trace(self):
        cfg = ExperimentConfig(sweep=SweepSettings(points=3, settle_s=0), powers_dbm=[-45],
                               temperatures_k=[None], cold_attenuation_db=43)
        with tempfile.TemporaryDirectory() as root:
            trace = next(iter_run(ResonatorPowerSweep(SimulatedVNA()).run(cfg, root)))
            self.assertIsNone(trace.metadata['estimated_device_power_dbm'])
            self.assertIsNone(trace.metadata['input_loss_db'])
            self.assertEqual(trace.metadata['cold_attenuation_db'], 43)

    def test_legacy_total_still_drives_power_estimate(self):
        cfg = ExperimentConfig(sweep=SweepSettings(points=3, settle_s=0), powers_dbm=[-45], input_loss_db=63)
        with tempfile.TemporaryDirectory() as root:
            trace = next(iter_run(ResonatorPowerSweep(SimulatedVNA()).run(cfg, root)))
            self.assertEqual(trace.metadata['estimated_device_power_dbm'], -108)

    def test_gui_parser_and_line_d_preset(self):
        from resonator_lab.gui import ResonatorApp
        from types import SimpleNamespace
        overrides = ResonatorApp.parse_ifbw_overrides('-45:10, -20:1e3')
        self.assertEqual([(i.power_dbm, i.if_bandwidth_hz) for i in overrides], [(-45,10), (-20,1000)])
        for text in ['-45:10, -45:100', '-45:0', '-45=100', 'nan:100', '-45:10,']:
            with self.assertRaises(ValueError): ResonatorApp.parse_ifbw_overrides(text)
        class Var:
            def __init__(self, value=''): self.value=value
            def get(self): return self.value
            def set(self, value): self.value=value
        app = object.__new__(ResonatorApp)
        app.vars = {key:Var() for key in ('input_loss_db','input_line','room_temperature_attenuation_db','cold_attenuation_db','attenuation_notes')}
        app.load_line_d_attenuation()
        self.assertEqual(app.vars['cold_attenuation_db'].get(), '43')
        self.assertEqual(app.vars['room_temperature_attenuation_db'].get(), '20')
        self.assertIn('cold plate 3 dB', app.vars['attenuation_notes'].get())

    def test_adapter_rejects_unaccepted_ifbw(self):
        resource = FakeResource()
        vna = SiglentVNA('TEST', FakeManager(resource))
        with self.assertRaisesRegex(RuntimeError, 'IF bandwidth'):
            vna.configure(SweepSettings(start_hz=100, stop_hz=200, points=3, averages=2, if_bandwidth_hz=10))
        self.assertNotIn(':TRIG:SEQ:SING', resource.commands)
        vna.close()
