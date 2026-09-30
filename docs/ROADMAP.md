# Staged development and publication

1. **Investigation and Git** — inspect model, hwmon, thermal zones, fan targets,
   module parameters and permissions; record findings; initialize `main`.
2. **Version 0.1: monitoring** — dependency-free English TUI, automatic discovery,
   capability diagnostics, demo mode, text/JSON snapshots, graceful read failures.
3. **Verification** — fixture tests for missing data, zero RPM, sensor faults,
   read-only detection and changing devices; live snapshot and terminal checks.
4. **GitHub** — review tracked files, commit, create public
   `l0nux/asahi-fan-control`, push `main`, run CI, inspect published files.
5. **Future manual-control prototype** — validate the exact installed driver's
   protocol on supported hardware before implementation. Investigate exclusive
   ownership, RPM bounds, telemetry gaps, privilege separation, return to firmware
   control, crashes, suspend/resume and competing services. Do not call a cleanup
   handler a hardware fail-safe. No automatic module enabling is planned.
6. **Future release** — hardware compatibility matrix, packaging, release notes,
   and a version tag after manual validation. Fan curves require dependable
   thermal feedback and are not part of version 0.1.

Publication commands (after the repository exists and Git is authenticated):

```sh
git remote add origin https://github.com/l0nux/asahi-fan-control.git
git push -u origin main
```
