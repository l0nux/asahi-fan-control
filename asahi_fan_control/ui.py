"""English curses dashboard and plain-text rendering."""

import curses
import time

from . import __version__
from .sensors import Snapshot


def number(value: int | float | None, suffix: str = '') -> str:
    if value is None:
        return 'N/A'
    return (f'{value:.1f}' if isinstance(value, float) else str(value)) + suffix


def overview(snapshot: Snapshot) -> list[str]:
    lines = ['FANS  |  Speed / advertised range / target', '']
    for fan in snapshot.fans:
        lines.extend([
            f'{fan.label}  {number(fan.rpm, " RPM")}  [{fan.status}]',
            f'  Range {number(fan.minimum)} - {number(fan.maximum)} RPM'
            f'   Target {number(fan.target)} RPM',
            f'  {fan.source}  |  {fan.target_access}', ''])
    if not snapshot.fans:
        lines.extend(['No fan sensors exposed by this system.', ''])
    lines.extend(['TEMPERATURES  |  Individual sensors, not CPU/GPU estimates', ''])
    for sensor in snapshot.temperatures:
        lines.extend([
            f'{number(sensor.celsius, " C"):>8}  {sensor.label}  [{sensor.status}]',
            f'          {sensor.source}' + (
                f'  Max {number(sensor.maximum, " C")} / Crit {number(sensor.critical, " C")}'
                if sensor.maximum is not None or sensor.critical is not None else '')])
    if not snapshot.temperatures:
        lines.append('No temperature sensors exposed by this system.')
    lines.extend(['', 'OK means readable with no reported fault/limit breach; it is not a safety guarantee.',
                  'Thermal zones may duplicate hwmon readings. 0 RPM can be a valid reading.'])
    if snapshot.issues:
        lines.extend(['', 'READ ERRORS'] + snapshot.issues)
    return lines


def diagnostics(snapshot: Snapshot) -> list[str]:
    lines = [
        'CONTROL CAPABILITIES', '',
        f'macsmc: {snapshot.fan_control}',
        'Application: read-only; no fan writes or module changes.',
        'Active SMC fan mode: unverified (target RPM does not identify mode).',
        'Manual fan control is marked unsafe by the kernel documentation.',
        'No synthetic CPU/GPU temperature or automatic fan curve is used.', '',
        'FAN TARGET ACCESS', '']
    lines += [f'{fan.source} / {fan.label}: {fan.target_access}' for fan in snapshot.fans]
    if not snapshot.fans:
        lines.append('No fans discovered.')
    lines += ['', 'LINUX COOLING DEVICES  |  These are not necessarily fans', '']
    lines += snapshot.cooling or ['No cooling devices exposed.']
    lines += ['', 'SENSOR PATHS', '']
    lines += [f'{s.label}: {s.path}' for s in snapshot.temperatures + snapshot.fans]
    lines += ['', 'READ ERRORS', ''] + (snapshot.issues or ['None in this snapshot.'])
    return lines


def text_snapshot(snapshot: Snapshot) -> str:
    return '\n'.join([
        f'ASAHI FAN CONTROL {__version__}' + (' [DEMO DATA]' if snapshot.demo else ''),
        snapshot.model, snapshot.timestamp, f'Control: {snapshot.fan_control}',
        'Application: READ-ONLY', '', *overview(snapshot), '', *diagnostics(snapshot)])


def clean(text: str) -> str:
    # Sysfs labels and terminal paths must not inject terminal control sequences.
    return ''.join(c if c.isprintable() else '?' for c in text)


def put(screen, y: int, x: int, text: str, style: int = 0) -> None:
    height, width = screen.getmaxyx()
    if 0 <= y < height and x < width - 1:
        try:
            screen.addnstr(y, x, clean(text), max(0, width - x - 1), style)
        except curses.error:
            pass  # Resizing or a wide character can race the current dimensions.


def run(screen, reader, interval: float) -> None:
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    screen.keypad(True)
    screen.timeout(100)
    accent = curses.A_BOLD
    if curses.has_colors():
        try:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            accent |= curses.color_pair(1)
        except curses.error:
            pass
    snapshot = reader.snapshot()
    next_sample = time.monotonic() + interval
    paused, tab, offset = False, 0, 0
    while True:
        now = time.monotonic()
        if not paused and now >= next_sample:
            snapshot = reader.snapshot()
            next_sample = now + interval
        height, width = screen.getmaxyx()
        screen.erase()
        if height < 10 or width < 42:
            put(screen, 0, 0, 'Terminal too small (minimum 42 x 10).')
            put(screen, 1, 0, 'Resize or press q to quit.')
            page_size = 1
        else:
            page_size = max(1, height - 8)
            body = overview(snapshot) if tab == 0 else diagnostics(snapshot)
            offset = min(offset, max(0, len(body) - page_size))
            put(screen, 0, 1, f'ASAHI FAN CONTROL  {__version__}  /  READ-ONLY', accent)
            put(screen, 1, 1, snapshot.model)
            marker = 'DEMO DATA' if snapshot.demo else 'LIVE'
            if paused:
                marker += ' / PAUSED'
            put(screen, 2, 1, f'{marker}  |  {snapshot.timestamp}  |  Poll {interval:g}s')
            put(screen, 3, 1, '[OVERVIEW]  Diagnostics' if tab == 0 else 'Overview  [DIAGNOSTICS]', accent)
            put(screen, 4, 1, '-' * (width - 2))
            for row, line in enumerate(body[offset:offset + page_size], 5):
                put(screen, row, 1, line, accent if line.isupper() else 0)
            put(screen, height - 3, 1, f'Lines {offset + 1}-{min(offset + page_size, len(body))}/{len(body)}'
                '  |  Control: ' + snapshot.fan_control)
            put(screen, height - 2, 1, 'Tab views | j/k scroll | Space pause | r refresh | q quit', accent)
        screen.refresh()
        key = screen.getch()
        if key in (ord('q'), ord('Q'), 27):
            return
        if key == ord('\t'):
            tab, offset = 1 - tab, 0
        elif key == ord(' '):
            paused = not paused
            next_sample = 0
        elif key in (ord('r'), ord('R')):
            snapshot = reader.snapshot()
            next_sample = time.monotonic() + interval
        elif key in (curses.KEY_DOWN, ord('j')):
            offset += 1
        elif key in (curses.KEY_UP, ord('k')):
            offset = max(0, offset - 1)
        elif key == curses.KEY_NPAGE:
            offset += page_size
        elif key == curses.KEY_PPAGE:
            offset = max(0, offset - page_size)
        elif key == curses.KEY_HOME:
            offset = 0
