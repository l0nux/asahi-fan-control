# Release notes

## 0.3.0

- Added an English GNOME Shell 51 panel with temperatures, fan RPM, per-fan
  bounded targets, explicit enabling, Auto, end-session and demo actions.
- Kept all telemetry and control I/O outside GNOME's main loop using GIO async
  subprocess APIs; a slow Enable request no longer blocks this interface.
- Added system authentication through pkexec for the separate root worker;
  monitoring stays unprivileged, with no installed authorization rules.
- Restarted the worker idle lease after a slow command response so a successful
  module reload does not immediately disconnect an otherwise healthy client.
- Added a reproducible self-contained ZIP, packaging regression tests, GJS
  transport/responsiveness tests and a headless GNOME 51 integration test.

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
