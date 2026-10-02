#!/usr/bin/env python3
"""Run the real extension in a private GNOME 51 headless session, using demo control."""
import os, socket, subprocess, tempfile, pathlib, time, zipfile, json, sys
root=pathlib.Path(tempfile.mkdtemp(prefix='asahi-shell-'))
for name in ('runtime','data','config'):
    (root/name).mkdir(mode=0o700)
uuid='asahi-fan-control@l0nux.github.io'
ext=root/'data/gnome-shell/extensions'/uuid
ext.mkdir(parents=True)
with zipfile.ZipFile(sys.argv[1]) as z: z.extractall(ext)
(ext/'extension.js').rename(ext/'subject.js')
(ext/'extension.js').write_text('''import GLib from 'gi://GLib';
import Subject from './subject.js';
function delay(ms) { return new Promise(resolve => GLib.timeout_add(GLib.PRIORITY_DEFAULT,ms,()=>{resolve();return GLib.SOURCE_REMOVE;})); }
export default class Test extends Subject {
 enable() {
  super.enable();
  this.test().catch(e => GLib.file_set_contents(GLib.getenv('ASAHI_TEST_RESULT'), 'FAIL '+e.message+' '+e.stack));
 }
 async test() {
  await delay(1200);
  this._demo = true;
  this._job?.cancel(); this._job=null;
  await this._poll();
  if(this._rows.size!==2) throw new Error('Expected two demo fan rows');
  await this._start();
  if(!this._worker || this._worker.closed) throw new Error('No control worker');
  await this._command('enable');
  if(!this._worker.state.enabled) throw new Error('Enable failed');
  const first=[...this._rows.values()][0];
  first.entry.set_text('2500');
  first.button.emit('clicked', 1);
  await delay(500);
  if(this._worker.state.manual['1']?.rpm!==2500) throw new Error('Set failed');
  await this._command('set', {fan:2,rpm:2700});
  if(this._worker.state.manual['2']?.rpm!==2700) throw new Error('Second fan failed');
  if(this._worker.state.manual['1'].remaining!==null) throw new Error('Unexpected target expiry');
  this._sharedEntry.set_text('3100');
  this._sharedButton.emit('clicked', 1);
  await delay(300);
  for(const fan of ['1','2']) if(this._worker.state.manual[fan]?.rpm!==3100) throw new Error('Shared field failed');
  await this._poll();
  if(this._sharedEntry.get_text()!=='3100') throw new Error('Shared entry lost during refresh');
  this._sharedEntry.set_text('1400');
  this._sharedButton.emit('clicked', 1);
  await delay(100);
  if(this._worker.state.manual['1'].rpm!==3100) throw new Error('Invalid shared RPM applied');
  for(const {rpm,button} of this._presetButtons) {
   if(!button.reactive) throw new Error('Preset unavailable');
   button.emit('clicked', 1);
   await delay(300);
   for(const fan of ['1','2']) if(this._worker.state.manual[fan]?.rpm!==rpm) throw new Error('Preset failed '+rpm);
  }
  await this._command('auto');
  if(Object.keys(this._worker.state.manual).length) throw new Error('Auto failed');
  await this._command('set_all', {rpm:3000});
  await this._end();
  if(this._ending) throw new Error('Session stuck ending');
  const rows=this._rows.size;
  super.disable();
  if(this._panel || this._worker || this._timer || this._job) throw new Error('Disable leak');
  super.enable();
  await delay(500);
  if(!this._panel || !this._timer) throw new Error('Re-enable failed');
  super.disable();
  GLib.file_set_contents(GLib.getenv('ASAHI_TEST_RESULT'), 'PASS: Shell 51 panel, '+rows+' fan rows, enable, individual/shared targets, three presets, no expiry, auto, end, disable, re-enable');
 }
}
''')
config=root/'bus.conf'
config.write_text('<busconfig><type>session</type><policy context="default"><allow send_destination="*"/><allow receive_sender="*"/><allow own="*"/></policy></busconfig>')
listener=socket.socket(socket.AF_UNIX)
listener.bind(str(root/'runtime/bus'))
listener.listen(128)
fd=listener.fileno()
launcher='import os,sys; fd=int(sys.argv[1]); os.dup2(fd,3); os.set_inheritable(3,True); os.environ["LISTEN_PID"]=str(os.getpid()); os.environ["LISTEN_FDS"]="1"; os.execv("/usr/bin/dbus-broker-launch",["dbus-broker-launch","--scope","user","--config-file",sys.argv[2]])'
buslog=open(root/'bus.log','w')
bus=subprocess.Popen([sys.executable,'-c',launcher,str(fd),str(config)],pass_fds=(fd,),stdout=buslog,stderr=buslog)
env={**os.environ, 'XDG_RUNTIME_DIR':str(root/'runtime'),'XDG_DATA_HOME':str(root/'data'),'XDG_CONFIG_HOME':str(root/'config'),'DBUS_SESSION_BUS_ADDRESS':f'unix:path={root}/runtime/bus','GSETTINGS_BACKEND':'keyfile','LIBGL_ALWAYS_SOFTWARE':'1','ASAHI_TEST_RESULT':str(root/'result.txt')}
for name in ('WAYLAND_DISPLAY','DISPLAY'):env.pop(name,None)
print(root,flush=True)
try:
    subprocess.run(['gsettings','set','org.gnome.shell','enabled-extensions',f"['{uuid}']"],env=env,check=True,timeout=8)
    with open(root/'shell.log','w') as log:
        shell=subprocess.Popen(['/usr/bin/gnome-shell','--headless','--wayland','--virtual-monitor','1280x800','--no-x11'],env=env,stdout=log,stderr=log)
    try:
        time.sleep(8)
        result=subprocess.run(['gdbus','call','--session','--dest','org.gnome.Shell','--object-path','/org/gnome/Shell','--method','org.gnome.Shell.Extensions.GetExtensionInfo',uuid],env=env,capture_output=True,text=True,timeout=10)
        print(result.stdout,result.stderr,flush=True)
        outcome = (root/'result.txt').read_text() if (root/'result.txt').exists() else 'NO RESULT'
        print(outcome, flush=True)
        if not outcome.startswith('PASS:'):
            print((root/'shell.log').read_text()[-7000:], flush=True)
            raise SystemExit(1)
    finally:
        shell.terminate()
        try:shell.wait(timeout=8)
        except subprocess.TimeoutExpired:shell.kill();shell.wait()
finally:
    bus.terminate()
    try:bus.wait(timeout=5)
    except subprocess.TimeoutExpired:bus.kill();bus.wait()
    listener.close()
