"""Real battle item-box pickup and green/red shell collisions across all player pairs."""
import argparse
from pathlib import Path
from test_battle import Game, link, word


def validate(worker,rom,checkpoint):
    game=Game(worker,rom)
    try:
        checkpoint=Path(checkpoint).resolve()
        def restore(): assert game.command(f'@load {checkpoint}')=='ok'
        restore()
        attributes=game.peek(0xb00,256)
        course=game.peek(0x10000,0x4000)
        index=next(i for i,tile in enumerate(course) if attributes[tile]==0x14)
        box=((index%128)*8+4,(index//128)*8+4)
        def position(slot,x,y,angle=0x8000):
            for offset,value in ((0x16,0),(0x18,x),(0x1a,0),(0x1c,y),(0xa4,angle),(0xa2,angle),(0x2a,angle)):
                assert game.command(f'@word {0x1000+slot*256+offset:x} {value:x}')=='ok'
        for slot in range(8):
            restore(); position(slot,*box)
            for _ in range(12): game.step([0]*8)
            inventory=link(game,0x500,16)
            assert word(inventory,slot*2)&0x8000, f'P{slot+1} did not collect a real item box'
            assert all(word(inventory,i*2)==0 for i in range(8) if i!=slot)
        print('PASS: all eight players collect real arena item boxes independently',flush=True)
        for item,label in ((4,'green shell'),(5,'red shell')):
            for owner in range(8):
                for victim in range(8):
                    if owner==victim: continue
                    restore()
                    for slot in range(8):
                        position(slot,512 if slot in (owner,victim) else 800+slot*8,
                                 392 if slot==owner else 464 if slot==victim else 800)
                    for _ in range(8): game.step([0]*8)
                    assert game.command(f'@linkword {0x500+owner*2:x} {0xc000+item:x}')=='ok'
                    spawned=False; targeted=False
                    for frame in range(120):
                        game.step([0x80 if i==owner and frame<4 else 0 for i in range(8)])
                        if frame==12:
                            objects=link(game,0x1c00,0x400)
                            spawned=any(word(objects,i*128+0x12)&0x8000 for i in range(8))
                            targeted=any(word(objects,i*128+0x64)==0x1000+victim*256 for i in range(8))
                    lives=[word(link(game,0xc10,16),i*2) for i in range(8)]
                    assert spawned, (label,owner,'no real projectile')
                    if item==5: assert targeted, (owner,victim,'wrong homing target')
                    assert lives==[2 if i==victim else 3 for i in range(8)], (label,owner,victim,lives)
            print(f'PASS: real {label} launch/collision removes only the victim balloon across all 56 player pairs',flush=True)
    finally: game.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',required=True);parser.add_argument('--rom',required=True)
    parser.add_argument('--checkpoint',required=True)
    args=parser.parse_args();validate(args.worker,args.rom,args.checkpoint)
