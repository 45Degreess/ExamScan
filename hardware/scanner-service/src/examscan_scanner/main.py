"""ExamScan entry point: real hardware, headless.

Serves the REST API and the MJPEG stream only — no web page. See rigserver.py
for the real-hardware testing UI, and devserver.py for fake hardware.

    uv run examscan
"""

from .drivers.factory import build_hardware
from .server import load_config, serve


def main():
    config_manager, config = load_config()
    camera, servos, stepper, stepper2, fan, obstruction = build_hardware(config)

    camera.start_recording()

    serve(config_manager, config, camera, servos, stepper, stepper2, fan,
          obstruction)


if __name__ == "__main__":
    main()
