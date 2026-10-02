"""Ensure the distributable is self-contained and excludes private files."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class ExtensionTests(unittest.TestCase):
    def test_bundle_runs_isolated_without_checkout_imports(self):
        subprocess.run([sys.executable, str(ROOT / 'tools/build-extension.py')],
                       check=True, capture_output=True)
        archive = ROOT / 'dist/asahi-fan-control@l0nux.github.io.shell-extension.zip'
        with tempfile.TemporaryDirectory() as folder, zipfile.ZipFile(archive) as bundle:
            names = set(bundle.namelist())
            self.assertEqual(names, {'metadata.json', 'extension.js', 'transport.js',
                                    'stylesheet.css', 'bridge.py', 'LICENSE',
                                    'asahi_fan_control/__init__.py',
                                    'asahi_fan_control/sensors.py', 'asahi_fan_control/control.py'})
            bundle.extractall(folder)
            result = subprocess.run([sys.executable, '-I', str(Path(folder) / 'bridge.py'),
                                     'snapshot', '--demo'], cwd=folder, capture_output=True,
                                    text=True, check=True, timeout=10)
            data = json.loads(result.stdout)
            self.assertTrue(data['demo'])
            self.assertEqual(len(data['fans']), 2)
            self.assertNotIn('model', data)
            self.assertEqual(json.loads(bundle.read('metadata.json'))['shell-version'], ['51'])

    def test_slow_enable_does_not_consume_idle_lease(self):
        code = '''
import time
from unittest.mock import patch
import asahi_fan_control.control as c
base = c.DemoBackend
class Slow(base):
    def enable(self):
        time.sleep(0.4)
        return super().enable()
with patch.object(c, 'DemoBackend', Slow):
    raise SystemExit(c.worker(True, 5, lease_seconds=0.2))
'''
        process = subprocess.Popen([sys.executable, '-c', code], cwd=ROOT,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        try:
            self.assertTrue(json.loads(process.stdout.readline())['ok'])
            process.stdin.write('{"action":"enable"}\n')
            process.stdin.flush()
            self.assertTrue(json.loads(process.stdout.readline())['enabled'])
            process.stdin.write('{"action":"set","fan":1,"rpm":2500}\n')
            process.stdin.flush()
            response = process.stdout.readline()
            self.assertTrue(response, 'Worker exited before client could send the next command')
            self.assertTrue(json.loads(response)['ok'])
            process.stdin.close()
            self.assertEqual(process.wait(timeout=5), 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
