"""Assembly of the real hardware stack from config.

Shared by the entry points that drive an actual scanner (`main.py`,
`rigserver.py`) so their wiring cannot drift apart.
"""

from .camera import CameraController, StreamOutput, make_camera
from .fan import FanController
from .motor import StepperMotor
from .servo import ServoController
from .vision import HandDetector, ObstructionMonitor
from ..runs import resolve_project_path


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
    # FanController drives the pin to 0% as it is constructed
    fan = FanController.from_config(config["fan"])

    obstruction = None
    if config["obstruction"]["enabled"]:
        detector_config = dict(config["obstruction"])
        detector_config["model_path"] = resolve_project_path(
            detector_config["model_path"]
        )
        if detector_config.get("landmark_model_path"):
            detector_config["landmark_model_path"] = resolve_project_path(
                detector_config["landmark_model_path"]
            )
        detector = HandDetector.from_config(detector_config)
        obstruction = ObstructionMonitor.from_config(
            camera, detector, config["obstruction"]
        )
    return camera, servos, stepper, stepper2, fan, obstruction
