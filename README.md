# ExamScan

A Raspberry Pi-based document scanner that captures high-resolution images of exam papers using a
fixed overhead camera and advances pages automatically. Each scanning run is saved as a folder of
JPEGs, downloadable as a ZIP.

The camera watches the bed throughout, and a hand appearing at any point stops the mechanism
where it stands and resumes once the area is clear — see
[Obstruction detection](#obstruction-detection).

A page turn has sixteen phases, driving two clamps, the arm, the fan and both steppers. The first
nine phases are shared by both turn modes:

1. **Drop the small clamp** onto the stack and hold it (`page_clamp_small`)
2. **Fan to `fan.duty_pct`**, then wait `fan.spinup_seconds` for it to reach speed
3. **Drop the arm** onto the page (`page_drop` to its `down_angle`), no hold
4. **Drop the big clamp** and hold it (`page_clamp_big`)
5. **Lift the small clamp** clear
6. **Turn motor 1** out `motor.page_turn_degrees`, staying energised
7. **Pre-position motor 2** by `motor2.preposition_degrees`, then wait `motor_pause`
8. **Lift the arm** clear
9. **Fan off** — the page is captive now

With `workflow.turn_sequence = "motor2_only"`, the remaining phases are:

10. **Return motor 1 exactly home**, then wait `motor_pause`
11. **Drop the small clamp** again and hold
12. **Lift the big clamp** clear
13. **Finish motor 2's first leg** using the exact step remainder
14. **Continue motor 2 alone** by `motor2.shared_degrees`
15. **Return motor 2** home
16. **Lift the small clamp** clear

The factory default is `motor2_only`. Motor 1 stays energised from phase 6 until its exact return
in phase 10. The big clamp remains engaged while motor 2 pre-positions and motor 1 returns; the
small clamp then grips before the big clamp releases.

The deployed rig currently uses `workflow.turn_sequence = "shared"`. Its remaining phases are:

10. **Drop the small clamp** again and hold
11. **Lift the big clamp** clear
12. **Finish motor 2's first leg** using the exact step remainder
13. **Turn both motors** through their configured `shared_degrees`
14. **Return motor 2** home
15. **Return motor 1 through its shared leg**, then lift the small clamp
16. **Complete motor 1's return**

In both modes, motor 2 pre-positions while the arm remains down and the fan remains on. The fan
switches off only after the arm has risen.

The demo's **Scan Last Page** action uses a separate last-page variant. It captures the page but
leaves the run open, keeps the big clamp at its hold angle through every configured forward motor
leg, and raises that clamp before the motors return. The hold setpoint is reasserted before the
postponed movement so the servo's safety timer does not release the clamp early. Ordinary page
turns and auto-scans keep the sequences above.

Every move is split by **step count, not degrees** — converting part-degree moves and rounding twice
can land a step away from the matching return, leaving a wheel off by a step on every page.

In `motor2_only` mode, motor 1 returns exactly to its starting step position and motor 2 retains
its configured `return_short_degrees` correction. In `shared` mode, both motors retain that
correction. Set `return_short_degrees = 0` for exact returns in the shared sequence as well.

Clamps seat at `contact_angle`, then ease back to `hold_angle` and stay powered there. Holding hard
against a stop the servo cannot reach leaves it stalled — buzzing, warming up and dragging the
supply down — so the few degrees of back-off keep the grip without the fight.

Each boundary has its own configurable pause: `clamp_down_pause`, `servo_down_pause`,
`clamp_up_pause`, `stepper_pause`, `servo_up_pause`.

## Architecture

The Pi runs **headless** and controls hardware only. It exposes a REST API and an MJPEG stream, and
serves no user interface — hitting `/` returns a small JSON service descriptor, not a page.

The GUI is a **separate client**, hosted elsewhere (e.g. a laptop on the same network). It displays
the stream and drives capture and page turns over the API. See [API](#api) for the endpoints and
[GUI integration](#gui-integration) for the two things that aren't obvious from the endpoint table.

## Hardware

| Component | Details |
|---|---|
| Camera | Raspberry Pi Camera Module 3 (IMX708) |
| Page drop / clamps | Servos |
| Fan | Waveshare FAN-4020-PWM-5V, 25 kHz hardware PWM |
| Stepper (page wheel) | NEMA 17 SM24240 with MKS TMC2209 V2.0, driven as step/dir |
| Stepper 2 | DRV8825, full step — drives phases 9 and 13 to 15 of the default page turn |

### Wiring

Pins are defined in `config.toml` and can be changed there; a pin change needs a restart.

| Signal | GPIO (BCM) |
|---|---|
| Servo — page drop | 22 |
| Servo — page clamp big / small | 19 / 27 |
| Stepper STEP / DIR / ENABLE | 21 / 20 / 16 |
| Stepper DIAG / UART TX / RX | 26 / 14 / 15 (wired, unused — see below) |
| Stepper 2 STEP / DIR / ENABLE | 23 / 24 / 25 |
| Fan PWM / tach | 18 / 17 |

On the fan, the **yellow** lead is PWM control — not blue, which is what the usual 4-pin PC fan
colour convention would suggest. Red is +5V, black is ground, and blue is the tach output. Driving
the wrong lead leaves the fan at full speed, since it reads an unconnected control line as a
request for 100%.

Camera is mounted approximately 43 cm above the scanning surface with a fixed lens position.

## Project Structure

```
ExamScan/
├── hardware/
│   ├── camera.py       # Camera streaming and capture
│   ├── fan.py          # PWM fan and tachometer (raw pigpio hardware PWM)
│   ├── vision.py       # hand detection and the page-turn gate
│   ├── motor.py        # Stepper motor (step/dir)
│   └── servo.py        # Servo control (page drop, clamps)
├── tests/              # Test suite (runs without hardware)
├── runs/               # Saved runs (auto-created)
├── config.py           # Config schema, validation, hot reload
├── config.toml         # Active configuration
├── runs.py             # Run lifecycle, manifests, archives
├── server.py           # HTTP routing, run workflow, server loop
├── fakes.py            # Stub hardware for tests and dev mode
├── demo.html           # Demo page, served only by examscan-demo
├── main.py             # Entry point — real hardware, headless
├── devserver.py        # Entry point — fake hardware, headless
└── demoserver.py       # Entry point — real hardware, with demo page
```

`server.py` holds everything hardware-agnostic; `hardware/factory.py` assembles the real stack. The
entry points differ only in which hardware they build and whether they override `/`.

## Configuration

All tunable values live in `config.toml` — GPIO pins, camera resolution and timings, motor speeds,
servo angles, and workflow pauses. It is validated on load, and unknown or malformed sections are
rejected outright.

You can also read and replace it over HTTP (see the API section). On upload the previous file is
backed up alongside it. Most changes apply immediately; changing a **GPIO pin** needs a restart,
which the app reports via `config_restart_required` in `/api/health`.

`workflow.default_pages` (default `7`) sets how many pages an auto-scan captures when the client
doesn't specify a count. It applies live — no restart needed.

### Page-turn tuning

| Field | Controls |
|---|---|
| `workflow.turn_sequence` | `motor2_only` for the default early return, or `shared` to restore parallel movement |
| `motor.page_turn_degrees` | Initial outward movement for each motor |
| `motor2.preposition_degrees` | Portion of motor 2's first leg moved before motor 1 returns |
| `motor.shared_degrees` | Motor 1's parallel leg in `shared` rollback mode |
| `motor2.shared_degrees` | Motor 2's continuation; performed alone by default or in parallel in `shared` mode |
| `motor.return_short_degrees` | How far the final return stops short of home; 0 for an exact round trip |
| `motor.default_clockwise` | Direction of the outward turn; returns are the opposite |
| `motor2.*` | Second stepper on GPIO 23/24/25, full step. Same page-turn keys as `motor` |
| `servos.page_drop.down_angle` / `up_angle` | Where the arm rests down and clear |
| `servos.page_clamp_*.contact_angle` / `hold_angle` | Where a clamp seats, and where it holds |
| `servos.page_clamp_*.use_hold` | False drops the clamp and lets it go limp instead of holding |
| `servos.*.max_hold_seconds` | Cut-off for a hold, so a servo cannot stay stalled |
| `fan.duty_pct` / `fan.spinup_seconds` | Duty during the page turn, and the wait for it to reach speed |
| `fan.min_start_duty_pct` | Floor applied to any non-zero duty so the fan actually spins up |
| `fan.tach_pulses_per_rev` | Tach pulses per revolution, used to convert edges to RPM |
| `workflow.*_pause` | Settling time at each phase boundary |
| `workflow.small_clamp_hold_seconds` | Dwell on the small clamp's first drop, before the fan starts |
| `camera.lores_width` / `lores_height` | Size of the second camera stream the obstruction check reads |
| `camera.exposure_mode` | `short` reduces motion blur; `normal` is the rollback setting |
| `obstruction.enabled` | False skips the check entirely and never loads the model |
| `obstruction.mode` | `full` verifies palm candidates with landmarks; `palm` is the rollback mode |
| `obstruction.min_confidence` | Minimum palm score sent to the landmark stage |
| `obstruction.min_presence_confidence` | Landmark score that confirms a hand |
| `obstruction.min_candidate_presence_confidence` | Compatibility setting; every decoded palm now remains fail-closed regardless of landmark score |
| `obstruction.max_hands` / `inference_threads` | Candidate limit and LiteRT CPU worker count |
| `obstruction.target_interval` | Target time between frame starts; an overrun starts the next frame immediately |
| `obstruction.poll_interval` | Backward-compatible wait cadence used by blocking callers |
| `obstruction.source_width` / `source_height` | Expected obstruction-stream size, checked against each converted frame |
| `obstruction.bed_roi` | Normalized scan-bed rectangle, including the calibrated hazard margin |
| `obstruction.region_schedule` | Repeating crop schedule; shipped as `bed`, `bed`, `full` |
| `obstruction.debug_overlay` | Shows operator diagnostics and the active bed rectangle on the preview |
| `obstruction.clear_frames` | Consecutive clear readings needed before a turn may start |
| `obstruction.stale_after_seconds` | A reading older than this is treated as no reading at all |
| `obstruction.wait_timeout_seconds` | How long a page turn waits for the bed to clear before failing |

Workflow and CORS settings apply live. Camera, obstruction and pin changes require a restart. The
shipped `config.toml` carries values tuned on the rig.

### Servo holding force

By default a servo detaches once it reaches its angle, so it goes limp and merely rests on the page.
Passing `hold=True` to `set_angle()` keeps it powered so it actually grips.

The page turn uses this for both clamps, via their `use_hold` setting. A held
servo draws near-stall current and warms up, so `max_hold_seconds` arms a timer that releases it if
no lift arrives. Lifting the servo cancels that timer, so the normal path never waits for it.

### Stepper driver

The stepper runs on an MKS TMC2209 V2.0, which replaced a DRV8825. Its EN input is active-low, so a
released or floating pin can leave the coils energised — `StepperMotor.cleanup()` drives EN high
before releasing the pins, and `hardware/test_stepper.py` has a `RELEASE_PINS` switch for checking
that on the bench.

**MS1 and MS2 are tied to GND**, which selects 1/8 microstepping. That is why `steps_per_rev` is
1600 rather than 200: it counts step pulses, not full steps. The DRV8825 defaulted to full steps
with its mode pins low, so this had to change with the driver.

The driver is used purely as step/dir. Its UART and StallGuard features are not used — see below.

#### StallGuard: wiring notes, kept for reference

Stall detection was built and then removed. It worked, in that the driver reported load over UART and
DIAG did eventually assert, but the gap between a healthy move and a stalled one was too narrow on
this mechanism to act on: unloaded readings sat around 88-108 and a hand-loaded shaft only fell to
around 84, so any threshold that caught a real jam also stopped healthy moves. The wiring is left in
place and recorded here in case it is worth revisiting.

| Signal | Pi pin | Notes |
|---|---|---|
| PDN/UART | GPIO14 TX, GPIO15 RX | **Both to the same pad** — the `R8 CONNECT = UART` one, fourth up from `En`. 1 kΩ in series on TX only; RX taps the junction |
| DIAG | GPIO26 | Asserts on stall |
| MS1 / MS2 | GND | Sets UART address 0 and 1/8 microstepping |

What cost the most time, in case it comes up again:

- On this board **R8 selects which pad is bonded to the chip's PDN_UART**, so the other pad is inert.
  RX on the wrong one means writes land and replies never come — which looks exactly like a dead
  driver while step/dir keeps working normally.
- **MS1/MS2 must not float.** They set the UART address, and a floating pin settles at no stable
  level, so the driver answers on no address at all.
- The **`pytmcstepper`** library derives its read timeout as `20000 // baudrate`, which floors to
  **0** at 115200 and leaves pyserial non-blocking, so every read returns empty. It also calls
  `sys.exit()` when the port cannot be opened. Talking to the chip directly avoided both.
- **StallGuard4 needs StealthChop** (unlike StallGuard2 on other TMC parts), is inactive below a
  speed gate set by `TCOOLTHRS`, and its reading climbs for the first fraction of a second of motion
  — so a standing start reads exactly like a stall.

#### Freeing the UART

The TMC2209's UART needs GPIO14/15, which on a stock Pi carry a login console on the mini-UART while
Bluetooth holds the better PL011. Mini-UART baud follows the VPU core clock and drifts, which is
poor for register traffic. The fix, already applied here, is:

- `console=serial0,115200` removed from `/boot/firmware/cmdline.txt`
- `dtoverlay=disable-bt` added to `/boot/firmware/config.txt`, moving the PL011 onto GPIO14/15
- `sudo systemctl mask serial-getty@ttyS0.service`

Both boot files were backed up alongside themselves as `*.examscan.bak`. This needed a reboot, after
which `ls -l /dev/serial0` points at `ttyAMA0` rather than `ttyS0`. Bluetooth is given up in
exchange. Nothing in the project uses the serial port now, so this can be reverted if Bluetooth is
wanted back.

### Servo motion profile

Servos ramp toward a target rather than jumping, and slow down near the end so the arm's inertia
doesn't carry it past the mark. Eight fields per servo control it, all applying live:

| Field | Default | Meaning |
|---|---|---|
| `step_degrees` | `3.0` | Increment size while still far from the target |
| `step_delay` | `0.015` | Seconds per step, far from the target |
| `approach_degrees` | `40.0` | Start slowing this many degrees out |
| `approach_step_degrees` | `1.0` | Increment size on the final approach |
| `approach_step_delay` | `0.04` | Seconds per step on the final approach |
| `departure_degrees` | `10.0` | Crawl for this many degrees after leaving the start |
| `departure_step_degrees` | `0.5` | Increment size while departing |
| `departure_step_delay` | `0.08` | Seconds per step while departing |

Speed is `step_degrees / step_delay`, so slower means a bigger delay, a smaller step, or both. With
the defaults a 105° move takes roughly 2 seconds. If the arm still overshoots, raise
`approach_degrees` to start slowing earlier or `approach_step_delay` to crawl the last stretch. Set
the delays to `0` for the old full-speed behaviour; the step sizes must stay above zero.

The `departure_*` fields mirror the approach ones at the other end of the move, for peeling the arm
off a page slowly instead of flicking it. They only take effect when a caller passes
`slow_start=True` to `set_angle()`, so every move is unaffected by default — nothing in the
page-turn uses it today, and it is exercised from `hardware/test_servo.py` via `SLOW_START_ANGLES`.
Where a move is shorter than `departure_degrees` the departure profile applies throughout, so it
never speeds up partway.

### Reversed servos

`min_angle` may be set **greater than** `max_angle` to mirror a servo's rotation — which is what
`page_clamp_big` does, since the clamps are mirrored hardware and would otherwise open when the
other closes. `down_angle` and `up_angle` stay the same numbers on both sides, so nothing downstream
has to know which side it's driving.

Changing this on an already-mounted servo moves where commanded `0` sits physically. Since
`AngularServo` drives to `0` the moment it's constructed, re-seat the horn before running anything.

### Fan

The fan needs a 25 kHz PWM carrier, which is far above what the pigpio daemon's software PWM can
hold steady. `hardware/fan.py` therefore talks to `pigpio` directly and calls `hardware_PWM()` on
GPIO18 — one of the two pins wired to the SoC's real PWM peripheral — rather than going through
`gpiozero` like the servos do. This is why `page_clamp_small` sits on GPIO27: it was
moved off 18 to free the hardware PWM channel, and being a 50 Hz servo it does not care which pin
it lands on.

Duty cycle maps to roughly 1800 RPM at 25%, 3700 at 50%, 5600 at 75%, and 7500 at 100%. Below about
10% the fan cannot break static friction and just sits stalled, so `set_duty()` floors any non-zero
request at `fan.min_start_duty_pct`. Zero still means off.

The fan reads a disconnected PWM line as a request for **full speed**, not zero — a failsafe for
cooling use, which is the opposite of what this rig wants. `FanController` drives the pin low as
soon as it connects and `cleanup()` always commands 0% before dropping the pigpio connection, so a
normal exit never leaves it spinning. Only a pulled wire or a dead `pigpiod` can trigger the
failsafe.

`read_rpm()` reports the average speed since the previous call rather than an instantaneous figure,
so polling it slowly gives a steadier number at the cost of lagging a speed change by up to one
polling interval. The tach line is an open-collector output driven low twice per revolution, so the
pin is configured with a pull-up — without it the level never rises and the edge count stays at
zero. If a fan reports double or half the expected speed, correct `fan.tach_pulses_per_rev` rather
than scaling the result.

`hardware/test_fan.py` drives all of this interactively: number keys and space step through the
speeds, `q` exits, and measured RPM prints every few seconds.

Requires the pigpio daemon (see [Setup](#2-enable-the-pigpio-daemon)).

## Obstruction detection

The mechanism brings clamps, the arm and the fan down onto the bed, in the same space an
operator's hands occupy when loading a booklet or clearing a misfeed. A background thread watches
the camera and `page_turn()` refuses to start while a hand is in frame.

`hardware/vision.py` runs Google's palm detector and 21-point hand-landmark model over a second,
960x540 camera stream (`camera.lores_*`) on a background thread. The aspect ratio matches the
preview and selected sensor mode. The repeating `bed`, `bed`, `full` schedule enlarges hands in a
calibrated scan-bed crop while retaining periodic coverage of the entire image. The shipped ROI is
the whole frame until it can be calibrated from a known-safe preview, so no hazardous area is
excluded by an assumed crop.

The palm model proposes a rotated hand crop; the monitor publishes that candidate immediately,
before the landmark stage completes. The landmark model may promote it to `confirmed`, but cannot
turn a decoded palm into `clear`; only a frame with no qualifying palm contributes to the
five-reading clearance debounce. Frames start on a target-period schedule, so inference time is
not followed by an additional fixed sleep. `page_turn()` polls the verdict continuously — inside
every stepper run, every servo ramp and every settle, not just at phase boundaries.

### Stopping and resuming

A hand stops the mechanism **where it stands**, mid-move if need be, and the sequence continues
from that exact point once the area clears:

```
!! HAND DETECTED - paused at phase 6/16 (motor 1 out)
   waiting for the scan area to clear...
-> area clear, resuming phase 6/16 (motor 1 out)
```

`/api/health` keeps the backward-compatible `hand_present` value and adds `hand_detection` with
the mode, state, palm and presence scores, confirmed-hand count, inference time, reading age,
source resolution, active region, effective sampling rate, exposure, analogue gain and error. The
demo page polls the health response to show a full-screen banner. Setting `debug_overlay = true`
also shows these diagnostics and the active bed rectangle without exposing landmark coordinates.

Resuming continues the **remainder** of an interrupted move rather than repeating it. Re-running a
400-step run that stopped at step 250 would turn the wheel 250 steps too far, and since nothing
measures wheel position it would creep silently on every interrupted page.

Motion stops, but static holds do not:

- **The fan stops.** Spinning blades are the actual hazard, and it is the only part that keeps
  moving on its own once commanded. It spins back up on resume.
- **The steppers stay energised.** A stationary energised motor is not a hazard, and de-energising
  motor 1 mid-turn would let the wheel slip under the clamp and lose the position the resume
  depends on.
- **Servo holds are re-asserted** for as long as the pause lasts. `max_hold_seconds` detaches a
  held servo on a timer rather than raising, so an unattended pause would otherwise end with the
  clamps limp and the page dropped, silently.

If the area never clears, `obstruction.wait_timeout_seconds` expires: the fan goes off, the
steppers are de-energised, the servos are released, and `POST /page-turn` returns 409 naming the
phase it stopped at. Recovery is deliberately manual — moving the mechanism unasked is the wrong
default when the reason it stopped is that something was in it.

### Why not the mediapipe package

`pip install mediapipe` does work on a Pi 4 running Bookworm, whose system Python is 3.11. It does
not work here. This is Debian 13 (trixie) with Python 3.13, and:

- The camera pins the project to 3.13 — `libcamera`'s binding is an apt package compiled as
  `_libcamera.cpython-313-aarch64-linux-gnu.so`, reached through `include-system-site-packages`.
- mediapipe's only py3.13 build (`1.0.1`) is compiled requiring AES instructions. The Pi 4's
  Cortex-A72 reports `fp asimd evtstrm crc32 cpuid` and no `aes`, so it dies with SIGILL.
- The aarch64 wheels that do run here (`0.10.13`–`0.10.18`) stop at cp312.

So both `hand_detector.tflite` and `hand_landmarks_detector.tflite` are extracted from the official
float16 Hand Landmarker v1 bundle and run through LiteRT, which does work on 3.13. The code
reproduces MediaPipe's 2,016-anchor decoding, weighted suppression, rotated hand crop and landmark
presence check. `obstruction.mode = "palm"` retains the previous score-only path for rollback.
The landmark model is the official float16 v1 asset; its SHA-256 is
`6acda74af3fbf40e68265c20c7394b2bad81a16a481dcd79ad7a081887c3d6b9`.

### Input scaling

The model wants pixels in `[0, 1]`. Scaling to `[-1, 1]` instead saturates every logit and reports
a hand in a blank frame, which would jam the gate shut on a working rig. `tests/test_vision.py`
pins this down against a real photograph rather than trusting it.

### What it does not cover

- **It is not a safety interlock.** The verdict is at most one poll interval old and inference is
  not instantaneous. It supports a hardware stop rather than replacing one.
- **Hands only.** A pen or a sleeve on the bed goes through undetected.
- **It cannot undo motion already made.** It stops the next step, not the one in progress.

## Setup

### What is uv?

`uv` is a fast Python package manager (a replacement for `pip` + `venv`). It manages the virtual environment and dependencies for this project. The `--system-site-packages` flag is required here so the virtual environment can access `libcamera`, which is a system-level Raspberry Pi library that cannot be installed via pip.

### 1. Install system dependencies

```bash
sudo apt install libcap-dev liblgpio-dev swig -y
```

### 2. Enable the pigpio daemon

The servos and the fan both drive their pins through `pigpiod`, so it has to be running before the
backend starts. Check whether it is already up:

```bash
systemctl status pigpiod
```

If the service is missing, install it — note that on this rig `pigpiod` lives in `/usr/local/bin`
from a source build rather than the apt package, so check `which pigpiod` before installing over it:

```bash
sudo apt install pigpio -y
```

Then enable it, which also brings it back after a reboot:

```bash
sudo systemctl enable --now pigpiod
```

`pigs hwver` should print a hardware revision number rather than an error once the daemon is up.

### 3. Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart your terminal after installing, or run:
```bash
source $HOME/.local/bin/env
```

### 4. Create the virtual environment

```bash
uv venv --system-site-packages
```

### 5. Install Python dependencies

```bash
uv sync
```

## Usage

```bash
uv run examscan
```

It prints the address the API is listening on. There is no interface to open — point your GUI at
that host and drive it through the [API](#api), or use the curl walkthrough below.

## Entry points

| Command | Hardware | Serves `/` |
|---|---|---|
| `uv run examscan` | Real | JSON descriptor — headless |
| `uv run examscan-dev` | Fake | JSON descriptor — headless |
| `uv run examscan-demo` | Real | `demo.html` |

All three expose the identical REST API and MJPEG stream; they differ only in which hardware they
build and whether `/` returns a page.

## Development

The dev server runs the real HTTP API against fake hardware — no camera, no GPIO — so every
endpoint can be exercised without a scanner attached. Captures are placeholder JPEGs written to the
normal runs directory, so the archive endpoint works against real files.

```bash
uv run examscan-dev
```

```bash
uv run pytest
```

### Demo mode

For showing the scanner to people. Real hardware, plus a page at `/` with a live feed and Scan Page
/ Auto Scan / Finish Run / Download buttons:

```bash
uv run examscan-demo
```

**This is not the product interface** — the GUI is a separate remote client (see
[Architecture](#architecture)). `demo.html` is a useful reference implementation to crib from,
though: it implements the reconnect-after-capture pattern the real GUI also needs. The page is
re-read on each request, so you can edit it and refresh mid-demo without restarting.

## API

All responses are JSON unless noted. There are no raw hardware endpoints by design — the motor and
servos are reachable only through the run actions below.

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Service descriptor (JSON) |
| GET | `/stream` | MJPEG live preview |
| GET | `/api/health` | Active run, busy flag, current operation, restart-required flag |
| GET | `/api/config` | Download `config.toml` |
| PUT | `/api/config` | Validate and apply a config; backs up the previous one |
| POST | `/api/runs` | Create a run. No body |
| GET | `/api/runs` | List all runs, newest first — `{"runs": [...]}` |
| DELETE | `/api/runs` | Delete all stored run folders. Refuses while hardware is busy |
| GET | `/api/runs/{id}` | Run manifest |
| POST | `/api/runs/{id}/capture` | Capture one page |
| POST | `/api/runs/{id}/page-turn` | The sixteen-phase clamp, arm, fan and stepper sequence |
| POST | `/api/runs/{id}/scan-step` | Capture, then turn the page |
| POST | `/api/runs/{id}/scan-last-page` | Capture, then turn with the big clamp held until all forward motor legs finish; leaves the run open |
| POST | `/api/runs/{id}/auto-scan` | Scan N pages then complete. Optional body `{"pages": N}`; defaults to `workflow.default_pages` |
| POST | `/api/runs/{id}/complete` | Close the run |
| GET | `/api/runs/{id}/archive` | Download all pages as a ZIP |

Status codes: `400` invalid config or run request, `404` unknown route or run, `409` hardware busy
with another operation, `500` unexpected failure.

Runs are stored as `runs/<run_id>/pages/page_NNN.jpg` alongside a `manifest.json`. The archive is
available as soon as a run has at least one page — you do not have to complete it first — and
unpacks to a folder named after the run.

`DELETE /api/runs` removes every valid run directory from the configured runs folder and leaves the
runs folder itself in place. It only deletes directories that contain a `manifest.json`, so stray
notes or unrelated folders under `runs/` are preserved. The endpoint uses the same hardware lock as
capture, page-turn and auto-scan; if the scanner is already busy, it returns `409` and deletes
nothing.

Successful deletion returns `{"ok": true, "deleted": N, "run_ids": [...]}`. The `run_ids` array
lists the runs that were removed.

### Run responses

Every endpoint that returns a run returns the same shape — `GET /api/runs/{id}` and all the POST
actions alike:

```json
{
  "run_id": "20260728-120942-95b0146e",
  "status": "open",
  "created_at": "...",
  "updated_at": "...",
  "pages": [
    {"page_number": 1, "filename": "page_001.jpg", "path": "pages/page_001.jpg", "captured_at": "..."}
  ],
  "errors": [],
  "page_count": 1,
  "archive_url": "/api/runs/20260728-120942-95b0146e/archive"
}
```

`archive_url` appears only once the run has at least one page.

`GET /api/runs` returns summaries rather than full manifests — `run_id`, `status`, `page_count`,
`error_count`, `created_at`, `updated_at` — sorted newest first. A run whose manifest is unreadable
is skipped rather than failing the whole listing.

### `errors[]`

Failed captures and page turns are appended here, so a failure during an unattended auto-scan is
still diagnosable afterwards:

```json
{"operation": "capture", "message": "sensor timeout", "page_number": 4, "occurred_at": "..."}
```

`page_number` is the page that was being attempted. Recording an error does not change the HTTP
response — the request that failed still returns `500`, and the run stays `open`.

### Testing the API

Start `uv run examscan-dev` in one terminal, then in another:

```bash
curl -s localhost:8000/api/health
```

Create a run and keep its ID:

```bash
RUN=$(curl -s -X POST localhost:8000/api/runs | python3 -c 'import json,sys;print(json.load(sys.stdin)["run_id"])')
```

Capture a page, or capture and turn in one call:

```bash
curl -s -X POST localhost:8000/api/runs/$RUN/capture
```

```bash
curl -s -X POST localhost:8000/api/runs/$RUN/scan-step
```

For the final page, capture it with the delayed big-clamp release and finish the run separately:

```bash
curl -s -X POST localhost:8000/api/runs/$RUN/scan-last-page
curl -s -X POST localhost:8000/api/runs/$RUN/complete
```

Scan a fixed number of pages and finish automatically:

```bash
curl -s -X POST localhost:8000/api/runs/$RUN/auto-scan -H 'Content-Type: application/json' -d '{"pages":3}'
```

Or omit the body to use `workflow.default_pages`:

```bash
curl -s -X POST localhost:8000/api/runs/$RUN/auto-scan
```

Inspect the run, list every run, then close it:

```bash
curl -s localhost:8000/api/runs/$RUN
```

```bash
curl -s localhost:8000/api/runs
```

Delete all stored runs:

```bash
curl -s -X DELETE localhost:8000/api/runs
```

```bash
curl -s -X POST localhost:8000/api/runs/$RUN/complete
```

Download the images and list them without unpacking:

```bash
curl -s -OJ localhost:8000/api/runs/$RUN/archive && unzip -l $RUN.zip
```

Config round-trip, then a deliberate rejection:

```bash
curl -s localhost:8000/api/config -o /tmp/config.toml && curl -s -X PUT localhost:8000/api/config --data-binary @/tmp/config.toml
```

```bash
curl -s -X PUT localhost:8000/api/config --data-binary 'invalid = ['
```

Show the busy lock returning `409` — the dev server's simulated motor delay makes the first call
slow enough for the second to collide with it:

```bash
curl -s -o /dev/null -X POST localhost:8000/api/runs/$RUN/scan-step & sleep 0.4; curl -s -X POST localhost:8000/api/runs/$RUN/capture; wait
```

## GUI integration

Two things that aren't obvious from the endpoint table.

### Displaying the stream

A plain `<img>` renders `multipart/x-mixed-replace` natively — no library required, and **no CORS**,
because image loading isn't CORS-restricted. Only `fetch` calls to `/api/*` are, which
`server.cors_enabled` already covers.

```html
<img id="feed" src="http://<pi-ip>:8000/stream">
```

### Reconnecting after a capture

**The stream connection dies on every capture, and the client must restart it.**

Taking a still requires reconfiguring the sensor from preview (1920×1080) to full resolution
(4608×2592). `CameraController.capture_file()` sets `streaming = False` for the duration, which
makes `_serve_stream`'s `while camera.streaming:` loop exit and closes the HTTP connection. Your
`<img>` goes blank and stays blank.

Re-set `img.src` after every `capture`, `scan-step`, `scan-last-page` or `auto-scan`, allowing
roughly a second for preview to resume:

```js
const PI = "http://<pi-ip>:8000";
const feed = document.getElementById("feed");

function startStream() {
  feed.src = `${PI}/stream?${Date.now()}`;   // timestamp defeats caching
}

async function scanStep(runId) {
  feed.src = "";                              // drop the dying connection
  await fetch(`${PI}/api/runs/${runId}/scan-step`, { method: "POST" });
  setTimeout(startStream, 1000);              // camera needs ~1s to resume preview
}

startStream();
```

> **Dev-mode divergence.** `FakeCamera.capture_file()` does not toggle `streaming`, so the stream
> under `examscan-dev` survives captures. A GUI built only against the dev server will appear to
> work with no reconnect logic at all, then fail against the real Pi. Write the reconnect handling
> even though dev mode doesn't seem to need it.

## Staff authentication

The operator-facing `final-ui` requires a registered staff account. It uses a
UCT ID and a random password delivered by email; users do not self-register or
choose passwords. The current password remains valid when a replacement is
requested and is retired only after the replacement is successfully used.

Authentication is enforced by the FastAPI application in `software/`, not just
by frontend routing. All document, scan-session, download, debug, and Pi-proxy
routes require a revocable browser session. `GET /health`, login, and password
request are the only public application routes. The low-level Pi hardware API
served by `server.py` is unchanged and must remain on its private network.

For the full user flow, API contracts, schema, security decisions, deployment,
and recovery procedures, see [Staff authentication](docs/authentication.md).

### Development setup: laptop UI and backend, Pi hardware

The recommended development layout keeps only camera and mechanical control on
the Raspberry Pi. A seperate device runs `final-ui`, FastAPI, MySQL, and
Mailpit. In this layout the browser talks to the laptop, and FastAPI proxies
hardware operations to the Pi's private API.

#### 1. Install prerequisites

Install and start:

- Docker Desktop using Linux containers. Wait for **Engine running** before
  using `docker compose`.
- a current Node.js LTS release, including npm;
- `uv` for the Python environment.

Open a new PowerShell window after installing Node.js, then verify:

```powershell
docker info
node --version
npm.cmd --version
uv --version
```

The laptop needs the complete ExamScan repository, not just `final-ui`, because
the Python project metadata and lockfile live at the repository root. Changes
that have not been committed and pushed cannot be obtained with `git pull`;
copy them from the Pi or commit and push them before cloning.

#### 2. Configure the laptop services

From PowerShell in the laptop repository:

```powershell
cd C:\Users\<you>\Documents\ExamScan\software
Copy-Item .env.example .env
notepad .env
```

Set local values similar to these, replacing the bootstrap identity and both
database passwords:

```dotenv
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=examscan
DB_PASSWORD=choose-a-local-development-password
DB_ROOT_PASSWORD=choose-a-different-local-development-password
DB_NAME=examscan

EXAMSCAN_BOOTSTRAP_UCT_ID=YOUR_UCT_ID
EXAMSCAN_BOOTSTRAP_NAME=Your Full Name
EXAMSCAN_BOOTSTRAP_EMAIL=admin@example.test

SMTP_HOST=127.0.0.1
SMTP_PORT=1025
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_SECURITY=none
SMTP_FROM=ExamScan <examscan@example.test>

EXAMSCAN_ENV=development
FRONTEND_URL=http://localhost:5173
FRONTEND_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
AUTH_COOKIE_SECURE=false
MAILPIT_UI_PORT=8025
```

Mailpit captures mail locally, so `admin@example.test` does not have to be a
real mailbox. The generated ExamScan staff password is unrelated to the two
MySQL passwords. Keep `.env` private; it is excluded from Git.

#### 3. Start the Pi hardware API

In a terminal connected to the Pi:

```bash
ssh Pi
cd /home/chidi/Desktop/ExamScan
sudo systemctl start pigpiod
uv run examscan
```

Keep that process running. From the laptop, verify the private hardware API:

```powershell
Invoke-RestMethod http://10.42.0.1:8000/api/health
```

`software/constants.py` currently points `RUNS_API_BASE_URL` at
`http://10.42.0.1:8000`. If the Pi is reached through mDNS instead of that
private address, change it to `http://examscan.local:8000` before starting the
laptop backend.

#### 4. Start MySQL and Mailpit on the laptop

In the first laptop PowerShell window:

```powershell
cd C:\Users\<you>\Documents\ExamScan\software
docker compose up -d
docker compose ps
```

Wait for MySQL and Mailpit to be running. On the first start Docker downloads
their images and creates the database named by `DB_NAME`.

#### 5. Start FastAPI on the laptop

In a second PowerShell window:

```powershell
cd C:\Users\<you>\Documents\ExamScan\software
uv run uvicorn scanner_api:app --host 0.0.0.0 --port 8000
```

FastAPI creates the scan and authentication tables automatically. Confirm it
is available with `Invoke-RestMethod http://localhost:8000/health`.

#### 6. Start the frontend on the laptop

In a third PowerShell window:

```powershell
cd C:\Users\<you>\Documents\ExamScan\final-ui
npm.cmd ci
npm.cmd run dev
```

Open `http://localhost:5173/login`. The existing Vite configuration proxies
`/api` to FastAPI on `localhost:8000`; it must not point directly to the Pi in
this layout.

#### 7. Create the first login

1. Enter `EXAMSCAN_BOOTSTRAP_UCT_ID` on the login page.
2. Select **Email me a password**.
3. Open Mailpit at `http://localhost:8025` and copy the generated password.
4. Sign in and use **Staff** to create operator accounts.

The bootstrap account is inserted only when the `users` table is empty. Later
changes to the three bootstrap environment variables do not alter that account.

To stop the laptop services without deleting data, stop FastAPI and Vite with
Ctrl+C, then run `docker compose down` from `software/`. Do not add `-v` unless
you intentionally want to delete the local database volume.

Common startup failures:

- `dockerDesktopLinuxEngine` pipe missing: open Docker Desktop and wait for
  **Engine running**.
- `npm` or `npm.cmd` not recognized: install Node.js LTS and open a new
  PowerShell window.
- MySQL authentication error after editing `.env`: the existing Docker volume
  still has its original credentials. Restore them, or intentionally reset the
  development volume with `docker compose down -v` before starting again.

The environment reference is grouped as follows: `DB_HOST`, `DB_PORT`,
`DB_USER`, `DB_PASSWORD`, and `DB_NAME` configure MySQL; the three
`EXAMSCAN_BOOTSTRAP_*` values create the first administrator; `SMTP_*`
configures delivery; and `FRONTEND_URL`, `FRONTEND_ORIGINS`, `EXAMSCAN_ENV`,
and `AUTH_COOKIE_SECURE` define the browser boundary. Safe placeholders and
development defaults are in `software/.env.example`.

Production deployments must use real SMTP credentials, set
`EXAMSCAN_ENV=production` (and preferably `AUTH_COOKIE_SECURE=true`
explicitly), serve the frontend over HTTPS, and restrict
`FRONTEND_ORIGINS` to the deployed frontend origin. Never copy SMTP or session
credentials from the reference Capstone project into ExamScan.

## Acknowledgements

The ExamScan authentication flow is adapted from Johan Bontes’s Capstone
project-selection application: https://github.com/JBontes/capstone

This is an acknowledgement of the authentication design and code influence;
it does not attribute the ExamScan project to Johan Bontes or assert a license
for the referenced project.
