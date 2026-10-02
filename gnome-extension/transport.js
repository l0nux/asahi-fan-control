// Non-blocking GIO transport. No shell strings, sync reads, or sync waits.
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

function removeTimer(id) {
    if (id)
        GLib.Source.remove(id);
}

function closeStream(stream) {
    stream.close_async(GLib.PRIORITY_DEFAULT, null, (object, result) => {
        try { object.close_finish(result); } catch (_) { /* Already closed. */ }
    });
}

export class SnapshotJob {
    constructor(argv) {
        this._proc = Gio.Subprocess.new(argv,
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
        this._cancel = new Gio.Cancellable();
        this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 10, () => {
            this._timer = 0;
            this.cancel();
            return GLib.SOURCE_REMOVE;
        });
        this.result = new Promise((resolve, reject) => {
            this._proc.communicate_utf8_async(null, this._cancel, (proc, result) => {
                removeTimer(this._timer);
                this._timer = 0;
                try {
                    const [, stdout, stderr] = proc.communicate_utf8_finish(result);
                    if (!proc.get_successful())
                        throw new Error(stderr.trim() || 'Sensor reader failed.');
                    resolve(JSON.parse(stdout));
                } catch (error) {
                    reject(error);
                }
            });
        });
    }

    cancel() {
        this._cancel.cancel();
        // Only a read-only telemetry process may be killed this way.
        this._proc.force_exit();
    }
}

export class WorkerClient {
    constructor(argv) {
        this.closed = false;
        this.busy = false;
        this.state = {};
        this._errorText = '';
        this._proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDIN_PIPE |
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
        this._input = this._proc.get_stdin_pipe();
        this._output = new Gio.DataInputStream({base_stream: this._proc.get_stdout_pipe()});
        this._errors = new Gio.DataInputStream({base_stream: this._proc.get_stderr_pipe()});
        this._readCancel = new Gio.Cancellable();
        this._writeCancel = new Gio.Cancellable();
        this._writing = false;
        this._inputClosed = false;
        this._timer = 0;
        this.ready = this._expect(60); // Authentication can take time; Shell remains responsive.
        this._readErrors();
        this._read();
        this.exited = new Promise(resolve => {
            this._proc.wait_async(null, (proc, result) => {
                try {
                    proc.wait_finish(result);
                    const ok = proc.get_successful();
                    resolve({ok, message: this._errorText || (ok ? '' : 'Worker exited unsuccessfully. Check fan status.')});
                } catch (error) {
                    resolve({ok: false, message: error.message});
                }
            });
        });
    }

    _expect(seconds) {
        this.busy = true;
        return new Promise((resolve, reject) => {
            this._pending = {resolve, reject};
            this._timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, seconds, () => {
                this._timer = 0;
                this._fail(new Error('Worker timed out. Recovery was requested; check fan status.'));
                return GLib.SOURCE_REMOVE;
            });
        });
    }

    _readErrors() {
        this._errors.read_line_async(GLib.PRIORITY_DEFAULT, this._readCancel, (stream, result) => {
            try {
                const [line] = stream.read_line_finish_utf8(result);
                if (line === null || this.closed)
                    return;
                this._errorText = (this._errorText + '\n' + line).slice(-2048).trim();
                this._readErrors();
            } catch (_) { /* Cancelled on extension disable. */ }
        });
    }

    _read() {
        this._output.read_line_async(GLib.PRIORITY_DEFAULT, this._readCancel, (stream, result) => {
            try {
                const [line] = stream.read_line_finish_utf8(result);
                if (this.closed)
                    return;
                if (line === null)
                    throw new Error(this._errorText || 'Authentication cancelled or worker disconnected.');
                const response = JSON.parse(line);
                if (!this._pending)
                    throw new Error('Unexpected worker response.');
                const pending = this._pending;
                this._pending = null;
                removeTimer(this._timer);
                this._timer = 0;
                this.busy = false;
                this.state = response;
                this._read();
                if (response.ok)
                    pending.resolve(response);
                else
                    pending.reject(new Error(response.message));
            } catch (error) {
                if (!this.closed)
                    this._fail(error);
            }
        });
    }

    request(action, values = {}) {
        if (this.closed || this.busy)
            return Promise.reject(new Error('Control worker is unavailable or busy.'));
        const response = this._expect(action === 'enable' ? 60 : 10);
        const bytes = new TextEncoder().encode(JSON.stringify({action, ...values}) + '\n');
        this._writing = true;
        this._input.write_all_async(bytes, GLib.PRIORITY_DEFAULT, this._writeCancel, (stream, result) => {
            this._writing = false;
            try {
                stream.write_all_finish(result);
            } catch (error) {
                if (!this.closed)
                    this._fail(error);
            }
            if (this.closed)
                this._closeInput();
        });
        return response;
    }

    _fail(error) {
        this.close(error);
    }

    _closeInput() {
        if (!this._writing && !this._inputClosed) {
            this._inputClosed = true;
            closeStream(this._input); // EOF lets the worker run its recovery path.
        }
    }

    close(error = new Error('Control session ended.')) {
        if (this.closed)
            return;
        this.closed = true;
        this.busy = false;
        removeTimer(this._timer);
        this._timer = 0;
        const pending = this._pending;
        this._pending = null;
        pending?.reject(error);
        this._writeCancel.cancel();
        this._closeInput();
        this._readCancel.cancel();
        // Never SIGKILL the process that owns manual fan targets.
        // Its EOF/heartbeat recovery continues independently of GNOME Shell.
    }
}
