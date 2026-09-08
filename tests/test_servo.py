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
        "step_degrees": 3.0,
        "step_delay": 0.015,
        "approach_degrees": 40.0,
        "approach_step_degrees": 1.0,
        "approach_step_delay": 0.04,
        "departure_degrees": 10.0,
        "departure_step_degrees": 0.5,
        "departure_step_delay": 0.08,
        "max_hold_seconds": 10.0,
        "down_angle": 105,
        "up_angle": 45,
        "default_settle_time": 0.4,
        "detach_after_move": False,
        "pin_factory": "default",
    }
    config.update(overrides)
    return config


def ramp_config(**overrides):
    """A profile whose numbers divide cleanly, so steps can be asserted exactly."""
    return servo_config(
        step_degrees=10.0,
        step_delay=0.01,
        approach_degrees=20.0,
        approach_step_degrees=5.0,
        approach_step_delay=0.05,
        departure_degrees=20.0,
        departure_step_degrees=2.0,
        departure_step_delay=0.1,
        **overrides,
    )


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

    # Ramped, so the target is reached over many commands rather than one.
    assert device.angles[-1] == 105
    assert device.angles == sorted(device.angles)
    assert sleeps[-1] == 0.4


def test_servo_can_detach_after_move(monkeypatch):
    module = load_servo_module(monkeypatch)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    servo = module.ServoMotor.from_config(servo_config(detach_after_move=True))
    device = FakeAngularServo.instances[0]

    servo.set_angle(45, settle_time=0.1)

    assert device.angles[-1] == 45
    # Detached once, at the end - never between ramp steps, or the arm would go
    # limp mid-move.
    assert device.detached == 1


def test_ramp_slows_on_the_final_approach(monkeypatch):
    module = load_servo_module(monkeypatch)
    servo = module.ServoMotor.from_config(ramp_config())
    device = FakeAngularServo.instances[0]

    sleeps = []
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))
    servo.set_angle(100, settle_time=0.2)

    # Coarse 10-degree steps until 20 degrees remain, then 5-degree steps.
    # The boundary is inclusive, so the step out of 80 is already a slow one.
    assert device.angles == [10, 20, 30, 40, 50, 60, 70, 80, 85, 90, 95, 100]
    assert sleeps == [0.01] * 8 + [0.05] * 4 + [0.2]


def test_ramp_crawls_out_of_the_start_when_asked(monkeypatch):
    module = load_servo_module(monkeypatch)
    servo = module.ServoMotor.from_config(ramp_config())
    device = FakeAngularServo.instances[0]

    sleeps = []
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))
    servo.set_angle(100, settle_time=0.2, slow_start=True)

    # Fine 2-degree steps for the first 20 degrees, then the usual coarse run
    # and the slow final approach.
    assert device.angles == [
        2, 4, 6, 8, 10, 12, 14, 16, 18, 20,
        30, 40, 50, 60, 70, 80,
        85, 90, 95, 100,
    ]
    assert sleeps == [0.1] * 10 + [0.01] * 6 + [0.05] * 4 + [0.2]


def test_ramp_does_not_crawl_out_of_the_start_by_default(monkeypatch):
    module = load_servo_module(monkeypatch)
    servo = module.ServoMotor.from_config(ramp_config())
    device = FakeAngularServo.instances[0]

    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    servo.set_angle(100, settle_time=0.2)

    # Same move without the flag leaves at full speed.
    assert device.angles == [10, 20, 30, 40, 50, 60, 70, 80, 85, 90, 95, 100]


def test_short_move_crawls_throughout(monkeypatch):
    module = load_servo_module(monkeypatch)
    servo = module.ServoMotor.from_config(ramp_config())
    device = FakeAngularServo.instances[0]

    sleeps = []
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))
    servo.set_angle(6, settle_time=0.2, slow_start=True)

    # Shorter than departure_degrees, so it never picks up speed - departure
    # takes precedence over the approach profile where the two overlap.
    assert device.angles == [2, 4, 6]
    assert sleeps == [0.1] * 3 + [0.2]


def test_ramp_handles_a_downward_move(monkeypatch):
    module = load_servo_module(monkeypatch)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    servo = module.ServoMotor.from_config(ramp_config())
    device = FakeAngularServo.instances[0]

    servo.set_angle(100)
    device.angles.clear()
    servo.set_angle(0)

    assert device.angles == [90, 80, 70, 60, 50, 40, 30, 20, 15, 10, 5, 0]


def test_ramp_works_with_a_reversed_angle_range(monkeypatch):
    """The left clamp uses min_angle > max_angle to mirror its rotation."""
    module = load_servo_module(monkeypatch)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    servo = module.ServoMotor.from_config(ramp_config(min_angle=180, max_angle=0))
    device = FakeAngularServo.instances[0]

    servo.set_angle(90)

    # The ramp steps numerically and is indifferent to the mapping.
    assert device.angles == [10, 20, 30, 40, 50, 60, 70, 75, 80, 85, 90]
    assert device.min_angle == 180
    assert device.max_angle == 0


def test_repeat_angle_still_commands_the_servo(monkeypatch):
    module = load_servo_module(monkeypatch)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    servo = module.ServoMotor.from_config(ramp_config(detach_after_move=True))
    device = FakeAngularServo.instances[0]

    servo.set_angle(50)
    device.angles.clear()
    servo.set_angle(50)

    # Already in position, but a detached servo needs re-commanding to hold.
    assert device.angles == [50]


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


class FakeTimer:
    """Stands in for threading.Timer so hold tests never actually wait."""

    instances = []

    def __init__(self, interval, function):
        self.interval = interval
        self.function = function
        self.started = False
        self.cancelled = False
        self.daemon = False
        FakeTimer.instances.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.function()


def hold_servo(monkeypatch, **overrides):
    module = load_servo_module(monkeypatch)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    FakeTimer.instances = []
    monkeypatch.setattr(module.threading, "Timer", FakeTimer)
    servo = module.ServoMotor.from_config(
        servo_config(detach_after_move=True, **overrides)
    )
    return servo, FakeAngularServo.instances[0]


def test_hold_keeps_the_servo_powered(monkeypatch):
    servo, device = hold_servo(monkeypatch)

    servo.set_angle(90, hold=True)

    # Without hold this same config detaches - that is the whole point.
    assert device.detached == 0
    timer = FakeTimer.instances[0]
    assert timer.interval == 10.0
    assert timer.started is True
    assert timer.daemon is True


def test_default_path_still_detaches(monkeypatch):
    """The guarantee that adding hold changed nothing for existing callers."""
    servo, device = hold_servo(monkeypatch)

    servo.set_angle(90)

    assert device.detached == 1
    assert FakeTimer.instances == []


def test_detach_cancels_the_hold_timer(monkeypatch):
    servo, device = hold_servo(monkeypatch)
    servo.set_angle(90, hold=True)

    servo.detach()

    assert FakeTimer.instances[0].cancelled is True
    assert device.detached == 1


def test_hold_timer_releases_when_nothing_lifts(monkeypatch):
    servo, device = hold_servo(monkeypatch, max_hold_seconds=2.5)
    servo.set_angle(90, hold=True)

    assert FakeTimer.instances[0].interval == 2.5
    FakeTimer.instances[0].fire()

    assert device.detached == 1


def test_cleanup_cancels_the_hold_timer(monkeypatch):
    servo, device = hold_servo(monkeypatch)
    servo.set_angle(90, hold=True)

    servo.cleanup()

    assert FakeTimer.instances[0].cancelled is True
    assert device.closed is True


def test_a_second_hold_replaces_the_first_timer(monkeypatch):
    servo, _ = hold_servo(monkeypatch)
    servo.set_angle(90, hold=True)

    servo.set_angle(45, hold=True)

    first, second = FakeTimer.instances
    assert first.cancelled is True
    assert second.cancelled is False


def test_set_angle_reports_reaching_the_target(monkeypatch):
    module = load_servo_module(monkeypatch)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    servo = module.ServoMotor.from_config(ramp_config())

    assert servo.set_angle(90) is True


def test_abort_stops_the_ramp_and_says_so(monkeypatch):
    module = load_servo_module(monkeypatch)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    servo = module.ServoMotor.from_config(ramp_config())
    device = FakeAngularServo.instances[0]

    calls = {"n": 0}

    def abort_after_2():
        calls["n"] += 1
        return calls["n"] > 2

    assert servo.set_angle(90, abort_check=abort_after_2) is False
    assert len(device.angles) == 2


def test_an_aborted_ramp_leaves_an_honest_position(monkeypatch):
    """_last_angle must track the ramp, not jump to the target at the end.

    Left stale, the next move would ramp from where this one began - so the arm
    would snap back across everything it already travelled before setting off.
    """
    module = load_servo_module(monkeypatch)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    servo = module.ServoMotor.from_config(ramp_config())
    device = FakeAngularServo.instances[0]

    calls = {"n": 0}
    servo.set_angle(90, abort_check=lambda: (calls.update(n=calls["n"] + 1), calls["n"] > 3)[1])

    stopped_at = device.angles[-1]
    device.angles.clear()
    servo.set_angle(90)

    # The resumed ramp starts from where the arm actually is, not from 0.
    assert device.angles[0] != 0
    assert min(device.angles) >= stopped_at
