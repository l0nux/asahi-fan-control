// Run with: gjs -m tests/test_transport.js /absolute/path/to/unpacked/bridge.py
import GLib from 'gi://GLib';
import {SnapshotJob, WorkerClient} from '../gnome-extension/transport.js';

function assert(value, message) {
    if (!value)
        throw new Error(message);
}

const loop = new GLib.MainLoop(null, false);
let failed = false;
async function main() {
    const bridge = ARGV[0];
    assert(bridge, 'Pass the packed extension bridge path.');
    const argv = ['/usr/bin/python3', '-I', bridge];
    const snapshot = await new SnapshotJob([...argv, 'snapshot', '--demo']).result;
    assert(snapshot.demo && snapshot.fans.length === 2, 'Bundled demo snapshot');
    assert(!('model' in snapshot), 'No machine identity in panel snapshot');
    const worker = new WorkerClient([...argv, 'worker', '--demo']);
    try {
        await worker.ready;
        let refused = false;
        try { await worker.request('set', {fan: 1, rpm: 2500}); } catch (_) { refused = true; }
        assert(refused, 'No implicit enable');
        await worker.request('enable');
        await worker.request('set', {fan: 1, rpm: 2500});
        assert(worker.state.manual['1'].rpm === 2500, 'Set response');
        await worker.request('set', {fan: 2, rpm: 2700});
        assert(worker.state.manual['2'].rpm === 2700, 'Independent fan control');
        await worker.request('set_all', {rpm: 3000});
        assert(worker.state.manual['1'].rpm === 3000 && worker.state.manual['2'].rpm === 3000, 'Shared target');
        assert(Object.values(worker.state.manual).every(fan => fan.remaining === null), 'No target expiry');
        let invalidShared = false;
        try { await worker.request('set_all', {rpm: 1400}); } catch (_) { invalidShared = true; }
        assert(invalidShared && worker.state.manual['1'].rpm === 3000, 'Shared bounds reject without mutation');
        await worker.request('auto');
        assert(Object.keys(worker.state.manual).length === 0, 'Automatic request');
    } finally {
        worker.close();
    }
    assert((await worker.exited).ok, 'Worker exits cleanly after EOF');
    // A slow enable must leave the GLib main loop running, unlike the old TUI.
    const fixture = 'import json,sys,time\nprint(json.dumps({"ok":True}),flush=True)\nfor line in sys.stdin:\n time.sleep(1.2)\n print(json.dumps({"ok":True,"enabled":True}),flush=True)';
    const delayed = new WorkerClient(['/usr/bin/python3', '-I', '-c', fixture]);
    let ticks = 0;
    const timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 20, () => {
        ticks++;
        return GLib.SOURCE_CONTINUE;
    });
    try {
        await delayed.ready;
        await delayed.request('enable');
        assert(ticks >= 20, `Main loop blocked during enable: ${ticks} ticks`);
    } finally {
        GLib.Source.remove(timer);
        delayed.close();
    }
    assert((await delayed.exited).ok, 'Delayed worker exits');
    const rejected = new WorkerClient(['/usr/bin/python3', '-I', '-c', 'raise SystemExit(126)']);
    let denied = false;
    try { await rejected.ready; } catch (_) { denied = true; }
    assert(denied && rejected.closed, 'Authentication failure disconnects cleanly');
    assert(!(await rejected.exited).ok, 'Nonzero exit reported');
    const cancelled = new SnapshotJob(['/usr/bin/python3', '-I', '-c', 'import time;time.sleep(60)']);
    cancelled.cancel();
    let stopped = false;
    try { await cancelled.result; } catch (_) { stopped = true; }
    assert(stopped, 'Read-only reader is cancellable');
    print('PASS: bundled reader, two-fan workflow, rejection, EOF, cancellation, responsive slow enable');
}
main().catch(error => {
    printerr(error.stack);
    failed = true;
}).finally(() => loop.quit());
loop.run();
if (failed)
    throw new Error('GJS transport tests failed');
