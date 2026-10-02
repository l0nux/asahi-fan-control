"""Supervised macsmc fan control, owned by an independent worker process.

Protocol: macsmc-hwmon accepts an in-range RPM as manual control and zero as
return-to-firmware, provided fan_min > 0. No persistent configuration is written.
"""

import argparse
from dataclasses import dataclass
import fcntl
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import time


def now() -> float:
    """Elapsed boot time, including suspend, for control leases and deadlines."""
    return time.clock_gettime(time.CLOCK_BOOTTIME)


class ControlError(RuntimeError):
    pass


def integer(value, name: str) -> int:
    if type(value) is not int:
        raise ControlError(f'{name} must be an integer.')
    return value


def read_number(path: Path) -> int:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError) as error:
        raise ControlError(f'Cannot read {path.name}: {error}') from error


def write_number(fd: int, value: int) -> None:
    payload = f'{value}\n'.encode('ascii')
    os.lseek(fd, 0, os.SEEK_SET)
    if os.write(fd, payload) != len(payload):
        raise ControlError('Incomplete sysfs write.')


@dataclass
class OwnedFan:
    fd: int
    directory: Path
    rpm: int
    deadline: float | None
    started: float


class Backend:
    def __init__(self, root: Path = Path('/sys'), hold_seconds: int = 120):
        self.root = root
        self.hold_seconds = hold_seconds
        self.owned: dict[int, OwnedFan] = {}
        self.events: list[str] = []

    @property
    def parameter(self) -> Path:
        return self.root / 'module/macsmc_hwmon/parameters/fan_control'

    def enabled(self) -> bool:
        try:
            return self.parameter.read_text().strip().lower() in ('y', '1')
        except OSError:
            return False

    def device(self) -> Path:
        found = []
        for path in self.root.glob('class/hwmon/hwmon*'):
            try:
                if (path / 'name').read_text().strip() == 'macsmc_hwmon':
                    found.append(path.resolve())
            except OSError:
                continue
        if len(found) != 1:
            raise ControlError('Expected exactly one macsmc_hwmon device; found ' + str(len(found)))
        return found[0]

    def bounds(self, device: Path, fan: int) -> tuple[int, int]:
        integer(fan, 'Fan number')
        if not 1 <= fan <= 256:
            raise ControlError('Invalid fan number.')
        low = read_number(device / f'fan{fan}_min')
        high = read_number(device / f'fan{fan}_max')
        if not 0 < low <= high:
            raise ControlError('Missing/invalid positive RPM bounds; refusing manual control.')
        return low, high

    def targets(self, device: Path) -> list[int]:
        return sorted(int(p.name[3:-7]) for p in device.glob('fan*_target')
                      if re.fullmatch(r'fan[1-9][0-9]*_target', p.name))

    def open_target(self, device: Path, fan: int) -> int:
        self.bounds(device, fan)  # Zero must mean automatic, not an in-range RPM.
        target = device / f'fan{fan}_target'
        try:
            if not target.stat().st_mode & 0o222:
                raise ControlError('Target is read-only. Enable control explicitly with E or --enable-control.')
            return os.open(target, os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        except OSError as error:
            raise ControlError(f'Cannot open Fan {fan} target: {error}') from error

    @staticmethod
    def modprobe(*args: str) -> None:
        executable = next((p for p in ('/usr/sbin/modprobe', '/sbin/modprobe')
                           if Path(p).is_file()), None)
        if executable is None:
            raise ControlError('modprobe is unavailable.')
        try:
            result = subprocess.run([executable, *args], text=True, capture_output=True,
                                    timeout=15, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C'})
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ControlError(f'modprobe failed: {error}') from error
        if result.returncode:
            raise ControlError(result.stderr.strip() or 'modprobe failed.')

    def enable(self) -> str:
        if self.owned:
            raise ControlError('Return controlled fans to automatic before enabling/reloading the driver.')
        device = self.device()
        fans = self.targets(device)
        if not fans:
            raise ControlError('No controllable fan targets found.')
        for fan in fans:
            self.bounds(device, fan)
        if not self.enabled():
            self.modprobe('-r', 'macsmc_hwmon')  # Never ignore unload errors.
            try:
                self.modprobe('macsmc_hwmon', 'fan_control=1')
            except ControlError as error:
                try:
                    self.modprobe('macsmc_hwmon', 'fan_control=0')
                except ControlError as recovery:
                    raise ControlError(f'{error}; driver recovery also failed: {recovery}') from error
                raise
        if not self.enabled():
            raise ControlError('Kernel did not enable fan_control; no manual speed was applied.')
        device = self.device()  # hwmon numbers can change after reload.
        fans = self.targets(device)
        if not fans:
            raise ControlError('No fan targets after reload.')
        for fan in fans:
            fd = self.open_target(device, fan)
            os.close(fd)
        return 'Manual capability enabled for this boot. Firmware control continues until Set.'

    def set(self, fan: int, rpm: int) -> str:
        integer(fan, 'Fan number')
        integer(rpm, 'RPM')
        if not self.enabled():
            raise ControlError('Kernel control is disabled. Use E or --enable-control first.')
        device = self.device()
        low, high = self.bounds(device, fan)
        if not low <= rpm <= high:
            raise ControlError(f'Fan {fan} requires {low}..{high} RPM; use Auto for firmware control.')
        self.check_feedback(device, fan)
        if fan in self.owned and self.owned[fan].directory != device:
            raise ControlError('Device changed during control; restore automatic mode first.')
        if fan not in self.owned:
            fd = self.open_target(device, fan)
            self.owned[fan] = OwnedFan(fd, device, rpm, 0, now())
        owned = self.owned[fan]
        owned.rpm = rpm
        owned.deadline = now() + self.hold_seconds if self.hold_seconds else None
        try:
            write_number(owned.fd, rpm)
            # SMC setpoints may become visible after the write has returned.
            # Keep ownership throughout this bounded settling interval so all
            # failures still take the automatic-return path below.
            verify_until = now() + 1.5
            if owned.deadline is not None:
                verify_until = min(owned.deadline, verify_until)
            while True:
                actual = read_number(device / f'fan{fan}_target')
                if abs(actual - rpm) <= 1:
                    break
                self.check_feedback(device, fan)
                if now() >= verify_until:
                    raise ControlError(f'Target read-back mismatch: requested {rpm}, received {actual}.')
                time.sleep(0.05)
        except (OSError, ControlError) as error:
            try:
                self.auto(fan)
            except ControlError as recovery:
                raise ControlError(f'{error}; automatic recovery FAILED: {recovery}') from error
            raise ControlError(f'{error}; automatic request accepted.') from error
        duration = f'automatic return in {self.hold_seconds}s' if self.hold_seconds else 'held until Auto or session end'
        return f'Fan {fan}: target {rpm} RPM verified; {duration}.'

    def set_all(self, rpm: int) -> str:
        """Set the two fans to one target; recover both if either application fails."""
        integer(rpm, 'RPM')
        if not self.enabled():
            raise ControlError('Kernel control is disabled. Enable control first.')
        device = self.device()
        if self.targets(device) != [1, 2]:
            raise ControlError('Shared RPM requires exactly two fan targets (1 and 2).')
        # Validate both channels and access before changing either target.
        for fan in (1, 2):
            low, high = self.bounds(device, fan)
            if not low <= rpm <= high:
                raise ControlError(f'Fan {fan} requires {low}..{high} RPM; shared RPM must fit both fans.')
            self.check_feedback(device, fan)
            if fan in self.owned and self.owned[fan].directory != device:
                raise ControlError('Device changed during control; restore automatic mode first.')
            fd = self.open_target(device, fan)
            os.close(fd)
        try:
            for fan in (1, 2):
                self.set(fan, rpm)
        except (OSError, ControlError) as error:
            try:
                self.auto()
            except ControlError as recovery:
                raise ControlError(f'Shared RPM failed: {error}; automatic recovery FAILED: {recovery}') from error
            raise ControlError(f'Shared RPM failed: {error}; session automatic requests accepted.') from error
        return f'Both fans: target {rpm} RPM verified.'

    @staticmethod
    def check_feedback(device: Path, fan: int) -> int:
        current = read_number(device / f'fan{fan}_input')
        if current < 0:
            raise ControlError(f'Fan {fan} has invalid feedback.')
        for suffix in ('fault', 'alarm'):
            path = device / f'fan{fan}_{suffix}'
            if path.exists() and read_number(path):
                raise ControlError(f'Fan {fan} reports {suffix}.')
        return current

    def auto(self, fan: int | None = None, all_fans: bool = False) -> str:
        errors = []
        requested = []
        if all_fans:
            if not self.enabled():
                raise ControlError('fan_control is disabled; automatic mode cannot be verified or commanded.')
            device = self.device()
            requested = self.targets(device)
            if not requested:
                raise ControlError('No fan targets found.')
        else:
            requested = list(self.owned) if fan is None else [fan]
            device = None
        for channel in requested:
            temporary = None
            try:
                owned = self.owned.get(channel)
                if owned is not None:
                    fd = owned.fd
                elif all_fans:
                    temporary = self.open_target(device, channel)
                    fd = temporary
                else:
                    continue
                write_number(fd, 0)
                # A successful kernel write acknowledges the mode request. Reading
                # fan_target does NOT verify mode and may retain the previous RPM.
                if owned is not None:
                    os.close(owned.fd)
                    del self.owned[channel]
            except (OSError, ControlError) as error:
                errors.append(f'Fan {channel}: {error}')
            finally:
                if temporary is not None:
                    os.close(temporary)
        if errors:
            raise ControlError('Automatic return failed: ' + '; '.join(errors))
        return 'Automatic request accepted by driver; active SMC mode is not readable.'

    def tick(self) -> None:
        current_time = now()
        for fan, owned in list(self.owned.items()):
            reason = None
            try:
                current = self.check_feedback(owned.directory, fan)
                if current == 0 and current_time - owned.started > 5:
                    reason = 'zero RPM feedback after spin-up grace period'
                target = read_number(owned.directory / f'fan{fan}_target')
                if abs(target - owned.rpm) > 1:
                    reason = 'target changed outside this session'
            except ControlError as error:
                reason = str(error)
            if owned.deadline is not None and current_time >= owned.deadline:
                reason = 'manual hold expired'
            if reason:
                self.auto(fan)
                self.events.append(f'Fan {fan}: {reason}; automatic request accepted.')

    def status(self) -> dict:
        events, self.events = self.events, []
        return {'enabled': self.enabled(), 'manual': {
            str(fan): {'rpm': owned.rpm, 'remaining': None if owned.deadline is None else max(0, math.ceil(owned.deadline - now()))}
            for fan, owned in self.owned.items()}, 'events': events}

    def close(self) -> None:
        self.auto()


class DemoBackend:
    """Same session API without module, privilege, lock or sysfs access."""
    def __init__(self, hold_seconds=120):
        self.hold_seconds = hold_seconds
        self.active = False
        self.manual = {}
        self.events = []

    def enable(self):
        self.active = True
        return 'DEMO: control enabled; no hardware changed.'

    def set(self, fan, rpm):
        integer(fan, 'Fan number')
        integer(rpm, 'RPM')
        if not self.active:
            raise ControlError('DEMO: enable control with E first.')
        bounds = {1: (1350, 5349), 2: (1522, 5777)}
        if fan not in bounds or not bounds[fan][0] <= rpm <= bounds[fan][1]:
            raise ControlError('DEMO: fan or RPM is outside its advertised range.')
        self.manual[str(fan)] = {'rpm': rpm, 'deadline': now() + self.hold_seconds if self.hold_seconds else None}
        return f'DEMO: Fan {fan} set to {rpm} RPM.'

    def set_all(self, rpm):
        integer(rpm, 'RPM')
        if not self.active:
            raise ControlError('DEMO: enable control first.')
        if not 1522 <= rpm <= 5349:
            raise ControlError('DEMO: shared RPM requires 1522..5349 RPM.')
        for fan in (1, 2):
            self.set(fan, rpm)
        return f'DEMO: both fans set to {rpm} RPM.'

    def auto(self, fan=None, all_fans=False):
        if fan is None:
            self.manual.clear()
        else:
            self.manual.pop(str(fan), None)
        return 'DEMO: automatic request accepted.'

    def tick(self):
        for fan, data in list(self.manual.items()):
            if data['deadline'] is not None and data['deadline'] <= now():
                self.manual.pop(fan)
                self.events.append(f'DEMO: Fan {fan} hold expired; returned to automatic.')

    def status(self):
        events, self.events = self.events, []
        return {'enabled': self.active, 'manual': {
            fan: {'rpm': data['rpm'], 'remaining': None if data['deadline'] is None else max(0, math.ceil(data['deadline'] - now()))}
            for fan, data in self.manual.items()}, 'events': events}

    def close(self):
        self.auto()


def acquire_lock(path=Path('/run/asahi-fan-control.lock')) -> int:
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
            raise ControlError('Unexpected control lock ownership/type.')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        os.close(fd)
        raise ControlError('Another control session is running, or the lock is invalid.')
    return fd


def dispatch(backend, request: dict) -> dict:
    action = request.get('action')
    message = ''
    if action == 'enable':
        message = backend.enable()
    elif action == 'set':
        message = backend.set(request.get('fan'), request.get('rpm'))
    elif action == 'set_all':
        message = backend.set_all(request.get('rpm'))
    elif action == 'auto':
        message = backend.auto(all_fans=True)
    elif action != 'status':
        raise ControlError('Unknown control operation.')
    return {'ok': True, 'message': message, **backend.status()}


def worker(demo: bool, hold_seconds: int, lease_seconds: float = 5.0) -> int:
    backend = DemoBackend(hold_seconds) if demo else Backend(hold_seconds=hold_seconds)
    lock = None
    selector = selectors.DefaultSelector()
    stop = False

    def terminate(signum, frame):
        nonlocal stop
        stop = True

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, terminate)
    # A terminal stop must not suspend the process responsible for recovery.
    signal.signal(signal.SIGTSTP, signal.SIG_IGN)
    exit_code = 0
    try:
        if not demo:
            if os.geteuid() != 0:
                raise ControlError('Control requires root. Start with sudo python3 -m asahi_fan_control --control.')
            lock = acquire_lock()
        selector.register(sys.stdin.fileno(), selectors.EVENT_READ)
        print(json.dumps({'ok': True, 'message': 'Control worker ready.', **backend.status()}), flush=True)
        last_message = now()
        buffer = b''
        while not stop:
            # Expire immediately after a long suspend or UI stall. Recovery
            # cannot run while the kernel/process itself is suspended.
            if now() - last_message > lease_seconds:
                break
            try:
                backend.tick()
            except ControlError as error:
                print(f'Control recovery: {error}', file=sys.stderr, flush=True)
                exit_code = 1
                break
            if not selector.select(0.2):
                continue
            data = os.read(sys.stdin.fileno(), 4096)
            if not data:
                break
            buffer += data
            if len(buffer) > 8192:
                raise ControlError('Control request is too large.')
            while b'\n' in buffer:
                line, buffer = buffer.split(b'\n', 1)
                last_message = now()
                try:
                    request = json.loads(line)
                    if not isinstance(request, dict):
                        raise ControlError('Control request must be an object.')
                    result = dispatch(backend, request)
                except (ValueError, ControlError, OSError) as error:
                    result = {'ok': False, 'message': str(error), **backend.status()}
                # Module reloads can outlast the idle lease. Allow the client
                # a fresh heartbeat window after the operation completes.
                last_message = now()
                print(json.dumps(result), flush=True)
    except (ControlError, OSError) as error:
        print(str(error), file=sys.stderr, flush=True)
        exit_code = 1
    finally:
        # Retry transient cleanup failures, retain a nonzero exit on any failure.
        for attempt in range(3):
            try:
                backend.close()
                break
            except (OSError, ControlError) as error:
                exit_code = 1
                print(f'AUTOMATIC RETURN FAILED: {error}', file=sys.stderr, flush=True)
                time.sleep(0.1)
        selector.close()
        if lock is not None:
            os.close(lock)
    return exit_code


class ControlSession:
    def __init__(self, demo=False, hold_seconds=120):
        self.process = subprocess.Popen(
            [sys.executable, '-m', 'asahi_fan_control.control', '--worker',
             '--hold-seconds', str(hold_seconds), *(['--demo'] if demo else [])],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.state = {}
        try:
            self.state = self._receive()
        except Exception:
            self.close()
            raise

    def _receive(self) -> dict:
        if not self.selector.select(20):
            # Closing stdin lets a blocked worker recover when its operation ends.
            self.process.stdin.close()
            raise ControlError('Control worker timed out; the session has been disconnected.')
        line = self.process.stdout.readline()
        if not line:
            self.process.wait(timeout=5)
            detail = self.process.stderr.read().decode(errors='replace').strip()
            raise ControlError(detail or 'Control worker disconnected; automatic recovery was attempted.')
        result = json.loads(line)
        self.state = result
        if not result.get('ok'):
            raise ControlError(result['message'])
        return result

    def request(self, action: str, **values) -> dict:
        try:
            self.process.stdin.write((json.dumps({'action': action, **values}) + '\n').encode())
            self.process.stdin.flush()
            return self._receive()
        except (BrokenPipeError, ValueError) as error:
            raise ControlError('Control worker disconnected; restart the control session.') from error

    def close(self) -> str:
        if not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            result = self.process.wait(timeout=35)
        except subprocess.TimeoutExpired:
            # Never SIGKILL a worker that may still be trying to restore fans.
            return 'Control worker is still recovering. Do not suspend; inspect fan status.'
        self.selector.close()
        detail = self.process.stderr.read().decode(errors='replace').strip()
        self.process.stdout.close()
        self.process.stderr.close()
        return detail or ('Automatic recovery failed; inspect fan status.' if result else '')


def hold_duration(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as error:
        raise argparse.ArgumentTypeError('hold duration must be an integer') from error
    if value != 0 and not 5 <= value <= 600:
        raise argparse.ArgumentTypeError('hold duration must be 0 (until session end) or between 5 and 600 seconds')
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Internal supervised fan-control worker.')
    parser.add_argument('--worker', action='store_true', required=True)
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--hold-seconds', type=hold_duration, default=120)
    args = parser.parse_args()
    raise SystemExit(worker(args.demo, args.hold_seconds))
