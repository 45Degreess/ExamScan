# Hardware testing and troubleshooting

## Automated tests

Run the non-actuating suite from `hardware/scanner-service`:

```bash
uv run pytest
```

The tests replace GPIO-facing modules with fakes and cover configuration, camera
and vision helpers, servo and stepper behaviour, workflow interruption, and API
responses. Automated validation must not drive the physical mechanism.

## Rig UI

Start the engineering interface with:

```bash
uv run examscan-rig
```

The page is explicitly labelled **ExamScan Rig UI**. It is not the production
operator interface, and its controls can move motors, clamps, the fan, and the
page-drop arm. Opening the page only loads the camera stream and health state; it
does not initiate capture or motion.

## Interactive tools

Stop every ExamScan service first, then run one utility from the service directory:

```bash
uv run python tools/test_fan.py
uv run python tools/test_servo.py
uv run python tools/test_stepper.py
uv run python tools/test_workflow.py
```

These utilities are manual bench programs, not pytest tests. Keep hands clear of
the mechanism and ensure only one process owns the GPIO devices.

## Common faults

- **Camera import or startup failure:** recreate the environment with
  `--system-site-packages` and confirm the system `libcamera` package works.
- **Fan or servo does not respond:** confirm `pigpiod` is running and the configured
  BCM pin matches the wiring.
- **Fan starts unexpectedly:** inspect the PWM connection and daemon state; the fan
  treats a disconnected control line as full speed.
- **Configuration rejected:** compare the uploaded file with
  `config/default.toml`; unknown sections and invalid ranges are refused.
- **Hand detection blocks permanently:** verify the model files and `[0,1]` input
  scaling, then inspect `/api/health` diagnostics.
- **Hand detection misses edge entries:** verify the configured bed ROI, source
  resolution, exposure mode, and `bed, bed, full` region schedule.
- **Request returns 409:** another operation owns the hardware lock, or the
  obstruction monitor has not reported enough consecutive clear frames.
- **Preview stays blank after capture:** reconnect `/stream`; full-resolution
  capture intentionally closes the previous MJPEG connection.

Hand detection does not cover every object and is not a substitute for a physical
emergency stop or certified protective equipment.

## AI declaration

OpenAI Codex using the GPT-5 model assisted with creating and revising automated
hardware-service tests and drafting the Rig UI, manual-testing, fault-diagnosis,
and troubleshooting guidance in this document. Anthropic Claude Opus 5 was used
in conjunction with Codex to assist with implementation, drafting, review, and
refinement. The AI models assisted with implementation, testing, and
documentation; all design decisions were made solely by the project author. The
project author reviewed the AI-assisted work, performed the physical rig
testing, and retains responsibility for the final implementation and
documentation.
