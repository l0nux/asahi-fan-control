# Asahi Fan Control

**GNOME Shell 51 extension available in version 0.4.0.** Monitor temperatures
and set supervised fan targets from the top panel, with asynchronous operations
that keep GNOME responsive during driver enabling. Targets stay active until
**Return all fans to automatic** or **End control session**. Use the **2000 RPM**,
**3000 RPM** or **4000 RPM** buttons to set both fans together, or enter a shared
RPM within their overlapping limits. See the
[GNOME installation and usage guide](docs/GNOME.md).

```sh
python3 tools/build-extension.py
gnome-extensions install --force dist/asahi-fan-control@l0nux.github.io.shell-extension.zip
gnome-extensions enable asahi-fan-control@l0nux.github.io
```

The original terminal interface remains available below.

An English terminal dashboard for temperatures and **supervised manual fan
control** on Apple Silicon Macs running Asahi Linux. Python 3.10+, Linux and
curses are required; there are no third-party runtime dependencies.

Monitoring is read-only by default. Version 0.2 adds explicit control sessions,
per-fan RPM targets, return to firmware control, and a separate recovery worker.

## Start

```sh
python3 -m asahi_fan_control                   # live monitor, no root
python3 -m asahi_fan_control --demo --control  # complete simulated workflow
sudo python3 -m asahi_fan_control --control   # real control session
```

In the control session:

1. Press `E`, then `Y`, to enable the kernel's manual-control capability if needed.
2. Press `N` to choose a fan, then `S`, enter its RPM and press Enter.
3. Press `A` to request firmware control for all macsmc fans.
4. Press `Q` to exit; the worker restores fans changed by this session.

`Tab` switches Overview / Diagnostics / Control. Arrow keys or `J`/`K` scroll.
`Space` pauses telemetry display (the control worker continues supervising).
`R` refreshes; `Esc` cancels an RPM entry. Minimum terminal size: 42 columns ×
14 rows. Lowercase keys work too.

In the terminal interface, a manual target lasts **120 seconds** by default; `--hold-seconds 60` changes
that limit (5–600 seconds). Use `--hold-seconds 0` to hold until Auto or session
exit, as the GNOME extension does. Setting a new timed target renews that fan's
duration. All targets remain supervised and return on session disconnection;
there is no unattended manual-speed mode.

## CLI

```sh
python3 -m asahi_fan_control --once
python3 -m asahi_fan_control --json
python3 -m asahi_fan_control --interval 2

# Explicitly enable capability, without setting a manual target:
sudo python3 -m asahi_fan_control --enable-control

# Hold a target while this command supervises it, then return to firmware:
sudo python3 -m asahi_fan_control --set 1 2500 --hold-seconds 60

# Request automatic control without reloading the module:
sudo python3 -m asahi_fan_control --auto

# Exercise the same command lifecycle with simulated hardware:
python3 -m asahi_fan_control --demo --enable-control --set 1 2500 --hold-seconds 5
```

Choose RPM values within the range reported by **your** fan. `--set` never
implicitly enables the driver. `--enable-control` can be combined with `--set`
or `--control` when enabling is intentional. `--auto` is not combined with
`--enable-control`: reloading a module is not the automatic-return protocol.

## Recovery and limits

The independent worker owns sysfs writes, verifies target read-back, rejects
missing/invalid limits, and requests automatic control on hold expiry, feedback
failure, detected target interference, normal exit, caught termination signals,
UI disconnection, or a five-second UI heartbeat lapse. It holds a process lock
to exclude other instances of this program. Demo mode never touches sysfs,
modprobe, the system lock, or hardware.

**Manual control is marked unsafe by the kernel.** Recovery is best effort:
it cannot protect against kernel failure, a killed/stuck worker, or failed
sysfs writes. A process cannot perform recovery while suspended. Boot-time
clocks expire the session after resume; return to Auto **before** suspending.
Do not run other fan-control utilities at the same time. No CPU/GPU temperature
is invented when the driver does not expose one, and no temperature-based fan
curve is provided.

The app reports an automatic request as **accepted by the driver**, not as a
verified physical SMC mode. `fanN_target` may retain its previous value after
Auto. Kernel capability may remain enabled until reboot; the app never edits
boot/module configuration or installs a background service.

## Installation

Run directly from the clone, or install into a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/asahi-fan-control
sudo .venv/bin/asahi-fan-control --control
```

## Verification

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q asahi_fan_control
```

Tests include actual curses interaction through a pseudo-terminal and worker
recovery against temporary sysfs fixtures. CI tests Python 3.10, 3.12 and 3.14.
Automated tests never change the host fans. An attended hardware test verified physical RPM response, explicit Auto
acknowledgement, timed expiry and EOF recovery using the real control worker.
SMC setpoint read-back can lag writes; verification allows at most 1.5 seconds
for it to settle. Machine-specific measurements remain local and ignored.
This validates the tested configuration, not every model or kernel.

See [hardware interfaces](docs/HARDWARE.md), [control design](docs/CONTROL.md),
[roadmap](docs/ROADMAP.md), and [release notes](CHANGELOG.md).

MIT licensed. Independent of Apple and the Asahi Linux project.
