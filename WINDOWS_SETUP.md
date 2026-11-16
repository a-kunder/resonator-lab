Version 1.3: use `launch_power_windows.bat` for multi-resonator base batches; see BATCH_SWEEPS.md for the queue and temperature-step planner.

# Windows setup

The GUI uses Tkinter and Matplotlib, paths use `pathlib`, and acquisition runs on a worker thread. No Linux shell, fixed lab-computer path, or DC source is required. Windows launchers are included; this delivery has not been run on a Windows machine or a physical VNA.

## Install once

1. Install **64-bit Python 3.9 or newer** from [python.org](https://www.python.org/downloads/windows/). Python 3.12 is a conservative choice. Include **pip**, **Tcl/Tk and IDLE**, and the Python launcher where offered. Check “Add Python to PATH” if offered. A code editor is optional.
2. Extract the entire ZIP into a writable folder, for example `C:\Lab\resonator-lab`. Do not run from inside the ZIP. Keep the package folders together.
3. Double-click **setup_windows.bat**. It creates a local `.venv`, installs the package and dependencies, and runs the automated tests. It needs internet access to download packages; no PowerShell activation or execution-policy changes are needed.
4. Double-click **launch_windows.bat**. Leave **Simulator** selected and click **Start batch**. Try saving/loading settings, then the simulated temperature-sweep mode.

If a lab PC has no internet access, prepare an offline wheel directory on an internet-connected **Windows PC with the same Python version and architecture**:

```bat
py -3 -m pip download --dest wheels numpy matplotlib pyvisa lakeshore setuptools wheel
```

Copy `wheels` and the application to the lab PC. In a Command Prompt opened in the application folder:

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install --no-index --find-links=wheels --no-build-isolation -e ".[temperature]"
.venv\Scripts\python.exe -m unittest discover -s tests -v
launch_windows.bat
```

## Enable real VNA communication

PyVISA is a Python interface; hardware also needs a VISA runtime. Install **NI-VISA** or **Keysight IO Libraries Suite**, following your lab's existing driver setup. Avoid replacing an existing working VISA installation. See the [official PyVISA installation instructions](https://pyvisa.readthedocs.io/en/latest/introduction/getting.html) and [NI-VISA setup guidance](https://pyvisa.readthedocs.io/en/stable/faq/getting_nivisa.html).

- Connect the Siglent by USB and confirm that it appears in the vendor's VISA utility (NI MAX or Keysight Connection Expert).
- Run **diagnose_windows.bat** to display Python/VISA details and discovered resources. This does not enable RF.
- In the GUI, choose **Siglent SNA5000A**, click **Find VISA instruments**, and enter the exact resource address for your instrument. The original USB address is supplied as an editable default.
- For LAN, use the address reported/configured by your VISA utility. Allow the required connection on your lab network/firewall if prompted. No administrator access should be needed for ordinary data acquisition after drivers are installed.
- For a VNA-only run, choose **Power sweep at one temperature**, **Label only** thermometry, and regulation **No**. Enter the nominal temperature in **mK**. For measured temperatures, enable **Read temperatures from LSCI logs** and select the CoolDownData folder. Direct Lake Shore access remains blocked. See TEMPERATURE_LOGS.md.
- Confirm the loaded VNA calibration and the measurement path using your normal lab procedure. The program does not perform calibration or load a calibration file.

Before collecting a large dataset, compare one trace at a modest, appropriate power against the VNA display and verify averaging on your firmware. The adapter preserves the supplied wrapper's `SENS1:DATA:RAWD? Sij` readout and grouped-trigger approach. Unsupported SCPI commands are reported as errors. In particular, the meaning of RAWD versus the displayed corrected trace must be verified before using Qi/Qc fits quantitatively. No physical-instrument test was possible during development.

## Current base-power workflow

Use **launch_power_windows.bat**. It opens the base power GUI and never opens COM3 or changes the LSCI Reader. Enable the optional CH6 T log reader to save measured temperatures; with logging disabled temperatures remain null. The current setup installs only the VNA/plotting dependencies. See BASE_POWER_SWEEP.md for the original Res1.1 preset and hardware first-run check.

## Running and stopping

The **Stop after acquisition** button stops the VNA cooperatively: it does not send competing VISA commands from the UI thread. A blocked acquisition can take up to the configured acquisition timeout before cleanup. Closing the window during a run requests Stop and waits for cleanup. RF-off failures are recorded in the manifest and shown in the GUI; a failed cleanup is never reported as a completed run.

## Troubleshooting

- **Python not found:** reopen the installer, enable the launcher/PATH option, or use `python` from your Python installation. The setup script checks both `py` and `python`.
- **No module named tkinter:** modify the Python installation to include Tcl/Tk; `pip install tkinter` is not the solution.
- **Could not locate VISA implementation:** install/repair your chosen VISA runtime, then restart the application. Match Python and driver architecture.
- **No resources listed:** confirm USB cable, instrument power, driver detection, and VISA utility configuration. A network instrument may require a manually configured address.
- **Timeout / SCPI errors:** check the correct model, firmware, frequency range, S-parameter, timeout, and supported sweep settings. If an acquisition timed out, confirm instrument communication and clear any pending response before retrying; reconnect or restart the instrument session as needed.
- **Package downloads blocked:** use your organization's approved Python package mirror or the offline wheel procedure. Do not disable certificate verification.
- **Access denied saving data:** choose a writable data folder. Settings and outputs are ordinary files, with no registry configuration.

To update after receiving revised source, replace the source files and rerun setup_windows.bat. Preserve your `data` folders and settings profiles.
