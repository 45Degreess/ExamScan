"""ExamScan entry point: real hardware, headless.

Serves the REST API and the MJPEG stream only — no web page. See demoserver.py
for the same hardware with a demo UI, and devserver.py for fake hardware.

    uv run examscan
"""

from hardware.factory import build_hardware
from server import load_config, serve


def main():
    config_manager, config = load_config()
    camera, servos, stepper = build_hardware(config)

    camera.start_recording()

    serve(config_manager, config, camera, servos, stepper)


if __name__ == "__main__":
    main()
