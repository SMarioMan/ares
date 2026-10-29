"""Render all eight local battle views and verify shaded player balloon colors."""
import argparse
from pathlib import Path
import tempfile
from test_battle import Game, link, word

NAMES=('blue','red','green','yellow','purple','cyan','orange','pink')

def matches(slot,r,g,b):
    return (
        b>200 and r<40 and 80<g<180,
        r>230 and g<40 and b<40,
        g>200 and r<40 and b<80,
        r>230 and g>200 and b<40,
        r>130 and b>180 and g<80,
        g>200 and b>230 and r<40,
        r>230 and 60<g<170 and b<50,
        r>230 and b>120 and 40<g<150,
    )[slot]


def validate(worker,rom,checkpoint,output):
    directory=Path(output).resolve();directory.mkdir(parents=True,exist_ok=True)
    for slot,name in enumerate(NAMES):
        game=Game(worker,rom)
        try:
            assert game.command(f'@load {Path(checkpoint).resolve()}')=='ok'
            # Isolate this player's three real balloon objects; native drawing,
            # shading, highlights, transparency, and its kart remain unchanged.
            for other in range(8):
                for balloon in range(3):
                    base=0x1000+other*0x180+balloon*0x80
                    assert word(link(game,base+0x14),0)&0x0e00==(other^1)*0x200
                    if other!=slot: assert game.command(f'@linkword {base+0x12:x} 1000')=='ok'
            assert game.command(f'@view {slot}')=='ok'
            before=game.peek(0,0x20000);device=link(game,0,0x2000);audio=game.command('@audio')
            assert game.command('@draw')=='ok'
            assert game.peek(0,0x20000)==before,'Private color rendering changed world memory'
            assert link(game,0,0x2000)==device,'Private color rendering changed link state'
            assert game.command('@audio')==audio,'Private color rendering changed canonical audio'
            image=directory/f'player-{slot+1}-{name}.ppm'
            assert game.command(f'@image {image}')=='ok'
            magic,size,maximum,pixels=image.read_bytes().split(b'\n',3)
            width,height=map(int,size.split());assert magic==b'P6' and maximum==b'255'
            # Native 2x horizontal samples, including the PPU's 26-pixel border.
            count=0
            for y in range(70,min(112,height)):
                for x in (*range(210,260),*range(320,365)):
                    offset=(y*width+x)*3
                    count+=matches(slot,*pixels[offset:offset+3])
            assert count>40,f'Player {slot+1} has no visible {name} balloon pixels ({count})'
            # The foreground kart must survive crowded sprite/camera warmup.
            colored=0
            for y in range(72,101):
                for x in range(268,297):
                    r,g,b=pixels[(y*width+x)*3:(y*width+x)*3+3]
                    road=(140<=r<=190 and 130<=g<=175 and 40<=b<=100)
                    colored+=not road
            assert colored>100,f'Player {slot+1} foreground kart is missing'
            print(f'PASS: player {slot+1} has {name} balloons, visible own kart, and unchanged world/link memory and audio',flush=True)
        finally:game.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--worker',required=True);p.add_argument('--rom',required=True)
    p.add_argument('--checkpoint',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();validate(a.worker,a.rom,a.checkpoint,a.output)
