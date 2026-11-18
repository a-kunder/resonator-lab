# Resonator Lab 1.4.1

Acquire complex VNA power sweeps for an **ordered batch of resonators**, with one shared power list. Each resonator has its own frequency window, IF bandwidth, averaging, point count, S-parameter, timeout and settling time. The same batch is the reusable measurement unit at every temperature.

The order is **temperature → resonator → power**. Base mode runs the batch once and leaves LSCI Reader untouched. Read-only CH6 T log integration is available; automatic temperature control is deferred; the complete nested schedule can already be rehearsed with the simulator.

## Start on Windows

Clone this repository (or extract the full source ZIP), run `setup_windows.bat`, then **launch_power_windows.bat**. It opens the simplified base-batch GUI in Simulator mode. Install/use a working VISA runtime and select the correct Siglent USB/TCPIP resource for a real measurement. COM/ASRL resources are rejected by the VNA adapter so it cannot open the logger's COM3 as a VNA.

See [WINDOWS_SETUP.md](WINDOWS_SETUP.md) and the [batch and temperature-step guide](BATCH_SWEEPS.md). Actual VNA acquisition and Windows execution still require lab verification; compare one low-power trace with the instrument display first.

## Power-dependent IFBW and attenuation

Use the **Power IFBW** tab to assign bandwidths to selected power rows for each resonator, then **Update selected** to apply. Unspecified powers use the base IFBW. Overrides stay tied to power values when reordered. Separate editable room-temperature/cold attenuation fields record nominal losses and estimated device power. The explicit **Line D** preset fills 20 dB RT and 43 dB cold (4 K 20 + cold plate 3 + MXC 20). See [the guide](docs/POWER_IFBW_AND_ATTENUATION.md) and `examples/line_d_power_ifbw.json`.

## GUI

- **Resonator editor:** select a queued row, edit its settings, then Update selected. Add to batch creates another resonator with a unique name.
- **Resonator batch tab:** review the order, remove/reorder rows, or Load original 9 from your supplied resonator script. All rows share the powers specified on the left.
- **Save/Load settings:** preserves the batch, editor selection, instrument address, output directory and generator settings. Load settings also accepts experiment JSON. Unapplied editor changes block Start/Save rather than being silently ignored.
- **VNA traces tab:** select one resonator to plot, or follow the active one. The GUI keeps the latest 40 traces per resonator; all data remain saved on disk.
- **Temperature plan tab:** generate by count or by an additive step size in mK. Descending lists are supported with a positive step magnitude. The explicit list remains editable. The base launcher still runs once at base; editing the plan cannot activate temperature control.
- **Export experiment JSON:** reusable input for the base batch. **Export future batch JSON:** the same resonator/power batch repeated over the planned temperatures; use `--simulate` until the owner-mediated temperature interface is implemented.

For fixed steps, stop is included only when aligned: 20→75 mK in 20 mK steps gives 20, 40, 60 mK. No short final step is appended. The displayed/generated list is authoritative.

## Examples / command line

```bat
.venv\Scripts\python.exe -m resonator_lab --simulate --config examples\base_batch_original.json --output data
.venv\Scripts\python.exe -m resonator_lab --simulate --config examples\temperature_batch_simulated.json --output data
```

The first example contains all nine original resonators and fourteen shared powers (126 traces at base). The second repeats them at five temperatures (630 traces). For a real base run, omit `--simulate` and add `--address "YOUR_VNA_USB_OR_TCPIP_RESOURCE"`.

Old single-resonator JSON files still work. GUI profiles accept versions 1–4. The new `resonators` list is authoritative when nonempty; otherwise the legacy `resonator` and `sweep` fields define a single resonator. The original frequency settings are packaged as JSON data; the supplied lab scripts are never executed to load a preset.

```python
from resonator_lab import ExperimentConfig, ResonatorConfig, SweepSettings

config = ExperimentConfig(
    batch_name="Device A",
    resonators=[
        ResonatorConfig("Res1", SweepSettings(start_hz=5.9297e9, stop_hz=5.9547e9,
                                              points=10001, if_bandwidth_hz=1000, averages=7)),
        ResonatorConfig("Res2", SweepSettings(start_hz=7.0576e9, stop_hz=7.0578e9,
                                              points=1001, if_bandwidth_hz=100, averages=3)),
    ],
    powers_dbm=[-45, -40, -35],
    temperatures_k=[None],
)
```

The runner is `ResonatorPowerSweep(vna, temperature_controller=None, temperature_reader=None)`. It owns/closes the supplied devices and saves each completed trace immediately. The same runner supports the future temperature outer loop by supplying the temperature list and an appropriate controller adapter. No direct Lake Shore access is enabled in GUI/config/device construction.

## Data for future Qi / Qc fitting

Each run contains `manifest.json`, reusable `config.json`, and `traces/trace_NNNNN.npz`, `.csv` and `.json` for every acquired trace. The GUI additionally saves per-resonator overview PNGs. Temperature logging files are retained where a simulated/readout interface is used. Per-power IFBW reconfigurations are included in configuration history with their power index.

The NPZ contract remains:

| Array | Type / units |
|---|---|
| `frequency_hz` | float64, Hz |
| `s_complex` | complex128, dimensionless S-parameter |

CSV duplicates the same samples as `frequency_hz,s_real,s_imag` with 17 significant digits. Each resonator has its own frequency axis and may have a different array length. No offsets, phase subtraction, normalization or fit model are applied to stored complex samples. `allow_pickle=False` is sufficient to read NPZ.

Trace JSON includes resonator name/index/config, temperature index, power index, requested/readback power, timestamps and the **effective settings for that trace**. The manifest records acquisition order and per-resonator configuration/readback history. Schema 1.2 loaders also accept 1.0 and 1.1 datasets. Base-temperature measurements with no thermometer connection store null temperatures rather than claiming a measured value.

```python
from resonator_lab import iter_run
for trace in iter_run(r"C:\Lab\data\YOUR_RUN"):
    f, z, metadata = trace.frequency_hz, trace.s_complex, trace.metadata
    resonator = metadata["resonator"]
    power = metadata["vna_power_readback_dbm"]
    # your_existing_Q_fitter(f, z, ...)
```

A mixed-grid example run is included in `examples/sample_batch_run`. The older `sample_run` and `sample_thermal_run` demonstrate backward-compatible loading. The supplied fitting model has not been replaced or assumed.

The Siglent adapter retains `SENS1:DATA:RAWD? Sij` from your wrapper. Verify its calibration/correction semantics, averaging and port-power behavior on the physical VNA before relying on quantitative Q fits. This application does not calibrate the VNA.

## Validation and temperature ownership

Run `python -m unittest discover -s tests -v`. [VALIDATION.md](VALIDATION.md) records the checks and limitations. Tests cover mixed grids, exact ordering, shared powers, reconfiguration with RF off, profile/editor fidelity, cancellation/failure preservation, array precision and temperature-grid endpoints.

LSCI Reader remains the owner of the fridge. Physical temperature control, return-to-base requests and shutdown must eventually go through its supported interface, not competing COM3 access. That integration is not implemented in this release. [THERMAL_CONTROL.md](THERMAL_CONTROL.md) retains explicitly marked historical prototype notes; they are not an active hardware workflow.

## Read temperatures alongside VNA acquisition

Use **Read temperatures from LSCI logs**, choose **Yes**, select Documents/CoolDownData, and click **Check latest temperature**. Channel 6, a 180-second maximum age, and automatic daily-folder following are the defaults. Both CH6 T26-11-17 and CH6 T 26-11-17 filenames work; dated-folder/file profiles follow new sibling daily folders automatically. No additional dependency is needed. See [TEMPERATURE_LOGS.md](TEMPERATURE_LOGS.md) for the observed format, timestamps, daily rollover and failure behavior.

## Development and AI contributors

Read [CONTRIBUTING.md](CONTRIBUTING.md), [AGENTS.md](AGENTS.md), [architecture](docs/ARCHITECTURE.md) and [data-format reference](docs/DATA_FORMAT.md). [PROJECT_MAP.json](PROJECT_MAP.json) provides machine-readable entry points, module responsibilities, commands and capability status. A [GitHub Actions template](docs/github-actions-tests.yml) is provided for Windows/Linux testing; see [activation instructions](docs/CI.md). Completed changes are committed and pushed when access permits. Version 1.4 preserves raw array schema 1.2 and records requested/readback IFBW per trace.

Clone with `git clone https://github.com/a-kunder/resonator-lab.git`. Measurement data belong in the ignored `data/` directory; the tracked sample runs are synthetic. The first Git commit snapshots version 1.3.0 and repository setup, rather than reconstructing earlier local history. See [CHANGELOG.md](CHANGELOG.md).

## License

No software license has been selected. Public visibility alone does not grant a general open-source reuse license.
