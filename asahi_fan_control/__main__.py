"""Command-line entry point."""

import argparse
import json
import math
import sys

from . import __version__
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
    parser = argparse.ArgumentParser(description='Read-only fan and thermal dashboard for Asahi Linux.')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--demo', action='store_true', help='use clearly labelled sample data')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--once', action='store_true', help='print one text snapshot')
    group.add_argument('--json', action='store_true', help='print one JSON snapshot')
    parser.add_argument('--interval', type=polling_interval, default=1.0, metavar='SECONDS')
    args = parser.parse_args(argv)
    reader = DemoReader() if args.demo else Reader()
    if args.json:
        print(json.dumps(reader.snapshot().to_dict(), indent=2))
        return 0
    try:
        import curses
        from .ui import clean, run, text_snapshot
    except ImportError:
        print('Python curses is unavailable. Use --json or install Python with curses.', file=sys.stderr)
        return 1
    if args.once:
        print('\n'.join(clean(line) for line in text_snapshot(reader.snapshot()).splitlines()))
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print('The dashboard needs a terminal. Use --once or --json for non-interactive output.', file=sys.stderr)
        return 2
    try:
        curses.wrapper(run, reader, args.interval)
    except KeyboardInterrupt:
        return 0
    except curses.error as error:
        print(f'Terminal initialization failed: {error}. Try --once or --json.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
