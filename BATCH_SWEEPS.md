# Resonator batches and temperature step sizes — version 1.2

The measurement unit at one temperature is now a **resonator batch**: an ordered list of resonator settings and one shared power sequence.

```text
Temperature 1: Res1 at all powers → Res2 at all powers → … → ResN at all powers
Temperature 2: Res1 at all powers → Res2 at all powers → … → ResN at all powers
…
```

At base, the same batch runs once. LSCI Reader remains untouched. Read-only CH6 T logging is available (see TEMPERATURE_LOGS.md); automatic temperature control is still deferred; the full nested schedule can be rehearsed with the simulator.

## Set up a batch in the GUI

1. Run `launch_power_windows.bat` for base measurements. The initial batch contains Res1.1 with the acquisition settings from your original script.
2. In the left **Resonator editor**, change name, S-parameter, frequency start/stop, IF bandwidth, averaging, point count, timeout and settling time. **Update selected** applies changes to the selected row; **Add to batch** adds a differently named resonator.
3. The **Resonator batch** tab shows the queue. Select rows to edit, remove them, or move them up/down. Names must be unique. Starting or saving is blocked if the editor has unapplied changes, so a changed frequency window cannot silently be omitted.
4. Set **Shared VNA output powers** once. Every queued resonator receives that same list in the same order. An explicit list overrides range/count fields.
5. **Load original 9** loads the nine resonators from your supplied `notch_res_sweep.py`, including each resonator's original frequency range, points, IFBW and averages. It also fills the original −45 to +20 dBm list in 5 dB increments. No lab script is executed.
6. Save settings to preserve the GUI batch, selected row, instrument address and temperature-generator settings. **Export experiment JSON** saves the reusable acquisition input without GUI state.
7. Choose Simulator or your real VNA address, output folder, then **Start batch**. The VNA is configured separately for each resonator with RF off during reconfiguration, using one connection for the full run. Stop retains completed traces and prevents further rows from running.

If every row is removed, the UI explicitly falls back to a single sweep using the editor. Re-add at least one row to create a named batch.

The VNA plot selector shows one resonator at a time, rather than joining different frequency windows on one plot. **Follow active resonator** switches automatically during acquisition. Disable it to inspect a different acquired resonator. The GUI retains the latest 40 traces per resonator for plotting; all acquired traces are saved to disk. Overview PNG files use resonator indices corresponding to the batch order.

## Temperature list by step size

The **Temperature plan** tab is available in the base-power GUI; using it does not operate the fridge.

- Choose **Step size (mK)**, enter start, stop and a positive step magnitude, then **Generate list**.
- Example: start 20, stop 100, step 20 → **20, 40, 60, 80, 100 mK**.
- Descending: start 100, stop 20, step 20 → **100, 80, 60, 40, 20 mK**.
- A stop that is off-grid is **not appended**: start 20, stop 75, step 20 → **20, 40, 60 mK**. The UI reports the actual list and off-grid endpoint. Add 75 manually if a shorter final interval is intended.
- **Number of temperatures** mode still supports linear and logarithmic spacing. Step mode is additive/linear, not logarithmic.
- The explicit generated list remains editable. The exported list—not rounded filenames or an inferred step—is the authoritative acquisition order.

**Export future batch JSON** combines that temperature list with the complete resonator queue and shared powers. Temperature values are converted from GUI mK to stored kelvin. The base launcher continues to run once at unmeasured base even while a temperature plan is being edited. It ignores imported thermal-control settings for actual base acquisition.

For now, use `--simulate` to run an exported future plan. A real temperature sweep requires the future interface to the existing LSCI software; no direct COM3 or heater/PID ownership is enabled.

## Input for scripts / future temperature module

```json
{
  "batch_name": "My resonators",
  "resonators": [
    {
      "name": "Res1",
      "sweep": {
        "start_hz": 5929700000,
        "stop_hz": 5954700000,
        "points": 10001,
        "if_bandwidth_hz": 1000,
        "averages": 7,
        "s_parameter": "S43"
      }
    },
    {
      "name": "Res2",
      "sweep": {
        "start_hz": 7057600000,
        "stop_hz": 7057800000,
        "points": 1001,
        "if_bandwidth_hz": 100,
        "averages": 3,
        "s_parameter": "S43"
      }
    }
  ],
  "powers_dbm": [-45, -40, -35],
  "temperatures_k": [null],
  "temperature_mode": "fixed",
  "thermometry": {"backend": "none"}
}
```

The same input becomes a temperature plan by setting, for example, `temperatures_k: [0.020, 0.040, 0.060]` and `temperature_mode: "controlled"`. The future controller adapter is supplied once to the runner, outside the resonator loop. The simulator already exercises this order.

```python
from resonator_lab import (
    ExperimentConfig, ResonatorConfig, SweepSettings,
    SimulatedVNA, ResonatorPowerSweep, stepped_sequence,
)
from resonator_lab.devices import create_temperature_devices

config = ExperimentConfig(
    batch_name="Device A",
    resonators=[
        ResonatorConfig("Res1", SweepSettings(start_hz=5.9297e9, stop_hz=5.9547e9)),
        ResonatorConfig("Res2", SweepSettings(start_hz=7.0576e9, stop_hz=7.0578e9,
                                              points=1001, if_bandwidth_hz=100, averages=3)),
    ],
    powers_dbm=[-45, -40, -35],
    temperatures_k=stepped_sequence(.020, .100, .020),
    temperature_mode="controlled",
)
vna = SimulatedVNA()
controller, reader = create_temperature_devices(config, vna)
run = ResonatorPowerSweep(vna, controller, reader).run(config, "data")
```

Examples included:

- `examples/base_batch_original.json`: all nine original resonators, one shared list, base only (126 traces).
- `examples/temperature_batch_simulated.json`: the same nine-resonator batch at five planned temperatures; **630 traces**, so simulation is longer than a small demo.

CLI:

```bat
.venv\Scripts\python.exe -m resonator_lab --simulate --config examples\base_batch_original.json --output data
```

Omit `--simulate` and supply your VNA address only for a hardware **base** run. First verify one trace against the physical VNA; Windows and physical-instrument operation remain untested here.

## Data and backward compatibility

A run manifest now states `measurement_order: ["temperature", "resonator", "power"]` and records every per-temperature/per-resonator configuration/readback in `configuration_history`.

Every trace JSON includes `resonator`, `resonator_index`, `resonator_config`, `temperature_index`, `power_index`, requested/readback power and the effective settings for **that trace**. Each NPZ/CSV has its own frequency array and complex samples; resonators may have different point counts. Group fitting results by resonator and temperature indices without assuming a common frequency grid.

Schema **1.2** keeps the same `frequency_hz` and `s_complex` arrays; loaders accept schema 1.0, 1.1 and 1.2. Legacy single-resonator experiment configs still work. A nonempty `resonators` list is authoritative over the legacy top-level `resonator`/`sweep` fields. The legacy manifest `effective_settings` is the **first** configuration only; use each trace or `configuration_history` for a batch.

GUI profiles use version 3 and still import versions 1 and 2. Load settings also accepts exported experiment JSON. Profile save/load preserves resonator order and each row's settings.
