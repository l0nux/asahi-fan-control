import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from asahi_fan_control.control import Backend, ControlError, acquire_lock, dispatch, now, read_number, write_number


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.device = self.root / 'class/hwmon/hwmon4'
        self.device.mkdir(parents=True)
        self.put('name', 'macsmc_hwmon')
        for fan in (1, 2):
            for suffix, value in [('min', 1000), ('max', 5000), ('input', 1800), ('target', 1800)]:
                self.put(f'fan{fan}_{suffix}', value)
        self.parameter = self.root / 'module/macsmc_hwmon/parameters/fan_control'
        self.parameter.parent.mkdir(parents=True)
        self.parameter.write_text('Y')
        self.backend = Backend(self.root, hold_seconds=5)
        # Regular files retain bytes after a short write; sysfs attributes do not.
        self.writes = []
        def fixture_write(fd, value):
            self.writes.append(value)
            os.ftruncate(fd, 0)
            write_number(fd, value)
        self.patch = patch('asahi_fan_control.control.write_number', side_effect=fixture_write)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.backend.close)

    def put(self, name, value):
        path = self.device / name
        path.write_text(str(value))
        return path

    def test_manual_and_zero_return_protocol(self):
        self.backend.set(1, 2500)
        self.assertEqual((self.device / 'fan1_target').read_text(), '2500\n')
        self.assertEqual(self.backend.status()['manual']['1']['rpm'], 2500)
        message = self.backend.auto()
        self.assertEqual(self.writes, [2500, 0])
        self.assertIn('not readable', message)
        self.assertEqual(self.backend.status()['manual'], {})

    def test_never_invents_missing_or_zero_bounds(self):
        for low, high in [(0, 5000), (5000, 1000), ('bad', 5000)]:
            self.put('fan1_min', low)
            self.put('fan1_max', high)
            with self.assertRaises(ControlError):
                self.backend.set(1, 2000)
        (self.device / 'fan1_min').unlink()
        with self.assertRaises(ControlError):
            self.backend.set(1, 2000)
        self.assertEqual(self.writes, [])

    def test_rejects_bad_input_before_writes(self):
        for fan, rpm in [(0, 2000), (3, 2000), ('../other', 2000), (True, 2000),
                         (1, '2000'), (1, False), (1, 0), (1, 999), (1, 5001)]:
            with self.subTest(fan=fan, rpm=rpm), self.assertRaises(ControlError):
                self.backend.set(fan, rpm)
        self.assertEqual(self.writes, [])

    def test_disabled_does_not_auto_reload(self):
        self.parameter.write_text('N')
        with patch.object(self.backend, 'modprobe') as reload:
            with self.assertRaises(ControlError):
                self.backend.set(1, 2000)
            reload.assert_not_called()
        self.assertEqual(self.writes, [])

    def test_driver_read_only_refused_even_as_root(self):
        self.put('fan1_target', 1800).chmod(0o444)
        with self.assertRaisesRegex(ControlError, 'read-only'):
            self.backend.set(1, 2000)

    def test_faulted_feedback_refuses_manual(self):
        self.put('fan1_fault', 1)
        with self.assertRaisesRegex(ControlError, 'fault'):
            self.backend.set(1, 2000)
        self.assertEqual(self.writes, [])

    def test_expiry_restores_and_releases_owned_fan(self):
        self.backend.set(1, 2000)
        deadline = self.backend.owned[1].deadline
        with patch('asahi_fan_control.control.now', return_value=deadline + 1):
            self.backend.tick()
        self.assertEqual(self.writes, [2000, 0])
        self.assertIn('expired', self.backend.status()['events'][0])

    def test_feedback_loss_restores_automatic(self):
        self.backend.set(1, 2000)
        (self.device / 'fan1_input').unlink()
        self.backend.tick()
        self.assertEqual(self.writes, [2000, 0])

    def test_stalled_fan_and_external_target_change_restore(self):
        self.backend.set(1, 2000)
        self.put('fan1_input', 0)
        with patch('asahi_fan_control.control.now', return_value=now() + 6):
            self.backend.tick()
        self.assertEqual(self.writes[-1], 0)
        self.put('fan1_input', 1500)
        self.backend.set(1, 2300)
        self.put('fan1_target', 3000)
        self.backend.tick()
        self.assertEqual(self.writes[-1], 0)

    def test_write_error_recovers_even_after_partial_application(self):
        def failure(fd, value):
            os.ftruncate(fd, 0)
            write_number(fd, value)
            if value:
                raise OSError('simulated partial write failure')
        with patch('asahi_fan_control.control.write_number', side_effect=failure):
            with self.assertRaisesRegex(ControlError, 'automatic request accepted'):
                self.backend.set(1, 2400)
        self.assertEqual((self.device / 'fan1_target').read_text(), '0\n')
        self.assertEqual(self.backend.owned, {})

    def test_cleanup_failures_remain_visible_and_retryable(self):
        self.backend.set(1, 2000)
        with patch('asahi_fan_control.control.write_number', side_effect=OSError('driver unavailable')):
            with self.assertRaisesRegex(ControlError, 'Automatic return failed'):
                self.backend.close()
        self.assertIn(1, self.backend.owned)
        self.backend.close()
        self.assertEqual(self.backend.owned, {})

    def test_readback_mismatch_restores(self):
        with patch('asahi_fan_control.control.read_number', side_effect=lambda path: 3333 if path.name == 'fan1_target' else read_number(path)):
            with self.assertRaisesRegex(ControlError, 'read-back mismatch'):
                self.backend.set(1, 2000)
        self.assertEqual(self.writes, [2000, 0])

    def test_auto_all_uses_zero_without_reloading(self):
        with patch.object(self.backend, 'modprobe') as reload:
            self.backend.auto(all_fans=True)
            reload.assert_not_called()
        self.assertEqual(self.writes, [0, 0])

    def test_other_drivers_and_duplicate_devices_refused(self):
        self.put('name', 'other_driver')
        with self.assertRaises(ControlError):
            self.backend.set(1, 2000)
        self.put('name', 'macsmc_hwmon')
        second = self.device.with_name('hwmon8')
        second.mkdir()
        (second / 'name').write_text('macsmc_hwmon')
        with self.assertRaises(ControlError):
            self.backend.set(1, 2000)

    def test_enable_checks_unload_and_parameter(self):
        self.parameter.write_text('N')
        with patch.object(self.backend, 'modprobe', side_effect=ControlError('busy')) as modprobe:
            with self.assertRaisesRegex(ControlError, 'busy'):
                self.backend.enable()
            self.assertEqual(modprobe.call_count, 1)
        with patch.object(self.backend, 'modprobe'):
            with self.assertRaisesRegex(ControlError, 'did not enable'):
                self.backend.enable()

    def test_enable_rediscovers_device_after_reload(self):
        self.parameter.write_text('N')
        def modprobe(*args):
            if args == ('macsmc_hwmon', 'fan_control=1'):
                self.parameter.write_text('Y')
                self.device.rename(self.device.with_name('hwmon9'))
                self.device = self.device.with_name('hwmon9')
        with patch.object(self.backend, 'modprobe', side_effect=modprobe):
            self.assertIn('enabled', self.backend.enable())
        self.backend.set(1, 2100)
        self.assertEqual(self.backend.owned[1].directory.name, 'hwmon9')

    def test_enable_load_failure_attempts_default_recovery(self):
        self.parameter.write_text('N')
        with patch.object(self.backend, 'modprobe', side_effect=[None, ControlError('load failed'), None]) as run:
            with self.assertRaisesRegex(ControlError, 'load failed'):
                self.backend.enable()
            self.assertEqual(run.call_args.args, ('macsmc_hwmon', 'fan_control=0'))

    def test_lock_excludes_second_session(self):
        path = self.root / 'control.lock'
        fd = acquire_lock(path)
        try:
            with self.assertRaises(ControlError):
                acquire_lock(path)
        finally:
            os.close(fd)
        fd = acquire_lock(path)
        os.close(fd)

    def test_unknown_worker_command_is_rejected(self):
        with self.assertRaises(ControlError):
            dispatch(self.backend, {'action': 'shell', 'command': 'anything'})
        self.assertEqual(self.writes, [])


class WorkerRecoveryTests(unittest.TestCase):
    def start_worker(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        device = root / 'class/hwmon/hwmon0'
        device.mkdir(parents=True)
        for name, value in {'name': 'macsmc_hwmon', 'fan1_input': 2000, 'fan1_target': 2000,
                            'fan1_min': 1000, 'fan1_max': 5000}.items():
            (device / name).write_text(str(value))
        parameter = root / 'module/macsmc_hwmon/parameters/fan_control'
        parameter.parent.mkdir(parents=True)
        parameter.write_text('Y')
        code = '''
import os, sys
from pathlib import Path
from unittest.mock import patch
import asahi_fan_control.control as c
root = Path(sys.argv[1])
base, write = c.Backend, c.write_number
class FixtureBackend(base):
    def __init__(self, hold_seconds):
        super().__init__(root, hold_seconds)
def fixture_write(fd, value):
    os.ftruncate(fd, 0)
    write(fd, value)
# Use only fixtures: mocking the privilege check grants no OS privileges.
with patch.object(c, 'Backend', FixtureBackend), patch.object(c, 'acquire_lock', lambda: os.open(root/'lock', os.O_RDWR|os.O_CREAT, 0o600)), patch.object(c.os, 'geteuid', return_value=0), patch.object(c, 'write_number', fixture_write):
    sys.exit(c.worker(False, 5, lease_seconds=0.5))
'''
        process = subprocess.Popen([sys.executable, '-c', code, str(root)], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        def cleanup():
            if process.poll() is None:
                process.kill()
                process.wait()
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
        self.addCleanup(cleanup)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        self.addCleanup(selector.close)
        def response():
            self.assertTrue(selector.select(5), 'worker response timed out')
            return json.loads(process.stdout.readline())
        self.assertTrue(response()['ok'])
        process.stdin.write(b'{"action":"set","fan":1,"rpm":2400}\n')
        process.stdin.flush()
        self.assertTrue(response()['ok'])
        self.assertEqual((device / 'fan1_target').read_text(), '2400\n')
        return process, device / 'fan1_target'

    def test_ui_disconnect_restores_automatic(self):
        process, target = self.start_worker()
        process.stdin.close()
        self.assertEqual(process.wait(timeout=5), 0, process.stderr.read().decode())
        self.assertEqual(target.read_text(), '0\n')

    def test_frozen_ui_lease_expiry_restores_automatic(self):
        process, target = self.start_worker()
        self.assertEqual(process.wait(timeout=5), 0, process.stderr.read().decode())
        self.assertEqual(target.read_text(), '0\n')

    def test_sigterm_restores_automatic(self):
        process, target = self.start_worker()
        process.send_signal(signal.SIGTERM)
        self.assertEqual(process.wait(timeout=5), 0, process.stderr.read().decode())
        self.assertEqual(target.read_text(), '0\n')


if __name__ == '__main__':
    unittest.main()
