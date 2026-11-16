import json
from pathlib import Path
import tempfile
import threading
import unittest
import numpy as np
from resonator_lab import (ExperimentConfig, ResonatorConfig, SweepSettings, SimulatedVNA,
                           SimulatedTemperatureController, ResonatorPowerSweep, iter_run,
                           stepped_sequence)


def plan():
    return [ResonatorConfig('ResA', SweepSettings(start_hz=100, stop_hz=200, points=3, averages=1, settle_s=0)),
            ResonatorConfig('ResB', SweepSettings(start_hz=300, stop_hz=450, points=5, if_bandwidth_hz=100, averages=3, settle_s=0)),
            ResonatorConfig('ResC', SweepSettings(start_hz=50, stop_hz=80, points=7, if_bandwidth_hz=500, averages=5, settle_s=0))]


class RecordingVNA(SimulatedVNA):
    def __init__(self):
        super().__init__()
        self.configurations = []
        self.closed_count = 0
    def configure(self, settings):
        if self.output:
            raise AssertionError('RF must be off before switching resonators')
        self.configurations.append(settings)
        return super().configure(settings)
    def close(self):
        self.closed_count += 1
        super().close()


class BatchTests(unittest.TestCase):
    def test_batch_round_trip_and_legacy_single_config(self):
        cfg = ExperimentConfig(resonators=plan(), powers_dbm=[-10, -30], temperatures_k=[None])
        loaded = ExperimentConfig.from_dict(cfg.to_dict())
        self.assertEqual([r.name for r in loaded.resonator_plan], ['ResA','ResB','ResC'])
        self.assertEqual(loaded.total_traces, 6)
        legacy = ExperimentConfig.from_dict({'resonator':'Old', 'sweep':{'points':5}})
        self.assertEqual(legacy.resonator_plan[0].name, 'Old')
        self.assertEqual(legacy.resonator_plan[0].sweep.points, 5)

    def test_duplicate_names_and_invalid_row_are_rejected(self):
        cfg = ExperimentConfig(resonators=plan())
        cfg.resonators[1].name = ' resa '
        with self.assertRaisesRegex(ValueError, 'unique'):
            cfg.validate()
        cfg.resonators[1].name = 'ResB'
        cfg.resonators[1].sweep.points = 1
        with self.assertRaises(ValueError):
            cfg.validate()

    def test_temperature_resonator_power_order_and_mixed_grids(self):
        cfg = ExperimentConfig(batch_name='All resonators at each temperature', resonators=plan(),
                               powers_dbm=[-10,-30], temperatures_k=[.02,.1], temperature_mode='controlled')
        vna = RecordingVNA()
        with tempfile.TemporaryDirectory() as root:
            path = ResonatorPowerSweep(vna, SimulatedTemperatureController(vna)).run(cfg, root)
            traces = list(iter_run(path))
            self.assertEqual(len(traces), 12)
            expected = [(ti,ri,pi) for ti in range(2) for ri in range(3) for pi in range(2)]
            actual = [(t.metadata['temperature_index'],t.metadata['resonator_index'],t.metadata['power_index']) for t in traces]
            self.assertEqual(actual, expected)
            for t, (ti,ri,pi) in zip(traces, expected):
                r = cfg.resonators[ri]
                self.assertEqual(t.metadata['resonator'], r.name)
                self.assertEqual(t.metadata['vna_power_readback_dbm'], cfg.powers_dbm[pi])
                self.assertEqual(t.metadata['temperature_target_k'], cfg.temperatures_k[ti])
                self.assertEqual(len(t.frequency_hz), r.sweep.points)
                self.assertEqual(t.frequency_hz[0], r.sweep.start_hz)
                self.assertEqual(t.frequency_hz[-1], r.sweep.stop_hz)
                self.assertEqual(t.metadata['effective_settings']['if_bandwidth_hz'], r.sweep.if_bandwidth_hz)
                self.assertEqual(t.metadata['effective_settings']['averages'], r.sweep.averages)
            m = json.loads((path/'manifest.json').read_text())
            self.assertEqual(m['measurement_order'], ['temperature','resonator','power'])
            self.assertEqual(len(m['configuration_history']), 6)
            self.assertEqual(vna.closed_count, 1)
            self.assertFalse(vna.output)

    def test_cancel_in_second_resonator_preserves_prior_data(self):
        cfg = ExperimentConfig(resonators=plan(), powers_dbm=[-40,-30], temperatures_k=[None])
        cancel = threading.Event(); vna = RecordingVNA()
        def event(kind, data):
            if kind == 'trace' and data['completed'] == 3:
                cancel.set()
        with tempfile.TemporaryDirectory() as root:
            path = ResonatorPowerSweep(vna).run(cfg, root, cancel, event)
            traces = list(iter_run(path))
            self.assertEqual([t.metadata['resonator'] for t in traces], ['ResA','ResA','ResB'])
            self.assertEqual(json.loads((path/'manifest.json').read_text())['status'], 'cancelled')
            self.assertEqual(vna.closed_count, 1)
            self.assertFalse(vna.output)

    def test_failure_reconfiguring_second_resonator_preserves_first(self):
        class BrokenVNA(RecordingVNA):
            def configure(self, settings):
                if self.configurations:
                    raise RuntimeError('Could not configure second resonator')
                return super().configure(settings)
        cfg = ExperimentConfig(resonators=plan(), powers_dbm=[-40], temperatures_k=[None])
        vna = BrokenVNA(); runner = ResonatorPowerSweep(vna)
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(RuntimeError, 'second resonator'):
                runner.run(cfg, root)
            traces = list(iter_run(runner.last_run_path))
            self.assertEqual(len(traces), 1)
            self.assertEqual(traces[0].metadata['resonator'], 'ResA')
            self.assertEqual(vna.closed_count, 1)
            self.assertFalse(vna.output)

    def test_step_grid_including_decimal_and_descending(self):
        self.assertEqual(stepped_sequence(20,100,20), [20,40,60,80,100])
        self.assertEqual(stepped_sequence(20,75,20), [20,40,60])
        self.assertEqual(stepped_sequence(80,20,20), [80,60,40,20])
        self.assertEqual(stepped_sequence(.1,.3,.1), [.1,.2,.3])
        self.assertEqual(stepped_sequence(20,20,5), [20])
        for step in (0,-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError): stepped_sequence(20,100,step)
        with self.assertRaises(ValueError): stepped_sequence(20,800,.00001)

    def test_gui_editor_round_trip_preserves_all_original_frequency_windows(self):
        from resonator_lab.gui import ResonatorApp
        class Var:
            def __init__(self): self.value = ''
            def get(self): return self.value
            def set(self, value): self.value = value
        app = object.__new__(ResonatorApp)
        app.vars = {key: Var() for key in ('resonator','start_ghz','stop_ghz','points',
            'if_bandwidth_hz','averages','s_parameter','timeout_s','settle_s')}
        path = Path(__file__).resolve().parents[1]/'examples/base_batch_original.json'
        config = ExperimentConfig.from_dict(json.loads(path.read_text()))
        entries = config.resonator_plan + [ResonatorConfig('Fractional Hz', SweepSettings(
            start_hz=5929700000.123456, stop_hz=5954700000.987654))]
        for entry in entries:
            app.set_editor(entry)
            self.assertEqual(app.editor_resonator().to_dict(), entry.to_dict())

    def test_vna_does_not_open_lsci_serial_port(self):
        from resonator_lab import SiglentVNA
        class ForbiddenManager:
            def open_resource(self, address):
                raise AssertionError('Serial port must not be opened')
        for address in ('COM3', 'ASRL3::INSTR', ' asrl3::instr '):
            with self.assertRaisesRegex(ValueError, 'LSCI Reader'):
                SiglentVNA(address, ForbiddenManager())

    def test_packaged_original_batch(self):
        path = Path(__file__).resolve().parents[1]/'examples/base_batch_original.json'
        cfg = ExperimentConfig.from_dict(json.loads(path.read_text()))
        self.assertEqual(len(cfg.resonator_plan), 9)
        self.assertEqual(cfg.total_traces, 126)
        self.assertEqual(cfg.powers_dbm, list(range(-45,21,5)))
        self.assertEqual(cfg.resonators[6].name, 'Res6')
        self.assertEqual(cfg.resonators[6].sweep.points, 1001)
        self.assertEqual(cfg.resonators[6].sweep.if_bandwidth_hz, 100)


if __name__ == '__main__':
    unittest.main()
