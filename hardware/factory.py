"""Assembly of the real hardware stack from config.

Shared by the entry points that drive an actual scanner (`main.py`,
`demoserver.py`) so their wiring cannot drift apart.
"""

from hardware.camera import CameraController, StreamOutput, make_camera
from hardware.motor import StepperMotor
from hardware.servo import ServoController


def build_hardware(config):
    picam2, camera_config, capture_config = make_camera(config["camera"])
    camera = CameraController(
        picam2,
        camera_config,
        capture_config,
        StreamOutput(),
        config["camera"],
    )
    servos = ServoController.from_config(config["servos"])
    stepper = StepperMotor.from_config(config["motor"])
    return camera, servos, stepper
