"""Linux sysfs reader. All hardware access is read-only."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import os
import re


@dataclass
class Temperature:
    source: str
    label: str
    celsius: float | None
    critical: float | None
    maximum: float | None
    status: str
    path: str


@dataclass
class Fan:
    source: str
    label: str
    rpm: int | None
    minimum: int | None
    maximum: int | None
    target: int | None
    target_access: str
    status: str
    path: str


@dataclass
class Snapshot:
    timestamp: str
    model: str
    fan_control: str
    temperatures: list[Temperature]
    fans: list[Fan]
    cooling: list[str]
    issues: list[str]
    demo: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def read_text(path: Path) -> str | None:
    try:
        return path.read_text().strip().rstrip('\0')
    except (OSError, UnicodeError):
        return None


def natural_key(path: Path) -> list:
    return [int(s) if s.isdigit() else s for s in re.split(r'(\d+)', path.name)]


class Reader:
    def __init__(self, root: Path = Path('/sys')):
        self.root = root
        self.issues: list[str] = []

    def number(self, path: Path, required: bool = False) -> int | None:
        raw = read_text(path)
        if raw is not None:
            try:
                return int(raw)
            except ValueError:
                self.issues.append(f'Invalid numeric reading: {path}')
        elif required:
            self.issues.append(f'Cannot read: {path}')
        return None

    def degrees(self, path: Path, required: bool = False) -> float | None:
        value = self.number(path, required)
        return value / 1000 if value is not None else None

    def entries(self, path: Path, pattern: str) -> list[Path]:
        try:
            return sorted(path.glob(pattern), key=natural_key)
        except OSError:
            self.issues.append(f'Cannot scan: {path}')
            return []

    @staticmethod
    def target_access(path: Path) -> str:
        try:
            mode = path.stat().st_mode
        except OSError:
            return 'not exposed'
        if not mode & 0o222:
            return 'driver read-only'
        if not os.access(path, os.W_OK):
            return 'permission required'
        return 'writable (app read-only)'

    def snapshot(self) -> Snapshot:
        self.issues = []
        temperatures, fans, cooling = [], [], []
        devices = self.entries(self.root / 'class/hwmon', 'hwmon*')
        for device in devices:
            name = read_text(device / 'name') or device.name
            source = f'{name}/{device.name}'
            for path in self.entries(device, 'temp*_input'):
                if not re.fullmatch(r'temp\d+_input', path.name):
                    continue
                prefix = path.name.removesuffix('_input')
                value = self.degrees(path, required=True)
                fault = self.number(device / f'{prefix}_fault')
                alarm = self.number(device / f'{prefix}_alarm')
                critical = self.degrees(device / f'{prefix}_crit')
                maximum = self.degrees(device / f'{prefix}_max')
                status = 'OK'
                if fault:
                    value, status = None, 'FAULT'
                elif value is None:
                    status = 'UNAVAILABLE'
                elif alarm:
                    status = 'ALARM'
                elif critical is not None and value >= critical:
                    status = 'CRITICAL'
                elif maximum is not None and value >= maximum:
                    status = 'HIGH'
                temperatures.append(Temperature(
                    source, read_text(device / f'{prefix}_label') or prefix,
                    value, critical, maximum, status, str(path)))
            for path in self.entries(device, 'fan*_input'):
                if not re.fullmatch(r'fan\d+_input', path.name):
                    continue
                prefix = path.name.removesuffix('_input')
                rpm = self.number(path, required=True)
                fault = self.number(device / f'{prefix}_fault')
                alarm = self.number(device / f'{prefix}_alarm')
                status = 'FAULT' if fault else 'ALARM' if alarm else 'OK'
                if fault or rpm is None or rpm < 0:
                    rpm = None
                    if not fault:
                        status = 'UNAVAILABLE'
                fans.append(Fan(
                    source, read_text(device / f'{prefix}_label') or prefix, rpm,
                    self.number(device / f'{prefix}_min'),
                    self.number(device / f'{prefix}_max'),
                    self.number(device / f'{prefix}_target'),
                    self.target_access(device / f'{prefix}_target'), status, str(path)))
        thermal = self.root / 'class/thermal'
        for zone in self.entries(thermal, 'thermal_zone*'):
            value = self.degrees(zone / 'temp', required=True)
            temperatures.append(Temperature(
                zone.name, read_text(zone / 'type') or zone.name, value,
                None, None, 'OK' if value is not None else 'UNAVAILABLE',
                str(zone / 'temp')))
        for device in self.entries(thermal, 'cooling_device*'):
            kind = read_text(device / 'type') or device.name
            current = self.number(device / 'cur_state', required=True)
            maximum = self.number(device / 'max_state')
            cooling.append(f'{kind}: state {current if current is not None else "N/A"}'
                           f' / {maximum if maximum is not None else "N/A"}')
        parameter = read_text(self.root / 'module/macsmc_hwmon/parameters/fan_control')
        if parameter is None:
            control = 'Unknown: macsmc fan_control parameter not readable/exposed'
        elif parameter.lower() in ('n', '0'):
            control = 'Disabled by kernel (fan_control=N)'
        elif parameter.lower() in ('y', '1'):
            control = 'Enabled in kernel; this application remains read-only'
        else:
            control = f'Unknown parameter value: {parameter}'
        if not temperatures and not fans:
            self.issues.append('No temperature or fan sensors discovered under ' + str(self.root))
        return Snapshot(
            datetime.now(timezone.utc).isoformat(timespec='seconds'),
            read_text(self.root / 'firmware/devicetree/base/model') or 'Linux system',
            control, temperatures, fans, cooling, self.issues.copy())


class DemoReader:
    """Deterministic sample readings, never touches sysfs."""

    def snapshot(self) -> Snapshot:
        return Snapshot(
            datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'Demo Apple Silicon Mac', 'Disabled by kernel (demo)',
            [Temperature('macsmc_hwmon/hwmon3', 'NAND Flash Temperature', 34.0,
                         None, None, 'OK', 'demo/temp1_input'),
             Temperature('macsmc_hwmon/hwmon3', 'Battery Hotspot', 33.0,
                         None, None, 'OK', 'demo/temp2_input'),
             Temperature('macsmc_hwmon/hwmon3', 'WiFi/BT Module Temp', 45.8,
                         None, None, 'OK', 'demo/temp3_input')],
            [Fan('macsmc_hwmon/hwmon3', 'Fan 1', 1800, 1350, 5349, 1800,
                 'driver read-only', 'OK', 'demo/fan1_input'),
             Fan('macsmc_hwmon/hwmon3', 'Fan 2', 1900, 1522, 5777, 1900,
                 'driver read-only', 'OK', 'demo/fan2_input')],
            ['Example PCIe link: state 0 / 1 (not a fan)'], [], True)
