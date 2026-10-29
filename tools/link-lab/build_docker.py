#!/usr/bin/env python3
"""Build the emulator and verified linked cartridge using Docker, Git, and Python 3."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def stage(ares,disassembly,destination):
    # Git's source list includes current edits/new code but excludes ignored builds.
    # No user ROM, extracted assets, Git credentials, or .git directory is sent.
    paths=subprocess.check_output(['git','-C',str(ares),'ls-files','-z','--cached',
                                  '--others','--exclude-standard']).decode().split('\0')
    forbidden={'.bin','.sfc','.smc','.state','.srm','.brr','.lz5','.o','.a','.so','.exe','.dll'}
    for relative in paths:
        if not relative: continue
        source=ares/relative
        if not source.is_file() or source.suffix.lower() in forbidden: continue
        target=destination/'ares'/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,target)
    for directory in ('Global','SMK','Firmware','tools'):
        for source in (disassembly/directory).rglob('*'):
            if not source.is_file() or source.suffix.lower() not in ('.asm','.py','.txt','.json'): continue
            if '__pycache__' in source.parts: continue
            target=destination/'disassembly'/source.relative_to(disassembly)
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,target)
    for directory in ('Firmware','SMK/Graphics','SMK/Graphics/Compressed',
                      'SMK/SPC700/Music','SMK/SPC700/Samples','SMK/TrackData'):
        (destination/'disassembly'/directory).mkdir(parents=True,exist_ok=True)
    # Fetch through the host's configured Git trust/proxy, rather than embedding
    # private proxy CA certificates or credentials into an image layer.
    with tempfile.TemporaryDirectory(prefix='smk-asar-source-') as temporary:
        source=Path(temporary)/'asar'
        subprocess.run(['git','clone','--branch','v1.71','--depth','1',
                        'https://github.com/RPGHacker/asar.git',str(source)],check=True)
        revision=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD']).decode().strip()
        if revision!='217a93ffd44a44f196a06cff9b96ddb7dc892b8b':
            raise RuntimeError('Asar v1.71 does not match the pinned source commit')
        shutil.copytree(source,destination/'asar',ignore=shutil.ignore_patterns('.git'))
    docker=Path(__file__).with_name('docker')
    for name in ('Dockerfile','entrypoint.py'): shutil.copy2(docker/name,destination/name)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rom',type=Path)
    parser.add_argument('--output',type=Path,default=Path('smk-link-build'))
    parser.add_argument('--disassembly',type=Path,default=Path(__file__).resolve().parents[3]/'Super-Mario-Kart-Disassembly')
    parser.add_argument('--image',default='smk-link-builder:local')
    parser.add_argument('--jobs',type=int,default=4)
    args=parser.parse_args()
    if not args.rom.is_file(): parser.error('Supply the commercial USA ROM file')
    if not (args.disassembly/'tools/build_stock.py').is_file(): parser.error('Companion disassembly checkout is missing; use --disassembly')
    if not 1<=args.jobs<=64: parser.error('--jobs must be 1..64')
    if not shutil.which('docker'): parser.error('Install Docker with a running daemon first')
    with tempfile.TemporaryDirectory(prefix='smk-docker-source-') as directory:
        stage(Path(__file__).resolve().parents[2],args.disassembly.resolve(),Path(directory))
        ares_image=args.image+'-ares'
        subprocess.run(['docker','build','--build-arg',f'JOBS={args.jobs}',
                        '-t',ares_image,str(Path(directory)/'ares')],check=True)
        subprocess.run(['docker','build','--build-arg',f'JOBS={args.jobs}',
                        '--build-arg',f'ARES_IMAGE={ares_image}',
                        '-t',args.image,directory],check=True)
    args.output.mkdir(parents=True,exist_ok=True)
    command=['docker','run','--rm','--network','none']
    if hasattr(os,'getuid'): command+=['--user',f'{os.getuid()}:{os.getgid()}']
    command+=['--mount',f'type=bind,source={args.rom.resolve()},target=/input/game.sfc,readonly',
              '--mount',f'type=bind,source={args.output.resolve()},target=/output',args.image]
    subprocess.run(command,check=True)
    print(f'Outputs: {args.output.resolve()}')


if __name__=='__main__': main()
