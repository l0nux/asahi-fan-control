# Hardware interfaces and control capabilities

This document describes Linux interfaces in general. Device-specific inspection
reports are kept locally and are not part of this public repository.

## Telemetry path

On supported Apple Silicon systems, the Apple System Management Controller
(SMC) exposes telemetry through the `macsmc-hwmon` kernel driver. The available
sensors depend on the machine's device tree and kernel version.

The dashboard discovers `/sys/class/hwmon/hwmon*` each refresh and reads:

| Attribute | Meaning |
| --- | --- |
| `name` | Driver/device name |
| `tempN_input` | Temperature in millidegrees Celsius for supported sensors |
| `tempN_label` | Driver-provided sensor name, when available |
| `tempN_max`, `tempN_crit` | Optional driver-provided temperature limits |
| `tempN_fault`, `tempN_alarm` | Optional fault/alarm indicators |
| `fanN_input` | Current speed in RPM |
| `fanN_min`, `fanN_max` | Advertised speed bounds, when available |
| `fanN_target` | Setpoint, when available; not an active-mode indicator |

Indices such as `hwmon3` can change across boots. Thermal zones in
`/sys/class/thermal` may expose overlapping readings. Linux cooling devices can
represent mechanisms other than fans, so the dashboard lists them separately.
A missing CPU/GPU sensor is not substituted with a battery or board reading.
Missing data is shown as unavailable; zero RPM remains a valid numeric reading.

## Control boundaries

The upstream driver exposes a `fan_control` module parameter, disabled by
default. Its documentation marks manual fan control unsafe because overheating
fail-safe behavior cannot be guaranteed. The application reports the parameter
when readable and checks target-file permissions independently.

A read-only target is a kernel capability/configuration constraint. Monitoring mode performs no writes. Version 0.2 adds an explicit root control
session; its Enable action may reload macsmc_hwmon. Boot configuration is never
edited. See [control design](CONTROL.md) for the write protocol and limitations.
A writable target or a nonzero setpoint does not prove the current SMC policy.

Manual control uses a separate worker with bounded holds and automatic-return
requests. An attended hardware cycle has been validated locally; process recovery cannot
cover every crash, suspend state or competing service. This project does not promise hardware fail-safe behavior.

## Primary references

- [Linux macsmc-hwmon documentation](https://docs.kernel.org/hwmon/macsmc-hwmon.html)
- [Linux hwmon sysfs ABI](https://docs.kernel.org/hwmon/sysfs-interface.html)
- [Upstream macsmc-hwmon implementation](https://github.com/torvalds/linux/blob/master/drivers/hwmon/macsmc-hwmon.c)

These references describe upstream interfaces. A particular installed kernel
may expose different capabilities; consult the dashboard's Diagnostics view.
