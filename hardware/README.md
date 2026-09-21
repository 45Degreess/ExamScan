# ExamScan hardware service

The hardware service runs on the Raspberry Pi and owns the camera, hand-obstruction
monitor, page-turn mechanism, run storage, REST API, and MJPEG preview.

> **Hardware warning:** stop the production service before using an interactive
> tool or the Rig UI. Those interfaces can move motors, servos, and the fan.

## Quick start

```bash
cd /home/chidi/Desktop/ExamScan/hardware/scanner-service
uv venv --system-site-packages
uv sync --extra pi
sudo systemctl start pigpiod
uv run examscan
```

Available services:

| Command | Hardware | Root response |
|---|---|---|
| `uv run examscan` | Real | JSON service descriptor |
| `uv run examscan-dev` | Fake | JSON service descriptor |
| `uv run examscan-rig` | Real | Engineering Rig UI |

The same three commands also work from the repository root and forward into this
isolated hardware project.

Run the non-actuating test suite with:

```bash
uv run pytest
```

Manual bench utilities are under `scanner-service/tools/`; do not run them while
another process owns the GPIO devices.

## Documentation

- [Hardware overview](../docs/hardware/README.md)
- [Setup and deployment](../docs/hardware/setup-deployment.md)
- [Configuration and API](../docs/hardware/configuration-api.md)
- [Testing and troubleshooting](../docs/hardware/testing-troubleshooting.md)

## AI declaration

OpenAI Codex using the GPT-5 model assisted with reorganising the Raspberry Pi
scanner service, updating its commands and paths, drafting this hardware quick
start, and creating or revising automated tests. Anthropic Claude Opus 5 was used
in conjunction with Codex to assist with implementation, drafting, review, and
refinement. The AI models assisted with implementation, testing, and
documentation; all design decisions were made solely by myself. I reviewed the AI-assisted changes, performed the physical validation, and retain responsibility for the final implementation.