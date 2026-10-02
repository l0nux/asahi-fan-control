"""Fixed entry point for the extension's bundled Python backend.

Use /usr/bin/python3 -I: ignore PYTHONPATH, user site packages and the cwd.
Only the explicitly installed extension bundle is added to the import path.
"""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asahi_fan_control.control import worker
from asahi_fan_control.sensors import DemoReader, Reader


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=('snapshot', 'worker'))
    parser.add_argument('--demo', action='store_true')
    args = parser.parse_args()
    if args.operation == 'snapshot':
        snapshot = (DemoReader() if args.demo else Reader()).snapshot().to_dict()
        # The panel does not need machine identity or a device inventory.
        snapshot.pop('model', None)
        snapshot.pop('cooling', None)
        print(json.dumps(snapshot), flush=True)
        return 0
    try:
        os.setsid()
    except PermissionError:
        pass  # Already a session leader.
    return worker(args.demo, 0)


if __name__ == '__main__':
    raise SystemExit(main())
