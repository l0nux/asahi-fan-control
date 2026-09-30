# Asahi Fan Control

An English terminal dashboard for fan speeds, temperatures, and fan-control
capabilities on Asahi Linux. Version 0.1 is **read-only**: it does not set fan
speeds, enable kernel parameters, or require root.

## Run

Requires Linux and Python 3.10+ with curses (included with Fedora's Python).
No third-party runtime dependencies.

```sh
python3 -m asahi_fan_control
python3 -m asahi_fan_control --demo
python3 -m asahi_fan_control --once
python3 -m asahi_fan_control --json
```

Use `Tab` to switch Overview/Diagnostics, arrow keys or `j`/`k` to scroll,
`Space` to pause, `r` to refresh, and `q` to quit. Resize is supported.
`--interval 2` changes the polling period in seconds. Demo data is explicitly
labelled and does not read hardware. JSON is one snapshot, suitable for scripts.

Optional installation into a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/asahi-fan-control
```

## What it reports

- Dynamically discovered hwmon sensors and thermal zones; no fixed hwmon index.
- Current/minimum/maximum/target fan RPM when the driver exposes them.
- Temperature labels, driver-reported limits, faults and alarms.
- Driver write permissions and the macsmc `fan_control` parameter, separately
  from the application's read-only policy.
- Missing or invalid readings as unavailable, never as a fabricated zero.

Zero RPM is a valid reading. The `fanX_target` value is a setpoint, **not** a
reliable indication of automatic/manual mode. The application cannot determine
the SMC's active policy from it. Temperatures are individual sensors, not an
estimate of CPU or GPU temperature. Thermal-zone and hwmon readings can overlap.
No generic safe-temperature thresholds or automatic fan curves are invented.

## Development

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q asahi_fan_control
```

See [hardware findings](docs/HARDWARE.md) and the [staged roadmap](docs/ROADMAP.md).

## License

MIT. This project is independent of Apple and the Asahi Linux project.
