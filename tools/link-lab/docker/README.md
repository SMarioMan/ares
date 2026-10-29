# Repository Docker builds

Each repository has its own root `Dockerfile`. Both use branch `feature/snes-link-8p`.
Clone the two repositories beside each other, then build from their respective roots:

```sh
docker build -t smk-link-rom ../Super-Mario-Kart-Disassembly
docker build -t smk-link-ares .
```

The disassembly image accepts the commercial ROM and exports verified stock and
linked cartridges. Its [instructions](../../../../Super-Mario-Kart-Disassembly/docs/docker.md)
show the read-only ROM mount and writable output mount. It requires no emulator.

The Ares image contains the SNES desktop emulator, the linked worker, and Python
launchers. It requires no companion source checkout to build. To inspect its commands:

```sh
docker run --rm smk-link-ares --help
docker run --rm smk-link-ares local --help
```

For an X11 Linux desktop, run a local battle with the linked ROM from the other
image's output directory. The X authority file must exist and authorize your display:

```sh
docker run --rm --network none --user "$(id -u):$(id -g)" \
  --tmpfs /tmp:rw,nosuid,nodev,size=256m,mode=1777 \
  -e DISPLAY -e SDL_VIDEODRIVER=x11 -e XAUTHORITY=/tmp/xauthority -e SDL_AUDIODRIVER=dummy \
  --mount type=bind,source=/tmp/.X11-unix,target=/tmp/.X11-unix,readonly \
  --mount "type=bind,source=${XAUTHORITY:-$HOME/.Xauthority},target=/tmp/xauthority,readonly" \
  --mount "type=bind,source=$PWD/../Super-Mario-Kart-Disassembly/output,target=/input,readonly" \
  smk-link-ares local --rom /input/linked-smk.sfc --players 2 --mode battle --course 0
```

This example deliberately uses silent audio for a portable display smoke test.
Use your normal SDL audio backend/socket mounts for sound. Give SDL access to each
physical controller device with Docker's `--device /dev/input/eventN` as appropriate
for your desktop. Player 1 uses the keyboard; the remaining players use separate
SDL gamepads. See the main [README](../README.md) for assignments and controls.
Eight simultaneous clients need substantial CPU resources. Physical controller and
non-X11 host configurations require local qualification.

For LAN play, use the `host`/`join` commands from the main README. Publish TCP 27888
with `-p 27888:27888` on the host container and use `host --listen 0.0.0.0`.
Alternatively, export `/opt/link` from a stopped Ares container and run the bundle
on a compatible Linux desktop. The desktop frontend is `/opt/link/desktop/bin/ares`;
the image's default command launches the linked frontend. Stock ROMs use the desktop
frontend; linked ROMs use the linked worker.

The combined `python3 tools/link-lab/build_docker.py USA_ROM --output DIR` remains
available. It stages both checkouts and pinned Asar, builds both executables and
cartridges, and exports a self-contained Linux launcher bundle in one invocation.
Its Dockerfile is versioned at `tools/link-lab/docker/Dockerfile`.
