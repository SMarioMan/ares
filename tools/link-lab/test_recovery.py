"""Exercise simultaneous native Lakitu recovery for eight off-track racers."""
import argparse
from pathlib import Path

from test_gameplay import Game, word


def validate(worker,rom,checkpoint):
    game=Game(worker,rom)
    try:
        assert game.command(f'@load {Path(checkpoint).resolve()}')=='ok'
        initial_coins=bytes.fromhex(game.command('@linkpeek 440 10'))
        started=word(game.peek(0x38,2),0)
        # Move all eight beyond the track bounds. Terrain detection and native
        # recovery scripts, not a direct state-machine write, must rescue them.
        for slot in range(8):
            for offset in (0x18,0x1c):
                assert game.command(f'@word {0x1000+slot*256+offset:x} 44c')=='ok'
        seen=[False]*8
        # A game tick can span multiple video frames while eight rescues run.
        # Bound actual game progression as well as wall/video-frame work.
        for frame in range(2400):
            game.step([0]*8)
            assert (word(game.peek(0x38,2),0)-started)&0xffff<900, 'Native rescue exceeded 900 game ticks'
            racers=game.peek(0x1000,0x800)
            for slot in range(8):
                seen[slot] |= word(racers,slot*256+0xa0)!=0
            if all(seen) and all(word(racers,i*256+0xa0)==0 for i in range(8)):
                break
        else:
            raise AssertionError('At least one racer remained stranded outside the course')
        # The last A0 transition can precede its control/flag cleanup within
        # the same world update. Let that native update complete before checking.
        for _ in range(12): game.step([0]*8)
        racers=game.peek(0x1000,0x800)
        assert all(word(racers,i*256+0x18)<1024 and word(racers,i*256+0x1c)<1024 for i in range(8))
        assert all(not(word(racers,i*256+0x10)&0x0800) for i in range(8)), 'Recovery inhibit did not clear'
        coins=bytes.fromhex(game.command('@linkpeek 440 10'))
        assert [word(coins,i*2) for i in range(8)]==[max(0,word(initial_coins,i*2)-2) for i in range(8)], 'Recovery penalty was not applied per player'
        for _ in range(60): game.step([0x8000]*8)
        racers=game.peek(0x1000,0x800)
        assert all(word(racers,i*256+0xea)>0 for i in range(8)), 'A rescued player could not accelerate'
        print(f'PASS: all eight simultaneous native rescues finish within {frame+1} frames; all resume control')
    finally:
        game.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',required=True)
    parser.add_argument('--rom',required=True)
    parser.add_argument('--checkpoint',required=True)
    args=parser.parse_args()
    validate(args.worker,args.rom,args.checkpoint)
