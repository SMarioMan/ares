"""Local cameras must change video while preserving canonical state and audio."""
import argparse
from pathlib import Path

from test_gameplay import Game


def validate(worker,rom,checkpoint,output):
    directory=Path(output).resolve()
    directory.mkdir(parents=True,exist_ok=True)
    results=[]
    for slot,full in ((None,False),(0,False),(7,False),(7,True)):
        game=Game(worker,rom)
        try:
            assert game.command(f'@load {Path(checkpoint).resolve()}')=='ok'
            if slot is not None: assert game.command(f'@view {slot}')=='ok'
            if full: assert game.command('@render-full')=='ok'
            digests=[]
            for frame in range(120):
                digests.append(game.step([0x8000 | (0x0100 if (frame//30+i)%2 else 0x0200) for i in range(8)]))
            image=directory/f'view-{slot}-{full}.ppm'
            assert game.command(f'@image {image}')=='ok'
            results.append((digests,game.command('@audio'),image.read_bytes()))
        finally:
            game.close()
    assert all(r[0]==results[0][0] for r in results), 'Local rendering changed canonical simulation'
    assert all(r[1]==results[0][1] for r in results), 'Speculative rendering changed canonical audio'
    assert results[2][2]==results[3][2], 'Run-ahead warmup changed the final local image'
    assert results[1][2]!=results[2][2], 'Different players received the same camera view'
    count=int(results[0][1].split()[0])
    assert count>0, 'No audio frames were exercised'
    print(f'PASS: 120 state barriers and {count} audio samples agree with rendering off and cameras 1/8')
    print('PASS: players 1 and 8 have distinct video output')
    print('PASS: fast presentation is pixel-identical to three fully rasterized drawing passes')
    # The shared HUD belongs to P1. Only the private view should expose P8's
    # inventory; refreshing its icon must not execute item transitions again.
    hud=[]
    for slot in (None,7):
        images=[]
        for item in (0,1):
            game=Game(worker,rom)
            try:
                assert game.command(f'@load {Path(checkpoint).resolve()}')=='ok'
                assert game.command(f'@linkword 50e {0xc000+item:x}')=='ok'
                if slot is not None: assert game.command(f'@view {slot}')=='ok'
                for _ in range(8): game.step([0]*8)
                image=directory/f'hud-{slot}-{item}.ppm'
                assert game.command(f'@image {image}')=='ok'
                images.append(image.read_bytes())
            finally:
                game.close()
        hud.append(images)
    assert hud[0][0]==hud[0][1], 'Guest inventory changed the host HUD'
    assert hud[1][0]!=hud[1][1], 'Guest HUD did not show its own item'
    print('PASS: player 8 sees its own item icon independently of the host HUD')
    # Draw the same frozen world with native pending/stolen timer phases. Private
    # presentation must reproduce the icon and blink without decrementing timers.
    icons={}
    for label,inventory,timer in (
        ('empty',0,0),('shell',0xc001,0),('boo-marker',0xc009,0),
        ('pending-visible',0x8001,0),('pending-hidden',0x8001,8),
        ('stolen-visible',0x9000,8),('stolen-hidden',0x9000,16)):
        game=Game(worker,rom)
        try:
            assert game.command(f'@load {Path(checkpoint).resolve()}')=='ok'
            assert game.command(f'@linkword 50e {inventory:x}')=='ok'
            assert game.command(f'@linkword 54e {timer:x}')=='ok'
            assert game.command('@view 7')=='ok'
            assert game.command('@draw')=='ok'
            image=directory/f'hud-{label}.ppm'
            assert game.command(f'@image {image}')=='ok'
            icons[label]=image.read_bytes()
            assert bytes.fromhex(game.command('@linkpeek 54e 2'))==timer.to_bytes(2,'little'), 'Private HUD advanced the item timer'
        finally:
            game.close()
    assert icons['pending-visible']==icons['shell']
    assert icons['pending-hidden']==icons['empty']
    assert icons['stolen-visible']==icons['boo-marker']
    assert icons['stolen-hidden']==icons['empty']
    assert icons['boo-marker']!=icons['shell']!=icons['empty']
    print('PASS: pending and stolen inventory icons follow native blink phases without advancing timers')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',required=True)
    parser.add_argument('--rom',required=True)
    parser.add_argument('--checkpoint',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    validate(args.worker,args.rom,args.checkpoint,args.output)
