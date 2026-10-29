"""Build from a read-only user ROM mount; ROM data never enters image layers."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

output=Path('/output')
if not output.is_dir(): raise SystemExit('Mount a writable output directory at /output')
subprocess.run(['python3','/opt/disassembly/tools/build_stock.py','/input/game.sfc',
    '--asar','/usr/local/bin/asar','--output',str(output/'stock-smk.sfc')],check=True)
subprocess.run(['python3','/opt/disassembly/tools/build_linked.py',str(output/'stock-smk.sfc'),
    '--asar','/usr/local/bin/asar','--output',str(output/'linked-smk.sfc')],check=True)
bundle=output/'link'
bundle.mkdir(exist_ok=True)
shutil.copytree('/opt/link',bundle,dirs_exist_ok=True)
manifest={name:hashlib.sha256((output/name).read_bytes()).hexdigest()
          for name in ('stock-smk.sfc','linked-smk.sfc','link/bin/ares-link-worker','link/desktop/bin/ares')}
(output/'SHA256.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Built stock-smk.sfc (byte-verified), linked-smk.sfc, and link/bin/ares-link-worker in /output')
