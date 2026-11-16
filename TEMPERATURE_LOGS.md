# Temperature recording from the existing LSCI logs (v1.3)

This integration reads the text files already written by LSCI Reader. It never opens COM3, sends Lake Shore commands, or changes PID, heaters, scanner or setpoints. The user confirmed that acquisition runs on the same Windows PC, CH6 T is the mixing-chamber thermometer and a new sample arrives about once per minute.

## Windows GUI

1. Extract the new package and launch `launch_power_windows.bat`. Existing dependencies suffice; rerun `setup_windows.bat` if this is a new installation.
2. In **Read temperatures from LSCI logs**, select **Yes**.
3. Choose the actual **Documents/CoolDownData** folder. The suggested home directory path is editable because Windows Documents may be redirected. You can also choose one daily folder or an individual temperature file.
4. Leave channel **6** and maximum reading age **180 seconds** initially.
5. Click **Check latest temperature**, compare it with LSCI Reader, then run the resonator batch as usual.

Logging is optional and disabled initially so existing base-power profiles still run. Save settings to retain your path/channel/age selection. If you enable logging, missing, invalid or stale temperatures stop the run rather than silently dropping temperature recording. If a failure happens after VNA acquisition, that acquired trace is saved with the read error before the run stops. RF is disabled during cleanup.

No additional Python dependency or Lake Shore driver is required for file reading. Keep LSCI Reader running and logging. File sharing must permit readers; a sharing violation is reported as an error rather than taking ownership.

## Observed file and record format

The supplied photo shows `CoolDownData/26-11-16/CH6 T 26-11-16.txt` (Explorer hides `.txt`) with rows like:

```
16-11-26,00:30:08,1.432770E-2
```

Filenames use **yy-mm-dd**. Row dates use **dd-mm-yy** and 24-hour local time. Values are kelvin: this example is **14.3277 mK**. Only `CH6 T` (or the selected channel's `T`) is accepted; `R`, `P` and MaxiGauge pressure logs are excluded. The reader supports UTF-8/ASCII and UTF-16 with a byte-order mark, CRLF/LF line endings, and scientific notation.

Select the top-level CoolDownData folder for unattended daily rollover. On every snapshot the reader searches the selected folder and its immediate daily subfolders and selects the newest dated matching temperature file. A selected daily folder or individual file stays pinned; it will eventually become stale after midnight. Duplicate newest-date files require choosing a more specific folder/file. No complete row in the newest file is an error.

Only complete newline-terminated rows are consumed, so an unfinished append is ignored. A malformed latest complete record is an error; the reader does not silently revert to an older valid record. It reads a bounded 64 KiB tail and closes the file immediately after each read.

## Timing and saved data

A snapshot is read before and after each VNA trace. With one-minute logging, fast traces may share the same temperature sample. A log sample is not a simultaneous thermometer conversion; the app does not interpolate or claim new samples between logger updates.

Each trace's JSON includes `temperature_before_k`, `temperature_after_k` and complete `temperature_snapshot_before`/`temperature_snapshot_after` records, including:

- `source_timestamp_utc`: original log time converted from this PC's local timezone.
- `read_ended_utc`: time the app observed the file.
- `age_s`: difference between those timestamps; the default maximum is 180 seconds.
- `log_file` and `source_line`: exact source and row for auditing.
- `primary_channel`, kelvin value and `simulated: false` for the thermometer source.

`temperature_log.csv` also includes source time, age, file and row at each trace boundary. Raw VNA complex arrays and fitting inputs remain unchanged. A simulated VNA can read an actual log file for an end-to-end rehearsal; the trace metadata still identifies the VNA as simulated.

Keep the Windows clock and timezone correct. Future timestamps more than five seconds ahead are rejected; smaller negative ages are retained explicitly. Age checks use the sample timestamp, never file modification time. Logs are interpreted in the local timezone of the acquisition PC, which is appropriate for the confirmed same-PC setup. A future move to a different-timezone computer needs an explicit timezone option.

## Scope

This version records temperature for base/single-temperature power batches, including all resonators. The temperature-history tab is available in the base GUI and plots snapshots at the app read times. It does not yet use the logs to prove a ten-minute stability window, change temperature targets or perform automated physical temperature sweeps. Setpoint/PID/heater ownership stays with LSCI Reader. The existing temperature step planner and simulated temperature sweeps remain available.

The parser was implemented from the visible photo. An actual log file and a Windows lab run are still needed to verify the precise encoding, append behavior and file sharing on Falkor.
