"""Launch eight real interactive peers, then verify coordinated disconnect/cleanup."""
import argparse
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time

from Xlib import X, XK, display, error
from Xlib.ext import xtest

from play import CHARACTERS


def validate(worker,rom,players=8,terminate_host=False):
    processes=[]
    connection=display.Display()
    escape=connection.keysym_to_keycode(XK.string_to_keysym('Escape'))
    xtest.fake_input(connection,X.KeyRelease,escape); connection.sync()
    def game_windows():
        result=[]
        for window in connection.screen().root.query_tree().children:
            try:
                name=str(window.get_wm_name())
            except error.BadWindow:
                continue  # SDL may destroy temporary windows during enumeration.
            if 'Super Mario Kart Link' in name: result.append((window,name))
        return result
    with tempfile.TemporaryDirectory(prefix='ares-launch-') as directory:
        logs=[]
        try:
            with socket.socket() as probe:
                probe.bind(('127.0.0.1',0))
                port=probe.getsockname()[1]
            def launch(command, slot):
                log=open(Path(directory)/f'{slot}.log','w+')
                logs.append(log)
                process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('play.py')),command,
                    '--rom',str(Path(rom).resolve()),'--worker',str(Path(worker).resolve()),
                    '--port',str(port),'--character',CHARACTERS[slot],
                    *(['--players',str(players)] if slot==0 else ['--host','127.0.0.1','--player',str(slot+1)])],
                    stdout=log,stderr=log,start_new_session=True,
                    env=dict(os.environ,SDL_VIDEODRIVER='x11'))
                processes.append(process)
            launch('host',0)
            deadline=time.monotonic()+30
            while True:
                logs[0].seek(0)
                if f'Hosting {players} players' in logs[0].read(): break
                assert processes[0].poll() is None, 'Host launcher exited during lobby setup'
                assert time.monotonic()<deadline, 'Host launcher timed out'
                time.sleep(0.05)
            for slot in range(1,players): launch('join',slot)
            deadline=time.monotonic()+60
            while True:
                windows=game_windows()
                if len(windows)==players and all(f' of {players}' in name for _,name in windows): break
                assert all(p.poll() is None for p in processes), 'An interactive peer failed to join'
                assert time.monotonic()<deadline, 'All SDL windows did not start'
                time.sleep(0.1)
            names=[name for _,name in windows]
            assert all(any(f'Player {slot}' in name for name in names) for slot in range(1,players+1))
            worker_pids=[]
            for window,_ in windows:
                prop=window.get_full_property(connection.intern_atom('_NET_WM_PID'),X.AnyPropertyType)
                assert prop is not None and len(prop.value)==1, 'SDL window has no process identity'
                worker_pids.append(int(prop.value[0]))
            time.sleep(2)
            assert all(p.poll() is None for p in processes), 'Interactive session failed after boot'
            # Each interactive client owns a canonical core and a render core.
            # Both must be reaped, including when the host is terminated.
            descendants=set(worker_pids)
            for pid in worker_pids:
                parent=int(Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[1])
                children=[]
                for entry in Path('/proc').iterdir():
                    if not entry.name.isdigit(): continue
                    try:
                        fields=(entry/'stat').read_text().rsplit(')',1)[1].split()
                    except (FileNotFoundError,ProcessLookupError):
                        continue
                    if int(fields[1])==parent: children.append(int(entry.name))
                assert len(children)==2, 'A client did not start its independent renderer'
                descendants.update(map(int,children))
            worker_pids=list(descendants)
            if terminate_host:
                os.kill(processes[0].pid,signal.SIGTERM)
            else:
                victim=next(w for w,name in game_windows() if f'Player {players}' in name)
                connection.set_input_focus(victim,X.RevertToParent,X.CurrentTime)
                connection.sync()
                xtest.fake_input(connection,X.KeyPress,escape); connection.sync()
            for index,process in enumerate(processes):
                expected=130 if terminate_host and index==0 else 1
                assert process.wait(timeout=30)==expected, 'Disconnect was not reported by a peer'
            deadline=time.monotonic()+5
            while True:
                remaining=game_windows()
                if not remaining: break
                assert time.monotonic()<deadline, 'A game worker/window survived session shutdown'
                time.sleep(0.05)
            assert all(not Path(f'/proc/{pid}').exists() for pid in worker_pids), 'A worker was orphaned or not reaped'
            print(f'PASS: host/join launchers, owner lobby, {players} SDL windows, coordinated disconnect, and cleanup')
        except BaseException:
            for index,log in enumerate(logs):
                log.flush(); log.seek(0)
                print(f'Player {index+1}: {log.read()}',file=sys.stderr)
            raise
        finally:
            xtest.fake_input(connection,X.KeyRelease,escape); connection.sync()
            for process in processes:
                if process.poll() is None:
                    os.killpg(process.pid,signal.SIGTERM)
                    process.wait(timeout=10)
            for log in logs: log.close()
            connection.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',required=True)
    parser.add_argument('--rom',required=True)
    parser.add_argument('--players',type=int,choices=range(2,9),default=8)
    parser.add_argument('--terminate-host',action='store_true')
    args=parser.parse_args()
    validate(args.worker,args.rom,args.players,args.terminate_host)
