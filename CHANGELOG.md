# Changelog

## 1.4.2 — 2026-11-17

- Replace unsupported grouped-sweep commands with documented Siglent TRIG:AVER native averaging trigger and TRIG:MODE HOLD.
- Validate trigger-average readback and record acquisition strategy/count metadata.
- Disable averaging for one-sweep requests without writing invalid averaging factor 1.
- Add protocol regression tests rejecting the previous unsupported command path.

## 1.4.1 — 2026-11-17

- Accept actual no-space LSCI filenames such as CH6 T26-11-17.txt, plus spaced names and case/extension/date-width variants.
- Default automatic daily rollover from root, dated-folder or daily-file profiles; recursive root search and explicit pin-mode option.
- Bridge empty/partial midnight files only with still-fresh previous-day data; never hide malformed complete records or stale data.
- Display application version in the GUI title to identify old launches.

## 1.4.0 — 2026-11-17

- Power-keyed IFBW overrides for each resonator; editable GUI table and settings profiles v4.
- Separate room-temperature/cold attenuation fields, input-line notes and explicit editable Line D preset (20 + 43 dB).
- Requested/readback IFBW per trace, per-power configuration history and nominal device-power metadata.
- Reject unaccepted IFBW readback; preserve completed traces if later reconfiguration fails.
- Fix obsolete VISA diagnostic command; remove serial-driver advice for text-log thermometry.
- User Windows screenshots show version 1.3 setup/tests succeeded (51 tests) and VISA enumeration found the Siglent. Physical trace/calibration verification remains pending.

## Repository setup

- Establish standalone Git repository, contributor/AI instructions, machine-readable project map and Windows/Linux CI template.
- Document configuration, raw data and ownership contracts for downstream analysis.

## 1.3.0 — 2026-11-16

- Read-only LSCI daily temperature logs, freshness checking and per-trace provenance.
- GUI log selection/checking and temperature history in base mode.

## 1.2.0

- Ordered resonator batches with shared powers and individual sweep settings.
- Temperature planning by count or additive step; mixed-grid storage/history.

## 1.1.1

- Preserve LSCI Reader ownership; block direct controller access in normal workflows.
- Represent unmeasured base temperatures as null.

## 1.0–1.1

- Initial modular acquisition, simulator, GUI, raw complex export and temperature prototypes.

These earlier versions were local deliverables. The initial repository commit snapshots the current source; it does not reconstruct earlier Git history.
