"""Exercise native linked battle initialization, control, damage, items and rematches."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
from test_gameplay import Game, word

ARENAS=(22,23,20,21)

def link(game,address,length=2):
    return bytes.fromhex(game.command(f'@linkpeek {address:x} {length:x}'))

def boot(game,players,arena):
    roster=[(arena+i)%8 for i in range(8)]
    assert len(game.command(f'@players {players}'))==64
    assert len(game.command('@mode battle'))==64
    assert len(game.command('@characters '+' '.join(map(str,roster))))==64
    assert len(game.command(f'@course {ARENAS[arena]}'))==64
    for frame in range(2500):
        button=0x1000 if frame==180 else (0x8000 if frame in range(300,2401,120) else 0)
        if button==0x8000 and word(game.peek(0x36,2),0)==14: button=0
        game.step([button]+[0]*7)
    assert word(game.peek(0x36,2),0)==14, 'Menu did not enter native battle'
    assert word(game.peek(0x3a,2),0)==6
    assert word(game.peek(0x142,2),0)==0xffff, 'Countdown did not finish'
    assert word(game.peek(0x124,2),0)==ARENAS[arena]
    assert word(game.peek(0xdfa,2),0)==0x3e60, 'Native item pool overlaps extra karts'
    racers=game.peek(0x1000,0x800)
    assert [word(racers,i*256+0x12) for i in range(players)]==[i*2 for i in roster[:players]]
    assert [bool(word(racers,i*256+0x10)&0x8000) for i in range(8)]==[i<players for i in range(8)]
    assert [word(link(game,0xc10,16),i*2) for i in range(8)]==[3 if i<players else 0 for i in range(8)]
    assert all(game.peek(address,1)==b'\x18' for address in (0x640,0x64d,0x65a,0x667)), 'Sprite drawing overwrote HDMA tables'
    return roster

def pop(game,slot):
    assert game.command(f'@word {0x108c+slot*256:x} 1')=='ok'
    for _ in range(8): game.step([0]*8)

def validate_case(worker,rom,players,arena,checkpoint=None):
    game=Game(worker,rom)
    try:
        roster=boot(game,players,arena)
        if players==8 and arena==0 and checkpoint:
            assert game.command(f'@save {Path(checkpoint).resolve()}')=='ok'
        with tempfile.TemporaryDirectory(prefix='battle-test-') as directory:
            snapshot=Path(directory)/'battle.state'
            assert game.command(f'@save {snapshot}')=='ok'
            for slot in range(players):
                game.command(f'@load {snapshot}')
                before=game.peek(0x1000+slot*256,256)
                for _ in range(40): game.step([0x8000 if i==slot else 0 for i in range(8)])
                racers=game.peek(0x1000,0x800)
                assert word(racers,slot*256+0xea)>0, f'P{slot+1} cannot accelerate'
                assert racers[slot*256+0x16:slot*256+0x1e]!=before[0x16:0x1e]
                assert [bool(word(racers,i*256+0xc4)&0x8000) for i in range(players)]==[i==slot for i in range(players)]
                game.command(f'@load {snapshot}')
                for expected in (2,1,0):
                    pop(game,slot)
                    lives=[word(link(game,0xc10,16),i*2) for i in range(players)]
                    assert lives==[expected if i==slot else 3 for i in range(players)], (slot,lives)
                assert word(game.peek(0x1010+slot*256,2),0)==0, 'Eliminated kart remains active'
            if players==8 and arena==0:
                for item in range(7):
                    for slot in range(players):
                        game.command(f'@load {snapshot}')
                        game.command(f'@linkword {0x500+slot*2:x} {0xc000+item:x}')
                        for frame in range(12): game.step([0x80 if i==slot and frame<4 else 0 for i in range(8)])
                        assert word(link(game,0x500+slot*2),0)!=0xc000+item, (item,slot,'not consumed')
                        if item==2: assert word(game.peek(0x10e2+slot*256,2),0)&2
                print('PASS: all seven native battle item types activate for all eight players',flush=True)
            if arena==0 and players in (2,8):
                for winner in (0,players-1):
                    game.command(f'@load {snapshot}')
                    for slot in range(players):
                        if slot!=winner:
                            for _ in range(3): pop(game,slot)
                    assert word(link(game,0xcb4),0)==1
                    assert word(link(game,0xcb0),0)==winner
                    # Let the real result screen and host confirmation restart a round.
                    for frame in range(1800):
                        button=0x8000 if frame>300 and frame%120==0 else 0
                        game.step([button]+[0]*7)
                        if word(link(game,0xcb4),0)==0 and word(game.peek(0x142,2),0)==0xffff:
                            break
                    assert word(link(game,0xcb4),0)==0, 'Native rematch did not initialize'
                    assert [word(link(game,0xc10,16),i*2) for i in range(players)]==[3]*players
                    assert [word(game.peek(0x1012+i*256,2),0) for i in range(players)]==[i*2 for i in roster[:players]]
                print(f'PASS: {players} players: host and guest victory, native result screen and rematch',flush=True)
        return f'PASS: {players} players, arena {arena+1}: boot, roster, independent movement, 3→0 balloons, HDMA integrity'
    finally: game.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',required=True)
    parser.add_argument('--rom',required=True)
    parser.add_argument('--checkpoint')
    parser.add_argument('--jobs',type=int,default=2)
    args=parser.parse_args()
    cases=[(n,0) for n in range(2,9)]+[(n,a) for a in range(1,4) for n in (2,8)]
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for result in pool.map(lambda case:validate_case(args.worker,args.rom,*case,args.checkpoint),cases): print(result,flush=True)
