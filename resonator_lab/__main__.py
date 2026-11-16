"""GUI by default; scriptable CLI with --config."""
import argparse
import json
import signal
import threading
from .model import ExperimentConfig
from .instruments import SiglentVNA, SimulatedVNA, DEFAULT_ADDRESS
from .experiment import ResonatorPowerSweep
from .devices import create_temperature_devices


def main():
    parser = argparse.ArgumentParser(description='Resonator Lab: desktop GUI or configured VNA acquisition')
    parser.add_argument('--config', help='Experiment config JSON; omit to launch GUI')
    parser.add_argument('--simulate', action='store_true', help='Use the simulated VNA')
    parser.add_argument('--address', default=DEFAULT_ADDRESS, help='VISA address for a hardware run')
    parser.add_argument('--output', default='data', help='Run output root')
    args = parser.parse_args()
    if not args.config:
        from .gui import main as gui_main
        gui_main()
        return
    with open(args.config, encoding='utf-8') as stream:
        config = ExperimentConfig.from_dict(json.load(stream))
        cancel = threading.Event()
    signal.signal(signal.SIGINT, lambda *unused: cancel.set())
    result = {}
    def event(kind, data):
        if kind in ('status', 'run_started'):
            print(data, flush=True)
        elif kind == 'finished':
            result.update(data)
            print(json.dumps(data, indent=2), flush=True)
    vna = SimulatedVNA() if args.simulate else SiglentVNA(args.address)
    try:
        controller, reader = create_temperature_devices(config, vna)
    except BaseException:
        vna.close()
        raise
    ResonatorPowerSweep(vna, controller, reader).run(config, args.output, cancel, event)
    if result.get('status') != 'completed':
        raise SystemExit(130 if result.get('status') == 'cancelled' else 1)


if __name__ == '__main__':
    main()
