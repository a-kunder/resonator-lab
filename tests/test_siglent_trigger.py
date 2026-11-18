"""Protocol regressions for native SNA5000A average triggering, without hardware."""
import threading
import unittest
from resonator_lab import SiglentVNA, SweepSettings
from test_acquisition import FakeResource, FakeManager


class NativeSiglentResource(FakeResource):
    def __init__(self, refuse_trigger_average=False):
        super().__init__()
        self.factor = 2
        self.average_enabled = False
        self.trigger_average = False
        self.refuse_trigger_average = refuse_trigger_average
        self.completed_sweeps = 0
        self.clears = 0
        self.reads = 0

    def write(self, command):
        if ':GRO' in command or command.startswith(':SENS1:SWE:MODE'):
            raise AssertionError('Foreign sweep/group command: ' + command)
        super().write(command)
        if command.startswith(':SENS1:AVER:COUN '):
            self.factor = int(command.split()[-1])
            if not 2 <= self.factor <= 999:
                raise AssertionError('SNA5000A average factor must be 2..999')
            self.replies[':SENS1:AVER:COUN?'] = str(self.factor)
        elif command.startswith(':SENS1:AVER '):
            self.average_enabled = bool(int(command.split()[-1]))
            self.replies[':SENS1:AVER?'] = str(int(self.average_enabled))
        elif command.startswith(':TRIG:AVER '):
            self.trigger_average = bool(int(command.split()[-1])) and not self.refuse_trigger_average
            self.replies[':TRIG:AVER?'] = str(int(self.trigger_average))
        elif command == ':SENS1:AVER:CLE':
            self.completed_sweeps = 0
            self.clears += 1
        elif command == ':TRIG:SEQ:SING':
            self.completed_sweeps += self.factor if self.average_enabled and self.trigger_average else 1

    def query_ascii_values(self, command):
        self.reads += 1
        if self.completed_sweeps != (self.factor if self.average_enabled else 1):
            raise AssertionError('Read before complete average')
        if self.commands[-2:] != [':TRIG:MODE HOLD', ':SYST:ERR?']:
            raise AssertionError('Must hold and check errors before reading')
        return super().query_ascii_values(command)


class NativeTriggerTests(unittest.TestCase):
    def configure(self, averages, **kwargs):
        dev = NativeSiglentResource(**kwargs)
        vna = SiglentVNA('TEST', FakeManager(dev))
        self.addCleanup(vna.close)
        effective = vna.configure(SweepSettings(start_hz=100,stop_hz=200,points=3,averages=averages))
        return dev, vna, effective

    def test_seven_averages_one_native_trigger_no_foreign_group_commands(self):
        dev, vna, effective = self.configure(7)
        trace = vna.acquire(threading.Event())
        self.assertEqual(dev.completed_sweeps, 7)
        self.assertEqual(dev.clears, 1)
        self.assertEqual(dev.reads, 1)
        self.assertEqual(dev.commands.count(':TRIG:SEQ:SING'), 1)
        self.assertEqual(trace.metadata['acquisition_average_count'], 7)
        self.assertEqual(trace.metadata['acquisition_strategy'], 'siglent_native_averaging_trigger')
        self.assertTrue(effective['trigger_averaging_enabled'])

    def test_one_average_disables_averaging_without_invalid_factor_one(self):
        dev, vna, effective = self.configure(1)
        vna.acquire(threading.Event())
        self.assertEqual(dev.completed_sweeps, 1)
        self.assertNotIn(':SENS1:AVER:COUN 1', dev.commands)
        self.assertEqual(effective['averages'], 1)
        self.assertEqual(effective['averaging_factor_readback'], 2)
        self.assertFalse(effective['trigger_averaging_enabled'])

    def test_each_power_trace_restarts_average_only_once(self):
        dev, vna, unused = self.configure(7)
        for _ in range(2):
            vna.acquire(threading.Event())
            self.assertEqual(dev.completed_sweeps, 7)
        self.assertEqual(dev.clears, 2)
        self.assertEqual(dev.commands.count(':TRIG:SEQ:SING'), 2)
        self.assertEqual(dev.reads, 2)

    def test_rejected_average_trigger_fails_before_acquisition(self):
        with self.assertRaisesRegex(RuntimeError, 'averaging-trigger'):
            self.configure(7, refuse_trigger_average=True)
