# Temperature integration deferred

LSCI Reader owns the physical controller. Do not use the earlier direct-controller procedure below. Version 1.1.1 blocks that route. Use `launch_power_windows.bat` for base power sweeps; this does not open COM3 or change heater/PID/setpoint settings. A future owner-mediated integration needs the existing logger's file format or supported interface.

## Historical version 1.1 prototype notes

# Falkor temperature integration

## What was reused

The supplied Snoopy script reads a Lake Shore Model 372 using `get_all_input_readings(channel)`, including `kelvin`, resistance, excitation power and quadrature. It applies scheduled manual heater loads in OPEN_LOOP mode, rather than temperature PID. This application reuses the readout pattern, not the manual heat-load schedule or database connection.

Assumption requested for development: Falkor also has a Model 372. Its port, sensor channels, heater resistance/range and tuned gains are **not known**. No Snoopy wiring/heater values are active defaults. Nothing in this application connects to a fridge until a hardware run is explicitly started with valid settings.

## Three useful configurations

| Desired measurement | GUI mode | Thermometry | Regulate |
|---|---|---|---|
| Power sweep at current temperature; log readings | Power sweep at one temperature | Lake Shore 372 | No |
| Set and stabilize one temperature, then all powers | Power sweep at one temperature | Lake Shore 372 | Yes |
| Stabilize each list temperature, all powers at each | Temperature × power sweep | Lake Shore 372 | Yes |

All three work in simulation by selecting Simulator for the VNA and thermometry. Label-only operation remains available without a thermometer, but labels are not reported as measurements.

## Configure at Falkor

Fill in these values when available:

- USB/serial COM port and baud rate, or the **instrument's** TCP address/port. A fridge computer hostname or database endpoint is not a Model 372 TCP endpoint. This version connects directly to the bridge; a remote-service/database/file reader can be added if another computer owns the connection.
- Primary thermometer input (1–16 or A) and all channels to log. Use the thermometer representing the sample/resonator stage. Confirm its calibration and excitation are appropriate for the intended range.
- For regulation: confirmed sample-heater output **0**, its measured/known resistance, allowed maximum power, and chosen Model 372 current-range code. The software checks full-scale `I²R` against that limit before any heater command. It does not calculate a heater setting from Snoopy's 120 Ω value.
- PID gains, in **Lake Shore units**, or leave P/I/D all blank to keep existing tuning. Partial gain triples and zero existing P are rejected. One gain triple is used for the run; gain scheduling/zone control and automatic tuning are not implemented.
- Actual desired base temperature, setpoint ceiling, tolerance, dwell, polling interval, stabilization timeout and passive-cooldown timeout.

The Model 372 sample heater's feedback input must already match the selected primary thermometer. The application checks this before enabling heating. If the primary is a scanned measurement input, the scanner must already be held on it with automatic scanning off; the application does not change scanning. A correctly configured dedicated control input A avoids that measurement-input scanning requirement. Other logged measurement inputs can still return cached values; their actual conversion times are not known.

The application neither configures calibration curves/excitation nor changes the still or warm-up heaters. Its shutdown applies to the selected sample heater. Confirm any existing logger's port ownership before running: do not let independent programs issue commands on the same serial connection. If the lab logger must remain the sole owner, supply its interface and adapt the reader/control transport instead.

## Native PID sequence

At each setpoint the controller adapter checks feedback, disables the sample-heater current range, clears manual output to zero, sets a Kelvin target, optionally applies the supplied P/I/D, selects native CLOSED_LOOP mode and enables the confirmed range. It verifies range, mode, setpoint and any supplied gain readbacks. The bridge executes PID independently while Python waits on the VNA.

The background temperature logger checks sensor-status flags, feedback/scanner configuration, and active range/mode/setpoint. A monitor fault attempts sample-heater/PID shutdown immediately, records the error, and stops the run. Acquired VNA data are retained even if the subsequent temperature read fails. Read-only logging does not issue these heater/control commands.

## Stability and interpreting Q(T)

The default acquisition gate is **within ±2 mK continuously for at least 600 seconds**, with at least three observations. Any sampled out-of-band temperature restarts that timer. Every trace must pass the rolling stable-dwell gate. The timer runs continuously across powers at the same setpoint; if all observations remain in band, the next power does not start a new ten-minute wait. Any sampled excursion between powers resets the timer, and acquisition waits for another full dwell. Each new temperature starts a new dwell. If a boundary reading or samples during acquisition are outside tolerance, the completed trace is flagged/saved and the run stops.

This is a reasonable initial acquisition rule, not proof that the resonator has fully thermalized. At 20 mK the ±2 mK band is 10% of the target; tighten it if the measured Qi(T) sensitivity or repeatability requires that. A thermometer can remain stable while the sample continues to equilibrate. Repeat the same temperature/power points and compare fitted Q and resonant frequency over time, and compare ascending/descending temperature sequences, before deciding whether ten minutes is sufficient. Repeated values and arbitrary order are preserved in lists and trace indices.

Sampling also cannot rule out excursions between readings. Before/after measurements, sampled min/max/count and the full temperature CSV let the later fitting script apply a quality filter. Thermometer observation timestamps are saved; no unverified sensor-conversion timestamps are invented.

## Completion, Stop and failure

On normal completion:

1. Disable VNA RF.
2. Set sample-heater range OFF, PID mode OFF, and manual output zero; store the configured base setpoint with the output off.
3. Keep logging **passive cooling**. Confirm `T <= base + tolerance` for the configured dwell (temperatures below base are accepted). Apply the separate cooldown timeout.
4. Record shutdown/cooldown verification and close connections.

The program does not heat the fridge back to an exact base value while claiming the heater is off. If passive cooling times out, already collected traces remain saved and the run is marked failed, with the heater left off if shutdown was verified.

Stop requests are shared with the thermal monitor: while a VISA acquisition is still blocking, the monitor attempts heater/PID shutdown at its next poll. The VNA worker waits for its current acquisition/timeout and retains any completed trace. Stop/failure initiates passive return by disabling heat and leaving the base setpoint; it does **not** wait for a full base-temperature dwell. The manifest reports `cooldown_confirmed: false` unless that confirmation occurred. The UI closes after worker cleanup.

Communication loss can prevent shutdown verification. Such errors are reported; the software cannot guarantee heater state after a disconnected cable, computer failure or process kill. Verify the Model 372's independent limits and normal lab operating setup before physical use.

## Dependencies and templates

Windows setup installs `lakeshore` along with the acquisition dependencies. Existing environments can run:

```bat
.venv\Scripts\python.exe -m pip install -e ".[temperature]"
```

Templates `examples/falkor_read_only_TEMPLATE.json` and `examples/falkor_pid_TEMPLATE.json` deliberately contain blank/null hardware details. Fill them only with the lab values; they fail validation as shipped. No `dmrdb`, PostgreSQL account, pandas, or Snoopy network credentials are required.

Implementation references: [official Model 372 driver API](https://lake-shore-python-driver.readthedocs.io/en/latest/model_372.html), [Lake Shore dilution-fridge control overview](https://www.lakeshore.com/products/product-detail/model-372/dilution-refrigerator-temperature-control), [Lake Shore driver distribution](https://pypi.org/project/lakeshore/). Hardware behavior has not been verified at Falkor.
