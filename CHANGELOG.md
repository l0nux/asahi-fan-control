# Release notes

## 0.5.0

- Simplified the GNOME menu to a primary control card with Enable control,
  three shared RPM presets, active-preset highlighting, Auto and End control.
- Enable control now starts authentication and enables capability in one flow;
  it still applies no speed until the user chooses one.
- Moved individual/shared RPM fields into Custom speeds and grouped
  temperatures and status/settings into collapsed sections. Errors remain
  visible on the main card.
- Verified the actual panel controls in an isolated GNOME Shell 51 session.

## 0.4.0

- GNOME manual targets now stay active until Auto or End control session;
  feedback checks, heartbeat recovery and disconnect cleanup remain active.
- Added a third, shared RPM field and 2000/3000/4000 RPM presets for both fans.
  Shared commands validate both ranges before writing and attempt automatic
  recovery if either fan fails during application.
- The terminal supports `--hold-seconds 0` for session lifetime; its default
  remains 120 seconds.
- Added backend, asynchronous transport and real GNOME panel tests for the
  shared controls, presets and unlimited supervised targets.

## 0.3.1

- Fixed false target mismatches on real hardware: allow up to 1.5 seconds for
  asynchronous SMC read-back, retaining automatic recovery on timeout/failure.
- Added delayed-read regression coverage and an attended real-hardware validator.
- Verified physical RPM response, Auto acknowledgement, hold expiry and EOF
  recovery on a local configuration. Private measurements are excluded.

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
