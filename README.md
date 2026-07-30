# ExamScan

A Raspberry Pi-based document scanner that captures high-resolution images of exam papers using a
fixed overhead camera and advances pages automatically. Each scanning run is saved as a folder of
JPEGs, downloadable as a ZIP.

A page turn has five phases:

1. **Drop the arm** onto the page (servo to `down_angle`)
2. **Spin the DC wheel** to feed the page across
3. **Turn the stepper** by `motor.default_degrees`
4. **Lift the arm** clear (servo to `up_angle`)
5. **Return the stepper** the same distance the other way

Phase 5 means the wheel ends every page turn where it started, so repeated turns can't let it creep
round. Each boundary has its own configurable pause — `servo_down_pause`, `wheel_pause`,
`stepper_pause`, `servo_up_pause`.

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
| Page wheel | DC motor, driven via PWM |
| Page drop / clamps | Servos |
| Stepper (unused) | NEMA 17 SM24240 with DRV8825 — driver retained, not in the current workflow |

### Wiring

Pins are defined in `config.toml` and can be changed there; a pin change needs a restart.

| Signal | GPIO (BCM) |
|---|---|
| DC motor IN1 / IN2 / ENABLE | 23 / 24 / 25 |
| Servo — page drop | 12 |
| Servo — page clamp left / right | 18 / 19 |
| Stepper STEP / DIR / ENABLE | 21 / 20 / 16 |

Camera is mounted approximately 43 cm above the scanning surface with a fixed lens position.

## Project Structure

```
ExamScan/
├── hardware/
│   ├── camera.py       # Camera streaming and capture
│   ├── motor.py        # DC motor (page wheel) and stepper motor
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
| `motor.default_degrees` | How far the stepper turns per page, and back again |
| `motor.default_clockwise` | Direction of the outward turn; the return is the opposite |
| `dc_motor.default_speed` / `default_turn_seconds` | How hard and how long the wheel spins |
| `dc_motor.default_forward` | Wheel direction |
| `servos.page_drop.down_angle` / `up_angle` | Where the arm rests down and clear |
| `workflow.*_pause` | Settling time at each phase boundary |

All apply live. The shipped `config.toml` carries values tuned on the rig, which are gentler than the
schema defaults — a short 0.35s nudge of the wheel at speed 35 rather than 3 seconds at full tilt.

### A note on the stepper driver

The DRV8825's nENBL is active-low with an internal pulldown, so a released GPIO floats low and leaves
the coils energised and audibly buzzing when nothing is driving the pin.

**Do not fix this with the Pi's internal pull-up.** It is too weak against the driver's pulldown —
the divider lands near the DRV8825's logic-high threshold, and an input hovering there can chatter,
toggling the driver on and off mid-step so the motor vibrates in place instead of rotating. The idle
buzz is the lesser problem. A proper fix would be an external pull-up strong enough to sit clearly
above threshold.

### Servo motion profile

Servos ramp toward a target rather than jumping, and slow down near the end so the arm's inertia
doesn't carry it past the mark. Five fields per servo control it, all applying live:

| Field | Default | Meaning |
|---|---|---|
| `step_degrees` | `3.0` | Increment size while still far from the target |
| `step_delay` | `0.015` | Seconds per step, far from the target |
| `approach_degrees` | `40.0` | Start slowing this many degrees out |
| `approach_step_degrees` | `1.0` | Increment size on the final approach |
| `approach_step_delay` | `0.04` | Seconds per step on the final approach |

Speed is `step_degrees / step_delay`, so slower means a bigger delay, a smaller step, or both. With
the defaults a 105° move takes roughly 2 seconds. If the arm still overshoots, raise
`approach_degrees` to start slowing earlier or `approach_step_delay` to crawl the last stretch. Set
the delays to `0` for the old full-speed behaviour; the step sizes must stay above zero.

### Reversed servos

`min_angle` may be set **greater than** `max_angle` to mirror a servo's rotation — which is what
`page_clamp_left` does, since the clamps are mirrored hardware and would otherwise open when the
other closes. `down_angle` and `up_angle` stay the same numbers on both sides, so nothing downstream
has to know which side it's driving.

Changing this on an already-mounted servo moves where commanded `0` sits physically. Since
`AngularServo` drives to `0` the moment it's constructed, re-seat the horn before running anything.

## Setup

### What is uv?

`uv` is a fast Python package manager (a replacement for `pip` + `venv`). It manages the virtual environment and dependencies for this project. The `--system-site-packages` flag is required here so the virtual environment can access `libcamera`, which is a system-level Raspberry Pi library that cannot be installed via pip.

### 1. Install system dependencies

```bash
sudo apt install libcap-dev liblgpio-dev swig -y
```

### 2. Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart your terminal after installing, or run:
```bash
source $HOME/.local/bin/env
```

### 3. Create the virtual environment

```bash
uv venv --system-site-packages
```

### 4. Install Python dependencies

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
| GET | `/api/runs/{id}` | Run manifest |
| POST | `/api/runs/{id}/capture` | Capture one page |
| POST | `/api/runs/{id}/page-turn` | Servo down, wheel turn, servo up |
| POST | `/api/runs/{id}/scan-step` | Capture, then turn the page |
| POST | `/api/runs/{id}/auto-scan` | Scan N pages then complete. Optional body `{"pages": N}`; defaults to `workflow.default_pages` |
| POST | `/api/runs/{id}/complete` | Close the run |
| GET | `/api/runs/{id}/archive` | Download all pages as a ZIP |

Status codes: `400` invalid config or run request, `404` unknown route or run, `409` hardware busy
with another operation, `500` unexpected failure.

Runs are stored as `runs/<run_id>/pages/page_NNN.jpg` alongside a `manifest.json`. The archive is
available as soon as a run has at least one page — you do not have to complete it first — and
unpacks to a folder named after the run.

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

Re-set `img.src` after every `capture`, `scan-step` or `auto-scan`, allowing roughly a second for
preview to resume:

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
