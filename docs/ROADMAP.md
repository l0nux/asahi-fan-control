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

6. Add a GNOME 51 extension with asynchronous telemetry/control, system
   authentication, a standalone ZIP and GJS/headless GNOME integration tests.

7. Keep GNOME targets active until Auto or session end, add a shared RPM field
   and 2000/3000/4000 RPM presets, and test continued supervision and recovery.

## Hardware validation completed locally

An attended real-worker test verified upward RPM response, explicit automatic
return acknowledgement, normal hold expiry, and recovery after client EOF.
The test exposed delayed SMC target read-back; bounded settling was added while
preserving strict validation and recovery on failure. Device-specific readings
and reports remain local and are not committed.

Additional models and kernel versions still need their own validation. The
physical SMC mode is not readable; driver acceptance and observed RPM response
are reported separately. No hardware fail-safe guarantee is made.

## Optional future work

- A compatibility matrix for more machines and kernel versions.
- Historical plots and telemetry export.
- A separately installed least-privilege helper and service-manager integration.
- Thermal curves only when dependable sensor coverage and validation exist.

No permanent fan overrides or guessed CPU/GPU temperatures are planned.
