#!/usr/bin/env python3
"""Host or join a two- through eight-player Super Mario Kart Link session."""
import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys

from session import profile

CHARACTERS=['mario','luigi','bowser','peach','donkey-kong-jr','koopa','toad','yoshi']


def stop(process):
    if process is not None and process.poll() is None:
        os.killpg(process.pid,signal.SIGTERM)
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL)
            process.wait()


def main():
    if len(sys.argv)>1 and sys.argv[1]=="local":
        from local import main as local_main
        return local_main(sys.argv[2:])
    parser=argparse.ArgumentParser(description=__doc__,epilog="For same-machine play: play.py local --help")
    sub=parser.add_subparsers(dest='command',required=True)
    for command in ('host','join'):
        p=sub.add_parser(command)
        p.add_argument('--rom',required=True,type=Path,help='ROM produced by build_linked.py')
        p.add_argument('--worker',type=Path,default=(Path(__file__).with_name('bin')/'ares-link-worker' if (Path(__file__).with_name('bin')/'ares-link-worker').is_file() else Path('/workspace/build/ares-stock/tools/link-lab/ares-link-worker')))
        p.add_argument('--character',required=True,choices=CHARACTERS)
        p.add_argument('--gamepad',type=int,choices=range(-1,8),help='SDL gamepad index; -1 disables gamepads')
        p.add_argument('--no-keyboard',action='store_true')
        p.add_argument('--port',type=int,default=27888)
        if command=='host':
            p.add_argument('--mode',choices=('grand-prix','battle'),default='grand-prix')
            p.add_argument('--players',type=int,choices=range(2,9),default=8)
            p.add_argument('--listen',default='127.0.0.1',help='Use a LAN interface address to accept remote consoles')
            p.add_argument('--course',type=int,choices=range(20),help='Optional course ID; omit to choose the cup in the game')
        else:
            p.add_argument('--host',required=True)
            p.add_argument('--player',type=int,required=True,choices=range(2,9))
    args=parser.parse_args()
    if args.command=='host' and args.course is not None and args.mode=='battle' and args.course>3:
        parser.error('Battle course must be 0..3 (arenas 1..4)')
    if not (0<=args.port<=65535) or (args.command=='join' and not args.port):
        parser.error('Port must be 1–65535 (host may use 0 to choose a free port)')
    try:
        data=args.rom.read_bytes()
    except OSError as error:
        parser.error(str(error))
    if data[0xffc0:0xffd5]!=b'SUPER MARIO KART LINK':
        parser.error('Build the linked ROM with the companion build_linked.py first')
    if not args.worker.is_file(): parser.error('Build the ares-link-worker CMake target first')
    args.rom=args.rom.resolve(); args.worker=args.worker.resolve()
    session=str(Path(__file__).with_name('session.py'))
    server=client=None
    child_environment=os.environ.copy()
    def terminate(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,terminate)
    try:
        if args.command=='host':
            child_environment['ARES_LINK_HOST_KEY']=secrets.token_urlsafe(32)
            server=subprocess.Popen([sys.executable,session,'host','--host',args.listen,'--port',str(args.port),
                                     '--players',str(args.players),'--timeout','300','--frame-timeout','15',
                                     '--profile',profile(args.rom,args.worker)],
                                    env=child_environment,stdout=subprocess.PIPE,text=True,start_new_session=True)
            ready=server.stdout.readline()
            if not ready: raise RuntimeError('Cannot start the session coordinator')
            port=json.loads(ready)['ready']
            host='127.0.0.1' if args.listen=='0.0.0.0' else args.listen
            slot=0
            print(f'Hosting {args.players} players on {args.listen}:{port}. Player 1 owns the game menus.',flush=True)
        else:
            child_environment.pop('ARES_LINK_HOST_KEY',None)
            host,port,slot=args.host,args.port,args.player-1
        command=[sys.executable,session,'join','--host',host,'--port',str(port),'--slot',str(slot),
                 '--character',str(CHARACTERS.index(args.character)),'--rom',str(args.rom),'--worker',str(args.worker),
                 '--interactive','--timeout','300','--frame-timeout','15']
        if args.gamepad is not None: command+=['--gamepad',str(args.gamepad)]
        if args.no_keyboard: command+=['--no-keyboard']
        if args.command=='host':
            command+=['--mode',args.mode]
            if args.course is not None: command+=['--course',str(args.course)]
        print('Controls: arrows steer; Z accelerates; X uses items; A/S are Y/X; Q/W are L/R; Enter pauses; Esc disconnects.',flush=True)
        client=subprocess.Popen(command,env=child_environment,start_new_session=True)
        return client.wait()
    except (OSError, ValueError, RuntimeError) as error:
        print(f'Link stopped: {error}',file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        stop(client); stop(server)
        if server and server.stdout: server.stdout.close()


if __name__=='__main__':
    sys.exit(main())
