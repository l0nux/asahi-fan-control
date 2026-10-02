# GNOME Shell extension

The English GNOME 51 panel replaces blocking terminal interactions with async
GIO operations. It shows fan RPM, sensor temperatures, driver capability,
individual and shared fan targets, with three quick RPM presets. It does not invent a CPU temperature.

## Install

From the repository:

```sh
python3 tools/build-extension.py
gnome-extensions install --force dist/asahi-fan-control@l0nux.github.io.shell-extension.zip
gnome-extensions enable asahi-fan-control@l0nux.github.io
```

If GNOME reports that a newly installed extension does not exist, log out and
back in, then run the enable command again. Do not restart GNOME Shell in a
Wayland session. After an upgrade, log out and back in if the panel still shows
the old controls: GNOME can cache extension code for the current login. The ZIP contains its Python backend and needs no pip install.
It requires `/usr/bin/python3`, GNOME Shell 51 and `pkexec` for real control.
Only GNOME 51 is currently advertised because that is the tested version.

## Use

Click **Fans** in the top panel. Monitoring requires no authentication.

1. Choose **Start control session…** and authenticate in the system dialog.
2. Choose **Enable manual capability…**, read the notice, then confirm.
   This may reload macsmc_hwmon; no RPM is applied by enabling alone.
3. Click **2000 RPM**, **3000 RPM** or **4000 RPM** to set both fans together.
   Presets outside either fan's limits are disabled. Alternatively enter a
   **Shared RPM** and click **Apply to both**, or use each fan's **Apply** field.
   Shared RPM uses the intersection of the two fan ranges. Both receive the
   same target; measured speeds may differ while settling. Individual fields
   remain independent if you change one later.
   Targets stay active until Auto or session end, with no two-minute expiry.
4. Use **Return all fans to automatic** or **End control session** when done.

Enable **Demo mode** before starting a session to try the complete workflow
without authentication or hardware writes. End the session before changing
between demo and live data. Disabling the extension disconnects the worker and
requests recovery for its owned fans; read-only processes are cancelled.

## Why enable no longer blocks the desktop

The terminal's Enable handler calls a synchronous request and waits for module
reload. The new extension never reads sysfs or waits for control on GNOME's main
loop: telemetry runs in a separate read-only process; worker reads, writes and
exit notifications all use GIO async APIs. Only one command is in flight, its
state is visible, and **End control session** stays available while it runs.
The worker starts a fresh heartbeat window after a slow operation returns.

The authentication timeout and enable-response timeout are 60 seconds. Ending
a session closes the pipe; it cannot interrupt a blocked kernel operation. An
already open authentication dialog may still need to be dismissed. A controller
that eventually starts after disconnection sees EOF and applies no new command.

## Privilege and recovery boundaries

The GNOME extension stays unprivileged. Only the explicitly authenticated Python
worker runs as root through the system's existing pkexec policy. Python starts
in isolated mode and loads the backend from the installed extension directory.
Authenticating grants that worker root execution; this is not a restricted
system daemon or a new authorization policy. Install the bundle only from a
source you trust. No sudoers, polkit rules, services or boot settings are added.

The supervised-control protocol, exclusive application lock, feedback
checks, heartbeat lease and best-effort cleanup still apply. The UI never kills
a fan-control worker to cancel a request. Manual mode remains marked unsafe by
the driver; recovery is not a hardware fail-safe. Return to Auto before suspend.
See [CONTROL.md](CONTROL.md). A separate attended hardware test verified physical RPM response, Auto
acknowledgement, expiry and EOF cleanup. Simulated extension tests alone do not
prove hardware behavior; additional models and kernels need their own validation.

## Verify and remove

```sh
python3 -m unittest discover -s tests -v
python3 tools/build-extension.py
python3 -m zipfile -e dist/asahi-fan-control@l0nux.github.io.shell-extension.zip /tmp/asahi-extension-check
gjs -m tests/test_transport.js /tmp/asahi-extension-check/bridge.py
gnome-extensions info asahi-fan-control@l0nux.github.io
```

Tests cover the standalone ZIP, GLib main-loop responsiveness during a slow
Enable operation, real asynchronous transport with the demo backend, both fans,
Auto, errors, process exit and cancellation. A GNOME 51 headless integration test
also exercises the actual panel class through enable, both targets, Auto, end
and disable, including shared targets, range rejection and all three presets. The test can be reproduced with `python3 tools/test-shell.py ZIP`;
it requires GNOME 51, dbus-broker, gsettings and a working headless renderer.

To remove: end any control session, then run:

```sh
gnome-extensions disable asahi-fan-control@l0nux.github.io
gnome-extensions uninstall asahi-fan-control@l0nux.github.io
```

References: [GIO subprocesses](https://gjs.guide/guides/gio/subprocesses.html),
[GNOME extension structure](https://gjs.guide/extensions/overview/anatomy.html).
