"""Exercise link MMIO through executed 65816 loads, rather than reading the bus from the host."""
import argparse
import selectors
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--worker', required=True)
p.add_argument('--rom', required=True, help='link_input_probe.asm assembled as a standalone ROM')
a = p.parse_args()
worker = subprocess.Popen([a.worker, '--verify-link-probe', a.rom], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
selector = selectors.DefaultSelector()
selector.register(worker.stdout, selectors.EVENT_READ)


def digest():
    if not selector.select(timeout=10):
        raise RuntimeError('65816 link probe timed out')
    line = worker.stdout.readline().strip()
    if len(line) != 64:
        raise RuntimeError('65816 link probe failed: ' + worker.stderr.read())
    return line


try:
    digest()
    # Distinct buttons for every slot; then move one held button through all slots.
    patterns = [[0x8000 >> i for i in range(8)], [0]*8, [0xfff0]*8]
    patterns += [[0x8000 if i == active else 0 for i in range(8)] for active in range(8)]
    for pads in patterns:
        worker.stdin.write(' '.join(f'{pad:04x}' for pad in pads) + '\n')
        worker.stdin.flush()
        digest()  # Worker checks the ROM's WRAM results for all eight words.
    worker.stdin.close()
    worker.wait(timeout=10)
    if worker.returncode:
        raise RuntimeError(worker.stderr.read())
    print(f'PASS: 65816 live/strobed reads and stable eight-pad latches for {len(patterns)} input patterns')
finally:
    if worker.poll() is None:
        worker.kill()
        worker.wait()
    selector.close()
    worker.stdout.close()
    worker.stderr.close()
