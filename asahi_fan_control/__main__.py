"""Command-line entry point for monitoring and bounded manual control."""

import argparse
import json
import math
import os
import signal
import sys
import time

from . import __version__
from .control import ControlError, ControlSession, hold_duration
from .sensors import DemoReader, Reader


def polling_interval(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError as error:
        raise argparse.ArgumentTypeError('interval must be a number') from error
    if not math.isfinite(value) or not 0.2 <= value <= 60:
        raise argparse.ArgumentTypeError('interval must be between 0.2 and 60 seconds')
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Asahi Linux thermal dashboard and supervised fan control.')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--demo', action='store_true', help='simulate telemetry and control without hardware access')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--once', action='store_true', help='print one read-only text snapshot')
    group.add_argument('--json', action='store_true', help='print one read-only JSON snapshot')
    group.add_argument('--set', nargs=2, type=int, metavar=('FAN', 'RPM'), help='supervise a temporary fan target, then return to automatic')
    group.add_argument('--auto', action='store_true', help='request firmware control for all macsmc fans')
    parser.add_argument('--control', action='store_true', help='enable control keys in the TUI (requires root except in demo)')
    parser.add_argument('--enable-control', action='store_true', help='explicitly reload macsmc_hwmon with fan_control=1 when disabled')
    parser.add_argument('--hold-seconds', type=hold_duration, default=120, metavar='SECONDS', help='manual hold duration, 5..600 seconds (default 120)')
    parser.add_argument('--interval', type=polling_interval, default=1.0, metavar='SECONDS')
    args = parser.parse_args(argv)
    wants_control = args.control or args.enable_control or args.set is not None or args.auto
    if (args.once or args.json) and wants_control:
        parser.error('--once and --json cannot be combined with control operations')
    if args.auto and args.enable_control:
        parser.error('--auto must not reload the driver; do not combine it with --enable-control')
    if args.set is not None and (not 1 <= args.set[0] <= 256 or args.set[1] <= 0):
        parser.error('--set requires a positive fan number and RPM; use --auto for automatic control')
    if wants_control and not args.demo and os.geteuid() != 0:
        print('Control requires root. Run sudo python3 -m asahi_fan_control --control, or try --demo --control.', file=sys.stderr)
        return 2
    reader = DemoReader() if args.demo else Reader()
    if args.json:
        print(json.dumps(reader.snapshot().to_dict(), indent=2))
        return 0
    interactive = not (args.once or args.auto or args.set is not None or (args.enable_control and not args.control))
    if interactive and (not sys.stdin.isatty() or not sys.stdout.isatty()):
        print('The dashboard needs a terminal. Use --once or --json for non-interactive output.', file=sys.stderr)
        return 2
    session = None
    result = 0
    handlers = {}

    def interrupted(signum, frame):
        raise KeyboardInterrupt

    try:
        for sig in (signal.SIGTERM, signal.SIGHUP):
            handlers[sig] = signal.signal(sig, interrupted)
        if wants_control:
            session = ControlSession(args.demo, args.hold_seconds)
        if args.enable_control:
            print(session.request('enable')['message'], flush=True)
        if args.auto:
            print(session.request('auto')['message'], flush=True)
        elif args.set is not None:
            print(session.request('set', fan=args.set[0], rpm=args.set[1])['message'], flush=True)
            print('Supervising target; Ctrl+C returns this session to automatic.', flush=True)
            while True:
                state = session.request('status')
                for event in state.get('events', []):
                    print(event, flush=True)
                if not state['manual']:
                    break
                time.sleep(0.25)
        elif interactive or args.once:
            import curses
            from .ui import clean, run, text_snapshot
            if args.once:
                print('\n'.join(clean(line) for line in text_snapshot(reader.snapshot()).splitlines()))
            else:
                try:
                    curses.wrapper(run, reader, args.interval, session)
                except curses.error as error:
                    raise ControlError(f'Terminal initialization failed: {error}. Try --once or --json.') from error
    except KeyboardInterrupt:
        pass
    except ImportError:
        print('Python curses is unavailable. Use --json or install Python with curses.', file=sys.stderr)
        result = 1
    except (ControlError, OSError) as error:
        print(f'Error: {error}', file=sys.stderr)
        result = 1
    finally:
        if session is not None:
            detail = session.close()
            if detail:
                print(detail, file=sys.stderr)
                result = 1
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    return result


if __name__ == '__main__':
    raise SystemExit(main())
