import importlib
import sys
import types

import pytest


class FakeDirectionDevice:
    def __init__(self, name):
        self.name = name
        self.actions = []

    def on(self):
        self.actions.append("on")


class FakeMotorDevice:
    instances = []

    def __init__(self, forward, backward, pwm=True):
        self.forward_pin = forward
        self.backward_pin = backward
        self.pwm = pwm
        self.forward_calls = []
        self.backward_calls = []
        self.stops = 0
        self.closed = False
        self.forward_device = FakeDirectionDevice("forward")
        self.backward_device = FakeDirectionDevice("backward")
        self.instances.append(self)

    def forward(self, speed=1):
        self.forward_calls.append(speed)

    def backward(self, speed=1):
        self.backward_calls.append(speed)

    def stop(self):
        self.stops += 1

    def close(self):
        self.closed = True


class FakePWMOutputDevice:
    instances = []

    def __init__(self, pin, frequency):
        self.pin = pin
        self.frequency = frequency
        self.values = []
        self.closed = False
        self.instances.append(self)

    @property
    def value(self):
        return self.values[-1] if self.values else 0

    @value.setter
    def value(self, value):
        self.values.append(value)

    def close(self):
        self.closed = True


class FakeGPIO(types.ModuleType):
    BCM = "BCM"
    OUT = "OUT"
    HIGH = 1
    LOW = 0


def load_dc_motor(monkeypatch):
    FakeMotorDevice.instances = []
    FakePWMOutputDevice.instances = []
    fake_gpiozero = types.ModuleType("gpiozero")
    fake_gpiozero.Motor = FakeMotorDevice
    fake_gpiozero.PWMOutputDevice = FakePWMOutputDevice
    fake_rpi = types.ModuleType("RPi")
    fake_rpi.GPIO = FakeGPIO("RPi.GPIO")
    monkeypatch.setitem(sys.modules, "gpiozero", fake_gpiozero)
    monkeypatch.setitem(sys.modules, "RPi", fake_rpi)
    monkeypatch.setitem(sys.modules, "RPi.GPIO", fake_rpi.GPIO)
    sys.modules.pop("hardware.motor", None)
    module = importlib.import_module("hardware.motor")
    return module.DCMotor, module


def test_forward_reverse_stop_and_brake(monkeypatch):
    DCMotor, _ = load_dc_motor(monkeypatch)
    motor = DCMotor(5, 6, enable_pin=13, pwm_freq=100, default_speed=80)
    device = FakeMotorDevice.instances[0]
    enable = FakePWMOutputDevice.instances[0]

    assert device.forward_pin == 5
    assert device.backward_pin == 6
    assert device.pwm is False
    assert enable.pin == 13
    assert enable.frequency == 100

    motor.forward()
    assert device.forward_calls[-1] == 1
    assert enable.values[-1] == 0.8

    motor.reverse(40)
    assert device.backward_calls[-1] == 1
    assert enable.values[-1] == 0.4

    motor.stop()
    assert device.stops >= 1
    assert enable.values[-1] == 0

    motor.brake()
    assert device.forward_device.actions[-1] == "on"
    assert device.backward_device.actions[-1] == "on"
    assert enable.values[-1] == 0


def test_speed_is_clamped(monkeypatch):
    DCMotor, _ = load_dc_motor(monkeypatch)
    motor = DCMotor(5, 6, enable_pin=13)
    enable = FakePWMOutputDevice.instances[0]

    assert motor.set_speed(-20) == 0
    assert enable.values[-1] == 0
    assert motor.set_speed(125) == 100
    assert enable.values[-1] == 1


def test_motor_without_enable_uses_internal_pwm_speed(monkeypatch):
    DCMotor, _ = load_dc_motor(monkeypatch)
    motor = DCMotor(5, 6, enable_pin=None, default_speed=55)
    device = FakeMotorDevice.instances[0]

    assert device.pwm is True
    motor.forward()
    motor.reverse(25)

    assert device.forward_calls[-1] == pytest.approx(0.55)
    assert device.backward_calls[-1] == pytest.approx(0.25)


def test_run_for_stops_or_brakes(monkeypatch):
    DCMotor, module = load_dc_motor(monkeypatch)
    sleeps = []
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))
    motor = DCMotor(5, 6, enable_pin=13)
    device = FakeMotorDevice.instances[0]

    motor.run_for(1.5, speed=55, forward=False)
    assert sleeps == [1.5]
    assert device.stops >= 1

    motor.run_for(0.25, speed=55, forward=True, brake=True)
    assert sleeps == [1.5, 0.25]
    assert device.forward_device.actions[-1] == "on"
    assert device.backward_device.actions[-1] == "on"


def test_cleanup_closes_gpiozero_devices(monkeypatch):
    DCMotor, _ = load_dc_motor(monkeypatch)
    motor = DCMotor(5, 6, enable_pin=13)
    device = FakeMotorDevice.instances[0]
    enable = FakePWMOutputDevice.instances[0]

    motor.cleanup()

    assert device.closed is True
    assert enable.closed is True
