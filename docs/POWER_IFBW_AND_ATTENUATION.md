# Power-dependent IFBW and input attenuation (v1.4)

## Set an IFBW for individual powers

1. Enter the shared power list as usual.
2. Select a resonator in the batch.
3. Open **Power IFBW** and click **Refresh powers**.
4. Select one or multiple rows, enter an IFBW in Hz and click **Set selected IFBW**.
5. Click **Update selected** in the resonator editor to commit those edits to the queued resonator.
6. Repeat for other resonators as needed. Save settings to keep the full configuration.

The editor also accepts explicit overrides such as `-45:10, -35:100, -20:1000`, meaning dBm:Hz. Unlisted powers use that resonator's base IFBW. Overrides are keyed to the numeric power, not its list position: reordering powers preserves their meaning. Duplicate override powers and overrides for deleted/nonexistent powers block Start. Reset overrides to base clears them. A repeated power in the shared list uses the same override each time.

The same overrides are reused at every simulated/future temperature. The requested IFBW is resolved before each trace. The runner switches RF off and reconfigures only when the requested sweep settings change. It verifies the VNA IFBW readback; an unaccepted/rounded bandwidth is an error, so choose instrument-supported values. Lower IFBW may require increasing the resonator's acquisition timeout. The app does not auto-scale timeouts.

## Room-temperature and cold attenuation

The GUI includes separately editable **Room-temperature input attenuation (dB)** and **Cold input attenuation (dB)**, an input-line label and notes. Values must be finite and nonnegative. Enter zero explicitly when a component is absent; blank means unknown.

If both components are entered:

```
nominal_total_db = room_temperature_attenuation_db + cold_attenuation_db
estimated_device_power_dbm = vna_power_readback_dbm - nominal_total_db
```

If either component is unknown, the device-power estimate is null. These fields describe external losses; they do not command an attenuator or change the VNA output-power sequence. Unmeasured cable/connector losses are excluded, and nominal attenuator values need not equal measured insertion loss at each frequency.

The older **Legacy total loss** field remains as an alternative for saved profiles/configs. Use components OR the legacy total. Entering both is rejected to avoid double counting. No losses are subtracted from raw complex samples.

## Line D record — user supplied, 2026-11-17

| Location | Attenuation |
| --- | ---: |
| Room temperature, currently | 20 dB |
| 4 K stage | 20 dB |
| Cold plate | 3 dB |
| Mixing chamber (MXC) | 20 dB |
| Cold total | 43 dB |
| Nominal RT + cold total | 63 dB |

**Load Line D: RT 20 dB + cold 43 dB** fills the editable fields and stage notes. It clears the alternative legacy total. This preset must be explicitly selected; other users do not inherit these losses as global defaults. At -45 dBm VNA output the nominal device estimate is -108 dBm, excluding unmeasured additional losses. Edit the room-temperature value whenever the attenuator changes.

## JSON and saved metadata

Within each resonator:

```json
"power_if_bandwidths": [
  {"power_dbm": -45, "if_bandwidth_hz": 10},
  {"power_dbm": -20, "if_bandwidth_hz": 1000}
]
```

The top-level field of the same name supports legacy single-resonator configs; a nonempty `resonators` batch is authoritative. The top-level attenuation fields are `room_temperature_attenuation_db`, `cold_attenuation_db`, `input_line` and `attenuation_notes`. See `examples/line_d_power_ifbw.json` for a complete two-resonator example.

Each trace saves `requested_settings`, `if_bandwidth_requested_hz`, `if_bandwidth_readback_hz`, `effective_settings`, both attenuation components, the line label/notes and the power estimate. Trace metadata `input_loss_db` remains the resolved total for existing fitting consumers; config `input_loss_db` remains the legacy alternative. Configuration history includes `power_index` for each reconfiguration. NPZ/CSV sample arrays and schema 1.2 are unchanged; GUI settings are version 4 (older profiles still load).

## Diagnostics on Windows

`diagnose_windows.bat` no longer calls the obsolete `python -m visa info`. It runs the existing PyVISA-based diagnostic script, lists available resources, and does not open a resource or change RF. Missing `serial`/`lakeshore` packages do not prevent VNA acquisition or LSCI text-log thermometry; diagnostics no longer suggest installing them for log reading.

Select the Siglent USB/TCPIP resource shown by discovery; do not select COM/ASRL resources. Hardware identity is checked on connection. Your instrument-specific serial/address belongs in a local saved profile rather than this public repository.
