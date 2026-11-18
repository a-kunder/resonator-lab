# Architecture and current status

## Supported workflows

- Power sweeps for one or multiple resonators, sharing one ordered power list.
- Per-resonator frequency bounds, base/power-specific IFBW, averages, point count, S-parameter and timing.
- Separate room/cold attenuation metadata and nominal device-power estimates.
- Optional read-only CH temperature log recording from LSCI Reader files.
- Temperature list generation by count or step and simulated temperature batches.

Physical automated temperature control and Qi/Qc fitting are future work. Siglent commands/calibration semantics require physical validation. The original scripts were used as design references; DC-bias and manual heater-load scheduling are excluded.

## Module boundaries

| Module | Responsibility |
| --- | --- |
| `model.py` | Serializable configuration, unit-explicit settings, validation and raw Trace |
| `instruments.py` | Siglent transport and simulated VNA; acquisition and RF state |
| `experiment.py` | Temperature -> resonator -> power orchestration, events and cleanup |
| `storage.py` | Immediate trace persistence, manifest, atomic replacement and loading |
| `thermometry.py` | TemperatureReader/settings plus retained native prototype definitions |
| `log_thermometry.py` | Read-only daily LSCI text-log parsing, freshness and provenance |
| `devices.py` | Shared GUI/CLI factory; rejects direct Lake Shore access |
| `temperature_control.py` | Simulated temperature orchestration and historical native PID prototype |
| `gui.py` | Tk editor, batch queue, plots, temperature planner and worker/event queue |
| `__main__.py` | GUI/CLI entry point |

`launch_power_gui.py` opens base-power mode, supports optional log thermometry, and forces physical regulation off. `launch_gui.py` exposes the general planner/simulator. Command-line JSON goes through `ExperimentConfig.from_dict()` and validation.

## Acquisition lifecycle

1. Validate config and establish the selected devices.
2. Create a run folder and record config/instrument metadata.
3. For each temperature, run each resonator with RF off during reconfiguration.
4. For each shared power: resolve its IFBW override, reconfigure with RF off if needed, verify bandwidth readback, set/read back power, settle, read temperature, acquire one complete averaged trace, read temperature again and save.
5. Save acquired data even if the subsequent temperature read fails; then stop and record the error.
6. Disable RF, close resources and finalize run status on success, cancellation or failure.

The Siglent adapter clears averaging once, uses native TRIG:AVER and a single bus trigger, waits, holds and reads without retriggering during save. Tests use fake VISA; they do not prove the real instrument's firmware behavior.

## Threading

Tk runs on the main thread. VISA/file checks and acquisition run on workers; events cross a queue. Persistent data are independent of plot caches. The GUI caches at most 40 traces per resonator, but saves all completed traces.

## Ownership and prototypes

LSCI Reader is the sole owner of fridge control. File reads do not grant control or prove a ten-minute temperature-stability interval. `LakeShore372Reader` and `LakeShore372PID` remain historical low-level prototypes, exercised with fakes; normal factories and config reject their real backend. THERMAL_CONTROL.md explicitly marks the old workflow as inactive. Do not use it as current setup guidance.

## Validation

Run `python -m unittest discover -s tests -v`. The optional CI template targets Windows and Linux with Python 3.10/3.12; it is not active until installed in .github/workflows (see CI.md). See VALIDATION.md for local evidence and remaining physical checks. GUI rendering, actual log sharing and Windows drivers need separate lab validation.

The native trigger sequence and command references are in [SIGLENT_ACQUISITION.md](SIGLENT_ACQUISITION.md).
