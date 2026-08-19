"""ExamScan entry point: fake hardware.

Every route, status code and response body matches the real server; only the
camera, servos and stepper are stubbed. Use this to exercise the REST API
without a scanner attached. Captures are still written to the configured
runs_dir, so the archive endpoint works against real files on disk.

    uv run examscan-dev
"""

from fakes import FakeCamera, FakeServoController, FakeStepperMotor
from server import load_config, serve

BANNER = "ExamScan DEV MODE - fake hardware, no camera or GPIO in use"


def main():
    config_manager, config = load_config()

    camera = FakeCamera()
    servos = FakeServoController(delay=True)
    stepper = FakeStepperMotor(delay=True)

    camera.start_streaming()

    serve(config_manager, config, camera, servos, stepper, banner=BANNER)


if __name__ == "__main__":
    main()
