# Hardware configuration and API

## Configuration

The active file is `hardware/scanner-service/config/default.toml`. Configuration
is validated at startup and when replaced through the API. Invalid and unknown
settings are rejected. GPIO, camera, and obstruction-model changes require a
restart; workflow and CORS settings can apply live.

Major groups are:

| Group | Purpose |
|---|---|
| `server` | Bind address, port, and CORS origins |
| `paths` | Run-storage location |
| `camera` | Preview, capture, obstruction-stream, focus, and exposure settings |
| `motor`, `motor2` | Pins, directions, speeds, travel, and return correction |
| `servos` | Pins, angles, movement profiles, and hold limits |
| `fan` | PWM, tachometer, duty, and spin-up timing |
| `obstruction` | Models, confidence thresholds, ROI schedule, and fail-closed timing |
| `workflow` | Page-turn mode, phase pauses, and default page count |

`workflow.turn_sequence` accepts `motor2_only` or `shared`. Both retain the
configured 16-phase workflow. The obstruction detector can run the full palm and
landmark pipeline or the palm-only rollback mode. When disabled, no model is
loaded and movement proceeds without the vision gate.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Service descriptor, or Rig UI in rig mode |
| `GET` | `/stream` | MJPEG preview |
| `GET` | `/api/health` | Busy state, active run, obstruction diagnostics, and restart state |
| `GET`, `PUT` | `/api/config` | Read or validate and replace configuration |
| `POST`, `GET`, `DELETE` | `/api/runs` | Create, list, or delete stored runs |
| `GET` | `/api/runs/{id}` | Read a run manifest |
| `POST` | `/api/runs/{id}/capture` | Capture without moving the mechanism |
| `POST` | `/api/runs/{id}/page-turn` | Run the page-turn sequence without capture |
| `POST` | `/api/runs/{id}/scan-step` | Capture and turn one page |
| `POST` | `/api/runs/{id}/scan-last-page` | Capture using delayed large-clamp release |
| `POST` | `/api/runs/{id}/auto-scan` | Scan the requested number of pages |
| `POST` | `/api/runs/{id}/complete` | Close an open run |
| `GET` | `/api/runs/{id}/archive` | Download captured pages as a ZIP |

The API contract is unchanged by the directory migration. Existing clients can
continue using the same routes and response bodies.

Capturing a full-resolution image temporarily reconfigures the camera and closes
the current MJPEG connection. Clients must reconnect `/stream` after capture,
scan-step, scan-last-page, and auto-scan operations.

## AI declaration

OpenAI Codex using the GPT-5 model assisted with implementing and documenting
the scanner configuration, API endpoints, page-turn modes, obstruction
detection, health diagnostics, and configuration validation described here.
Anthropic Claude Opus 5 was used in conjunction with Codex to assist with
implementation, drafting, review, and refinement. The AI models assisted with
implementation, testing, and documentation; all design decisions were made
solely by the project author. The project author reviewed the AI-assisted code
and text, validated the configuration against the physical rig, and retains
responsibility for the final implementation and documentation.
