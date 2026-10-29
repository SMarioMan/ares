# Validation record

Both repositories use `feature/snes-link-8p`. Generated ROMs, extracted assets,
firmware, screenshots, executables and diagnostic states remain outside Git.
Reproduction commands are in [README.md](README.md).

## Build baseline

The desktop frontend and optional linked worker build with GCC 14, CMake/Ninja and
SDL3. Asar 1.71 is pinned to commit
`217a93ffd44a44f196a06cff9b96ddb7dc892b8b`. The stock builder extracts **132** assets
from the supplied USA ROM, including 46 verified slices omitted by the framework's
original extraction table. It compares **all 524,288 output bytes** before publishing.

Stock SHA-256: `2ada8919688087be60a6a48cace8f877add60c45d2e5d09e2442faa55be62a49`.
Linked cartridge SHA-256: `5d5cfa055a35670c74676d4e5db9f918571e50fc4302bf575a21e1619127f9ba`.
The linked cartridge is 1 MiB and the builder verifies 72 original instruction
operands/opcodes before applying the separate adapter.

Each repository has a root Dockerfile. The disassembly image builds from a source
context that excludes ROMs and extracted `.bin`, `.brr` and `.lz5` files; runtime
extraction recreates them from the commercial ROM. The ROM mount is read-only, the
runtime network is disabled, and output is written as the host UID. The Ares image
builds both frontends and provides the linked launcher. Numeric UIDs without passwd
entries are supported by the corrected POSIX user-directory fallback. Standalone
and combined Docker checks reproduce both native ROMs byte for byte. An invalid ROM
is rejected without replacing existing output. The root Ares runtime, with an
unregistered numeric UID, passes eight protocol tests and a two-client battle with
2501 matching barriers; two tiled SDL windows also run with no network and bounded
temporary storage. The exported launcher help runs on the host. Evidence is recorded
in the logs below.

Protocol `ares-link-lab/2`, 8 KiB of device RAM and SFC serializer `v147-link1` require
matching builds and regenerated diagnostic checkpoints. The serializer version was
changed because accurate-PPU OBJ metadata was added; older save states are rejected.
Workers from separately compiled builds need not have the same executable hash.
Distribute one matching bundle to every peer.

## Native battle gameplay

- Every count **2–8** boots with exactly N humans, unique reserved characters, three
  balloons per human, and no CPU vacancies. Every connected player independently
  accelerates and moves. All four arenas boot at both 2P and 8P; rosters rotate with
  arena choice. HDMA descriptors remain intact with the crowded sprite scene.
- Three damage events exercise the native balloon-pop scripts and reduce each
  player's balloons **3→2→1→0**. Eliminated racers leave the active world. These
  damage tests seed the native damage flag; they do not simulate every cause of damage.
- All seven native battle item types activate for every human. Every human also
  collects a real arena item box outside the host camera.
- Actual green and red shells launch, travel and hit the intended victim across
  **all 56 ordered player pairs for each shell type**. Only that victim loses a balloon;
  the thrower and other six players retain theirs. Red-shell target pointers identify
  the nearest living opponent. Tests arrange item inventories and separated kart
  positions, then exercise the real A-button transition, projectile physics and contact.
- Both host and guest victories complete native results and rematch at 2P and 8P,
  restoring the roster and three balloons each. Simultaneous final losses produce
  a draw and also rematch at both counts. Native result animation may temporarily
  use CPU flags for its noninteractive karts; eliminated humans cannot drive them.
- All eight local views show their own kart and the assigned balloon color:
  **blue, red, green, yellow, purple, cyan, orange, pink**. Real balloon-object
  palettes and rasterized color pixels are checked; drawing preserves world/link
  memory and canonical audio. The tint is independent of the selected character.

## Presentation, synchronization and local instances

Battle presentation checks 120 canonical frames and 95,840 audio samples with views
disabled and local cameras 1/8. Fast drawing is pixel-identical to fully rasterized
reference drawing. Local inventory and pending/stolen blink phases retain source
snapshot values. Three **completed drawing passes**, rather than three video frames,
warm up the native projection/graphics buffers before final presentation.

Asynchronous battle images match synchronous pixels at their exact source frame.
Canonical state/audio, NTSC refresh pacing and stale/future-image rejection pass.
Eliminated clients spectate living racers, including after host elimination. Changing
spectator target invalidates old images. Host pause/resume and round completion restore
shared native UI and invalidate outstanding private images.

Eight protocol tests cover owner/profile authority, duplicate/invalid reservations,
battle settings, malformed packets/input/frame numbers, disconnect, timeout and
divergence. Failed barriers stop every peer. Independent moving battle traces with
asynchronous views passed every barrier, including the final state:

| Players | Video frames | Matching barriers | Final canonical SHA-256 |
| --- | --- | --- | --- |
| 2 | 3300 | 3301 | `0b99f40dee14cf06a51f664b93a95c415a4a07ea7b2e2d3f92cfae0adffcb2b7` |
| 8 | 3300 | 3301 | `f1403074e8a82824cf2c003e29bd617ec9379b008f470c62aba8267b6b3cacd5` |

Actual X11/SDL local tests start 2 and 8 tiled windows with **no TCP coordinator**.
Keyboard input reaches only its assigned player, all 121 barriers match, and all
4/16 canonical/render workers are reaped. Longer local runs at both counts traverse
native menus into moving battle gameplay: **2501 matching barriers**, private images
for every player, and closed windows after shutdown. These use scripted pads for the
full match trace; the separate keyboard test injects actual X11 key events.

## Grand Prix regression

Current-build checks cover independent eight-human movement, all nine item types,
star/status behavior, Boo theft across 56 player pairs, lightning, real item-box/coin
pickup and deterministic save/replay. Presentation again checks 120 canonical frames,
95,842 audio samples, separate cameras/HUDs, fast/full pixels and frozen blink phases.
Asynchronous source pixels, state/audio, pause/resume and results boundaries pass.
Both 8P and 2P with six CPUs complete five seeded final-lap races, unique standings,
awards/results and a new cup with clean inventories. They do not drive five naturally
completed full-length races.

Prior Grand Prix qualification additionally covered every count 2–8, CPU vacancies
and inventories, all twenty courses with rotated rosters/host authority, simultaneous
Lakitu rescues, and every count's asynchronous network trace (2–7: 3300 frames;
8: 6000). Their older endpoint hashes are not references for the expanded state format.

## Evidence and limits

Logs and generated artifacts are under `/workspace/toolchain` and `/workspace/build`.
Current checks: `stock-final.log`, `worker-release.log`, `probe-final.log`,
`battle-final.log`, `combat-final.log`, `colors-final.log`, `tie-final-2.log`,
`tie-final-8.log`, `battle-presentation-final.log`, `battle-async-final.log`,
`session-battle-2.log`, `session-battle-8.log`, `local-2-final.log`, `local-8-final.log`,
`local-battle-2.log`, `local-battle-8.log`, `gp-final.log`, `gp-presentation-final.log`,
`gp-async-final.log`, `gp-cup-2-final.log`, `gp-cup-8-final.log`, `docker-rom-final.log`,
`docker-rom-run.log`, `docker-ares-final.log`, `docker-build-final.log`,
`docker-battle-final.log`, `docker-local-final.log`, and `docker-invalid-final.log`.
Only completed PASS/exit-zero checks count as validation.

This is an experimental linked adapter. Physical gamepads, eight humans on separate
LAN machines, Internet latency, other CPU/OS/library combinations and rare native
game situations require human qualification. Matching builds and a trusted LAN are
required. The protocol detects divergence and stops; it does not repair it. Local
video can drop intermediate images under load, and eight instances demand substantial
CPU resources. Native sprite limits still cause ordinary crowded-scene culling.
Audio is the shared host mix; results retain the native two-viewport layout, with
window titles identifying the winner/draw. The eight-color palette extension and link
RAM device are emulator-backed. No F-Zero adapter or licensed-device/real-SNES backend
is implemented. Automated coverage is not Nintendo-level release qualification.
