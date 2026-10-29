"""Boot every course with permuted rosters and verify host-only menu authority."""
import argparse
from concurrent.futures import ThreadPoolExecutor

from test_gameplay import Game, word


def validate_course(worker, rom, course):
    game=Game(worker,rom)
    roster=[(course+i)%8 for i in range(8)]
    try:
        assert len(game.command('@characters '+' '.join(map(str,roster))))==64
        assert len(game.command(f'@course {course}'))==64
        character_screen=False
        for frame in range(2200):
            button=0x1000 if frame==180 else (0x8000 if frame in range(300,2101,120) else 0)
            # Guests continually request menus/pause/selection. Only host input
            # may reach native menus. Host directions cannot change a reservation.
            if not button and word(game.peek(0x36,2),0)==6:
                character_screen=True
                button=0x0200 if frame%2 else 0x0100
            game.step([button]+[0xfff0 if frame%2 else 0]*7)
        globals=game.peek(0,0x180)
        assert character_screen, 'Character reservation was not exercised'
        assert word(globals,0x36)==2 and word(globals,0x3a)==6, f'Course {course}: menu failed'
        assert word(globals,0x124)==course, f'Host course override {course} was ignored'
        assert word(globals,0x162)&0x8000==0, 'A guest paused the race'
        racers=game.peek(0x1000,0x800)
        assert [word(racers,i*256+0x12) for i in range(8)]==[c*2 for c in roster]
        assert all(word(racers,i*256+0x10)&0x8000 for i in range(8))
        # Verify that P1 can pause, guests cannot unpause, and P1 resumes.
        game.step([0]*8)
        game.step([0x1000]+[0]*7)
        for _ in range(8): game.step([0]*8)
        assert word(game.peek(0x162,2),0)&0x8000, 'Host cannot pause'
        for frame in range(8): game.step([0]+[0x1000 if frame%2 else 0]*7)
        assert word(game.peek(0x162,2),0)&0x8000, 'Guest could unpause'
        game.step([0x1000]+[0]*7)
        for _ in range(8): game.step([0]*8)
        assert word(game.peek(0x162,2),0)&0x8000==0, 'Host cannot resume'
        for frame in range(180):
            game.step([0x8000 | (0x0020 if frame%30==0 else 0) |
                       (0x0100 if (frame//30+i)%2 else 0x0200) for i in range(8)])
        assert word(game.peek(0x36,2),0)==2
        return f'PASS: course {course:2}, roster {roster}, host menus/pause, guest exclusion'
    finally:
        game.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',required=True)
    parser.add_argument('--rom',required=True)
    parser.add_argument('--jobs',type=int,default=2)
    args=parser.parse_args()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for result in pool.map(lambda course: validate_course(args.worker,args.rom,course),range(20)):
            print(result,flush=True)
