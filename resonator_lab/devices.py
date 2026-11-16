"""Construct temperature devices for either the GUI or command line."""
from .instruments import SimulatedVNA
from .log_thermometry import LSCILogReader
from .thermometry import LakeShore372Reader, TemperatureReader
from .temperature_control import LakeShore372PID, SimulatedPIDTemperature
from .storage import utc_now


class SimulatedTemperatureReader(TemperatureReader):
    def __init__(self, vna, temperature_k):
        if not isinstance(vna, SimulatedVNA):
            raise ValueError('Simulated thermometry requires a simulated VNA.')
        self.vna = vna
        self.vna.temperature_k = temperature_k

    def read_snapshot(self):
        stamp = utc_now()
        return {'source': 'simulator', 'primary_channel': 'SIM', 'primary_kelvin': self.vna.temperature_k,
                'started_utc': stamp, 'ended_utc': stamp, 'simulated': True,
                'channels': {'SIM': {'kelvin': self.vna.temperature_k, 'read_ended_utc': stamp}}}

    def close(self):
        pass


def create_temperature_devices(config, vna):
    backend = config.thermometry.backend
    if backend == 'lakeshore372':
        raise ValueError('Direct Lake Shore access is disabled: LSCI Reader retains ownership. Use VNA-only mode for now.')
    if backend == 'lsci_log':
        if config.temperature_mode != 'fixed':
            raise ValueError('LSCI logs provide read-only temperatures, not setpoint control. Use a single-temperature power batch.')
        return None, LSCILogReader(config.thermometry)
    if backend == 'simulator' or (config.temperature_mode == 'controlled' and isinstance(vna, SimulatedVNA)):
        if config.temperature_mode == 'controlled':
            controller = SimulatedPIDTemperature(vna, config.pid, config.temperature_tolerance_k)
            return controller, controller
        return None, SimulatedTemperatureReader(vna, config.temperatures_k[0] if config.temperatures_k[0] is not None else vna.temperature_k)
    if config.temperature_mode == 'controlled':
        raise ValueError('Regulated temperatures require Lake Shore PID or simulated thermometry.')
    return None, None
