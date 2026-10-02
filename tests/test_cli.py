import json
import subprocess
import sys
import unittest


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'asahi_fan_control', *args],
                              text=True, capture_output=True, timeout=5)

    def test_json_snapshot(self):
        result = self.run_cli('--demo', '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data['demo'])
        self.assertEqual(data['fans'][0]['rpm'], 1800)

    def test_once_snapshot_is_clearly_read_only(self):
        result = self.run_cli('--demo', '--once')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('DEMO DATA', result.stdout)
        self.assertIn('READ-ONLY', result.stdout)
        self.assertIn('unverified', result.stdout)

    def test_bad_interval_rejected(self):
        for value in ('nan', 'inf', '-1', '0', '61', 'fast'):
            with self.subTest(value=value):
                result = self.run_cli('--json', '--interval', value)
                self.assertEqual(result.returncode, 2)
                self.assertIn('interval', result.stderr)

    def test_non_terminal_is_actionable(self):
        result = self.run_cli('--demo')
        self.assertEqual(result.returncode, 2)
        self.assertIn('--once or --json', result.stderr)

    def test_control_argument_validation(self):
        for args in [('--json', '--control'), ('--auto', '--enable-control'),
                     ('--set', '1', '0'), ('--set', '../bad', '2000'),
                     ('--hold-seconds', '1'), ('--hold-seconds', '601')]:
            with self.subTest(args=args):
                result = self.run_cli('--demo', *args)
                self.assertEqual(result.returncode, 2)

    def test_control_does_not_implicitly_enable(self):
        result = self.run_cli('--demo', '--set', '1', '2000')
        self.assertEqual(result.returncode, 1)
        self.assertIn('enable control', result.stderr)

    def test_explicit_demo_enable(self):
        result = self.run_cli('--demo', '--enable-control')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('no hardware changed', result.stdout)


if __name__ == '__main__':
    unittest.main()
