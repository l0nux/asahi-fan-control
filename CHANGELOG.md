# Release notes

## 0.2.0

- Added a Control view with fan selection, RPM entry, explicit driver enabling
  and return-to-firmware actions.
- Added --control, --enable-control, --set, --auto and --hold-seconds.
- Added a separate recovery worker with bounded holds, UI heartbeat monitoring,
  exclusive application lock, feedback checks and cleanup on disconnect/signals.
- Require valid positive hardware bounds and verify target read-back; no guessed
  fallback limits or implicit driver enabling.
- Auto uses macsmc's zero-target protocol, without module reload or boot changes.
- Added backend, worker-process, CLI and terminal interaction tests.
- Hardware telemetry is validated; real manual writes remain unvalidated on the
  development host because sudo authentication is interactive.

## 0.1.0

- Read-only live dashboard, capability diagnostics, demo mode and text/JSON snapshots.
- Dynamic discovery of hwmon sensors and thermal zones.
- Sensor/CLI tests and GitHub CI.
