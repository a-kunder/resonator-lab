import json
import tempfile
import threading
import unittest
import numpy as np
from resonator_lab import (SweepSettings, ExperimentConfig, ResonatorPowerSweep,
                           SimulatedVNA, SimulatedTemperatureController, SiglentVNA,
                           iter_run, sequence)


class FakeResource:
    def __init__(self, malformed=False, fail_opc=False):
        self.commands = []
        self.timeout = 5000
        self.closed = False
        self.malformed, self.fail_opc = malformed, fail_opc
        self.replies = {'*IDN?': 'SIGLENT,SNA5014A,TEST,1.0', ':SYST:ERR?': '0,"No error"',
                        ':SENS1:FREQ:STAR?': '100', ':SENS1:FREQ:STOP?': '200',
                        ':SENS1:SWE:POIN?': '3', ':SENS1:BAND?': '1000',
                        ':SENS1:AVER:COUN?': '2', ':SENS1:AVER?': '1', ':OUTP?': '0',
                        ':SOUR1:POW?': '-30', '*OPC?': '1'}

    def write(self, command):
        self.commands.append(command)
        if command.startswith(':OUTP '):
            self.replies[':OUTP?'] = command.split()[-1]

    def query(self, command):
        self.commands.append(command)
        if self.fail_opc and command == '*OPC?':
            raise TimeoutError('simulated timeout')
        return self.replies[command]

    def query_ascii_values(self, command):
        self.commands.append(command)
        return [1, 0, 0.5, -0.1] if self.malformed else [1, 0, 0.5, -0.1, 0.9, 0.1]

    def close(self):
        self.closed = True


class FakeManager:
    def __init__(self, resource):
        self.resource = resource
        self.closed = False

    def open_resource(self, address):
        return self.resource

    def close(self):
        self.closed = True


def config():
    return ExperimentConfig(sweep=SweepSettings(start_hz=100, stop_hz=200, points=3, averages=2, settle_s=0),
                            powers_dbm=[-40, -30], temperatures_k=[0.025])


class Tests(unittest.TestCase):
    def test_sequence(self):
        self.assertEqual(sequence(-10, -30, 3), [-10, -20, -30])
        with self.assertRaises(ValueError): sequence(-40, -20, 1)

    def test_validation(self):
        for key, value in [('points', 1), ('averages', 1.2), ('if_bandwidth_hz', float('nan')),
                           ('s_parameter', 'S21;*RST'), ('settle_s', -1)]:
            c = config(); setattr(c.sweep, key, value)
            with self.assertRaises(ValueError): c.validate()
        c = config(); c.temperatures_k = [0]
        with self.assertRaises(ValueError): c.validate()

    def test_roundtrip_complex_and_csv_precision(self):
        with tempfile.TemporaryDirectory() as root:
            vna = SimulatedVNA(); emitted = []
            path = ResonatorPowerSweep(vna).run(config(), root, on_event=lambda k, d: emitted.append((k, d)))
            m = json.loads((path / 'manifest.json').read_text())
            self.assertEqual(m['status'], 'completed'); self.assertEqual(len(m['traces']), 2)
            self.assertTrue(vna.closed); self.assertFalse(vna.output)
            for i, trace in enumerate(iter_run(path)):
                original = [d['trace'] for k, d in emitted if k == 'trace'][i]
                np.testing.assert_array_equal(trace.s_complex, original.s_complex)
                csv = np.loadtxt(str(path / m['traces'][i]['csv']), delimiter=',', skiprows=1)
                np.testing.assert_array_equal(csv[:, 0], trace.frequency_hz)
                np.testing.assert_array_equal(csv[:, 1] + 1j * csv[:, 2], trace.s_complex)
                self.assertIsNone(trace.metadata['temperature_before_k'])
                self.assertEqual(trace.metadata['temperature_label_k'], 0.025)
                self.assertTrue(trace.metadata['simulated'])

    def test_cancel_preserves_data(self):
        with tempfile.TemporaryDirectory() as root:
            cancel = threading.Event(); vna = SimulatedVNA()
            def event(kind, payload):
                if kind == 'trace': cancel.set()
            path = ResonatorPowerSweep(vna).run(config(), root, cancel, event)
            m = json.loads((path / 'manifest.json').read_text())
            self.assertEqual(m['status'], 'cancelled'); self.assertEqual(len(m['traces']), 1)
            self.assertFalse(vna.output); self.assertTrue(vna.closed)

    def test_failure_preserves_data_and_cleans_up(self):
        class Broken(SimulatedVNA):
            calls = 0
            def acquire(self, cancel):
                self.calls += 1
                if self.calls == 2: raise RuntimeError('test failure')
                return super().acquire(cancel)
        with tempfile.TemporaryDirectory() as root:
            vna = Broken(); runner = ResonatorPowerSweep(vna)
            with self.assertRaisesRegex(RuntimeError, 'test failure'): runner.run(config(), root)
            m = json.loads((runner.last_run_path / 'manifest.json').read_text())
            self.assertEqual(m['status'], 'failed'); self.assertEqual(len(m['traces']), 1)
            self.assertFalse(vna.output); self.assertTrue(vna.closed)

    def test_temperature_sweep_and_missing_controller(self):
        with tempfile.TemporaryDirectory() as root:
            c = config(); c.temperature_mode = 'controlled'; c.temperatures_k = [0.025, 0.1]
            vna = SimulatedVNA()
            path = ResonatorPowerSweep(vna, SimulatedTemperatureController(vna)).run(c, root)
            traces = list(iter_run(path))
            self.assertEqual(len(traces), 4)
            self.assertEqual(traces[-1].metadata['temperature_after_k'], 0.1)
            self.assertIsNone(traces[-1].metadata['temperature_label_k'])
            with self.assertRaisesRegex(ValueError, 'TemperatureController'):
                ResonatorPowerSweep(SimulatedVNA()).run(c, root)

    def test_temperature_drift_saved_and_flagged(self):
        class Drifting(SimulatedTemperatureController):
            reads = 0
            def read_temperature(self):
                self.reads += 1
                return self.vna.temperature_k + (0.01 if self.reads >= 3 else 0)
        with tempfile.TemporaryDirectory() as root:
            c = config(); c.temperature_mode = 'controlled'
            vna = SimulatedVNA(); runner = ResonatorPowerSweep(vna, Drifting(vna))
            with self.assertRaisesRegex(RuntimeError, 'drifted'): runner.run(c, root)
            traces = list(iter_run(runner.last_run_path))
            self.assertEqual(len(traces), 1)
            self.assertFalse(traces[0].metadata['temperature_within_tolerance'])

    def test_cleanup_errors_prevent_success(self):
        class BadShutdown(SimulatedVNA):
            calls = 0
            def set_output(self, enabled):
                self.calls += 1
                if self.calls > 3 and not enabled: raise RuntimeError('RF off failed')
                super().set_output(enabled)
        with tempfile.TemporaryDirectory() as root:
            vna = BadShutdown(); path = ResonatorPowerSweep(vna).run(config(), root)
            m = json.loads((path / 'manifest.json').read_text())
            self.assertEqual(m['status'], 'failed')
            self.assertTrue(m['cleanup_errors']); self.assertTrue(vna.closed)

    def test_adapter_single_trigger_and_hold_before_read(self):
        dev = FakeResource(); rm = FakeManager(dev); vna = SiglentVNA('fake', rm)
        vna.configure(config().sweep); vna.set_power(-30); vna.set_output(True)
        trace = vna.acquire(threading.Event())
        self.assertEqual(trace.s_complex.shape, (3,))
        self.assertEqual(dev.commands.count(':TRIG:SEQ:SING'), 1)
        self.assertIn(':SENS1:SWE:GRO:COUN 2', dev.commands)
        self.assertLess(dev.commands.index('*OPC?'), dev.commands.index(':SENS1:DATA:RAWD? S43'))
        self.assertEqual(dev.commands[dev.commands.index('*OPC?') + 1], ':SENS1:SWE:MODE HOLD')
        self.assertEqual(dev.timeout, 5000)
        vna.close(); self.assertTrue(dev.closed); self.assertFalse(rm.closed)

    def test_adapter_malformed_and_timeout(self):
        for malformed, fail_opc, error in [(True, False, ValueError), (False, True, TimeoutError)]:
            dev = FakeResource(malformed, fail_opc); vna = SiglentVNA('fake', FakeManager(dev))
            vna.configure(config().sweep)
            with self.assertRaises(error): vna.acquire(threading.Event())
            self.assertEqual(dev.timeout, 5000); vna.close()

    def test_precancel(self):
        with tempfile.TemporaryDirectory() as root:
            cancel = threading.Event(); cancel.set()
            path = ResonatorPowerSweep(SimulatedVNA()).run(config(), root, cancel)
            m = json.loads((path / 'manifest.json').read_text())
            self.assertEqual(m['status'], 'cancelled'); self.assertEqual(m['traces'], [])


if __name__ == '__main__':
    unittest.main()
