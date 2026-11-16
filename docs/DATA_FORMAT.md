# Data and configuration reference

## Experiment input

Input is UTF-8 JSON accepted by `ExperimentConfig.from_dict()`. Runtime validation in model.py is authoritative, including cross-field constraints. Unknown dataclass keys are rejected. GUI settings profiles are separate objects with `gui_schema_version: 3`; prefer **Export experiment JSON** for scripts.

| Field | Meaning / units |
| --- | --- |
| `resonators` | Ordered `{name, sweep}` objects; nonempty list overrides legacy `resonator`/`sweep` |
| `batch_name` | Human-readable run name for a batch |
| `powers_dbm` | Shared ordered finite VNA output powers; no device attenuation correction applied |
| `temperatures_k` | Kelvin targets/labels; `[null]` means unknown base temperature in fixed mode |
| `temperature_mode` | `fixed` or `controlled`; physical automated control is not enabled |
| `temperature_tolerance_k` | Positive tolerance for controlled simulations |
| `temperature_timeout_s` | Positive stabilization timeout |
| `input_loss_db` | Optional nonnegative loss; estimated device power = VNA power minus loss |
| `thermometry` | `none`, `simulator` or `lsci_log`; legacy `lakeshore372` is rejected |
| `pid` | Simulator/prototype settings; not permission to control real hardware |
| `notes` | User annotation |

Each sweep defines `start_hz`, `stop_hz`, `points`, `if_bandwidth_hz`, `averages`, `s_parameter`, `timeout_s`, `settle_s`. Start must be below stop, points >= 2, averages >= 1. For log thermometry, set `backend: "lsci_log"`, `log_path`, `log_channel: "6"`, `log_max_age_s: 180`. See TEMPERATURE_LOGS.md for timestamp parsing. Examples are complete executable inputs except explicitly named inactive templates.

## Run directory

- `config.json`: input configuration.
- `manifest.json`: run ID, instrument, config, status, trace list, order and configuration history.
- `traces/trace_00000.npz`: numeric arrays.
- Matching `.csv` and `.json`: same samples and trace-specific metadata.
- `temperature_log.csv`: before/after snapshots; may contain only a header with logging disabled.
- GUI runs may also contain overview PNGs.

`manifest.status` is `running`, `completed`, `cancelled` or `failed`. A failed/cancelled run can contain valid completed traces. Do not infer success from a folder's existence. Individual files use temporary-file replacement; the three trace files are not a single multi-file transaction. Use the manifest trace list and loaders to find registered traces.

## Numeric arrays (schema 1.2)

| NPZ key | Dtype | Shape | Units |
| --- | --- | --- | --- |
| `frequency_hz` | float64 | `(N,)` | Hz, strictly increasing |
| `s_complex` | complex128 | `(N,)` | Dimensionless complex S-parameter |

Load with `numpy.load(path, allow_pickle=False)`. CSV columns are `frequency_hz,s_real,s_imag` with 17 significant digits. Stored samples have no normalization, magnitude offset, phase subtraction or fitted correction. Grids/lengths can differ across resonators.

## Trace metadata

Use `resonator`, `resonator_index`, `temperature_index`, `power_index` to group data. `resonator_config` and `effective_settings` describe that trace's sweep; manifest `effective_settings` is only the first configuration. Use `configuration_history` for all configurations.

`vna_power_requested_dbm` and `vna_power_readback_dbm` distinguish request/readback. `estimated_device_power_dbm` is null unless an input loss was provided. `temperature_label_k` is a label, not a reading; `temperature_target_k` is for controlled runs. Measured values are `temperature_before_k`/`temperature_after_k` or null, with full provenance in their snapshots. Log snapshots include source timestamp, observation time, age, file and original row. A repeated source timestamp means a reused logger sample.

`acquisition_started_utc`/`acquisition_ended_utc` are ISO-8601 UTC. Trace `simulated` describes the VNA; each thermometer snapshot separately declares its own source/simulation flag. A simulated VNA can be paired with a real log reader.

Loaders accept schemas 1.0, 1.1 and 1.2. Additive fields may be absent in older traces. Use `.get()` for optional metadata. Future fit results should be separate derived files, preserving raw data and recording the fit model/version, exclusions and quality metrics. Qi/Qc fitting is not yet implemented.
