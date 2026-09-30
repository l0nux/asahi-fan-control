import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asahi_fan_control.sensors import DemoReader, Reader


class SensorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.device = self.root / 'class/hwmon/hwmon7'
        self.device.mkdir(parents=True)
        self.write('name', 'macsmc_hwmon')
        self.reader = Reader(self.root)

    def write(self, name, value):
        path = self.device / name
        path.write_text(str(value))
        return path

    def test_temperature_units_and_real_zero_rpm(self):
        self.write('temp1_input', '45813\n')
        self.write('temp1_label', 'WiFi/BT Module Temp')
        self.write('fan1_input', 0)
        self.write('fan1_min', 1350)
        self.write('fan1_target', 0).chmod(0o444)
        snapshot = self.reader.snapshot()
        self.assertEqual(snapshot.temperatures[0].celsius, 45.813)
        self.assertEqual(snapshot.temperatures[0].label, 'WiFi/BT Module Temp')
        fan = snapshot.fans[0]
        self.assertEqual(fan.rpm, 0)
        self.assertEqual(fan.target, 0)
        self.assertIsNone(fan.maximum)
        self.assertEqual(fan.target_access, 'driver read-only')
        self.assertEqual(fan.status, 'OK')

    def test_invalid_reading_is_unavailable_not_zero(self):
        self.write('temp1_input', 'broken')
        self.write('fan1_input', 'broken')
        snapshot = self.reader.snapshot()
        self.assertIsNone(snapshot.temperatures[0].celsius)
        self.assertEqual(snapshot.temperatures[0].status, 'UNAVAILABLE')
        self.assertIsNone(snapshot.fans[0].rpm)
        self.assertEqual(len(snapshot.issues), 2)

    def test_faulted_sensor_cannot_be_reported_ok(self):
        self.write('temp1_input', 44000)
        self.write('temp1_fault', 1)
        self.write('fan1_input', 1500)
        self.write('fan1_fault', 1)
        snapshot = self.reader.snapshot()
        self.assertIsNone(snapshot.temperatures[0].celsius)
        self.assertEqual(snapshot.temperatures[0].status, 'FAULT')
        self.assertIsNone(snapshot.fans[0].rpm)
        self.assertEqual(snapshot.fans[0].status, 'FAULT')

    def test_limits_come_from_driver(self):
        self.write('temp1_input', 95000)
        self.assertEqual(self.reader.snapshot().temperatures[0].status, 'OK')
        self.write('temp1_max', 90000)
        self.assertEqual(self.reader.snapshot().temperatures[0].status, 'HIGH')
        self.write('temp1_crit', 95000)
        self.assertEqual(self.reader.snapshot().temperatures[0].status, 'CRITICAL')
        self.write('temp1_alarm', 1)
        self.assertEqual(self.reader.snapshot().temperatures[0].status, 'ALARM')

    def test_device_renumbering_and_disappearance(self):
        self.write('fan1_input', 2000)
        self.assertEqual(len(self.reader.snapshot().fans), 1)
        new_path = self.device.with_name('hwmon12')
        self.device.rename(new_path)
        snapshot = self.reader.snapshot()
        self.assertEqual(snapshot.fans[0].source, 'macsmc_hwmon/hwmon12')
        (new_path / 'fan1_input').unlink()
        self.assertEqual(self.reader.snapshot().fans, [])

    def test_missing_and_permission_limited_targets_are_distinct(self):
        path = self.device / 'fan1_target'
        self.assertEqual(Reader.target_access(path), 'not exposed')
        self.write('fan1_target', 1500).chmod(0o644)
        with patch('asahi_fan_control.sensors.os.access', return_value=False):
            self.assertEqual(Reader.target_access(path), 'permission required')
        with patch('asahi_fan_control.sensors.os.access', return_value=True):
            self.assertEqual(Reader.target_access(path), 'writable (app read-only)')

    def test_disabled_parameter_and_missing_model(self):
        path = self.root / 'module/macsmc_hwmon/parameters/fan_control'
        path.parent.mkdir(parents=True)
        path.write_text('N\n')
        snapshot = self.reader.snapshot()
        self.assertEqual(snapshot.model, 'Linux system')
        self.assertIn('Disabled', snapshot.fan_control)
        path.write_text('Y')
        self.assertIn('remains read-only', self.reader.snapshot().fan_control)
        path.unlink()
        self.assertIn('Unknown', self.reader.snapshot().fan_control)

    def test_thermal_zone_and_cooling_device(self):
        thermal = self.root / 'class/thermal'
        zone = thermal / 'thermal_zone0'
        zone.mkdir(parents=True)
        (zone / 'temp').write_text('33000')
        (zone / 'type').write_text('macsmc-battery')
        device = thermal / 'cooling_device0'
        device.mkdir()
        (device / 'type').write_text('PCIe_Port_Link_Speed')
        (device / 'cur_state').write_text('0')
        (device / 'max_state').write_text('1')
        snapshot = self.reader.snapshot()
        self.assertEqual(snapshot.temperatures[0].celsius, 33.0)
        self.assertEqual(snapshot.cooling, ['PCIe_Port_Link_Speed: state 0 / 1'])
        self.assertEqual(snapshot.fans, [])

    def test_no_writes_during_snapshot(self):
        self.write('fan1_input', 2000)
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.reader.snapshot()
        after = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_demo_does_not_read_sysfs(self):
        with patch('pathlib.Path.read_text', side_effect=AssertionError('Hardware read')):
            snapshot = DemoReader().snapshot()
        self.assertTrue(snapshot.demo)
        self.assertEqual(len(snapshot.fans), 2)

    def test_unreadable_sensor_and_negative_temperature(self):
        self.write('temp1_input', -1000)
        self.assertEqual(self.reader.snapshot().temperatures[0].celsius, -1.0)
        with patch('pathlib.Path.read_text', side_effect=PermissionError):
            snapshot = self.reader.snapshot()
        self.assertIsNone(snapshot.temperatures[0].celsius)
        self.assertTrue(snapshot.issues)


if __name__ == '__main__':
    unittest.main()
