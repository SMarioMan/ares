"""Drive final-lap crossings and a complete linked Grand Prix through native results."""
import argparse
import math
import time
from pathlib import Path

from test_gameplay import Game, word


def finish_inputs(game, racers, count, path, sections, players=8):
    """Drive human controls toward the next native course-center checkpoint."""
    pads=[]
    for slot in range(8):
        base=slot*256
        others_finished=all(word(racers,i*256+0x10)&0x20 for i in range(1,players))
        if slot>=players or word(racers,base+0x10)&0x20 or (slot==0 and not others_finished):
            pads.append(0)
            continue
        target=((word(racers,base+0xc0)&255)+1)%sections
        dx=word(path,target*2)-word(racers,base+0x18)
        dy=word(path,256+target*2)-word(racers,base+0x1c)
        angle=int(math.atan2(dx,-dy)*65536/(2*math.pi))&65535
        delta=((angle-word(racers,base+0xa4)+32768)&65535)-32768
        pads.append(0x8000 | (0x0100 if delta>0x200 else 0x0200 if delta< -0x200 else 0))
    return pads


def validate(worker, rom, checkpoint=None, rounds=5, players=8):
    game=Game(worker,rom)
    started=time.monotonic()
    try:
        if checkpoint:
            assert game.command(f'@load {Path(checkpoint).resolve()}')=='ok'
            assert int(game.command('@linkpeek 3b2 1'),16)==players, 'Checkpoint belongs to a different lobby size'
        else:
            assert len(game.command(f'@players {players}'))==64
            for frame in range(2200):
                button=0x1000 if frame==180 else 0x8000 if frame in range(300,2101,120) else 0
                if button==0x8000 and word(game.peek(0x36,2),0)==2: button=0
                game.step([button]+[0]*7)
        for round in range(rounds):
            globals=game.peek(0,0x180)
            assert word(globals,0x152)==round
            assert word(globals,0x36)==2 and word(globals,0x3a)==6
            previous_course=word(globals,0x124)
            racers=game.peek(0x1000,0x800)
            assert [word(racers,i*256+0x12) for i in range(8)]==list(range(0,16,2))
            inventory=bytes.fromhex(game.command('@linkpeek 500 10'))
            assert inventory[:players*2]==bytes(players*2), 'Human inventory leaked from the previous race'
            # Arrange the final lap, but let real movement and the real line
            # crossing logic record every finisher and determine their order.
            for slot in range(players):
                for offset in (0xc0,0xf8):
                    progress=word(racers,slot*256+offset)
                    assert progress>>8==0x7f, 'Unexpected initial lap state'
                    assert game.command(f'@word {0x1000+slot*256+offset:x} {progress+0x500:x}')=='ok'
            path=game.peek(0x900,512)
            sections=word(globals,0x148)
            assert 0<sections<=128
            count=0
            for frame in range(2400):
                racers=game.peek(0x1000,0x800)
                game.step(finish_inputs(game,racers,count,path,sections,players))
                globals=game.peek(0,0x180)
                count=word(globals,0x144)
                assert count<=16 and count%2==0
                if count<16:
                    assert word(globals,0x128)==0, 'Results started before every player finished'
                else:
                    break
            else:
                racers=game.peek(0x1000,0x800)
                details=[[hex(word(racers,i*256+o)) for o in (0x10,0x18,0x1c,0x68,0xa0,0xc0,0xea)] for i in range(8)]
                failed=Path(checkpoint or '/workspace/build/race-cycle').resolve().with_suffix('.failed.state')
                assert game.command(f'@save {failed}')=='ok'
                raise AssertionError(f'Round {round+1}, course {previous_course}: not all eight finished; flags/x/y/terrain/action/progress/speed={details}; saved {failed}')
            racers=game.peek(0x1000,0x800)
            assert all(word(racers,i*256+0x10)&0x20 for i in range(8)), 'A human finish was not recorded'
            ranks=[word(racers,i*256+0xe6) for i in range(8)]
            assert sorted(ranks)==list(range(0,16,2)), 'Finish ranks are duplicated or missing'
            assert all(ranks[0]>ranks[i] for i in range(1,players)), 'The host must qualify after every other connected player'
            print(f'PASS: race {round+1}, course {previous_course}: all eight finish; unique ranks {ranks}',flush=True)
            if round+1<rounds:
                for frame in range(4200):
                    game.step([0x8000 if frame>=300 and frame%90==0 else 0]+[0]*7)
                    globals=game.peek(0,0x180)
                    if (word(globals,0x152)==round+1 and word(globals,0x36)==2
                            and word(globals,0x3a)==6 and word(globals,0x144)==0):
                        if word(globals,0x142)==0xffff:
                            assert word(globals,0x124)!=previous_course, 'Cup did not advance to the next course'
                            break
                else:
                    raise AssertionError('Host could not advance the whole lobby to the next race')
            else:
                # Complete the award/results sequence and return to the title.
                for frame in range(14000):
                    game.step([0x8000 if frame>=300 and frame%90==0 else 0]+[0]*7)
                    globals=game.peek(0,0x180)
                    if word(globals,0x36)==4:
                        print('PASS: completed cup returns to the LINK GP menu',flush=True)
                        break
                else:
                    raise AssertionError('Cup completion did not return to the menu')
                for frame in range(4200):
                    game.step([0x8000 if frame%90==0 else 0]+[0]*7)
                    globals=game.peek(0,0x180)
                    if (word(globals,0x36)==2 and word(globals,0x3a)==6
                            and word(globals,0x142)==0xffff and word(globals,0x144)==0):
                        assert word(globals,0x152)==0, 'Rematch retained the previous round'
                        racers=game.peek(0x1000,0x800)
                        assert [word(racers,i*256+0x12) for i in range(8)]==list(range(0,16,2))
                        assert bytes.fromhex(game.command('@linkpeek 500 10'))[:players*2]==bytes(players*2)
                        print('PASS: host starts a new cup with the same roster and clean inventories',flush=True)
                        break
                else:
                    raise AssertionError('Host could not start another cup')
        print(f'PASS: linked Grand Prix cycle completed in {time.monotonic()-started:.1f}s',flush=True)
    finally:
        game.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',required=True)
    parser.add_argument('--rom',required=True)
    parser.add_argument('--checkpoint')
    parser.add_argument('--players',type=int,choices=range(2,9),default=8)
    args=parser.parse_args()
    validate(args.worker,args.rom,args.checkpoint,players=args.players)
