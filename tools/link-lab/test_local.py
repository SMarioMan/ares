"""Exercise same-machine windows, isolated keyboard input, state barriers and cleanup."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from Xlib import X, XK, display, error
from Xlib.ext import xtest


def validate(worker,rom,players,mode='grand-prix'):
    connection=display.Display()
    key=connection.keysym_to_keycode(XK.string_to_keysym('z'))
    xtest.fake_input(connection,X.KeyRelease,key);connection.sync()
    def windows():
        found=[]
        for window in connection.screen().root.query_tree().children:
            try: name=str(window.get_wm_name())
            except error.BadWindow: continue
            if 'Super Mario Kart Link' in name: found.append((window,name))
        return found
    with tempfile.TemporaryDirectory(prefix='ares-local-test-') as directory:
        report=Path(directory)/'report.json'
        with (Path(directory)/'console.log').open('w+') as log:
            process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('play.py')),'local',
                '--worker',str(Path(worker).resolve()),'--rom',str(Path(rom).resolve()),
                '--players',str(players),'--mode',mode,'--frames','120','--report',str(report)],
                stdout=log,stderr=log,env=dict(os.environ,SDL_VIDEODRIVER='x11'),start_new_session=True)
            pids=[]
            try:
                deadline=time.monotonic()+60
                while True:
                    log.flush();log.seek(0)
                    if f'Local {players}-player' in log.read():break
                    assert process.poll() is None, 'Local launcher failed during startup'
                    assert time.monotonic()<deadline,'Local windows did not initialize'
                    time.sleep(0.05)
                live=windows();assert len(live)==players
                positions={(w.get_geometry().x,w.get_geometry().y) for w,_ in live}
                assert len(positions)==players,'Local windows were not tiled'
                target=next(w for w,name in live if 'Player 1 of' in name)
                connection.set_input_focus(target,X.RevertToParent,X.CurrentTime)
                xtest.fake_input(connection,X.KeyPress,key);connection.sync()
                # The launcher directly owns every core, without TCP coordinators.
                for entry in Path('/proc').iterdir():
                    if not entry.name.isdigit():continue
                    try: fields=(entry/'stat').read_text().rsplit(')',1)[1].split()
                    except (FileNotFoundError,ProcessLookupError):continue
                    if int(fields[1])==process.pid:pids.append(int(entry.name))
                assert len(pids)==players*2,'Canonical or render worker missing'
                assert process.wait(timeout=120)==0,'Local session failed'
                result=json.loads(report.read_text())
                assert result['frames']==120 and len(set(result['states']))==1
                assert result['pads'][0]&0x8000,'Keyboard player received no input'
                assert result['pads'][1:]==[0]*(players-1),'Keyboard input leaked into other players'
                assert not windows(),'A local game window survived cleanup'
                assert all(not Path(f'/proc/{pid}').exists() for pid in pids),'A local worker was orphaned'
                print(f'PASS: {players} tiled local windows, isolated keyboard/gamepad assignments, 121 state barriers, and {2*players} workers reaped')
            except BaseException:
                log.flush();log.seek(0);print(log.read(),file=sys.stderr);raise
            finally:
                xtest.fake_input(connection,X.KeyRelease,key);connection.sync()
                if process.poll() is None:
                    process.terminate();process.wait(timeout=30)
                connection.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--worker',required=True);p.add_argument('--rom',required=True)
    p.add_argument('--players',type=int,choices=range(2,9),default=2)
    p.add_argument('--mode',choices=('grand-prix','battle'),default='grand-prix')
    a=p.parse_args();validate(a.worker,a.rom,a.players,a.mode)
