import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import St from 'gi://St';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {SnapshotJob, WorkerClient} from './transport.js';

const display = value => typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value)}` : 'N/A';
const safeText = value => String(value ?? '').replace(/[\x00-\x1f\x7f]/g, ' ').slice(0, 250);

export default class AsahiFanControl extends Extension {
    enable() {
        this._alive = true;
        this._generation = Symbol('activation');
        this._snapshot = null;
        this._demo = false;
        this._ending = false;
        this._worker = null;
        this._job = null;
        this._rows = new Map();
        this._tempSignature = '';
        this._tempRows = [];
        this._panel = new PanelMenu.Button(0.0, 'Asahi Fan Control');
        this._label = new St.Label({text: 'Fans …', y_align: Clutter.ActorAlign.CENTER});
        this._panel.add_child(this._label);
        Main.panel.addToStatusArea(this.uuid, this._panel);
        const menu = this._panel.menu;
        this._statusItem = new PopupMenu.PopupMenuItem('Reading sensors…', {reactive: false});
        this._statusItem.label.add_style_class_name('asahi-status');
        menu.addMenuItem(this._statusItem);
        this._notice = new PopupMenu.PopupMenuItem('Monitoring only', {reactive: false});
        this._notice.label.add_style_class_name('asahi-status');
        menu.addMenuItem(this._notice);
        this._fanSection = new PopupMenu.PopupMenuSection();
        menu.addMenuItem(this._fanSection);
        const sharedItem = new PopupMenu.PopupBaseMenuItem({reactive: false, can_focus: false});
        const sharedBox = new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL, x_expand: true});
        this._sharedLabel = new St.Label({text: 'Both fans · Reading limits…', style_class: 'asahi-fan-label'});
        const sharedControls = new St.BoxLayout({style_class: 'asahi-controls'});
        this._sharedEntry = new St.Entry({hint_text: 'Shared RPM', can_focus: true, x_expand: true});
        this._sharedButton = new St.Button({label: 'Apply to both', style_class: 'button', can_focus: true});
        sharedControls.add_child(this._sharedEntry);
        sharedControls.add_child(this._sharedButton);
        sharedBox.add_child(this._sharedLabel);
        sharedBox.add_child(sharedControls);
        const presets = new St.BoxLayout({style_class: 'asahi-controls'});
        this._presetButtons = [2000, 3000, 4000].map(rpm => {
            const button = new St.Button({label: `${rpm} RPM`, style_class: 'button', can_focus: true, x_expand: true});
            button.connect('clicked', () => this._command('set_all', {rpm}));
            presets.add_child(button);
            return {rpm, button};
        });
        sharedBox.add_child(presets);
        sharedItem.add_child(sharedBox);
        menu.addMenuItem(sharedItem);
        this._sharedButton.connect('clicked', () => this._applyShared());
        this._sharedEntry.clutter_text.connect('activate', () => this._applyShared());
        this._temps = new PopupMenu.PopupSubMenuMenuItem('Temperatures');
        menu.addMenuItem(this._temps);
        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._startItem = menu.addAction('Start control session…', () => this._start());
        this._enableItem = menu.addAction('Enable manual capability…', () => {
            this._confirmItem.visible = !this._confirmItem.visible;
            this._message('Enabling may reload macsmc_hwmon. Manual control is marked unsafe by the kernel.');
        });
        this._confirmItem = menu.addAction('Confirm: enable kernel fan control', () => {
            this._confirmItem.visible = false;
            this._command('enable');
        });
        this._confirmItem.visible = false;
        this._autoItem = menu.addAction('Return all fans to automatic', () => this._command('auto'));
        this._endItem = menu.addAction('End control session', () => this._end());
        this._demoItem = new PopupMenu.PopupSwitchMenuItem('Demo mode (no hardware writes)', false);
        this._demoItem.connect('toggled', (_item, value) => {
            if (this._worker || this._ending) {
                this._demoItem.setToggleState(this._demo);
                this._message('End the control session before switching demo mode.');
                return;
            }
            this._demo = value;
            this._job?.cancel();
            this._job = null;
            this._message(value ? 'Simulated hardware. Start a demo control session.' : 'Monitoring only');
            this._poll();
        });
        menu.addMenuItem(this._demoItem);
        menu.addAction('Refresh sensors', () => this._poll());
        menu.addMenuItem(new PopupMenu.PopupMenuItem('Targets stay until Auto or End. Return to Auto before suspend.', {reactive: false}));
        this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 1, () => {
            this._heartbeat();
            if (!this._job)
                this._poll();
            return GLib.SOURCE_CONTINUE;
        });
        this._updateControls();
        this._poll();
    }

    _argv(operation) {
        return ['/usr/bin/python3', '-I', `${this.path}/bridge.py`, operation,
            ...(this._demo ? ['--demo'] : [])];
    }

    _message(text) {
        if (this._alive)
            this._notice.label.text = safeText(text);
    }

    async _poll() {
        if (!this._alive || this._job)
            return;
        let job;
        try {
            job = new SnapshotJob(this._argv('snapshot'));
            this._job = job;
            const data = await job.result;
            if (!this._alive || this._job !== job)
                return;
            this._snapshot = data;
            this._render(data);
        } catch (error) {
            if (this._alive && (!job || this._job === job)) {
                this._label.text = 'Fans —';
                this._statusItem.label.text = 'Sensor readings unavailable (stale)';
                this._message(error.message);
                this._snapshot = null;
                for (const row of this._rows.values())
                    row.label.text = 'Reading unavailable';
                this._updateControls();
            }
        } finally {
            if (this._job === job)
                this._job = null;
        }
    }

    _render(data) {
        const fans = data.fans.filter(fan => fan.source.startsWith('macsmc_hwmon/'));
        const readings = fans.map(fan => display(fan.rpm));
        this._label.text = `${this._demo ? 'DEMO ' : ''}Fans ${readings.join(' / ') || 'N/A'}`;
        this._statusItem.label.text = `${this._demo ? 'DEMO · ' : ''}${safeText(data.fan_control)}`;
        const keys = new Set(fans.map(fan => fan.path));
        for (const [key, row] of this._rows) {
            if (!keys.has(key)) {
                row.item.destroy();
                this._rows.delete(key);
            }
        }
        for (const fan of fans) {
            let row = this._rows.get(fan.path);
            if (!row) {
                const item = new PopupMenu.PopupBaseMenuItem({reactive: false, can_focus: false});
                const box = new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL, x_expand: true});
                const label = new St.Label({text: '', style_class: 'asahi-fan-label'});
                const controls = new St.BoxLayout({style_class: 'asahi-controls'});
                const entry = new St.Entry({hint_text: 'Target RPM', can_focus: true, x_expand: true});
                const button = new St.Button({label: 'Apply', style_class: 'button', can_focus: true});
                controls.add_child(entry);
                controls.add_child(button);
                box.add_child(label);
                box.add_child(controls);
                item.add_child(box);
                row = {item, label, entry, button, fan};
                const apply = () => {
                    const text = entry.get_text().trim();
                    const current = row.fan;
                    if (!/^\d{1,6}$/.test(text) || Number(text) < current.minimum || Number(text) > current.maximum) {
                        this._message(`Enter ${current.minimum}–${current.maximum} RPM for ${current.label}.`);
                        return;
                    }
                    const channel = /fan(\d+)_input$/.exec(current.path);
                    if (channel)
                        this._command('set', {fan: Number(channel[1]), rpm: Number(text)});
                };
                button.connect('clicked', apply);
                entry.clutter_text.connect('activate', apply);
                this._fanSection.addMenuItem(item);
                this._rows.set(fan.path, row);
            }
            row.fan = fan;
            const channel = /fan(\d+)_input$/.exec(fan.path)?.[1];
            const owned = this._worker?.state.manual?.[channel];
            const rpm = this._demo && owned ? owned.rpm : fan.rpm;
            row.label.text = `${safeText(fan.label)} · ${display(rpm)} RPM · ${safeText(fan.status)}\n` +
                `${display(fan.minimum)}–${display(fan.maximum)} RPM` +
                (owned ? ` · Target ${owned.rpm} · ${owned.remaining === null ? 'Until Auto / End' : `${owned.remaining}s left`}` : ' · No session override');
        }
        if (fans.length === 0)
            this._statusItem.label.text = 'No macsmc fan sensors found';
        const signature = data.temperatures.map(temp => temp.path).join('\n');
        if (signature !== this._tempSignature || this._tempRows.length === 0) {
            this._temps.menu.removeAll();
            this._tempRows = data.temperatures.map(() => {
                const item = new PopupMenu.PopupMenuItem('', {reactive: false});
                this._temps.menu.addMenuItem(item);
                return item;
            });
            this._tempSignature = signature;
        }
        data.temperatures.forEach((temp, index) => {
            this._tempRows[index].label.text = `${safeText(temp.label)}: ${display(temp.celsius)} °C · ${safeText(temp.status)}`;
        });
        this._temps.label.text = `Temperatures (${data.temperatures.length})`;
        this._updateControls();
    }

    _sharedBounds() {
        const fans = this._snapshot?.fans.filter(fan => fan.source.startsWith('macsmc_hwmon/')) ?? [];
        if (fans.length !== 2 || !fans.some(fan => /\/fan1_input$/.test(fan.path)) ||
            !fans.some(fan => /\/fan2_input$/.test(fan.path)) ||
            fans.some(fan => !Number.isFinite(fan.minimum) || !Number.isFinite(fan.maximum) || fan.minimum <= 0))
            return null;
        const minimum = Math.max(...fans.map(fan => fan.minimum));
        const maximum = Math.min(...fans.map(fan => fan.maximum));
        return minimum <= maximum ? {minimum, maximum} : null;
    }

    _applyShared() {
        const bounds = this._sharedBounds();
        const text = this._sharedEntry.get_text().trim();
        if (!bounds) {
            this._message('Shared RPM requires two fans with overlapping limits.');
            return;
        }
        if (!/^\d{1,6}$/.test(text) || Number(text) < bounds.minimum || Number(text) > bounds.maximum) {
            this._message(`Enter ${bounds.minimum}–${bounds.maximum} RPM for both fans.`);
            return;
        }
        this._command('set_all', {rpm: Number(text)});
    }

    _updateControls() {
        const worker = this._worker;
        const ready = worker && !worker.closed && !worker.busy;
        this._startItem.setSensitive(!worker && !this._ending);
        this._enableItem.setSensitive(Boolean(ready));
        this._confirmItem.setSensitive(Boolean(ready));
        this._autoItem.setSensitive(Boolean(ready && worker.state.enabled));
        this._endItem.setSensitive(Boolean(worker));
        this._demoItem.setSensitive(!worker && !this._ending);
        const sharedBounds = this._sharedBounds();
        this._sharedLabel.text = sharedBounds
            ? `Both fans · ${sharedBounds.minimum}–${sharedBounds.maximum} RPM`
            : 'Both fans · Shared RPM unavailable';
        const sharedReady = Boolean(sharedBounds && ready && worker.state.enabled);
        this._sharedButton.reactive = sharedReady;
        this._sharedButton.can_focus = sharedReady;
        this._sharedEntry.reactive = sharedReady;
        for (const {rpm, button} of this._presetButtons) {
            const sensitive = sharedReady && rpm >= sharedBounds.minimum && rpm <= sharedBounds.maximum;
            button.reactive = sensitive;
            button.can_focus = sensitive;
        }
        for (const row of this._rows.values()) {
            const bounds = row.fan.minimum > 0 && row.fan.maximum >= row.fan.minimum;
            const sensitive = Boolean(this._snapshot && ready && worker.state.enabled && bounds);
            row.button.reactive = sensitive;
            row.button.can_focus = sensitive;
            // Keep entry text and focus when heartbeat responses update state.
            row.entry.reactive = sensitive;
        }
    }

    async _start() {
        if (this._worker || this._ending)
            return;
        this._message(this._demo ? 'Starting demo session…' : 'Waiting for system authentication…');
        let worker;
        try {
            const argv = this._argv('worker');
            worker = new WorkerClient(this._demo ? argv : ['/usr/bin/pkexec', '--disable-internal-agent', ...argv]);
            this._worker = worker;
            this._updateControls();
            await worker.ready;
            if (!this._alive || this._worker !== worker)
                return;
            this._message('Control session ready. Enable capability before applying an RPM target.');
        } catch (error) {
            if (this._alive && (!worker || this._worker === worker)) {
                this._message(error.message);
                await this._end(false);
            }
        } finally {
            if (this._alive)
                this._updateControls();
        }
    }

    async _command(action, values = {}) {
        const worker = this._worker;
        if (!worker || worker.closed || worker.busy || this._ending)
            return;
        this._message(action === 'enable' ? 'Enabling… The menu remains available; End cancels the session.' : 'Applying request…');
        const request = worker.request(action, values);
        this._updateControls();
        try {
            const response = await request;
            if (this._alive && this._worker === worker)
                this._message(response.message);
        } catch (error) {
            if (this._alive && this._worker === worker)
                this._message(error.message);
        } finally {
            if (this._alive && this._worker === worker) {
                if (worker.closed)
                    await this._end(false);
                if (this._snapshot)
                    this._render(this._snapshot);
                this._updateControls();
            }
        }
    }

    async _heartbeat() {
        const worker = this._worker;
        if (worker?.closed && !this._ending) {
            this._message('Worker disconnected. Recovery was requested; check fan status.');
            await this._end(false);
            return;
        }
        if (!worker || worker.busy || this._ending)
            return;
        try {
            const response = await worker.request('status');
            if (!this._alive || this._worker !== worker)
                return;
            if (response.events?.length)
                this._message(response.events.at(-1));
            if (this._snapshot)
                this._render(this._snapshot);
        } catch (error) {
            if (this._alive && this._worker === worker) {
                this._message(error.message);
                await this._end(false);
            }
        }
    }

    async _end(showMessage = true) {
        const worker = this._worker;
        if (!worker || this._ending)
            return;
        this._worker = null;
        const generation = this._generation;
        this._ending = true;
        this._confirmItem.visible = false;
        worker.close();
        if (showMessage)
            this._message('Ending session; waiting for automatic-return requests…');
        this._updateControls();
        const outcome = await worker.exited;
        if (!this._alive || this._generation !== generation)
            return;
        this._ending = false;
        if (!outcome.ok || showMessage)
            this._message(outcome.ok ? 'Session ended. Recovery requests completed; physical SMC mode is unverified.' : outcome.message);
        this._updateControls();
    }

    disable() {
        this._alive = false;
        if (this._timer)
            GLib.Source.remove(this._timer);
        this._timer = 0;
        this._job?.cancel();
        this._job = null;
        this._worker?.close();
        this._worker = null;
        this._panel?.destroy();
        this._panel = null;
        this._rows.clear();
    }
}
