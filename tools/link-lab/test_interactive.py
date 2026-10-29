"""Exercise the real SDL3 window and keyboard backend on an X11 test display."""
import argparse
import os
import subprocess
import time
from pathlib import Path

from Xlib import X, XK, display, error
from Xlib.ext import xtest
from PIL import Image


def validate(worker, rom, output):
    # XTEST key state outlives a window; clean up prior interrupted test runs.
    setup=display.Display()
    for key in ('Escape','z','x','Left','Right','Up','Down','Return','q','w'):
        xtest.fake_input(setup,X.KeyRelease,setup.keysym_to_keycode(XK.string_to_keysym(key)))
    setup.sync(); setup.close()
    process=subprocess.Popen([worker,'--window','0',rom],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE,text=True,bufsize=1,
                             env=dict(os.environ,SDL_VIDEODRIVER='x11'))
    connection=None
    try:
        assert len(process.stdout.readline().strip())==64, 'SDL worker did not start'
        connection=display.Display()
        windows=[]
        for candidate in connection.screen().root.query_tree().children:
            try:
                if 'Super Mario Kart Link' in str(candidate.get_wm_name()): windows.append(candidate)
            except error.BadWindow:
                continue
        assert windows, 'SDL game window was not created'
        window=windows[-1]
        connection.set_input_focus(window,X.RevertToParent,X.CurrentTime)
        connection.sync()

        def command(text):
            process.stdin.write(text+'\n');process.stdin.flush()
            answer=process.stdout.readline().strip()
            assert answer, 'SDL worker exited unexpectedly'
            return answer

        assert command('@poll')=='0'
        for key, expected in [('z',0x8000),('x',0x0080),('Left',0x0200),('Right',0x0100),
                              ('Up',0x0800),('Down',0x0400),('Return',0x1000),('q',0x0020),('w',0x0010)]:
            keycode=connection.keysym_to_keycode(XK.string_to_keysym(key))
            xtest.fake_input(connection,X.KeyPress,keycode);connection.sync();time.sleep(0.03)
            assert int(command('@poll'),16)==expected, f'Incorrect SNES mapping for {key}'
            xtest.fake_input(connection,X.KeyRelease,keycode);connection.sync();time.sleep(0.03)
            assert command('@poll')=='0', f'Stuck button after releasing {key}'
        for _ in range(240): command('0000 0000 0000 0000 0000 0000 0000 0000')
        assert command(f'@image {Path(output).resolve()}')=='ok'
        image=Image.open(output)
        assert image.width>=256 and image.height>=224
        assert len(image.getcolors(maxcolors=1000000))>10, 'ROM video did not render'
        width,height=map(int,command('@display').split())
        assert 1.3<width/height<1.4, 'SNES pixel aspect/sample scaling was ignored'
        xtest.fake_input(connection,X.KeyPress,connection.keysym_to_keycode(XK.string_to_keysym('Escape')))
        connection.sync();time.sleep(0.03)
        assert command('@poll')=='quit'
        process.stdin.close();process.wait(timeout=10)
        assert process.returncode==0, process.stderr.read()
        print('PASS: SDL3 window, ROM video/aspect, nine keyboard mappings, key releases, and quit')
    finally:
        if connection:
            xtest.fake_input(connection,X.KeyRelease,connection.keysym_to_keycode(XK.string_to_keysym('Escape')))
            connection.sync(); connection.close()
        if process.poll() is None:
            process.kill();process.wait()
        process.stdout.close();process.stderr.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',required=True)
    parser.add_argument('--rom',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    validate(args.worker,args.rom,args.output)
