"""Validate every lobby size, native CPU vacancies, and human completion barriers."""
import argparse
from concurrent.futures import ThreadPoolExecutor

from test_gameplay import Game, word
from test_race_cycle import finish_inputs


def validate_count(worker,rom,players):
    game=Game(worker,rom)
    try:
        assert len(game.command(f'@players {players}'))==64
        for frame in range(2200):
            button=0x1000 if frame==180 else 0x8000 if frame in range(300,2101,120) else 0
            if button==0x8000 and word(game.peek(0x36,2),0)==2: button=0
            game.step([button]+[0]*7)
        globals=game.peek(0,0x180)
        assert word(globals,0x36)==2 and word(globals,0x3a)==6, f'{players}P did not enter a race'
        racers=game.peek(0x1000,0x800)
        assert [bool(word(racers,i*256+0x10)&0x8000) for i in range(8)]==[i<players for i in range(8)]
        assert len(set(word(racers,i*256+0x12) for i in range(8)))==8
        before=racers
        for _ in range(120): game.step([0]*8)
        racers=game.peek(0x1000,0x800)
        for slot in range(players,8):
            assert racers[slot*256+0x16:slot*256+0x1e]!=before[slot*256+0x16:slot*256+0x1e], 'A CPU vacancy remained stationary'
        if players<8:
            slot=players
            assert game.command(f'@linkword {0x500+slot*2:x} c002')=='ok'
            for _ in range(12): game.step([0]*8)
            inventory=bytes.fromhex(game.command('@linkpeek 500 10'))
            assert word(inventory,slot*2)==0, 'CPU vacancy cannot use its inventory'
        # Only humans are advanced to the final lap. CPUs deliberately remain
        # several laps behind, so waiting for absent controller slots will fail.
        racers=game.peek(0x1000,0x800)
        for slot in range(players):
            for offset in (0xc0,0xf8):
                value=word(racers,slot*256+offset)
                assert value>>8==0x7f, 'An uncommanded human left the starting area'
                assert game.command(f'@word {0x1000+slot*256+offset:x} {value+0x500:x}')=='ok'
        path=game.peek(0x900,512)
        sections=word(globals,0x148)
        count=0
        for frame in range(2400):
            racers=game.peek(0x1000,0x800)
            game.step(finish_inputs(game,racers,count,path,sections,players))
            globals=game.peek(0,0x180)
            count=word(globals,0x144)
            assert 0<=count<=16 and count%2==0, 'Invalid finish count'
            racers=game.peek(0x1000,0x800)
            humans_done=all(word(racers,i*256+0x10)&0x20 for i in range(players))
            if not humans_done:
                assert word(globals,0x128)==0, 'Results started while a connected player was racing'
            if count==16 and all(word(racers,i*256+0x10)&0x20 for i in range(8)):
                break
        else:
            raise AssertionError(f'{players}P completion waited for absent players or stranded a racer')
        assert sorted(word(racers,i*256+0xe6) for i in range(8))==list(range(0,16,2))
        for _ in range(60): game.step([0]*8)
        assert word(game.peek(0x128,2),0)!=0, 'Native results did not start'
        print(f'PASS: {players} connected humans, {8-players} CPU vacancies, unique roster/ranks, results after all humans finish',flush=True)
    finally:
        game.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',required=True)
    parser.add_argument('--rom',required=True)
    parser.add_argument('--jobs',type=int,default=2)
    args=parser.parse_args()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(lambda players: validate_count(args.worker,args.rom,players),range(2,9)))
