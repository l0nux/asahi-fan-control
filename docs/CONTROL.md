# Supervised control design

## Driver protocol

The implementation targets `macsmc_hwmon` specifically. It requires one matching
hwmon device, a readable enabled `fan_control` parameter, a writable target,
and valid positive minimum/maximum RPM values. It does not apply this protocol
to arbitrary hwmon drivers.

In the upstream `macsmc_hwmon_write_fan` implementation, an in-range value
selects manual mode and writes the setpoint. Zero requests automatic mode only
when it is outside the advertised RPM interval. Consequently this application
refuses control if the minimum is zero or missing. It never interprets a zero
command as "stop the fan".

Read-back checks the setpoint within one RPM to accommodate conversion rounding;
actual fan speed takes time to settle. Automatic-mode acceptance is the success
of the zero write. The driver does not expose the SMC mode, so neither target
zero nor falling RPM is used as proof of firmware mode.

## Process model

The default dashboard is unprivileged and read-only. `--control`, `--set`,
`--auto`, and `--enable-control` require an explicitly root-launched process,
except in demo mode. The root TUI launches a separate worker in a separate
session, using a pipe and a small JSON command allowlist. This is process
isolation for recovery, **not a security privilege boundary**: both processes
run as root in a real control session. No network server or privileged service
is installed.

The worker holds `/run/asahi-fan-control.lock` and accepts only enable, set,
auto and status operations. Fan indices and RPMs must be integers. All hardware
paths are constructed from a dynamically discovered macsmc device; the CLI
cannot supply arbitrary sysfs paths. Open target descriptors are retained for
recovery so a renumbered hwmon entry is not mistaken for the original device.
The worker registers ownership before a write, since a failed target write
may already have changed the driver's manual-mode bit.

## Lifetime

- A target expires after its configured 5–600 second hold.
- The worker checks fan feedback and target consistency approximately every 0.2s.
- Zero RPM after a five-second spin-up grace period triggers automatic return.
- The dashboard sends status heartbeats about twice per second, including while
  paused or editing a target. Five seconds without messages ends the worker.
- EOF, caught SIGTERM/SIGINT/SIGHUP, or normal exit requests automatic control
  for every fan touched by the session. Terminal job-control stop is ignored by
  the worker. Cleanup failures produce errors and are retried three times.
- CLOCK_BOOTTIME includes suspend. A long suspend expires the lease on resume;
  no userspace process can write to hardware while it is suspended.

The lock does not exclude unrelated utilities or manual sysfs writes. The
application cannot promise protection against SIGKILL to the worker, a kernel
hang, an uninterruptible sysfs operation, or an unsupported driver variant.

## Enabling and recovery

Enabling capability is a separate explicit operation. If disabled, it unloads
only `macsmc_hwmon` and reloads it with `fan_control=1`. Every subprocess result
is checked. If loading fails, it attempts to load with `fan_control=0`; failure
of that recovery is also reported. Device paths are rediscovered and permissions
checked after reload. No persistent configuration is edited. Existing modprobe
configuration remains the user's responsibility.

Auto writes zero directly and never reloads the driver. On an already disabled
parameter, the program refuses to claim a verified transition. On default exit,
only session-owned fans are restored; the explicit Auto action targets all
exposed macsmc fans.

## Verification scope and references

Fixture tests exercise the real backend's writes and recovery protocol. Process
tests exercise EOF, heartbeat expiry and SIGTERM. A PTY test uses the actual TUI
and demo worker to set both fans, reject invalid input, return to Auto, pause,
resize and exit. This validates software behavior without claiming physical
fan-control verification on a particular machine.

- [Upstream macsmc-hwmon source](https://github.com/torvalds/linux/blob/master/drivers/hwmon/macsmc-hwmon.c)
- [Kernel driver documentation](https://docs.kernel.org/hwmon/macsmc-hwmon.html)
- [Original Bash project referenced during investigation](https://github.com/l0nux/asahi-fan-control-)

The Bash project helped identify the relevant operations. Its module reload and
fallback-limit behavior was not used as the application's control protocol.
