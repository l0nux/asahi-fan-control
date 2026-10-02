#!/usr/bin/env python3
"""Build a reproducible, self-contained GNOME extension ZIP from explicit files."""
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'gnome-extension'
DEST = ROOT / 'dist'


def build():
    metadata = json.loads((SOURCE / 'metadata.json').read_text())
    DEST.mkdir(exist_ok=True)
    archive = DEST / f"{metadata['uuid']}.shell-extension.zip"
    files = [(SOURCE / name, name) for name in
             ('metadata.json', 'extension.js', 'transport.js', 'stylesheet.css', 'bridge.py')]
    files += [(ROOT / 'asahi_fan_control' / name, f'asahi_fan_control/{name}')
              for name in ('__init__.py', 'sensors.py', 'control.py')]
    files.append((ROOT / 'LICENSE', 'LICENSE'))
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for source, name in files:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
    print(archive)
    return archive


if __name__ == '__main__':
    build()
