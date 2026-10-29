"""Simultaneous final-balloon losses must yield a draw and a host-controlled rematch."""
import argparse
from pathlib import Path
from test_battle import Game,boot,pop,link,word


def validate(worker,rom,players,checkpoint=None):
    game=Game(worker,rom)
    try:
        if checkpoint:
            assert players==8
            assert game.command(f'@load {Path(checkpoint).resolve()}')=='ok'
        else:boot(game,players,0)
        for slot in range(players):
            pop(game,slot);pop(game,slot)
        assert [word(link(game,0xc10,16),i*2) for i in range(players)]==[1]*players
        for slot in range(players):game.command(f'@word {0x108c+slot*256:x} 1')
        for _ in range(8):game.step([0]*8)
        assert word(link(game,0xcb4),0)==1 and word(link(game,0xcb0),0)==0xffff
        assert all(not(word(game.peek(0x1010+slot*256,2),0)&0x8000) for slot in range(players))
        for frame in range(1800):
            game.step([0x8000 if frame>300 and frame%120==0 else 0]+[0]*7)
            if word(link(game,0xcb4),0)==0 and word(game.peek(0x142,2),0)==0xffff:break
        assert word(link(game,0xcb4),0)==0
        assert [word(link(game,0xc10,16),i*2) for i in range(players)]==[3]*players
        print(f'PASS: {players}-player simultaneous elimination produces a draw, removes every kart, and rematches with three balloons each')
    finally:game.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--worker',required=True);p.add_argument('--rom',required=True)
    p.add_argument('--players',type=int,choices=(2,8),default=8);p.add_argument('--checkpoint')
    a=p.parse_args();validate(a.worker,a.rom,a.players,a.checkpoint)
