"""English curses dashboard and plain-text rendering."""

import curses
import time
import re
import textwrap

from .control import ControlError

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


def diagnostics(snapshot: Snapshot, control=False) -> list[str]:
    lines = [
        'CONTROL CAPABILITIES', '',
        f'macsmc: {snapshot.fan_control}',
        ('Application: supervised manual control session.' if control else
         'Application: read-only; no fan writes or module changes.'),
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


def control_lines(controller, snapshot, selected):
    fans = [fan for fan in snapshot.fans if fan.source.startswith('macsmc_hwmon/')]
    lines = ['FAN CONTROL', '', 'N: select fan   S: set RPM   A: automatic for all   E: enable capability', '']
    if controller is None:
        return lines + ['Monitoring only. Start with --control (root required),',
                        'or --demo --control to try the complete workflow without hardware writes.']
    if controller.state.get('disconnected'):
        return lines + ['Worker disconnected; automatic recovery was attempted.',
                        'Check fan status and restart the control session. Active mode is unverified.']
    lines += ['Manual speeds expire automatically; the worker also monitors UI connectivity.',
              'Kernel manual capability: ' + ('ENABLED' if controller.state.get('enabled') else 'DISABLED'),
              'The driver cannot report active SMC mode. Session targets are shown below.', '']
    for index, fan in enumerate(fans):
        channel = re.search(r'fan(\d+)_input$', fan.path)
        entry = controller.state.get('manual', {}).get(channel.group(1)) if channel else None
        state = (f"{entry['rpm']} RPM / {entry['remaining']}s left" if entry else 'No session override')
        lines.append(f"{'>' if index == selected else ' '} {fan.label}: {state}")
    lines += ['', 'Enable reloads only macsmc_hwmon, and verifies the parameter and target access.',
              'Auto uses the driver zero-target command; it does not unload the driver.',
              'No boot configuration or permanent manual speed is saved.',
              'Recovery is best effort; it cannot protect against worker/kernel failure.',
              'Return to Auto before suspend. Do not run other fan controllers concurrently.']
    return lines


def run(screen, reader, interval: float, controller=None) -> None:
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
    selected, editing, digits = 0, None, ''
    message = 'Monitor mode. Use --control to enable control actions.' if controller is None else 'Control session ready. E enables kernel capability; S sets a bounded target.'
    next_control = 0.0
    disconnected = False
    while True:
        now = time.monotonic()
        if not paused and now >= next_sample:
            snapshot = reader.snapshot()
            next_sample = now + interval
        if controller is not None and not disconnected and now >= next_control:
            try:
                result = controller.request('status')
                if result.get('events'):
                    message = result['events'][-1]
            except ControlError as error:
                message = str(error)
                disconnected = True
                controller.state['disconnected'] = True
            next_control = now + 0.5
        fans = [fan for fan in snapshot.fans if fan.source.startswith('macsmc_hwmon/')]
        selected = min(selected, max(0, len(fans) - 1))
        if snapshot.demo and controller is not None:
            for fan in fans:
                channel = re.search(r'fan(\d+)_input$', fan.path)
                entry = controller.state.get('manual', {}).get(channel.group(1)) if channel else None
                fan.rpm = entry['rpm'] if entry else 0
                fan.target = entry['rpm'] if entry else 0
        height, width = screen.getmaxyx()
        screen.erase()
        if height < 14 or width < 42:
            put(screen, 0, 0, 'Terminal too small (minimum 42 x 14).')
            put(screen, 1, 0, 'Resize or press q to quit.')
            page_size = 1
        else:
            page_size = max(1, height - 10)
            body = (overview(snapshot) if tab == 0 else diagnostics(snapshot, controller is not None)
                    if tab == 1 else control_lines(controller, snapshot, selected))
            if tab == 2:
                body += ['', 'LAST ACTION'] + textwrap.wrap(clean(message), max(20, width - 4))
            offset = min(offset, max(0, len(body) - page_size))
            put(screen, 0, 1, f'ASAHI FAN CONTROL  {__version__}  /  ' + ('CONTROL' if controller else 'READ-ONLY'), accent)
            put(screen, 1, 1, snapshot.model)
            marker = 'DEMO DATA' if snapshot.demo else 'LIVE'
            if paused:
                marker += ' / PAUSED'
            put(screen, 2, 1, f'{marker}  |  {snapshot.timestamp}  |  Poll {interval:g}s')
            put(screen, 3, 1, '  '.join(('[' + label.upper() + ']') if i == tab else label
                                        for i, label in enumerate(('Overview', 'Diagnostics', 'Control'))), accent)
            put(screen, 4, 1, '-' * (width - 2))
            for row, line in enumerate(body[offset:offset + page_size], 5):
                put(screen, row, 1, line, accent if line.isupper() else 0)
            prompt = ('Enable kernel manual capability (marked unsafe)? y / Esc' if editing == 'enable'
                      else f'New RPM for {fans[selected].label}: {digits}_  Enter applies / Esc cancels'
                      if editing == 'rpm' and fans else message)
            put(screen, height - 5, 1, prompt, accent)
            put(screen, height - 4, 1, 'N fan | S set RPM | A automatic | E enable | Tab views')
            put(screen, height - 3, 1, f'Lines {offset + 1}-{min(offset + page_size, len(body))}/{len(body)}'
                '  |  Control: ' + snapshot.fan_control)
            put(screen, height - 2, 1, 'Tab views | j/k scroll | Space pause | r refresh | q quit', accent)
        screen.refresh()
        key = screen.getch()
        if editing:
            if key == 27:
                editing, digits = None, ''
            elif editing == 'rpm' and key in (curses.KEY_BACKSPACE, 127, 8):
                digits = digits[:-1]
            elif editing == 'rpm' and ord('0') <= key <= ord('9') and len(digits) < 6:
                digits += chr(key)
            elif (editing == 'rpm' and key in (10, 13)) or (editing == 'enable' and key in (ord('y'), ord('Y'))):
                try:
                    if editing == 'enable':
                        result = controller.request('enable')
                    elif digits and fans:
                        channel = int(re.search(r'fan(\d+)_input$', fans[selected].path).group(1))
                        result = controller.request('set', fan=channel, rpm=int(digits))
                    else:
                        raise ControlError('Enter a numeric RPM.')
                    message = result['message']
                    next_sample = 0
                except ControlError as error:
                    message = str(error)
                editing, digits = None, ''
            continue
        if key in (ord('e'), ord('E'), ord('s'), ord('S'), ord('a'), ord('A')):
            tab, offset = 2, 0
            if controller is None or disconnected:
                message = 'No active control worker. Restart with --control (or --demo --control).'
            elif key in (ord('e'), ord('E')):
                editing = 'enable'
            elif key in (ord('s'), ord('S')):
                if fans:
                    editing, digits = 'rpm', ''
                else:
                    message = 'No macsmc fans available.'
            else:
                try:
                    message = controller.request('auto')['message']
                    next_sample = 0
                except ControlError as error:
                    message = str(error)
            continue
        if key in (ord('n'), ord('N')):
            selected = (selected + 1) % max(1, len(fans))
            tab, offset = 2, 0
        if key in (ord('q'), ord('Q'), 27):
            return
        if key == ord('\t'):
            tab, offset = (tab + 1) % 3, 0
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
