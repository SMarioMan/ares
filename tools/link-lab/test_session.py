import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import unittest

import session


class ProtocolTests(unittest.TestCase):
    def hello(self, slot=0, character=0):
        return dict(protocol=session.PROTOCOL, profile='a'*64, slot=slot, character=character,
                    settings=dict(mode='stock-validation', course=0, frames=3) if slot == 0 else None)

    def test_duplicate_character(self):
        with self.assertRaisesRegex(session.LinkError, 'character'):
            session.validate_hello(self.hello(1, 0), {0: self.hello()}, 8)

    def test_guest_settings(self):
        message = self.hello(1, 1)
        message['settings'] = self.hello()['settings']
        with self.assertRaisesRegex(session.LinkError, 'only player 1'):
            session.validate_hello(message, {}, 8)

    def test_rom_or_emulator_mismatch(self):
        message = self.hello(1, 1)
        message['profile'] = 'b'*64
        with self.assertRaisesRegex(session.LinkError, 'mismatch'):
            session.validate_hello(message, {0: self.hello()}, 8)

    def test_invalid_slot_and_types(self):
        for slot in (-1, 8, True, '0'):
            with self.subTest(slot=slot), self.assertRaises(session.LinkError):
                session.validate_hello(self.hello(slot, 1), {}, 8)

    def test_guest_can_join_before_host(self):
        guest = self.hello(7, 4)
        session.validate_hello(guest, {}, 8)
        session.validate_hello(self.hello(), {7: guest}, 8)

    def test_battle_settings(self):
        for players in range(2,9):
            host=self.hello()
            host['settings'].update(mode='linked-battle',course=3)
            session.validate_hello(host,{},players)
            host['settings']['course']=4
            with self.assertRaises(session.LinkError): session.validate_hello(host,{},players)

    def test_lobby_rejects_bad_joins_without_losing_host(self):
        server, port = start_host(2, timeout=5, owner=True)
        connections, streams = [], []
        try:
            def connect(message):
                connection=socket.create_connection(('127.0.0.1',port),timeout=5)
                connections.append(connection)
                stream=connection.makefile('rwb'); streams.append(stream)
                session.send(stream,message)
                return stream
            with self.assertRaisesRegex(session.LinkError,'session owner'):
                session.receive(connect(self.hello()))
            host=self.hello(); host['host_key']='test-only-owner-key'
            first=connect(host)
            for rejected in (self.hello(1,0),dict(self.hello(1,1),settings=host['settings']),
                             dict(self.hello(1,1),profile='b'*64)):
                with self.assertRaises(session.LinkError): session.receive(connect(rejected))
            guest=connect(self.hello(1,1))
            for stream in (first,guest): self.assertIn('start',session.receive(stream))
            for frame in range(4):
                for stream in (first,guest): session.send(stream,dict(frame=frame,pad=0,state='a'*64))
                for stream in (first,guest):
                    self.assertIn('done' if frame==3 else 'pads',session.receive(stream))
            server.communicate(timeout=5)
            self.assertEqual(server.returncode,0)
        finally:
            for stream in streams: stream.close()
            for connection in connections: connection.close()
            stop(server)

    def test_network_faults_stop_all_peers(self):
        for fault in ('desync', 'frame', 'disconnect', 'input', 'timeout', 'oversized'):
            with self.subTest(fault=fault):
                server, port = start_host(2, timeout=1)
                connections, streams = [], []
                try:
                    for slot in range(2):
                        connection = socket.create_connection(('127.0.0.1', port), timeout=5)
                        connections.append(connection)
                        streams.append(connection.makefile('rwb'))
                        session.send(streams[-1], self.hello(slot, slot))
                    for stream in streams:
                        self.assertIn('start', session.receive(stream))
                    session.send(streams[0], dict(frame=0, pad=0, state='a'*64))
                    if fault == 'disconnect':
                        streams[1].close()
                        connections[1].close()
                    elif fault == 'timeout':
                        pass  # The missing peer must never release another bundle.
                    elif fault == 'oversized':
                        streams[1].write(b'x'*(session.LIMIT+1) + b'\n')
                        streams[1].flush()
                    else:
                        session.send(streams[1], dict(frame=1 if fault == 'frame' else 0,
                                     pad=1 if fault == 'input' else 0,
                                     state=('b' if fault == 'desync' else 'a')*64))
                    with self.assertRaises(session.LinkError):
                        session.receive(streams[0])
                    server.communicate(timeout=5)
                    self.assertEqual(server.returncode, 1)
                finally:
                    for stream in streams:
                        stream.close()
                    for connection in connections:
                        connection.close()
                    stop(server)


def start_host(players, timeout=30, owner=False):
    environment=os.environ.copy()
    environment.pop('ARES_LINK_HOST_KEY',None)
    if owner: environment['ARES_LINK_HOST_KEY']='test-only-owner-key'
    server = subprocess.Popen([sys.executable, str(Path(__file__).with_name('session.py')),
                               'host', '--port', '0', '--players', str(players), '--timeout', str(timeout)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              env=environment, start_new_session=True)
    line = server.stdout.readline()
    if not line:
        raise RuntimeError(server.communicate(timeout=5))
    return server, json.loads(line)['ready']


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    for stream in (process.stdout, process.stderr):
        if stream:
            stream.close()


def integration(worker, rom, frames, players=8, asynchronous=False, mode='grand-prix'):
    server, port = start_host(players, timeout=60)
    clients = []
    try:
        for slot in range(players):
            command = [sys.executable, str(Path(__file__).with_name('session.py')), 'join',
                       '--port', str(port), '--slot', str(slot), '--character', str(slot),
                       '--rom', rom, '--worker', worker, '--timeout', '60']
            if slot == 0:
                command += ['--frames', str(frames), '--mode', mode]
            if asynchronous: command+=['--async-view']
            clients.append(subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                            text=True, start_new_session=True))
        outcomes = []
        for client in clients:
            out, err = client.communicate(timeout=max(120, frames))
            if client.returncode:
                raise RuntimeError(f'Client failed: {out}\n{err}')
            outcomes.append(json.loads(out))
        out, err = server.communicate(timeout=10)
        if server.returncode:
            raise RuntimeError(f'Coordinator failed: {out}\n{err}')
        assert all(outcome['passed'] == frames for outcome in outcomes)
        assert len({outcome['state'] for outcome in outcomes}) == 1
        if asynchronous and frames>2300:
            assert all(outcome.get('views',0)>0 for outcome in outcomes), 'A local renderer never presented a race frame'
        print(out.strip())
        print(f'PASS: {players} independent SNES workers agreed at all {frames+1} state barriers')
        return outcomes[0]['state']
    finally:
        for client in clients:
            stop(client)
        stop(server)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker')
    parser.add_argument('--rom')
    parser.add_argument('--frames', type=int, default=600)
    parser.add_argument('--players',type=int,choices=range(2,9),default=8)
    parser.add_argument('--async-view',action='store_true')
    parser.add_argument('--mode',choices=('grand-prix','battle'),default='grand-prix')
    args = parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ProtocolTests))
    if not result.wasSuccessful():
        sys.exit(1)
    if args.worker and args.rom:
        integration(args.worker, args.rom, args.frames,args.players,args.async_view,args.mode)
