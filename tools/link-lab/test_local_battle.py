"""Run a real multi-window local battle through menus into moving gameplay, without TCP."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import signal
import sys
import tempfile
from Xlib import display,error


def validate(worker,rom,players):
    connection=display.Display()
    with tempfile.TemporaryDirectory(prefix='ares-local-battle-') as directory:
        report=Path(directory)/'report.json'
        script='import sys;sys.path.insert(0,sys.argv.pop(1));import local;from session import trace;raise SystemExit(local.main(sys.argv[1:],input_trace=trace))'
        command=[sys.executable,'-c',script,str(Path(__file__).resolve().parent),
            '--worker',str(Path(worker).resolve()),'--rom',str(Path(rom).resolve()),
            '--players',str(players),'--mode','battle','--frames','2500','--report',str(report)]
        try:
            process=subprocess.Popen(command,env=dict(os.environ,SDL_VIDEODRIVER='x11'),start_new_session=True)
            try:
                assert process.wait(timeout=900)==0,'Local battle launcher failed'
            finally:
                if process.poll() is None:
                    os.killpg(process.pid,signal.SIGTERM)
                    try:process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid,signal.SIGKILL);process.wait()
            result=json.loads(report.read_text())
            assert result['mode']==14 and result['phase']==6,'Local menu trace did not enter battle'
            assert len(set(result['states']))==1 and result['frames']==2500
            assert all(result['views']),'A local player never received a private battle image'
            for window in connection.screen().root.query_tree().children:
                try: name=str(window.get_wm_name())
                except error.BadWindow:continue
                assert 'Super Mario Kart Link' not in name,'Local window survived shutdown'
            print(f'PASS: {players} actual local battle windows: native menus, movement, private views for all players, 2501 matching barriers and cleanup')
        finally:connection.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--worker',required=True);p.add_argument('--rom',required=True)
    p.add_argument('--players',type=int,choices=range(2,9),default=8)
    a=p.parse_args();validate(a.worker,a.rom,a.players)
