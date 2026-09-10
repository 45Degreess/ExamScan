"""Assembly of the real hardware stack from config.

Shared by the entry points that drive an actual scanner (`main.py`,
`demoserver.py`) so their wiring cannot drift apart.
"""

from hardware.camera import CameraController, StreamOutput, make_camera
from hardware.fan import FanController
from hardware.motor import StepperMotor
from hardware.servo import ServoController
from hardware.vision import HandDetector, ObstructionMonitor


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
    stepper2 = StepperMotor.from_config(config["motor2"])
    # FanController drives the pin to 0% as it is constructed, so the fan reads
    # off from the moment the stack exists rather than spinning up on a
    # floating line.
    fan = FanController.from_config(config["fan"])
    # Disabled leaves the model unloaded entirely, so a rig without it still
    # runs - the page turn simply goes unguarded.
    obstruction = None
    if config["obstruction"]["enabled"]:
        detector = HandDetector.from_config(config["obstruction"])
        obstruction = ObstructionMonitor.from_config(
            camera, detector, config["obstruction"]
        )
    return camera, servos, stepper, stepper2, fan, obstruction
