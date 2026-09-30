"""Exercise the actual curses/worker workflow in a pseudo-terminal."""
import fcntl
import os
import pty
import select
import signal
import struct
import subprocess
import sys
import termios
import time
import unittest


class TerminalTests(unittest.TestCase):
    def test_demo_control_workflow_and_resize(self):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        def resize(rows, columns):
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', rows, columns, 0, 0))
        resize(35, 120)
        process = subprocess.Popen(
            [sys.executable, '-m', 'asahi_fan_control', '--demo', '--control', '--hold-seconds', '5'],
            stdin=slave, stdout=slave, stderr=slave, env={**os.environ, 'TERM': 'xterm-256color'})
        def cleanup():
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
        self.addCleanup(cleanup)
        def until(expected):
            output = b''
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if select.select([master], [], [], 0.1)[0]:
                    output += os.read(master, 65536)
                    if expected in output:
                        return
            self.fail(f'Missing {expected!r}: {output[-1800:]!r}')
        until(b'ASAHI FAN CONTROL')
        os.write(master, b'e')
        until(b'marked unsafe')
        os.write(master, b'y')
        until(b'DEMO: control enabled')
        os.write(master, b's2500\n')
        until(b'DEMO: Fan 1 set to 2500 RPM')
        os.write(master, b'ns2700\n')
        until(b'DEMO: Fan 2 set to 2700 RPM')
        os.write(master, b'a')
        until(b'automatic request accepted')
        os.write(master, b's99999\n')
        until(b'outside its advertised range')
        os.write(master, b' ')
        until(b'PAUSED')
        resize(6, 30)
        process.send_signal(signal.SIGWINCH)
        until(b'Terminal too small')
        resize(35, 120)
        process.send_signal(signal.SIGWINCH)
        until(b'FAN CONTROL')
        os.write(master, b'q')
        self.assertEqual(process.wait(timeout=10), 0)


if __name__ == '__main__':
    unittest.main()
