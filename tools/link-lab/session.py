#!/usr/bin/env python3
"""Frame barriers and session authority for deterministic linked SNES instances."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import select
import signal
import socket
import subprocess
import sys
import time

PROTOCOL = 'ares-link-lab/2'
LIMIT = 4096


class LinkError(Exception):
    pass


def send(stream, message):
    data = json.dumps(message, sort_keys=True, separators=(',', ':')).encode() + b'\n'
    if len(data) > LIMIT:
        raise LinkError('oversized packet')
    stream.write(data)
    stream.flush()


def receive(stream):
    line = stream.readline(LIMIT + 1)
    if not line or len(line) > LIMIT or not line.endswith(b'\n'):
        raise LinkError('disconnected or oversized packet')
    try:
        message = json.loads(line)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise LinkError('invalid JSON packet') from error
    if not isinstance(message, dict):
        raise LinkError('packet must be an object')
    if 'error' in message:
        raise LinkError(message['error'])
    return message


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def validate_hello(message, peers, count):
    fields={'protocol', 'profile', 'slot', 'character', 'settings'}
    if set(message) not in (fields,fields|{'host_key'}):
        raise LinkError('invalid hello fields')
    if message['protocol'] != PROTOCOL:
        raise LinkError('protocol mismatch')
    slot, character = message['slot'], message['character']
    if not integer(slot, 0, count-1) or slot in peers:
        raise LinkError('invalid or occupied player slot')
    if not integer(character, 0, 7) or any(p['character'] == character for p in peers.values()):
        raise LinkError('character already selected or invalid')
    profile = message['profile']
    if not isinstance(profile, str) or len(profile) != 64 or any(c not in '0123456789abcdef' for c in profile):
        raise LinkError('invalid profile digest')
    if any(p['profile'] != profile for p in peers.values()):
        raise LinkError('ROM, emulator, or deterministic settings mismatch')
    settings = message['settings']
    if slot != 0:
        if settings is not None:
            raise LinkError('only player 1 may select session settings')
    elif (not isinstance(settings, dict) or set(settings) != {'mode', 'course', 'frames'}
          or settings['mode'] not in ('stock-validation','linked-grand-prix','linked-battle')
          or (settings['course'] is not None and not integer(settings['course'], 0, 3 if settings['mode']=='linked-battle' else 19))
          or not integer(settings['frames'], 1, 10000000)):
        raise LinkError('invalid host settings')


def serve(host, port, count=8, timeout=30, expected_profile=None, host_key=None, frame_timeout=None):
    peers = {}
    sockets = []
    streams = {}
    peer_sockets = {}
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen(count)
        listener.settimeout(min(timeout, 1))
        print(json.dumps({'ready': listener.getsockname()[1]}), flush=True)
        try:
            lobby_deadline = time.monotonic() + timeout
            while len(peers) < count:
                for slot, connection in list(peer_sockets.items()):
                    if select.select([connection], [], [], 0)[0]:
                        try:
                            closed = not connection.recv(1, socket.MSG_PEEK)
                        except OSError:
                            closed = True
                        if closed:
                            streams.pop(slot).close()
                            connection.close()
                            sockets.remove(connection)
                            del peers[slot], peer_sockets[slot]
                if time.monotonic() >= lobby_deadline:
                    raise LinkError('Lobby timed out waiting for players')
                try:
                    connection, _ = listener.accept()
                except socket.timeout:
                    continue
                connection.settimeout(min(timeout, 10))
                connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                stream = connection.makefile('rwb')
                try:
                    message = receive(stream)
                    if expected_profile and message.get('profile')!=expected_profile:
                        raise LinkError('ROM, emulator, or deterministic settings mismatch')
                    if host_key and message.get('slot')==0 and message.get('host_key')!=host_key:
                        raise LinkError('Only the session owner may join as player 1')
                    validate_hello(message, peers, count)
                except (LinkError, OSError) as error:
                    try:
                        send(stream, {'error': str(error)})
                    except OSError:
                        pass
                    stream.close()
                    connection.close()
                    continue
                peers[message['slot']] = message
                streams[message['slot']] = stream
                peer_sockets[message['slot']] = connection
                sockets.append(connection)
                lobby_deadline = time.monotonic() + timeout
            settings = peers[0]['settings']
            for connection in sockets:
                if connection.fileno()!=-1: connection.settimeout(frame_timeout or timeout)
            roster = [peers[i]['character'] for i in range(count)]
            for stream in streams.values():
                send(stream, {'start': settings, 'characters': roster})
            # A bundle is issued only after every peer reports the same prior state.
            for frame in range(settings['frames'] + 1):
                pads, hashes = [], []
                for slot in range(count):
                    packet = receive(streams[slot])
                    if set(packet) != {'frame', 'pad', 'state'} or not integer(packet['frame'], frame, frame):
                        raise LinkError(f'out-of-order frame from player {slot+1}')
                    if not integer(packet['pad'], 0, 0xfff0) or packet['pad'] & 15:
                        raise LinkError('invalid SNES input bits')
                    digest = packet['state']
                    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                        raise LinkError('invalid state digest')
                    pads.append(packet['pad'])
                    hashes.append(digest)
                if len(set(hashes)) != 1:
                    raise LinkError(f'desynchronization before frame {frame}')
                if frame == settings['frames']:
                    for stream in streams.values():
                        send(stream, {'done': frame, 'state': hashes[0]})
                    print(json.dumps({'passed': frame, 'peers': count, 'state': hashes[0]}), flush=True)
                    return
                pads += [0] * (8-count)
                for stream in streams.values():
                    send(stream, {'frame': frame, 'pads': pads})
        except (LinkError, OSError) as error:
            for stream in streams.values():
                try:
                    send(stream, {'error': str(error)})
                except OSError:
                    pass
            raise LinkError(str(error)) from error
        finally:
            for stream in streams.values():
                stream.close()
            for connection in sockets:
                connection.close()


def profile(rom, worker):
    h = hashlib.sha256()
    for value in (PROTOCOL.encode(), Path(rom).read_bytes(), Path(worker).read_bytes(),
                  b'SFC/NTSC;deterministic-entropy=1;pixel-accuracy=0;clean-save;link-mmio=3;battle-object-ram=1;atomic-world-inputs=1'):
        h.update(len(value).to_bytes(8, 'big'))
        h.update(value)
    return h.hexdigest()


def trace(slot, frame):
    # Reproducible controller traffic, with P1 navigating title/menu screens.
    if slot == 0 and frame == 180:
        return 0x1000  # Start
    if slot == 0 and frame in range(300,2101,120):
        return 0x8000  # Confirm class, character, and cup through the native menus.
    if frame >= 2300:
        return 0x8000 | (0x0100 if (frame//60 + slot) % 2 else 0x0200)
    return 0


def worker_line(worker, timeout):
    with selectors.DefaultSelector() as selector:
        selector.register(worker.stdout, selectors.EVENT_READ)
        if not selector.select(timeout=timeout):
            raise LinkError('emulator worker timed out')
    line = worker.stdout.readline(LIMIT + 1)
    if not line or len(line) > LIMIT or not line.endswith('\n'):
        raise LinkError('emulator worker failed')
    return line.strip()


def read_worker(worker, timeout):
    state = worker_line(worker, timeout)
    if len(state) != 64 or any(c not in '0123456789abcdef' for c in state):
        raise LinkError('emulator worker failed')
    return state


class AsyncView:
    """Render frozen canonical snapshots without blocking the input barrier."""
    def __init__(self, executable, rom, slot, directory, timeout):
        self.timeout=timeout
        self.snapshot=Path(directory)/'presentation.state'
        self.picture=Path(directory)/'presentation.ppm'
        self.future=None
        self.queried=-1
        self.presented=0
        self.last_presented_frame=-1
        self.pool=ThreadPoolExecutor(max_workers=1)
        self.worker=None
        try:
            self.worker=subprocess.Popen([executable,str(rom)],stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,text=True,bufsize=1)
            if hasattr(os,'setpriority'):
                try:
                    priority=os.getpriority(os.PRIO_PROCESS,self.worker.pid)
                    os.setpriority(os.PRIO_PROCESS,self.worker.pid,min(19,priority+5))
                except OSError:
                    pass  # Priority is an optimization, never a startup prerequisite.
            read_worker(self.worker,timeout)
            self.command(f'@view {slot}')
        except BaseException:
            self.close()
            raise

    def command(self, text):
        self.worker.stdin.write(text+'\n'); self.worker.stdin.flush()
        if worker_line(self.worker,self.timeout)!='ok':
            raise LinkError('local presentation worker failed')

    def render(self, frame, epoch):
        self.command(f'@load {self.snapshot}')
        self.command('@draw')
        self.command(f'@image {self.picture}')
        return frame,epoch

    def pump(self, canonical, frame):
        if self.future is not None:
            if not self.future.done(): return
            source,epoch=self.future.result()
            canonical.stdin.write(f'@import-image {source} {epoch} {self.picture}\n'); canonical.stdin.flush()
            answer=worker_line(canonical,self.timeout)
            if answer not in ('ok','skip'): raise LinkError('Cannot present the local image')
            self.presented+=answer=='ok'
            if answer=='ok': self.last_presented_frame=source
            self.future=None
        if self.queried==frame: return
        canonical.stdin.write(f'@export {self.snapshot}\n'); canonical.stdin.flush()
        answer=worker_line(canonical,self.timeout)
        self.queried=frame
        if answer=='skip': return
        try:
            source,epoch=map(int,answer.split())
        except ValueError as error:
            raise LinkError('Invalid canonical presentation snapshot') from error
        if source!=frame or epoch<0: raise LinkError('Invalid presentation generation')
        self.future=self.pool.submit(self.render,source,epoch)

    def close(self):
        if self.worker is not None:
            if self.worker.poll() is None:
                self.worker.terminate()
            try: self.worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.worker.kill(); self.worker.wait()
        self.pool.shutdown(wait=True,cancel_futures=True)
        if self.worker is not None:
            try: self.worker.stdin.close()
            except BrokenPipeError: pass
            self.worker.stdout.close()


def client(args):
    if args.slot != 0 and (args.course is not None or args.frames is not None or args.mode is not None):
        raise LinkError('only player 1 may select session settings')
    linked=Path(args.rom).read_bytes()[0xffc0:0xffd5]==b'SUPER MARIO KART LINK'
    if args.mode=='battle' and not linked: raise LinkError('Battle requires the linked ROM')
    settings = {'mode': ('linked-battle' if args.mode=='battle' else 'linked-grand-prix') if linked else 'stock-validation', 'course': args.course,
                'frames': args.frames if args.frames is not None else (10000000 if args.interactive else 600)} if args.slot == 0 else None
    # Each worker gets a clean ROM directory, so existing SRAM cannot contaminate a session.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='ares-link-') as directory:
        rom = Path(directory) / 'game.sfc'
        rom.write_bytes(Path(args.rom).read_bytes())
        with socket.create_connection((args.host, args.port), timeout=args.timeout) as connection:
            connection.settimeout(args.timeout)
            connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            with connection.makefile('rwb') as stream:
                hello={'protocol': PROTOCOL, 'profile': profile(args.rom, args.worker),
                       'slot': args.slot, 'character': args.character, 'settings': settings}
                if args.slot==0 and os.environ.get('ARES_LINK_HOST_KEY'):
                    hello['host_key']=os.environ['ARES_LINK_HOST_KEY']
                send(stream,hello)
                print(f'Player {args.slot+1}: waiting for the lobby to fill.',file=sys.stderr,flush=True)
                start = receive(stream)
                connection.settimeout(args.frame_timeout or args.timeout)
                if set(start) != {'start', 'characters'}:
                    raise LinkError('invalid session start')
                worker_command=[args.worker]
                if args.interactive:
                    worker_command += ['--window', str(args.slot)]
                worker = subprocess.Popen([*worker_command, str(rom)], stdin=subprocess.PIPE,
                                          stdout=subprocess.PIPE, text=True, bufsize=1)
                view=None
                try:
                    operation_timeout = args.frame_timeout or args.timeout
                    state = read_worker(worker, operation_timeout)
                    roster=start['characters']
                    if (not isinstance(roster,list) or not 2<=len(roster)<=8
                            or any(not integer(c,0,7) for c in roster)
                            or len(set(roster))!=len(roster) or args.slot>=len(roster)
                            or roster[args.slot]!=args.character):
                        raise LinkError('Invalid character roster')
                    validate_hello(dict(protocol=PROTOCOL,profile=hello['profile'],slot=0,
                                        character=roster[0],settings=start['start']),{},len(roster))
                    if args.slot==0 and start['start']!=settings:
                        raise LinkError('Coordinator changed the host settings')
                    worker.stdin.write(f'@players {len(roster)}\n'); worker.stdin.flush()
                    state=read_worker(worker,operation_timeout)
                    worker.stdin.write('@mode '+('battle' if start['start']['mode']=='linked-battle' else 'grand-prix')+'\n'); worker.stdin.flush()
                    state=read_worker(worker,operation_timeout)
                    roster += [c for c in range(8) if c not in roster]
                    worker.stdin.write('@characters '+' '.join(str(c) for c in roster)+'\n')
                    worker.stdin.flush()
                    state=read_worker(worker,operation_timeout)
                    course=start['start']['course']
                    if course is not None and start['start']['mode']=='linked-battle': course=[22,23,20,21][course]
                    worker.stdin.write(f'@course {255 if course is None else course}\n'); worker.stdin.flush()
                    state=read_worker(worker,operation_timeout)
                    if args.interactive and (args.gamepad is not None or args.no_keyboard):
                        index=args.gamepad if args.gamepad is not None else 0
                        worker.stdin.write(f'@input {index} {int(not args.no_keyboard)}\n'); worker.stdin.flush()
                        if worker_line(worker,operation_timeout)!='ok': raise LinkError('Cannot assign the local controller')
                    asynchronous=args.interactive or args.async_view
                    worker.stdin.write(f'@{"external-view" if asynchronous else "view"} {args.slot}\n'); worker.stdin.flush()
                    if worker_line(worker,operation_timeout)!='ok':
                        raise LinkError('Cannot configure local presentation')
                    worker.stdin.write('@rate\n'); worker.stdin.flush()
                    rate=float(worker_line(worker,operation_timeout))
                    if not math.isfinite(rate) or not 30<=rate<=120:
                        raise LinkError('Invalid emulated refresh rate')
                    interval=1/rate
                    if asynchronous:
                        view=AsyncView(args.worker,rom,args.slot,directory,operation_timeout)
                    frame = 0
                    next_frame=time.monotonic()
                    while True:
                        pad=trace(args.slot,frame)
                        if args.interactive:
                            remaining=next_frame-time.monotonic()
                            if remaining>0: time.sleep(remaining)
                            worker.stdin.write('@poll\n'); worker.stdin.flush()
                            answer=worker_line(worker,operation_timeout)
                            if answer=='quit': raise LinkError('Player closed the game')
                            pad=int(answer,16)
                            next_frame=max(next_frame+interval,time.monotonic()-interval)
                        if view: view.pump(worker,frame)
                        send(stream, {'frame': frame, 'pad': pad, 'state': state})
                        if args.interactive:
                            # Keep the SDL event queue responsive while another
                            # console stalls the input barrier; no frame advances.
                            barrier_deadline=time.monotonic()+operation_timeout
                            while not select.select([connection], [], [], 0.05)[0]:
                                if time.monotonic()>=barrier_deadline:
                                    raise LinkError('input barrier timed out')
                                worker.stdin.write('@poll\n'); worker.stdin.flush()
                                if worker_line(worker,operation_timeout)=='quit':
                                    raise LinkError('Player closed the game')
                                if view: view.pump(worker,frame)
                        bundle = receive(stream)
                        if 'done' in bundle:
                            if bundle != {'done': frame, 'state': state}:
                                raise LinkError('invalid completion barrier')
                            result={'slot':args.slot,'passed':frame,'state':state}
                            if view: result['views']=view.presented
                            print(json.dumps(result),flush=True)
                            break
                        if (set(bundle) != {'frame', 'pads'} or bundle['frame'] != frame
                                or not isinstance(bundle['pads'], list) or len(bundle['pads']) != 8
                                or any(not integer(p, 0, 0xfff0) or p & 15 for p in bundle['pads'])):
                            raise LinkError('invalid input bundle')
                        if bundle['pads'][args.slot]!=pad:
                            raise LinkError('Coordinator changed the local player input')
                        worker.stdin.write(' '.join(f'{pad:04x}' for pad in bundle['pads']) + '\n')
                        worker.stdin.flush()
                        state = read_worker(worker, operation_timeout)
                        frame += 1
                finally:
                    if view: view.close()
                    try:
                        worker.stdin.close()
                    except BrokenPipeError:
                        pass
                    try:
                        worker.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        worker.kill()
                        worker.wait()
                    worker.stdout.close()
                if worker.returncode:
                    raise LinkError(f'emulator worker exited {worker.returncode}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    server = sub.add_parser('host')
    server.add_argument('--host', default='127.0.0.1')
    server.add_argument('--port', type=int, default=27888)
    server.add_argument('--players', type=int, choices=range(2, 9), default=8)
    server.add_argument('--timeout', type=float, default=30)
    server.add_argument('--frame-timeout',type=float)
    server.add_argument('--profile')
    peer = sub.add_parser('join')
    peer.add_argument('--host', default='127.0.0.1')
    peer.add_argument('--port', type=int, default=27888)
    peer.add_argument('--timeout', type=float, default=30)
    peer.add_argument('--frame-timeout',type=float)
    peer.add_argument('--slot', type=int, choices=range(8), required=True, help='zero-based; 0 is player 1')
    peer.add_argument('--character', type=int, choices=range(8), required=True)
    peer.add_argument('--course', type=int, choices=range(20))
    peer.add_argument('--mode',choices=('grand-prix','battle'))
    peer.add_argument('--frames', type=int)
    peer.add_argument('--rom', required=True)
    peer.add_argument('--worker', required=True)
    peer.add_argument('--gamepad',type=int,choices=range(-1,8),help='SDL gamepad index; -1 disables gamepads')
    peer.add_argument('--no-keyboard',action='store_true')
    peer.add_argument('--interactive', action='store_true', help='play in an SDL3 window with keyboard or gamepad')
    peer.add_argument('--async-view',action='store_true',help='exercise the asynchronous renderer without a window')
    args = parser.parse_args()
    if args.timeout<=0 or (args.frame_timeout is not None and args.frame_timeout<=0):
        parser.error('Timeouts must be positive')
    def terminate(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,terminate)
    try:
        if args.command == 'host':
            serve(args.host, args.port, args.players, args.timeout,args.profile,os.environ.get('ARES_LINK_HOST_KEY'),args.frame_timeout)
        else:
            client(args)
    except (LinkError, OSError, ValueError) as error:
        print(f'Link stopped: {error}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Link stopped: interrupted',file=sys.stderr)
        return 130
    return 0


if __name__ == '__main__':
    sys.exit(main())
