# ExamScan hardware overview

The Raspberry Pi service is the hardware boundary of ExamScan. It captures pages,
stores scanner runs, streams the camera preview, detects hands near the mechanism,
and coordinates the clamps, fan, arm, and two stepper motors. The separate product
frontend and OCR backend call its REST API; they do not access GPIO directly.

## Components

| Area | Responsibility |
|---|---|
| `src/examscan_scanner/server.py` | HTTP API, run workflow, locking, and cleanup |
| `src/examscan_scanner/config.py` | Defaults, validation, live reload, and restart detection |
| `src/examscan_scanner/runs.py` | Run manifests, captured pages, deletion, and ZIP archives |
| `src/examscan_scanner/drivers/` | Camera, fan, servo, stepper, and hand-detection implementations |
| `static/rig.html` | Engineering interface for testing the physical rig |
| `tools/` | Interactive bench utilities that directly actuate hardware |

The production service is headless: `GET /` returns a JSON descriptor and the
operator interface remains a separate application. `examscan-rig` deliberately
replaces only that root response with the Rig UI while retaining the same API.

## Runtime flow

1. The selected entry point loads and validates `config/default.toml`.
2. Real entry points build the camera and actuators; development mode creates fakes.
3. The camera preview and obstruction monitor start before requests are accepted.
4. Run actions acquire the hardware lock before capture or movement.
5. Shutdown releases the camera, servos, fan, and both steppers.

The obstruction detector is a risk-reduction layer rather than a certified safety
interlock. Missing, stale, or failed detection is treated as obstructed while it is
enabled.

## More information

- [Setup and deployment](setup-deployment.md)
- [Configuration and API](configuration-api.md)
- [Testing and troubleshooting](testing-troubleshooting.md)

## AI declaration

OpenAI Codex using the GPT-5 model assisted with reorganising the hardware
service and drafting this description of its architecture, component
responsibilities, and runtime data flow. Anthropic Claude Opus 5 was used in
conjunction with Codex to assist with implementation, drafting, review, and
refinement. The AI models assisted with implementation, testing, and
documentation; all design decisions were made solely by the project author. The
project author reviewed the AI-assisted material, performed the physical
validation, and retains responsibility for the final implementation and
documentation.
