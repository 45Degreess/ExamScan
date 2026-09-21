# Hardware setup and deployment

## Raspberry Pi prerequisites

The scanner expects Raspberry Pi GPIO access, Camera Module 3 support, and the
`pigpiod` daemon used by the servos and PWM fan.

```bash
sudo apt install libcap-dev liblgpio-dev swig -y
sudo systemctl enable --now pigpiod
```

Confirm `pigs hwver` succeeds before starting the real service.

## Environment

From the hardware service directory:

```bash
cd /home/chidi/Desktop/ExamScan/hardware/scanner-service
uv venv --system-site-packages
uv sync --extra pi
```

System site packages are required because the Pi camera's `libcamera` binding is
installed by the operating system rather than PyPI.

## Starting services

```bash
uv run examscan
```

Use `uv run examscan-dev` for API development without GPIO, or
`uv run examscan-rig` for supervised bench testing with the real mechanism. Never
run two of these services at the same time because they would compete for the
camera and GPIO devices.

Stop a foreground service with Ctrl+C and wait for the `Stopped.` message. The
shared shutdown path stops the camera and obstruction monitor, turns the fan off,
releases servos, and de-energises the steppers.

## Runtime data

Relative runtime paths are resolved from `hardware/scanner-service/`:

- `runs/` contains manifests and captured JPEG files.
- `models/` contains the required LiteRT palm and landmark models.
- `config/default.toml` is the active configuration and is backed up before an
  uploaded replacement is applied.

These runtime paths are independent of the shell's current working directory.

## AI declaration

OpenAI Codex using the GPT-5 model assisted with reorganising the Raspberry Pi
scanner service and drafting the installation, startup, shutdown, deployment,
and runtime-path guidance in this document. Anthropic Claude Opus 5 was used in
conjunction with Codex to assist with implementation, drafting, review, and
refinement. The AI models assisted with implementation, testing, and
documentation; all design decisions were made solely by the project author. The
project author reviewed the AI-assisted material, verified the procedures on the
target hardware, and retains responsibility for the final implementation and
documentation.
