#!/usr/bin/env python3
"""Attended real-hardware validation; private measurements stay in .local/.

The parent is unprivileged. pkexec authenticates only the existing control
worker. Manual holds are bounded to 20 seconds even if this runner disappears.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from asahi_fan_control.sensors import Reader


def targets_for(fans):
    targets = {}
    for fan in fans:
        if not fan.source.startswith('macsmc_hwmon/'):
            continue
        channel = int(Path(fan.path).name.removeprefix('fan').removesuffix('_input'))
        if fan.status != 'OK' or fan.rpm is None or fan.rpm < 0 or not fan.minimum or not fan.maximum:
            raise RuntimeError('Unavailable/faulted fan or missing hardware bounds.')
        if not 0 < fan.minimum < fan.maximum or fan.rpm > fan.maximum - 300:
            raise RuntimeError('No suitable RPM headroom for an observable upward test.')
        target = min(fan.maximum, math.ceil(max(fan.minimum, fan.rpm + 600, fan.maximum * 0.55) / 100) * 100)
        targets[channel] = target
    if not targets:
        raise RuntimeError('No macsmc fans found.')
    return targets


def converged(fans, targets):
    actual = {int(Path(f.path).name.removeprefix('fan').removesuffix('_input')): f
              for f in fans if f.source.startswith('macsmc_hwmon/')}
    return all(channel in actual and actual[channel].status == 'OK' and
               actual[channel].rpm is not None and abs(actual[channel].rpm - rpm) <= max(150, rpm * 0.10)
               for channel, rpm in targets.items())


class Session:
    def __init__(self):
        self.process = subprocess.Popen(
            ['/usr/bin/pkexec', '--disable-internal-agent', '/usr/bin/python3', '-I',
             str(ROOT / 'asahi_fan_control/control.py'), '--worker', '--hold-seconds', '20'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)

    def receive(self, timeout=60):
        if not self.selector.select(timeout):
            raise RuntimeError('Authentication or worker response timed out.')
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError('Worker did not start or disconnected: ' + self.process.stderr.read().decode(errors='replace'))
        result = json.loads(line)
        if not result.get('ok'):
            raise RuntimeError(result.get('message', 'Worker rejected request.'))
        return result

    def request(self, action, **kwargs):
        self.process.stdin.write((json.dumps({'action': action, **kwargs}) + '\n').encode())
        self.process.stdin.flush()
        return self.receive()

    def close(self):
        if not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            code = self.process.wait(timeout=50)
        except subprocess.TimeoutExpired:
            raise RuntimeError('Worker is still running; cleanup unverified. Inspect fan status. No SIGKILL was sent.')
        detail = self.process.stderr.read().decode(errors='replace').strip()
        self.selector.close()
        self.process.stdout.close()
        self.process.stderr.close()
        if code:
            raise RuntimeError(detail or f'Worker cleanup failed (exit {code}).')
        return {'exit_code': code, 'detail': detail, 'automatic_request': 'accepted for owned fans; SMC mode unreadable'}


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real', action='store_true', help='authenticate and perform bounded upward RPM tests')
    args = parser.parse_args()
    if not args.real:
        parser.error('Pass --real only for an attended hardware test.')
    report_dir = ROOT / '.local'
    report_dir.mkdir(exist_ok=True)
    report = report_dir / ('hardware-validation-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.jsonl')
    reader = Reader()
    session = None
    closed = False
    def emit(event, **data):
        record = {'time': datetime.now(timezone.utc).isoformat(), 'event': event, **data}
        with report.open('a') as stream:
            stream.write(json.dumps(record) + '\n')
        print(json.dumps(record), flush=True)
    def sample(stage):
        snap = reader.snapshot()
        emit('sample', stage=stage, fans=[vars(f) for f in snap.fans],
             temperatures=[vars(t) for t in snap.temperatures], issues=snap.issues)
        if any(f.status != 'OK' for f in snap.fans) or any(t.status in ('FAULT', 'ALARM', 'CRITICAL', 'HIGH') for t in snap.temperatures):
            raise RuntimeError('Sensor fault or reported temperature limit; ending manual test.')
        return snap
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    try:
        initial = sample('baseline')
        targets = targets_for(initial.fans)
        emit('plan', targets=targets, hold_seconds=20, report=str(report))
        session = Session()
        emit('ready', result=session.receive())
        emit('enable', result=session.request('enable'))
        # Establish a driver-acknowledged automatic baseline before manual writes.
        emit('initial-auto', result=session.request('auto'))
        for channel, rpm in targets.items():
            emit('set', fan=channel, rpm=rpm, result=session.request('set', fan=channel, rpm=rpm))
        stable = 0
        for _ in range(14):
            status = session.request('status')
            if len(status.get('manual', {})) != len(targets):
                raise RuntimeError('Unexpected loss of manual targets before speed verification.')
            snap = sample('manual-response')
            stable = stable + 1 if converged(snap.fans, targets) else 0
            if stable >= 3:
                break
            time.sleep(1)
        if stable < 3:
            raise RuntimeError('Actual fan speeds did not settle near requested RPM.')
        emit('physical-response-passed', targets=targets)
        emit('explicit-auto', result=session.request('auto'))
        for _ in range(5):
            session.request('status')
            sample('after-explicit-auto')
            time.sleep(1)
        # Confirm natural expiry while the client continues heartbeating.
        for channel, rpm in targets.items():
            emit('expiry-set', fan=channel, result=session.request('set', fan=channel, rpm=rpm))
        expiry_events = []
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            status = session.request('status')
            emit('expiry-status', result=status)
            expiry_events.extend(status.get('events', []))
            sample('expiry-cycle')
            if not status['manual']:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Timed targets did not expire.')
        if any(not any(f'Fan {channel}: manual hold expired;' in event for event in expiry_events)
               for channel in targets):
            raise RuntimeError('Targets ended for a reason other than normal hold expiry.')
        emit('expiry-passed')
        # Confirm EOF cleanup through the actual privileged worker exit status.
        for channel, rpm in targets.items():
            emit('disconnect-set', fan=channel, result=session.request('set', fan=channel, rpm=rpm))
        emit('disconnect-cleanup', result=session.close())
        closed = True
        for _ in range(5):
            sample('after-disconnect')
            time.sleep(1)
        emit('PASS', scope='Physical RPM response, explicit Auto acknowledgement, expiry, EOF cleanup; physical SMC mode remains unreadable.')
        return 0
    except (Exception, KeyboardInterrupt) as error:
        emit('FAIL', reason=str(error) or 'Interrupted')
        return 1
    finally:
        if session is not None and not closed:
            try:
                emit('final-cleanup', result=session.close())
            except Exception as error:
                emit('CLEANUP-UNVERIFIED', reason=str(error))
        print(f'Private report: {report}', flush=True)


if __name__ == '__main__':
    raise SystemExit(run())
