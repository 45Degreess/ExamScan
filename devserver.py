"""ExamScan entry point: fake hardware.

Every route, status code and response body matches the real server; only the
camera, servos, steppers and fan are stubbed. Use this to exercise the REST API
without a scanner attached. Captures are still written to the configured
runs_dir, so the archive endpoint works against real files on disk.

    uv run examscan-dev
"""

from fakes import (
    FakeCamera,
    FakeFan,
    FakeObstructionMonitor,
    FakeServoController,
    FakeStepperMotor,
)
from server import load_config, serve

BANNER = "ExamScan DEV MODE - fake hardware, no camera or GPIO in use"


def main():
    config_manager, config = load_config()

    camera = FakeCamera()
    servos = FakeServoController(delay=True)
    stepper = FakeStepperMotor(delay=True)
    stepper2 = FakeStepperMotor(delay=True)
    fan = FakeFan()
    obstruction = FakeObstructionMonitor()

    camera.start_streaming()

    serve(config_manager, config, camera, servos, stepper, stepper2, fan,
          obstruction, banner=BANNER)


if __name__ == "__main__":
    main()
