# Super Mario Kart Link

Two through eight independent Ares processes simulate the same Grand Prix or balloon battle. Each
connected player contributes one controller and displays their own kart, camera, coins,
and inventory. In Grand Prix, native CPU driving fills unoccupied grid slots. Battle includes
only the connected players, each with three balloons; the last survivor wins. Player 1 owns the native mode/course menus and pause control. Characters
are reserved before boot; duplicate characters are rejected.

This is an optional frontend and experimental ROM adapter. The regular Ares desktop
frontend remains available for the byte-identical stock ROM. Build the linked ROM using
the companion `Super-Mario-Kart-Disassembly` repository; stock SMK does not acquire
eight human racers just by running this frontend.

## Docker build: supply your ROM

Both repositories include independent **root Dockerfiles**. Run `docker build -t
smk-link-rom .` from the disassembly checkout and `docker build -t smk-link-ares .`
from the Ares checkout. See [their build/run commands](docker/README.md), including
ROM/output mounts and Linux desktop forwarding. The combined build below remains
available for exporting both cartridges and executables in one command.


Install Docker with a running daemon, Git, and Python 3.10+. Keep both repositories
beside each other on `feature/snes-link-8p`, then from the Ares checkout run:

```sh
python3 tools/link-lab/build_docker.py '/path/to/Super Mario Kart (USA).sfc' --output ./smk-link-build
```

Use `--disassembly /path/to/Super-Mario-Kart-Disassembly` if the companion checkout
is elsewhere. Docker builds Asar 1.71, the Ares desktop frontend and link worker,
rebuilds and byte-compares the stock cartridge, and builds the linked cartridge.
It exports `stock-smk.sfc`, `linked-smk.sfc`, `SHA256.json`, and a `link/` launcher
bundle, including `link/bin/ares-link-worker` and `link/desktop/bin/ares`.
No host compiler, Asar, or manual asset extraction is needed. Git fetches the pinned
public Asar source through the host's configured trust; Debian packages and the
base image require Internet access during image construction.

The ROM is mounted read-only **after** the image is built. The cartridge build runs
without networking and as the host user on Linux. Neither the commercial ROM nor
extracted commercial assets enter image layers or the staged source context. Do not
publish generated cartridges. The supported dump is USA, 524288 bytes (a 512-byte
copier header is also accepted); other regions/revisions fail validation.

Exported executables target the container's Linux platform, validated here on x86-64
Debian 13. To play on a Linux desktop, provide SDL3 and the corresponding GTK3/audio/
OpenGL runtime libraries; the image contains these dependencies. Docker Desktop can
build the files on other hosts, but the exported Linux executables are not native
Windows/macOS apps. GUI/device forwarding into a container is not configured.

## Native development build

Both repositories use branch `feature/snes-link-8p`. On the prepared cloud machine:

```sh
. /workspace/toolchain/activate.sh
cmake -S /workspace/ares -B /workspace/build/ares-stock -DARES_BUILD_LINK_LAB=ON
cmake --build /workspace/build/ares-stock -j 4
python3 /workspace/Super-Mario-Kart-Disassembly/tools/build_stock.py \
  '/path/to/Super Mario Kart (USA).sfc' --output /workspace/build/stock-smk.sfc
python3 /workspace/Super-Mario-Kart-Disassembly/tools/build_linked.py \
  /workspace/build/stock-smk.sfc --output /workspace/build/linked-smk.sfc
```

Outside this environment, follow Ares's normal build prerequisites, enable the `sfc`
core and `ARES_BUILD_LINK_LAB`, and install SDL3 development files. The worker and its
staged `Database` directory must remain together. The Python launcher needs Python 3.10
or newer and only the standard library. Asar **1.71** is required for the stock rebuild;
pass its path with `--asar` to both ROM tools. ROMs, assets, DSP firmware, SRAM, and
generated snapshots are not distributed.

## Play on one machine

From the Docker output directory:

```sh
python3 link/play.py local --rom linked-smk.sfc --players 4 --mode battle --course 0
```

From a source checkout, use `python3 tools/link-lab/play.py local` and your ROM path;
pass `--worker PATH` if needed. This starts one synchronized canonical core and one
background renderer per player, tiles the windows, and uses **no TCP ports**.
One keyboard belongs to player 1 by default; other players receive separate SDL
gamepads in connection order. `--keyboard-player 2` moves keyboard control to player 2;
`--keyboard-player 0` assigns all players separate gamepads. Use
`--characters mario,luigi,bowser,peach` to reserve exactly one unique character per
player; otherwise the first N characters in the list below are used. Plug gamepads
in before launch; removal of an assigned device stops the session. Closing any
window or pressing Escape stops and reaps all cores/renderers. Only one canonical
audio mix is played. Budget roughly two CPU cores per player; eight local clients
are demanding and may run slower than real time.

## Play on a trusted LAN

Each player needs exactly the same linked ROM and worker binary. On player 1's machine,
use the LAN interface's address (or `0.0.0.0`) to accept other players:

```sh
python3 tools/link-lab/play.py host --rom /workspace/build/linked-smk.sfc \
  --worker /workspace/build/ares-stock/tools/link-lab/ares-link-worker \
  --listen 0.0.0.0 --players 4 --character mario
```

Choose `--players 2` through `--players 8` on the host (default: 8). On each other
machine, choose a different player number **2 through the host’s count** and character:

```sh
python3 tools/link-lab/play.py join --rom /path/to/linked-smk.sfc \
  --worker /path/to/ares-link-worker --host PLAYER_1_LAN_ADDRESS \
  --player 2 --character luigi
```

Characters: `mario`, `luigi`, `bowser`, `peach`, `donkey-kong-jr`, `koopa`, `toad`,
`yoshi`. The lobby starts automatically when the selected number of slots is occupied. A
rejected duplicate/profile/slot reservation does not drop accepted players; retry with a
free choice. Disconnected reservations are released before start. The lobby timeout is
five minutes after the most recent successful join. Allow inbound TCP port **27888** on
the host, or choose the same `--port` on every client. The default listener is loopback
for local instances.

Choose `--mode battle` on the host or local launcher for balloon battle; the default
is `--mode grand-prix`. For battle, `--course 0..3` selects Battle Course 1..4; omit
it to choose through the native course menu. Guests inherit the host's mode/course.
Balloon colors follow player slots, independently of character choice:
blue, red, green, yellow, purple, cyan, orange, pink (players 1 through 8).
These DS-style colors retain the native balloon shapes, white highlights and dark
shading. The linked Ares worker provides a separate OBJ color lookup for balloon
tiles, preserving shared kart/item palettes and native sprite priority/color math.
This palette extension is emulator-backed, like the link device itself.

Each connected player starts with three balloons. Eliminated karts leave the world;
their clients spectate a living racer. Window titles identify elimination, spectator
target, and the winning player (or draw). Only the host advances results/rematches.
The native result screen retains its two-viewport layout and shows the winning
character; it is not an eight-player scoreboard.

After boot, player 1 presses Enter at the title and Z to confirm LINK, the native
options, reserved characters, and course/cup. In battle the host confirms both native
character panels; reservations remain locked. In Grand Prix all players remain in the
cup even when finishing below fourth place. Results wait for all connected humans to
finish. Remaining CPU racers are placed in their current native order, and player 1
advances the group through results and into another cup. Host option `--course 0..19`
overrides the native course for each race; omit it for the normal five-course cup
sequence. This option is primarily useful for course testing; the numbers are native ROM
IDs, not cup positions.

| Keyboard | SNES action |
| --- | --- |
| Arrows | D-pad |
| Z | B: accelerate / confirm |
| X | A: item |
| A / S | Y / X |
| Q / W | L / R: hop / slide |
| Enter | Start: title / host pause |
| Backspace | Select |
| Escape or close window | Disconnect and stop the session |

SDL gamepads use the corresponding face buttons, shoulders, Start/Back, D-pad, and left
stick. Network clients default to the first connected gamepad with hotplug. Use
`--gamepad 0..7` and `--no-keyboard` to assign a particular device, or `--gamepad -1`
to disable gamepads. Explicitly assigned devices stop the client if removed. The
local launcher assigns devices exclusively and keeps its keyboard input isolated. Video uses
integer-source pixels with nearest-neighbor scaling and letterboxing. Audio is the
canonical game's stereo mix, shared by all peers; it is not independently remixed around
each local kart. Audio-device failure permits silent play.

## Synchronization contract

`session.py` separates game-independent transport from the ROM-specific worker adapter.
The coordinator and `play.py` support every count from 2 through 8. The host selects the
count; only those peers are required to start or finish. Before boot it verifies
protocol, ROM bytes, the complete worker executable, fixed emulation settings, and
unique slot/character claims. The high-level host launcher generates a private local
owner credential for slot 0 and pins the profile before accepting guests. Only slot 0
supplies session settings. Fresh temporary ROM directories prevent old SRAM from
changing boot.

At every frame, all peers send their held controller input and SHA-256 of the
**preceding synchronized emulated state**, including the link device's input, frame,
course, roster, and scratch RAM. Only a complete matching barrier releases the next
eight-input bundle. The final state also requires agreement. The ROM strobes an atomic
eight-pad latch at the start of each game update; physics and inventories use that
frozen bundle even when an update spans multiple video frames. A mismatch, invalid
packet, disconnect, or 15-second frame timeout stops the session. There is no
prediction, rollback, late joining, or mid-race reconnection. A slow peer stalls the
group; per-frame barriers add network latency. Rendering and hashing are deliberately
more expensive than ordinary emulation.

The canonical simulation always uses the host's native view. A private render pass
exchanges the local kart's semantic data into the native foreground object, draws
through the buffered projection/OAM pipeline, and restores the complete core using
Ares's run-ahead serializer. The ROM's presentation gate excludes world physics, race
progression, and inventory transitions. The private pass suppresses output audio
**before** filters/resampling, so it cannot advance the canonical audio stream. Two complete native drawing passes warm up projection and graphics caches using
Ares's run-ahead mode to skip intermediate rasterization. The final pass and buffer
upload are rasterized and compared against fully rasterized reference drawing.
A crowded battle pass can span several video frames; completion is acknowledged by
the ROM rather than assuming a fixed number of frames. Each racer also has an isolated
native Lakitu interpreter, timer, and rescue state; simultaneous rescues cannot strand
off-camera racers. Frame capture uses a blocking completion signal rather than spinning
while the video thread finishes. Local view selection never enters shared simulation.

Interactive clients run a second, local renderer process. The canonical worker exports
its already synchronized snapshot; the renderer runs the private passes in the
background and returns an image labelled with its source frame and race generation.
Inventory icons and their blink phases are frozen from the source snapshot. Only one
render job is pending at a time, so intermediate images are dropped when the
renderer is busy. Menus, host pause screens, and completed-race results use canonical
video; old-course, pre-pause, future, and out-of-order images are rejected. This keeps private rendering outside the network frame barrier. Input
and audio follow the canonical simulation at the native NTSC refresh rate (about
60.098 Hz); local video can update less often under load. Budget two CPU cores per
interactive client. On this cloud machine, a 120-frame measurement reached 77.8
canonical frames/second with asynchronous local rendering; this is not a performance
guarantee for other machines. Closing a peer or terminating the host stops the session
and reaps both workers. The synchronous private view remains a diagnostic reference.

This policy detects divergence and refuses further input bundles; it is not a proof of
determinism for every possible trace or CPU architecture. Use matching builds. Dynamic
libraries and different platforms have not been qualified. TCP messages are bounded,
validated newline-delimited JSON with deadlines. This is a trusted-LAN protocol without
TLS, accounts, or cheating protection; the owner credential reserves host control but is
not public-network authentication.

## ROM ABI

Mirrored in banks `$00–$3F,$80–$BF`; only the input-strobe register accepts writes:

| Address | Meaning |
| --- | --- |
| `$21C0–$21CF` | Eight live little-endian pad words; standard SNES bits, low nibble zero |
| `$21D0–$21D3` | ASCII `LNK1` |
| `$21D4` | Capacity: 8 |
| `$21D5` | Private presentation pass flag; zero in the canonical world |
| `$21D6` | Host course ID, or 255 for native cup selection |
| `$21D7` | Connected human count: 2–8 |
| `$21D8–$21DB` | Frame number, little endian |
| `$21DC` | Write any byte to atomically latch all eight live pads |
| `$21DD` | Host session mode: 0 Grand Prix, 1 battle |
| `$21E0–$21EF` | Frozen pad words from the most recent strobe |
| `$21F0–$21F7` | Unique character IDs 0–7, in player order |

The linked cartridge also maps 8 KiB of serialized scratch RAM at
`$00–$0F,$80–$8F:$3000–$3FFF` and `$5000–$5FFF`. The second window holds
24 battle balloon objects and eight battle item/projectile objects, away from the
eight racer records. Battle balloon counts, winner and initialization state live
in `$3C10–$3CD1`; native rank/draw lists exclude eliminated racers. The latch also appears at `$33A0–$33AF`; `$33B2` retains
the configured human count. DSP1's `$6000–$7FFF` region is preserved. Native controller
2 cannot accept guest menu input; host confirmation is routed to its reserved battle
character panel when needed. All eight race
controllers are read through the link device. This ABI has no licensed physical
peripheral implementation. F-Zero requires a separate ROM adapter; the transport does
not itself convert AI racers or provide additional cameras.

## Validation

Protocol `ares-link-lab/2` and the expanded RAM state format are incompatible with
older workers and raw snapshots. Regenerate diagnostic checkpoints after rebuilding.

The [validation record](VALIDATION.md) describes coverage, reference traces, and limits.

Set paths once, then run the real emulator checks:

```sh
worker=/workspace/build/ares-stock/tools/link-lab/ares-link-worker
rom=/workspace/build/linked-smk.sfc
python3 tools/link-lab/test_gameplay.py --worker "$worker" --rom "$rom" \
  --checkpoint /workspace/build/current-race.state
python3 tools/link-lab/test_battle.py --worker "$worker" --rom "$rom" \
  --checkpoint /workspace/build/battle-final.state
python3 tools/link-lab/test_race_cycle.py --worker "$worker" --rom "$rom" \
  --checkpoint /workspace/build/current-race.state
python3 tools/link-lab/test_race_cycle.py --worker "$worker" --rom "$rom" --players 2
python3 tools/link-lab/test_configuration.py --worker "$worker" --rom "$rom"
python3 tools/link-lab/test_player_counts.py --worker "$worker" --rom "$rom"
python3 tools/link-lab/test_recovery.py --worker "$worker" --rom "$rom" \
  --checkpoint /workspace/build/current-race.state
python3 tools/link-lab/test_presentation.py --worker "$worker" --rom "$rom" \
  --checkpoint /workspace/build/current-race.state --output /workspace/build/views
python3 tools/link-lab/test_async_view.py --worker "$worker" --rom "$rom" \
  --checkpoint /workspace/build/current-race.state
python3 tools/link-lab/test_session.py --worker "$worker" --rom "$rom" --frames 6000 --async-view
```

Gameplay checks exercise independent motion, all nine items for all eight racers, real
item-box/coin pickup outside the host camera, status timer progression, Boo theft across
all 56 player pairs, lightning against seven opponents, and deterministic replay.
Race-cycle checks seed the final lap, use real movement/finish crossings, verify eight
unique ranks, complete all five races and awards, and start another cup. Player-count
checks cover 2–8 humans, CPU movement/item use, and results without waiting for vacant
slots. Recovery checks move all eight racers beyond course bounds and require native
rescues, individual coin penalties, and resumed control. Configuration checks boot all
twenty course IDs with rotated rosters and verify host-only menus/pause. Presentation
checks compare canonical state and audio with rendering off and different cameras,
including ready, pending, and stolen inventory blink phases. Asynchronous view checks
compare each returned image against the synchronous rendering of its exact source frame,
verify unchanged canonical audio/state, native refresh pacing, stale-image rejection, and shared host UI at pause/results
boundaries.
Protocol tests exercise conflicts, authority, invalid input/frame/packet sizes, timeout,
EOF, and desync, followed by independent workers agreeing at every barrier of moving
race traces. Pass `--players N` to test_session.py to check any supported count; 3300
frames include native menu navigation and a moving race.

The independent asset-free `link_input_probe.asm` in the companion repository can be
assembled with Asar and checked using `test_probe.py --worker PATH --rom PROBE_ROM`; it
executes real 65816 live/latched reads for eleven eight-pad patterns and checks that
latches survive changes to live inputs until the next ROM strobe. For an X11 SDL smoke
test, install `requirements-test.txt`, start Xvfb if needed, then run:

```sh
DISPLAY=:99 SDL_AUDIODRIVER=dummy python3 tools/link-lab/test_interactive.py \
  --worker "$worker" --rom "$rom" --output /workspace/build/interactive.ppm
```

The interactive test checks ROM video/aspect, nine keyboard mappings, releases, and
quit. `test_launcher.py --worker "$worker" --rom "$rom" --players N` additionally starts
the real host/join launchers and N SDL windows, then verifies coordinated disconnect and
cleanup of canonical and render processes (requires the same X11 display). Add
`--terminate-host` to exercise SIGTERM shutdown instead of a guest pressing Escape. Physical gamepads, eight human LAN play,
Internet latency, cross-platform builds, and real SNES hardware have not been tested.
Native sprite/CPU limits and rare game situations still need human playtesting;
automated coverage must not be described as Nintendo-level release qualification. Worker
`@peek`, `@word`, `@save`, and `@load` are local diagnostic commands, not a network
save-state API; raw diagnostic snapshots require the matching ROM/build and should be
regenerated after changes. Keep generated outputs outside the repositories.

Battle checks boot every supported count and all four arenas (2P/8P on each), verify
unique rosters, independent movement, three native balloon losses, all native battle
item activations, and host/guest victory plus rematch. Use `test_async_view.py --battle`
with the battle checkpoint for spectator/pause/results boundaries; `test_session.py
--mode battle --players N --frames 3300 --async-view` checks moving battle transport.
`test_local.py --worker PATH --rom ROM --players 2` (or 8) checks actual local windows,
exclusive keyboard input, frame agreement and process cleanup on X11.

Additional battle checks:

```sh
python3 tools/link-lab/test_battle_combat.py --worker "$worker" --rom "$rom" \
  --checkpoint /workspace/build/battle-final.state
python3 tools/link-lab/test_battle_colors.py --worker "$worker" --rom "$rom" \
  --checkpoint /workspace/build/battle-final.state --output /workspace/build/battle-colors
python3 tools/link-lab/test_battle_tie.py --worker "$worker" --rom "$rom" --players 2
python3 tools/link-lab/test_battle_tie.py --worker "$worker" --rom "$rom" \
  --checkpoint /workspace/build/battle-final.state
DISPLAY=:99 SDL_AUDIODRIVER=dummy python3 tools/link-lab/test_local_battle.py \
  --worker "$worker" --rom "$rom" --players 8
```

The full local-window trace uses scripted controllers to traverse menus into battle;
the shorter `test_local.py` check injects actual X11 keyboard events and verifies that
other players receive none of them. Physical gamepads still require local testing.
SFC save-state format `v147-link1` rejects older states; rebuild matching ROM/worker
pairs and regenerate diagnostic checkpoints after updating this branch.
