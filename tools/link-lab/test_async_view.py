"""Separate renderers must reproduce synchronous pixels without changing world/audio."""
import argparse
from pathlib import Path
import tempfile

from session import AsyncView
from test_gameplay import Game


def validate(worker,rom,checkpoint,battle=False):
    canonical=Game(worker,rom)
    reference=Game(worker,rom)
    view=None
    try:
        for game in (canonical,reference):
            assert game.command(f'@load {Path(checkpoint).resolve()}')=='ok'
        assert canonical.command('@external-view 7')=='ok'
        assert reference.command('@view 7')=='ok'
        rate=float(canonical.command('@rate'))
        assert 60<rate<61, 'The frontend is not using the native NTSC refresh rate'
        with tempfile.TemporaryDirectory(prefix='ares-async-test-') as directory:
            source=Path(directory)/'probe.state'
            original=Path(directory)/'reference.ppm'
            shown=Path(directory)/'displayed.ppm'
            images={}
            pads=[0x8000]*8
            assert canonical.step(pads)==reference.step(pads)
            frame,epoch=map(int,canonical.command(f'@export {source}').split())
            reference.command(f'@image {original}')
            images[frame]=original.read_bytes()
            view=AsyncView(worker,rom,7,directory,15)
            view.pump(canonical.process,frame)
            for index in range(90):
                pads=[0x8000 | (0x100 if (index//30+i)%2 else 0x200) for i in range(8)]
                assert canonical.step(pads)==reference.step(pads), 'Rendering changed a canonical frame'
                frame+=1
                reference.command(f'@image {original}')
                images[frame]=original.read_bytes()
                before=view.presented
                view.pump(canonical.process,frame)
                if view.presented>before:
                    canonical.command(f'@image {shown}')
                    assert shown.read_bytes()==images[view.last_presented_frame], 'Asynchronous image differs from its synchronous source frame'
            assert view.presented>0, 'No asynchronous view was presented'
            assert canonical.command('@audio')==reference.command('@audio'), 'Rendering changed canonical audio'
            assert canonical.command(f'@import-image {frame+1} {epoch} {original}')=='skip', 'Future frame was accepted'
            assert canonical.command(f'@import-image {frame} {epoch-1} {original}')=='skip', 'Stale race generation was accepted'
            print(f'PASS: 91 canonical frames/audio agree; {view.presented} asynchronous images match their synchronous source pixels')
            print('PASS: native NTSC pacing and stale/future image rejection')
            if battle:
                # Eliminate this local player, then eliminate the host it was
                # spectating. Reattach the foreground object only in private RAM.
                view.close(); view=None
                for slot in (7,0):
                    for _ in range(3):
                        for game in (canonical,reference):
                            assert game.command(f'@word {0x108c+slot*256:x} 1')=='ok'
                        for _ in range(8):
                            assert canonical.step([0]*8)==reference.step([0]*8)
                new_frame,new_epoch=map(int,canonical.command(f'@export {source}').split())
                assert new_epoch>epoch, 'Spectator target did not invalidate old video'
                assert canonical.command(f'@import-image {frame} {epoch} {original}')=='skip'
                view=AsyncView(worker,rom,7,directory,15)
                for _ in range(45):
                    assert canonical.step([0]*8)==reference.step([0]*8)
                    source_frame,source_epoch=map(int,canonical.command(f'@export {source}').split())
                    reference.command(f'@image {original}')
                    images[source_frame]=original.read_bytes()
                    before=view.presented
                    view.pump(canonical.process,source_frame)
                    if view.presented>before:
                        canonical.command(f'@image {shown}')
                        assert shown.read_bytes()==images[view.last_presented_frame]
                assert view.presented>0
                assert canonical.command('@audio')==reference.command('@audio')
                print('PASS: eliminated client spectates living racers, including after host elimination; private images/state/audio agree')
            # A host pause must show shared native UI, invalidate the outstanding
            # camera generation, and recover a new local view only after resume.
            view.close(); view=None
            for game in (canonical,reference):
                game.step([0]*8)
                for _ in range(4):game.step([0x1000]+[0]*7)
                for _ in range(8): game.step([0]*8)
                assert int.from_bytes(game.peek(0x162,2),'little')&0x8000
            assert canonical.command(f'@export {source}')=='skip', 'Paused game exported a private camera'
            canonical.command(f'@image {shown}')
            reference.command(f'@image {original}')
            assert shown.read_bytes()==original.read_bytes(), 'Pause did not restore shared host video'
            assert canonical.command(f'@import-image {frame} {epoch} {original}')=='skip'
            for game in (canonical,reference):
                for _ in range(4):game.step([0x1000]+[0]*7)
                for _ in range(8): game.step([0]*8)
            resumed_frame,resumed_epoch=map(int,canonical.command(f'@export {source}').split())
            assert resumed_epoch>epoch and resumed_frame>frame
            assert canonical.command(f'@import-image {frame} {epoch} {original}')=='skip'
            assert canonical.command('@audio')==reference.command('@audio')
            # Seed the native completion counter to check the results boundary.
            # No private image from the just-finished race may obscure its UI.
            for game in (canonical,reference):
                if battle:
                    for slot in range(1,6):
                        for _ in range(3):
                            assert game.command(f'@word {0x108c+slot*256:x} 1')=='ok'
                            for _ in range(8): game.step([0]*8)
                else:
                    assert game.command('@word 144 10')=='ok'
                    game.step([0]*8)
            assert canonical.command(f'@export {source}')=='skip', 'Finished race exported a private camera'
            canonical.command(f'@image {shown}')
            reference.command(f'@image {original}')
            assert shown.read_bytes()==original.read_bytes(), 'Finished race did not restore shared host video'
            assert canonical.command(f'@import-image {resumed_frame} {resumed_epoch} {original}')=='skip'
            print('PASS: native host pause/resume and race completion restore shared UI and invalidate old camera images')
    finally:
        if view: view.close()
        reference.close();canonical.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',required=True)
    parser.add_argument('--rom',required=True)
    parser.add_argument('--checkpoint',required=True)
    parser.add_argument('--battle',action='store_true')
    args=parser.parse_args()
    validate(args.worker,args.rom,args.checkpoint,args.battle)
