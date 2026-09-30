# Development stages

## Completed

1. Inspect Linux hwmon/thermal interfaces and initialize Git.
2. Build an English TUI with live telemetry, diagnostics, demo and text/JSON output.
3. Add supervised manual control: explicit enabling, per-fan targets, strict
   bounds/read-back checks and direct zero-target return to firmware.
4. Add a separate recovery worker, bounded holds, heartbeat monitoring, a
   controller-instance lock and error recovery.
5. Test sensor failures, command validation, worker shutdown/expiry and the
   complete terminal workflow; package the application and publish source/CI.

## Validation still needed on hardware

A real manual set/return cycle with authenticated root access has not yet been
performed on the development host. Test only in an attended session, starting
from firmware control, without competing fan utilities, and verify that actual
RPM responds to an in-range request. The program cannot read the physical SMC
mode; a successful zero write is reported only as driver acceptance.

## Optional future work

- A compatibility matrix for more machines and kernel versions.
- Historical plots and telemetry export.
- A separately installed least-privilege helper and service-manager integration.
- Thermal curves only when dependable sensor coverage and validation exist.

No permanent fan overrides or guessed CPU/GPU temperatures are planned.
