#!/usr/bin/env python3
"""Run 2–8 independent, synchronized game windows on one desktop without TCP."""
import argparse
import math
import json
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from session import AsyncView, LinkError, read_worker, worker_line

CHARACTERS=['mario','luigi','bowser','peach','donkey-kong-jr','koopa','toad','yoshi']


def main(argv=None,input_trace=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom',type=Path,required=True)
    parser.add_argument('--worker',type=Path,default=Path(__file__).with_name('bin')/'ares-link-worker')
    parser.add_argument('--players',type=int,choices=range(2,9),default=2)
    parser.add_argument('--mode',choices=('grand-prix','battle'),default='grand-prix')
    parser.add_argument('--course',type=int)
    parser.add_argument('--frames',type=int,help='Stop after this many frames for validation')
    parser.add_argument('--report',type=Path,help='Write a local validation report on successful completion')
    parser.add_argument('--characters',help='Comma-separated unique character names, one per player')
    parser.add_argument('--keyboard-player',type=int,default=1,help='1..N: keyboard player; 0: all use gamepads')
    args=parser.parse_args(argv)
    if not args.worker.is_file():
        fallback=Path('/workspace/build/ares-stock/tools/link-lab/ares-link-worker')
        if fallback.is_file(): args.worker=fallback
        else: parser.error('Build the worker or provide --worker')
    if args.frames is not None and args.frames<1: parser.error('--frames must be positive')
    if args.report and args.frames is None: parser.error('--report requires --frames')
    if not 0<=args.keyboard_player<=args.players: parser.error('--keyboard-player must be 0..N')
    if args.course is not None and not 0<=args.course<(4 if args.mode=='battle' else 20):
        parser.error('Course must be 0..3 for battle, or 0..19 for Grand Prix')
    names=args.characters.split(',') if args.characters else CHARACTERS[:args.players]
    if len(names)!=args.players or len(set(names))!=args.players or any(c not in CHARACTERS for c in names):
        parser.error('--characters must name one unique character per player')
    try: data=args.rom.read_bytes()
    except OSError as error: parser.error(str(error))
    if data[0xffc0:0xffd5]!=b'SUPER MARIO KART LINK': parser.error('Supply the linked ROM')
    roster=[CHARACTERS.index(c) for c in names]
    roster+=[c for c in range(8) if c not in roster]
    worker_path=str(args.worker.resolve())
    workers=[]; views=[]
    def terminate(signum,frame): raise KeyboardInterrupt
    previous=signal.signal(signal.SIGTERM,terminate)
    try:
        with tempfile.TemporaryDirectory(prefix='ares-local-') as temporary:
            for slot in range(args.players):
                directory=Path(temporary)/str(slot); directory.mkdir()
                rom=directory/'game.sfc'; rom.write_bytes(data)
                worker=subprocess.Popen([worker_path,'--window',str(slot),str(rom)],
                    stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
                workers.append(worker)
            def command(slot,line):
                process=workers[slot]
                process.stdin.write(line+'\n'); process.stdin.flush()
                return worker_line(process,15)
            columns=math.ceil(math.sqrt(args.players)); rows=math.ceil(args.players/columns)
            for slot,worker in enumerate(workers):
                read_worker(worker,30)
                for line in (f'@players {args.players}',f'@mode {args.mode}',
                             '@characters '+' '.join(map(str,roster)),
                             f'@course {([22,23,20,21][args.course] if args.mode=="battle" else args.course) if args.course is not None else 255}'):
                    if len(command(slot,line))!=64: raise LinkError("Cannot configure the local core")
                keyboard=slot+1==args.keyboard_player
                gamepad=-1 if keyboard else slot-int(args.keyboard_player>0 and slot+1>args.keyboard_player)
                for line in (f'@input {gamepad} {int(keyboard)}',f'@audio-output {int(slot==0)}',f'@external-view {slot}',
                             f'@tile {slot%columns} {slot//columns} {columns} {rows}'):
                    if command(slot,line)!='ok': raise LinkError('Cannot configure local window/input')
                views.append(AsyncView(worker_path,Path(temporary)/str(slot)/'game.sfc',slot,
                                       Path(temporary)/str(slot),15))
                print(f'Player {slot+1}: {names[slot]}, '+('keyboard' if keyboard else f'gamepad {gamepad+1}'),flush=True)
            if args.keyboard_player: command(args.keyboard_player-1,'@focus')
            interval=1/float(command(0,'@rate'))
            states=[command(i,'@state') for i in range(args.players)]
            frame=0; deadline=time.monotonic(); seen=[0]*args.players
            print(f'Local {args.players}-player {args.mode}; Player 1 owns menus. Close any window to stop.',flush=True)
            while True:
                if len(set(states))!=1: raise LinkError(f'Local state divergence before frame {frame}')
                delay=deadline-time.monotonic()
                if delay>0: time.sleep(delay)
                pads=[]
                for slot in range(args.players):
                    value=command(slot,'@poll')
                    if value=='quit': return 0
                    pads.append(int(value,16) if input_trace is None else input_trace(slot,frame))
                    seen[slot]|=pads[-1]
                    views[slot].pump(workers[slot],frame)
                bundle=' '.join(f'{pad:04x}' for pad in pads+[0]*(8-args.players))+'\n'
                # Submit all cores before waiting: emulation runs concurrently.
                for worker in workers:
                    worker.stdin.write(bundle); worker.stdin.flush()
                states=[read_worker(worker,15) for worker in workers]
                frame+=1
                if args.frames is not None and frame==args.frames:
                    if len(set(states))!=1: raise LinkError('Local final state divergence')
                    if args.report:
                        native=bytes.fromhex(command(0,'@peek 36 6'))
                        args.report.write_text(json.dumps(dict(players=args.players,frames=frame,states=states,pads=seen,
                            mode=int.from_bytes(native[:2],'little'),phase=int.from_bytes(native[4:6],'little'),
                            views=[view.presented for view in views]))+'\n')
                    return 0
                deadline=max(deadline+interval,time.monotonic()-interval)
    except KeyboardInterrupt:
        return 130
    except (OSError,ValueError,LinkError) as error:
        print(f'Local session stopped: {error}',file=__import__('sys').stderr)
        return 1
    finally:
        for view in views: view.close()
        for worker in workers:
            try: worker.stdin.close()
            except BrokenPipeError: pass
            try: worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                worker.kill(); worker.wait()
            worker.stdout.close()
        signal.signal(signal.SIGTERM,previous)


if __name__=='__main__': raise SystemExit(main())
