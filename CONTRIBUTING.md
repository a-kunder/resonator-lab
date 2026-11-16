# Contributing

Start with README.md and [the architecture guide](docs/ARCHITECTURE.md). AI contributors must also read [AGENTS.md](AGENTS.md). Machine-readable entry points are in [PROJECT_MAP.json](PROJECT_MAP.json).

## Development setup

Use Python 3.9 or newer with Tk installed. On Windows, `setup_windows.bat` creates the environment, installs the package and runs tests. Or use:

```sh
python -m venv .venv
# Activate .venv using the command for your operating system.
python -m pip install -e .
python -m unittest discover -s tests -v
```

The simulator needs no instruments or VISA runtime. On Linux, install your distribution's Python Tk package if `import tkinter` fails. The provided CI template runs headless tests; GUI methods are tested without constructing windows where possible. Live hardware and Windows GUI validation must be reported separately from automated checks.

## Changes and commits

Use a branch for a contribution and open a pull request. State the concrete behavior change, validation and any hardware checks still needed. Update docs and examples together with behavior changes. Include focused tests for acquisition, metadata or failure-handling changes. Keep commits small enough to review and give them descriptive imperative subjects.

The project owner's requested workflow is to commit completed changes and push them to the configured GitHub remote. Do not mix unrelated edits, rewrite published history, or commit generated lab data. See AGENTS.md for the same guidance for AI agents.

## Hardware boundary

Development must default to simulation. LSCI Reader keeps control of the Lake Shore. The enabled temperature reader consumes existing text files only. Direct COM3 access and physical temperature regulation are blocked. Do not enable historical PID prototypes as part of unrelated improvements.

## Compatibility and data

Preserve the documented NPZ/CSV contract and older readers unless a migration is explicitly documented. Each resonator can have a different number of samples; downstream code must read each frequency axis. Use null for unknown values. Do not put credentials, actual fridge logs or machine-specific profiles in issues, commits or test fixtures.

## Licensing

No open-source license has been selected. Public visibility does not itself grant a general reuse license. Obtain the owner's licensing decision before redistribution or adopting a license for contributions.
