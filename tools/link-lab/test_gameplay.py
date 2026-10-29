"""Verify real ROM initialization and independent human control, not just packet delivery."""
import argparse
from pathlib import Path
import subprocess
import tempfile
import select


class Game:
    def __init__(self, worker, rom):
        self.process=subprocess.Popen([worker,rom],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
        self.initial=self.process.stdout.readline().strip()
        if len(self.initial)!=64: raise RuntimeError('Worker did not initialize')

    def command(self, text):
        self.process.stdin.write(text+'\n'); self.process.stdin.flush()
        if not select.select([self.process.stdout],[],[],60)[0]:
            self.process.kill()
            raise RuntimeError(f'Emulator did not answer {text[:100]} within 60 seconds')
        answer=self.process.stdout.readline().strip()
        if not answer: raise RuntimeError('Emulator exited during gameplay validation')
        return answer

    def step(self, pads):
        answer=self.command(' '.join(f'{pad:04x}' for pad in pads))
        if len(answer)!=64: raise RuntimeError(answer)
        return answer

    def peek(self,address,length):
        return bytes.fromhex(self.command(f'@peek {address:x} {length:x}'))

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=10)
        self.process.stdout.close()
        if self.process.returncode: raise RuntimeError('Emulator failed')


def word(data, offset):
    return int.from_bytes(data[offset:offset+2],'little')


def validate(worker, rom, checkpoint=None):
    game=Game(worker,rom)
    try:
        for frame in range(2200):
            button=0x1000 if frame==180 else (0x8000 if frame in range(300,2101,120) else 0)
            if button==0x8000 and word(game.peek(0x36,2),0)==2:
                button=0  # Stop menu confirms once the race has loaded.
            game.step([button]+[0]*7)
        globals=game.peek(0,0x180)
        assert word(globals,0x36)==2 and word(globals,0x3a)==6, 'Native menu trace did not enter a running race'
        initial=game.peek(0x1000,0x800)
        assert [word(initial,i*256+0x12) for i in range(8)]==list(range(0,16,2)), 'Roster was not applied'
        assert all(word(initial,i*256+0x10)&0x8000 for i in range(8)), 'A racer is still AI-controlled'
        assert all(word(initial,i*256+0xea)==0 for i in range(8)), 'Uncommanded acceleration at the starting grid'
        if checkpoint:
            assert game.command(f'@save {Path(checkpoint).resolve()}')=='ok'
        with tempfile.TemporaryDirectory(prefix='smk-gameplay-') as directory:
            snapshot=Path(directory)/'race.state'
            assert game.command(f'@save {snapshot}')=='ok'
            for slot in range(8):
                assert game.command(f'@load {snapshot}')=='ok'
                for _ in range(45):
                    game.step([0x8000 if i==slot else 0 for i in range(8)])
                racers=game.peek(0x1000,0x800)
                for i in range(8):
                    speed=word(racers,i*256+0xea)
                    held=word(racers,i*256+0xc4)&0x8000
                    if i==slot:
                        assert held and speed>0, f'Player {slot+1} did not accelerate'
                        assert racers[i*256+0x16:i*256+0x1e]!=initial[i*256+0x16:i*256+0x1e], 'Racer did not move'
                    else:
                        assert not held and speed==0, f'Input for player {slot+1} moved player {i+1}'
                print(f'PASS: player {slot+1} controls only its assigned racer',flush=True)
            for slot in range(8):
                assert game.command(f'@load {snapshot}')=='ok'
                # Arrange a ready star, then exercise the game's real A-button
                # inventory transition and physics effect, independently per player.
                assert game.command(f'@linkword {0x500+slot*2:x} c002')=='ok'
                for frame in range(12):
                    game.step([0x0080 if i==slot and frame<2 else 0 for i in range(8)])
                inventory=bytes.fromhex(game.command('@linkpeek 500 10'))
                racers=game.peek(0x1000,0x800)
                assert word(inventory,slot*2)==0, f'Player {slot+1} could not use an item'
                assert word(racers,slot*256+0xe2)&2, f'Player {slot+1} did not receive the star effect'
                assert all(not(word(racers,i*256+0xe2)&2) for i in range(8) if i!=slot), 'Item affected the wrong player'
                print(f'PASS: player {slot+1} activates its own inventory item',flush=True)
            for item in range(9):
                for slot in range(8):
                    assert game.command(f'@load {snapshot}')=='ok'
                    assert game.command(f'@linkword {0x500+slot*2:x} {0xc000+item:x}')=='ok'
                    assert game.command(f'@linkword {0x440+slot*2:x} 5')=='ok'
                    for frame in range(12):
                        game.step([0x0080 if i==slot and frame<2 else 0 for i in range(8)])
                    inventory=bytes.fromhex(game.command('@linkpeek 500 10'))
                    assert word(inventory,slot*2)!=0xc000+item, f'Item {item} was not consumed for player {slot+1}'
                    if item==7:
                        coins=bytes.fromhex(game.command('@linkpeek 440 10'))
                        assert word(coins,slot*2)==7, f'Coin item credited the wrong player {slot+1}'
                print(f'PASS: item type {item} activates for every player',flush=True)
            assert game.command(f'@load {snapshot}')=='ok'
            tick=word(game.peek(0x38,2),0)
            for slot in range(8):
                assert game.command(f'@word {0x1082+slot*256:x} 100')=='ok'
            for _ in range(60): game.step([0]*8)
            racers=game.peek(0x1000,0x800)
            elapsed=(word(game.peek(0x38,2),0)-tick)&0xffff
            assert elapsed>0
            assert all(abs(word(racers,i*256+0x82)-(256-elapsed))<=1 for i in range(8)), 'Human status timers did not tick once per player'
            print('PASS: human status timers advance exactly once for all eight racers',flush=True)
            for owner in range(8):
                for victim in range(8):
                    if owner==victim: continue
                    assert game.command(f'@load {snapshot}')=='ok'
                    assert game.command(f'@linkword {0x500+owner*2:x} c006')=='ok'
                    assert game.command(f'@linkword {0x500+victim*2:x} c002')=='ok'
                    # A real ready item retains its roulette script pointer.
                    assert game.command(f'@linkword {0x520+victim*2:x} b4dc')=='ok'
                    for frame in range(12):
                        game.step([0x0080 if i==owner and frame<2 else 0 for i in range(8)])
                    inventory=bytes.fromhex(game.command('@linkpeek 500 10'))
                    assert word(inventory,owner*2)&0x800f==0x8002, f'Player {owner+1} could not steal from {victim+1}'
                    assert word(inventory,victim*2)==0x9000, 'Boo did not remove its victim inventory'
                    assert all(word(inventory,i*2)==0 for i in range(8) if i not in (owner,victim))
            print('PASS: Boo can steal across all 56 distinct player pairs',flush=True)
            for owner in (0,7):
                assert game.command(f'@load {snapshot}')=='ok'
                assert game.command(f'@linkword {0x500+owner*2:x} c008')=='ok'
                for frame in range(12):
                    game.step([0x0080 if i==owner and frame<2 else 0 for i in range(8)])
                racers=game.peek(0x1000,0x800)
                assert word(racers,owner*256+0x84)==0, 'Lightning shrank its owner'
                assert all(word(racers,i*256+0x84)>0 for i in range(8) if i!=owner), 'Lightning missed a human opponent'
            print('PASS: lightning affects all seven opponents and excludes its owner',flush=True)
            for kind,x,y in [('item box',52,260),('coin',364,116)]:
                for slot in range(8):
                    assert game.command(f'@load {snapshot}')=='ok'
                    for offset,value in [(0x16,0),(0x18,x),(0x1a,0),(0x1c,y)]:
                        assert game.command(f'@word {0x1000+slot*256+offset:x} {value:x}')=='ok'
                    assert game.command(f'@linkword {0x440+slot*2:x} 5')=='ok'
                    for _ in range(12): game.step([0]*8)
                    if kind=='item box':
                        values=bytes.fromhex(game.command('@linkpeek 500 10'))
                        assert word(values,slot*2)&0x8000, f'Player {slot+1} could not collect an item box'
                        assert all(word(values,i*2)==0 for i in range(8) if i!=slot), 'Pickup credited another player'
                    else:
                        values=bytes.fromhex(game.command('@linkpeek 440 10'))
                        assert word(values,slot*2)==6, f'Player {slot+1} could not collect a coin'
                print(f'PASS: every player collects a real {kind} outside the host camera',flush=True)
            # Repeat the same replay after restoration and require the same canonical digest.
            digests=[]
            for _ in range(2):
                assert game.command(f'@load {snapshot}')=='ok'
                for frame in range(120):
                    digest=game.step([0x8000 | (0x100 if (frame//30+i)%2 else 0x200) for i in range(8)])
                digests.append(digest)
            assert digests[0]==digests[1], 'Snapshot replay is not deterministic'
            print('PASS: deterministic eight-human replay after snapshot restore',flush=True)
    finally:
        game.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',required=True)
    parser.add_argument('--rom',required=True)
    parser.add_argument('--checkpoint')
    args=parser.parse_args()
    validate(args.worker,args.rom,args.checkpoint)
