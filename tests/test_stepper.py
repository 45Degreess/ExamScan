import importlib
import sys
import types


class FakeGPIO:
    """Enough of the RPi.GPIO surface for StepperMotor, recording writes."""

    BCM = "BCM"
    OUT = "OUT"
    LOW = 0
    HIGH = 1

    def __init__(self):
        self.outputs = []
        self.cleaned = None

    def setmode(self, mode):
        self.mode = mode

    def setup(self, pins, direction):
        self.pins = pins

    def output(self, pin, value):
        self.outputs.append((pin, value))

    def cleanup(self, pins):
        self.cleaned = pins


def load_motor_module(monkeypatch, gpio):
    fake_rpi = types.ModuleType("RPi")
    fake_gpio_mod = types.ModuleType("RPi.GPIO")
    for name in ("BCM", "OUT", "LOW", "HIGH"):
        setattr(fake_gpio_mod, name, getattr(gpio, name))
    for name in ("setmode", "setup", "output", "cleanup"):
        setattr(fake_gpio_mod, name, getattr(gpio, name))
    fake_rpi.GPIO = fake_gpio_mod

    fake_gpiozero = types.ModuleType("gpiozero")
    fake_gpiozero.Motor = object
    fake_gpiozero.PWMOutputDevice = object

    monkeypatch.setitem(sys.modules, "RPi", fake_rpi)
    monkeypatch.setitem(sys.modules, "RPi.GPIO", fake_gpio_mod)
    monkeypatch.setitem(sys.modules, "gpiozero", fake_gpiozero)
    sys.modules.pop("hardware.motor", None)
    return importlib.import_module("hardware.motor")


def motor_config(**overrides):
    config = {
        "step_pin": 21,
        "dir_pin": 20,
        "enable_pin": 16,
        "steps_per_rev": 1600,
        "step_delay": 0.0,
        "fast_delay": 0.0,
        "invert_direction": False,
    }
    config.update(overrides)
    return config


def build(module, **overrides):
    return module.StepperMotor.from_config(motor_config(**overrides))


def test_starts_de_energised(monkeypatch):
    gpio = FakeGPIO()
    module = load_motor_module(monkeypatch, gpio)

    build(module)

    # ENABLE is active low, so idle must leave it high or the coils stay live.
    assert gpio.outputs[-1] == (16, gpio.HIGH)


def test_move_steps_pulses_once_per_step(monkeypatch):
    gpio = FakeGPIO()
    module = load_motor_module(monkeypatch, gpio)
    motor = build(module)

    motor.move_steps(5)

    assert gpio.outputs.count((21, gpio.HIGH)) == 5
    assert gpio.outputs.count((21, gpio.LOW)) == 5
    # De-energised again at the end of the move.
    assert gpio.outputs[-1] == (16, gpio.HIGH)


def test_direction_pin_follows_the_argument(monkeypatch):
    gpio = FakeGPIO()
    module = load_motor_module(monkeypatch, gpio)
    motor = build(module)

    motor.move_steps(1, clockwise=True)
    assert (20, gpio.LOW) in gpio.outputs

    gpio.outputs.clear()
    motor.move_steps(1, clockwise=False)
    assert (20, gpio.HIGH) in gpio.outputs


def test_move_degrees_converts_through_steps_per_rev(monkeypatch):
    gpio = FakeGPIO()
    module = load_motor_module(monkeypatch, gpio)
    motor = build(module)

    motor.move_degrees(90)

    # 1600 pulses per revolution at 1/8 microstepping, so a quarter turn is 400.
    assert gpio.outputs.count((21, gpio.HIGH)) == 400


def test_cleanup_releases_only_its_own_pins(monkeypatch):
    gpio = FakeGPIO()
    module = load_motor_module(monkeypatch, gpio)
    motor = build(module)

    motor.cleanup()

    assert gpio.cleaned == [21, 20, 16]


def dir_level_for(monkeypatch, clockwise, **overrides):
    """The level written to the DIR pin for a given requested direction."""
    gpio = FakeGPIO()
    module = load_motor_module(monkeypatch, gpio)
    motor = build(module, **overrides)
    gpio.outputs.clear()
    motor.move_steps(1, clockwise=clockwise)
    return next(value for pin, value in gpio.outputs if pin == 20)


def test_invert_direction_flips_the_dir_level(monkeypatch):
    """Which DIR level means clockwise is a per-motor wiring fact."""
    plain = dir_level_for(monkeypatch, clockwise=True)
    inverted = dir_level_for(monkeypatch, clockwise=True, invert_direction=True)

    assert plain != inverted


def test_invert_direction_still_distinguishes_the_two_directions(monkeypatch):
    """Inverting must swap both senses, not collapse them onto one level."""
    cw = dir_level_for(monkeypatch, clockwise=True, invert_direction=True)
    ccw = dir_level_for(monkeypatch, clockwise=False, invert_direction=True)

    assert cw != ccw
