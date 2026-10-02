"""Validate test planning without invoking pkexec or touching hardware."""
import runpy
from pathlib import Path
import unittest

from asahi_fan_control.sensors import DemoReader

MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'tools/validate-hardware.py'))


class HardwarePlanTests(unittest.TestCase):
    def test_targets_increase_rpm_without_exceeding_bounds(self):
        fans = DemoReader().snapshot().fans
        targets = MODULE['targets_for'](fans)
        for index, fan in enumerate(fans, 1):
            self.assertGreater(targets[index], fan.rpm)
            self.assertGreaterEqual(targets[index], fan.minimum)
            self.assertLessEqual(targets[index], fan.maximum)
            fan.rpm = targets[index]
        self.assertTrue(MODULE['converged'](fans, targets))
        fans[0].rpm = 0
        self.assertFalse(MODULE['converged'](fans, targets))

    def test_unavailable_bounds_and_insufficient_headroom_refused(self):
        for mutation in ({'minimum': None}, {'rpm': -1}, {'rpm': None}, {'status': 'FAULT'}):
            fans = DemoReader().snapshot().fans
            for key, value in mutation.items():
                setattr(fans[0], key, value)
            with self.assertRaises(RuntimeError):
                MODULE['targets_for'](fans)
        fans = DemoReader().snapshot().fans
        fans[0].rpm = fans[0].maximum
        with self.assertRaises(RuntimeError):
            MODULE['targets_for'](fans)
