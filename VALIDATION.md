# Version 1.4.2 validation — 2026-11-17

- All 72 tests passed with Python 3.11 in 13.242 seconds, including four new native Siglent trigger protocol regressions. The fake resource rejects GRO/foreign sweep-mode writes and validates averaging trigger use, one-sweep handling with a legal inactive factor, single clear/trigger/read per trace, repeated acquisitions and fail-before-acquisition on refused trigger-average readback.
- Updated existing adapter order checks to assert native triggering, OPC then HOLD before RAWD, with no GRO commands. Existing timeout restoration, malformed-data, RF-off/error preservation and batch/logging tests pass.
- Official Siglent programming-guide sections document native TRIG:AVER, TRIG:MODE and TRIG:SEQ:SING/OPC synchronization; see docs/SIGLENT_ACQUISITION.md.
- No real VNA acquisition was performed here. User lab screenshot establishes that the old GRO command is rejected and LSCI logging succeeds, not that the replacement is physically validated. Calibration/RAWD semantics remain a lab check.

---

# Version 1.4.1 validation — 2026-11-17

- All 68 automated tests passed with Python 3.11 in 13.188 seconds. Eight added tests cover actual no-space and spaced filenames, case/extensions/four-digit dates, saved dated-folder/file rollover without restart, a missing saved daily folder, empty/partial new-day files with freshness-gated fallback, malformed complete new-day records, explicit pinning/duplicate rejection, recursive year/month layout, channel/quantity filtering, and settings serialization/type checks.
- Local Tk smoke test passed: version 1.4.1 title, automatic-follow default, actual-style no-space filename in a selected dated folder, and asynchronous GUI temperature check.
- No physical instruments or real log files were read. The fix is based on filenames visible in the supplied Windows photo; real log encoding/sharing still needs lab verification. Sensor timestamp age checks, source provenance and LSCI ownership are preserved.

---

# Version 1.4 validation — 2026-11-17

- All 60 automated tests passed with Python 3.11 in 12.622 seconds. Nine new tests cover power-keyed IFBW schedules, reordering/base fallback, invalid/deleted override powers, legacy and component attenuation semantics, nested temperature/resonator/power metadata, RF-off reconfiguration, failed reconfiguration preserving completed data, GUI parser/Line D preset, and rejection of unaccepted instrument IFBW readback.
- Local Tk smoke test passed: power-table row editing, unapplied-change guard, GUI profile v4 save/load, power reordering, Line D preset (63 dB total), and simulated 3-trace acquisition with IFBW [1000, 300, 10] Hz and estimated device powers [-83, -98, -108] dBm.
- Complete example `line_d_power_ifbw.json` ran in CLI simulation: 2 resonators x 3 powers, completed with no cleanup errors.
- User-provided Windows screenshots show the earlier v1.3 setup passed 51 tests on the lab PC, and the VISA backend enumerated the Siglent resource. They also exposed the obsolete `-m visa info` command and irrelevant optional serial-driver advice, corrected here. No physical trace/calibration/IFBW acceptance check is claimed.
- Raw array schema remains 1.2 with additive metadata; old inputs/data remain covered by regression tests. GUI profiles v1-v3 still load; new saves use v4.

---

# Version 1.3 validation — 2026-11-16

- 51 automated tests passed with Python 3.11 (9.306 seconds), including all prior acquisition, batch and ownership tests plus nine log-reader tests.
- Log tests use the visible CH6 T row format from the photo. Cover exact kelvin conversion, source timestamps/age/provenance, no source-file writes, daily rollover, wrong R/P quantity rejection, UTF-16/large tails, partial appends, malformed/latest-invalid/stale/future/missing data, read-only factory behavior, base-GUI config, JSON/CSV persistence and saving a completed trace before stopping on a stale post-acquisition reading.
- Tk GUI construction and asynchronous Check latest temperature passed in a local smoke test with a generated current-time log: 14.32 mK, LSCI log, age 0 s. This was a functional smoke test, not Windows visual QA.
- No VNA or Lake Shore hardware was contacted. The lab's actual log file encoding, append/file-sharing behavior, Windows execution and physical VNA commands still require lab verification.
- VNA array schema remains 1.2; temperature source/provenance fields are additive. Earlier data remains loadable.

---

# Version 1.2 batch and step-size validation

The regression suite and new batch checks passed on Python 3.11.13 / NumPy 2.3.1 on macOS. Tests cover temperature → resonator → power ordering; different point counts, frequency windows, IF bandwidths and averages; one shared power order; RF-off during reconfiguration; cancellation/failure in later resonators; manifest configuration history; legacy single-resonator configs; exact editor frequency round trips for all nine original resonators and fractional-Hz endpoints; stepped grids including decimal, descending and off-grid cases; and rejection of serial VNA addresses before any port is opened.

A native GUI test completed a three-resonator × two-power run with different point counts, and exercised add/update/remove/reorder, unapplied-edit detection, profile version 3 save/load, plot selection, overview saving, and temperature-step generation/export. A follow-up harness checked that all nine imported original resonators could be started without false editor-dirty detection. The GUI was also captured with the temperature-step planner visible.

An exported five-temperature × three-resonator × two-power plan completed all 30 simulated acquisitions in the intended order. No physical VNA or Lake Shore was contacted. Windows and physical-instrument validation remain pending; LSCI ownership is preserved and direct fridge integration remains disabled.

Earlier validation records follow for historical detail:

# Version 1.1.1 base-workflow checks

Three additional tests cover imported-profile isolation in the power-only GUI, unknown/unmeasured base temperature and rejection of direct Lake Shore ownership. The actual native GUI was launched and captured on macOS, with a simulated 14-power × 10,001-point Res1.1 sweep and temperature integration disabled. Physical Siglent acquisition and Windows execution remain unverified. See BASE_POWER_SWEEP.md.

# Validation of version 1.1

## Completed checks

**30 automated tests passed** on Python 3.11.13 / NumPy 2.3.1 on macOS. These include:

- Exact complex NPZ and full-precision CSV round trips; legacy schema 1.0 loading.
- VNA command ordering and averaging group count using fake VISA, HOLD before readout, malformed-data rejection, and timeout restoration.
- Cancellation, incremental trace preservation, connection cleanup and cleanup-error reporting.
- Explicit thermometry configuration, multi-channel readouts and timestamps, sensor-status rejection, and absence of heater writes in the read-only adapter.
- No assumed Falkor heater wiring or power limit; full-scale current-range power checks; feedback-input checks before heating.
- Sampled 600-second dwell, reset after excursions, timeout/cancellation, reuse of the rolling dwell across powers and reacquisition of the dwell after a new excursion. Time injection or acceleration avoids waiting ten minutes in tests.
- Native-PID supervision through an injected simulated bridge, verified heater/PID OFF and base-setpoint shutdown, passive cooldown confirmation, and monitor-triggered shutdown on invalid readings or Stop.
- Stop while a fake VNA is still busy: the monitor disables heating before the VNA returns, and completed complex data are retained.
- An excursion during acquisition is flagged even if the before/after temperatures are both good.
- Thermometry failure after acquisition preserves the completed VNA trace with an error flag.

The CLI completed an accelerated **20 / 100 / 800 mK × 3-power** run, including native-supervision simulation, rolling-dwell gates, continuous CSV logging and passive cooldown.

GUI functional smoke checks completed a single-temperature power sweep and a two-temperature nested sweep. They verified Start/worker events, progress, VNA/temperature plotting, temperature-list generation (linear and logarithmic), overview/thermal PNG saving, profiles and old-profile migration, completed-state controls, and rejection of unconfigured physical PID settings. The exported thermal plot was visually inspected.

The local headless macOS display reports zero/invalid DPI, so the GUI smoke harness supplied a **test-only** pixel conversion for toolbar icons. Those UI checks used the available older Python 3.7/Tk runtime. A separate local Python 3.11 GUI attempt could not initialize Tk because of a native macOS display/menu exception before application construction. This establishes functional GUI behavior in the available harness, not Windows visual QA. The supported package target remains Python >=3.9.

## Not established by these checks

No physical VNA or temperature controller was contacted. Windows installation/driver discovery, actual Model 372 command acceptance/connection details, calibration/thermometer conversion freshness, heater wiring/resistance/limits, gain tuning across 20–800 mK, achieved stability, resonator thermalization and passive base-temperature recovery remain to be checked at Falkor. The tests establish software behavior and fake-driver command flow, not physical performance or a shutdown guarantee after a broken connection.

See WINDOWS_SETUP.md and THERMAL_CONTROL.md. The hardware templates are incomplete by design and fail validation until the missing lab values are filled.
