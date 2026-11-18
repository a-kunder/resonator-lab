Version 1.4 adds per-power IFBW and separate room/cold attenuation controls. See [the guide](docs/POWER_IFBW_AND_ATTENUATION.md).

Version 1.3 adds optional read-only CH6 T logging in the base-power GUI. See [TEMPERATURE_LOGS.md](TEMPERATURE_LOGS.md). The no-thermometry instructions below apply when logging is disabled.

# Base-temperature VNA power sweeps

Version 1.2 supports a batch of resonators with shared powers. See [BATCH_SWEEPS.md](BATCH_SWEEPS.md). Click **Update selected** after changing a queued resonator, or **Add to batch** to add a different resonator. **Load original 9** loads all the original frequency windows/settings.

This workflow only connects to the VNA. It does not open COM3, connect to the Lake Shore, change a setpoint, or change the LSCI Reader's heater/PID state. Optional read-only temperature-log integration is available; physical temperature control remains deferred. The temperature value is saved as null unless you explicitly supply an unmeasured label in the general GUI/config.

## Windows

1. Extract the whole application ZIP into a writable folder.
2. Run `setup_windows.bat` to install the Python package and dependencies. A working VISA runtime is needed for the real VNA.
3. Run **launch_power_windows.bat** for the simplified power-only GUI.
4. Select **Siglent SNA5000A**, click **Find VISA instruments**, and enter/select the exact VNA resource address. The address starts blank; copy the exact Siglent resource from discovery.
5. Enter your resonator's frequency window, S-parameter, IF bandwidth, points, averages and output power sequence. Choose the output folder in the scrollable settings pane.
6. Start with one trace at a suitable low power to check communication, averaging and agreement with the VNA display. Hardware acquisition/correction semantics have not yet been tested on your instrument.
7. Run the full sequence. Each completed trace is saved as complex NPZ + CSV + metadata JSON. RF is turned off during final cleanup.

The launcher initially selects **Simulator**, so opening it does not connect to any instrument. The GUI screenshot uses simulated traces and macOS window decorations; the Windows version uses the same controls.

## Original Res1.1 settings supplied in notch_res_sweep.py

| Setting | Value |
|---|---|
| S-parameter | S43 |
| Start / stop | 5.9297 / 5.9547 GHz |
| Points | 10,001 |
| IF bandwidth | 1,000 Hz |
| Averages | 7 |
| VNA output powers | −45 to +20 dBm, 14 values (5 dB spacing) |

`launch_power_windows.bat` preloads these acquisition settings. Other resonators require their own frequency windows. Values are carried over from your script, not measured device limits or a claim that the VNA accepts every setting.

CLI equivalent:

```bat
.venv\Scripts\python.exe -m resonator_lab --config examples\base_power_res1_1.json --address "YOUR_VNA_RESOURCE_ADDRESS" --output data
```

Add `--simulate` to run the example without hardware. Keep the LSCI Reader running as usual; this software does not communicate with it in the base-power workflow.
