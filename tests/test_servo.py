import importlib
import sys
import types


class FakeAngularServo:
    instances = []

    def __init__(
        self,
        pin,
        min_angle,
        max_angle,
        min_pulse_width,
        max_pulse_width,
        frame_width,
        pin_factory=None,
    ):
        self.pin = pin
        self.min_angle = min_angle
        self.max_angle = max_angle
        self.min_pulse_width = min_pulse_width
        self.max_pulse_width = max_pulse_width
        self.frame_width = frame_width
        self.pin_factory = pin_factory
        self.angles = []
        self.detached = 0
        self.closed = False
        self.instances.append(self)

    @property
    def angle(self):
        return self.angles[-1] if self.angles else None

    @angle.setter
    def angle(self, value):
        self.angles.append(value)

    def detach(self):
        self.detached += 1

    def close(self):
        self.closed = True


class FakePiGPIOFactory:
    instances = []

    def __init__(self):
        self.instances.append(self)


def load_servo_module(monkeypatch):
    FakeAngularServo.instances = []
    FakePiGPIOFactory.instances = []
    fake_gpiozero = types.ModuleType("gpiozero")
    fake_gpiozero.AngularServo = FakeAngularServo
    fake_pins = types.ModuleType("gpiozero.pins")
    fake_pigpio = types.ModuleType("gpiozero.pins.pigpio")
    fake_pigpio.PiGPIOFactory = FakePiGPIOFactory
    monkeypatch.setitem(sys.modules, "gpiozero", fake_gpiozero)
    monkeypatch.setitem(sys.modules, "gpiozero.pins", fake_pins)
    monkeypatch.setitem(sys.modules, "gpiozero.pins.pigpio", fake_pigpio)
    sys.modules.pop("hardware.servo", None)
    return importlib.import_module("hardware.servo")


def servo_config(**overrides):
    config = {
        "pin": 12,
        "min_angle": 0,
        "max_angle": 180,
        "min_pulse_width": 0.0005,
        "max_pulse_width": 0.0025,
        "frame_width": 0.02,
        "down_angle": 105,
        "up_angle": 45,
        "default_settle_time": 0.4,
        "detach_after_move": False,
        "pin_factory": "default",
    }
    config.update(overrides)
    return config


def test_servo_uses_angular_servo_settings(monkeypatch):
    module = load_servo_module(monkeypatch)

    servo = module.ServoMotor.from_config(servo_config())
    device = FakeAngularServo.instances[0]

    assert device.pin == 12
    assert device.min_angle == 0
    assert device.max_angle == 180
    assert device.min_pulse_width == 0.0005
    assert device.max_pulse_width == 0.0025
    assert device.frame_width == 0.02
    assert device.pin_factory is None

    sleeps = []
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))
    servo.set_angle(105)

    assert device.angles == [105]
    assert sleeps == [0.4]


def test_servo_can_detach_after_move(monkeypatch):
    module = load_servo_module(monkeypatch)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    servo = module.ServoMotor.from_config(servo_config(detach_after_move=True))
    device = FakeAngularServo.instances[0]

    servo.set_angle(45, settle_time=0.1)

    assert device.angles == [45]
    assert device.detached == 1


def test_pigpio_pin_factory_is_optional(monkeypatch):
    module = load_servo_module(monkeypatch)

    module.ServoMotor.from_config(servo_config(pin_factory="pigpio"))
    device = FakeAngularServo.instances[0]

    assert device.pin_factory is FakePiGPIOFactory.instances[0]


def test_controller_reloads_same_pin_servo_settings(monkeypatch):
    module = load_servo_module(monkeypatch)
    controller = module.ServoController.from_config({"page_drop": servo_config()})
    first_device = FakeAngularServo.instances[0]

    updated = servo_config(down_angle=90, min_pulse_width=0.0006)
    controller.reload_config({"page_drop": servo_config()}, {"page_drop": updated})

    assert first_device.closed is True
    assert len(FakeAngularServo.instances) == 2


def test_controller_skips_pin_change_until_restart(monkeypatch):
    module = load_servo_module(monkeypatch)
    controller = module.ServoController.from_config({"page_drop": servo_config()})
    first_device = FakeAngularServo.instances[0]

    updated = servo_config(pin=13)
    controller.reload_config({"page_drop": servo_config()}, {"page_drop": updated})

    assert first_device.closed is False
    assert len(FakeAngularServo.instances) == 1


def test_controller_cleanup_closes_all_servos(monkeypatch):
    module = load_servo_module(monkeypatch)
    controller = module.ServoController.from_config(
        {
            "page_drop": servo_config(),
            "left_assist": servo_config(pin=16),
        }
    )

    controller.cleanup()

    assert all(device.closed for device in FakeAngularServo.instances)
