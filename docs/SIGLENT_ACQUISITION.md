# Siglent SNA5000A acquisition sequence (v1.4.2)

## Observed lab failure

The supplied Windows error reports SCPI -113 for `SENS1:SWE:GRO:COUN 7`, followed by -224 and -200. The previous grouped-sweep path was incompatible with the connected SNA5014A firmware. This is an adapter issue, not evidence of a temperature-reader failure. The same screenshot shows a successful LSCI log reading.

## Documented replacement

The [official SNA5000A programming guide](https://siglentna.com/wp-content/uploads/dlm_uploads/2021/10/SNA5000A_ProgrammingGuide_PG09050_E01A.pdf), sections 4.5.1–4.5.2, documents `TRIG:AVER` and `TRIG:MODE`. With average triggering enabled, one trigger performs the configured averaging factor. The guide's trigger-single section documents `TRIG:SEQ:SING` and waiting with `*OPC?`. The [E03 guide](https://siglentna.com/wp-content/uploads/dlm_uploads/2022/11/SNA5000A_ProgrammingGuide_PG09050_E03.pdf) also documents these commands and the averaging factor range 2–999.

Configuration uses channel 1 and:

```
:TRIG:MODE HOLD
:SENS1:AVER:COUN <N, at least 2>
:SENS1:AVER <1 for N>1, otherwise 0>
:TRIG:SEQ:SOUR BUS
:TRIG:AVER <1 for N>1, otherwise 0>
```

Both averaging and averaging-trigger states are read back and validated. A one-sweep request disables both, keeps a valid inactive factor of 2, and records effective `averages: 1` separately from `averaging_factor_readback: 2`.

For each trace:

```
:SENS1:AVER:CLE
:TRIG:SEQ:SING
*OPC?
:TRIG:MODE HOLD
:SYST:ERR?
:SENS1:DATA:RAWD? <Sij>
```

The application clears accumulation once, waits for one native averaged acquisition, then reads once. Saving does not trigger another acquisition. The adapter sends no GRO commands and does not put the VNA into continuous sweeping after the read.

Trace metadata includes `acquisition_strategy: siglent_native_averaging_trigger`, `acquisition_trigger_count: 1` and `acquisition_average_count`. Requested/effective settings are also saved as before.

## Lab check still required

Regression tests use a fake resource that rejects foreign group/sweep-mode commands, enforces the documented averaging-count range and checks native-trigger state/order. They cover seven averages, one unaveraged sweep, restarting a subsequent trace and rejected trigger-average readback. Existing OPC timeout, malformed data, RF-off cleanup and data preservation tests remain.

This is checked against the command reference, not yet a successful physical acquisition. Update to v1.4.2, confirm the title, then try one resonator at one appropriate low output power with your intended averaging. No factory preset or firmware update is part of this fix. The separate RAWD/calibration/averaging-data semantics still need comparison against the instrument display before quantitative fits.
