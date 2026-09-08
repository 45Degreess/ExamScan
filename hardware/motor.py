import time

from gpiozero import Motor as GpioZeroMotor
from gpiozero import PWMOutputDevice
import RPi.GPIO as GPIO


class DCMotor:
    def __init__(
        self,
        in1_pin,
        in2_pin,
        enable_pin=None,
        pwm_freq=100,
        default_speed=100,
        motor_class=GpioZeroMotor,
        pwm_class=PWMOutputDevice,
    ):
        self._in1_pin = in1_pin
        self._in2_pin = in2_pin
        self._enable_pin = enable_pin
        self._pwm_freq = pwm_freq
        self._default_speed = self._clamp_speed(default_speed)
        self._speed = 0
        self._enable = None

        if self._enable_pin is not None:
            self._enable = pwm_class(self._enable_pin, frequency=self._pwm_freq)
            self._motor = motor_class(
                forward=self._in1_pin,
                backward=self._in2_pin,
                pwm=False,
            )
        else:
            self._motor = motor_class(
                forward=self._in1_pin,
                backward=self._in2_pin,
                pwm=True,
            )

        self.stop()

    @classmethod
    def from_config(cls, config):
        return cls(
            in1_pin=config["in1_pin"],
            in2_pin=config["in2_pin"],
            enable_pin=config["enable_pin"],
            pwm_freq=config["pwm_freq"],
            default_speed=config["default_speed"],
        )

    def set_speed(self, speed):
        self._speed = self._clamp_speed(speed)
        if self._enable is not None:
            self._enable.value = self._speed_fraction
        return self._speed

    def forward(self, speed=None):
        self.set_speed(self._default_speed if speed is None else speed)
        self._motor.forward(self._run_speed)

    def reverse(self, speed=None):
        self.set_speed(self._default_speed if speed is None else speed)
        self._motor.backward(self._run_speed)

    def stop(self):
        self._motor.stop()
        self.set_speed(0)

    def brake(self):
        self.set_speed(0)
        self._motor.forward_device.on()
        self._motor.backward_device.on()

    def run_for(self, seconds, speed=None, forward=True, brake=False):
        if seconds < 0:
            raise ValueError("seconds must be at least 0")

        if forward:
            self.forward(speed)
        else:
            self.reverse(speed)

        time.sleep(seconds)
        if brake:
            self.brake()
        else:
            self.stop()

    def cleanup(self):
        self.stop()
        self._motor.close()
        if self._enable is not None:
            self._enable.close()

    def _clamp_speed(self, speed):
        return max(0, min(100, float(speed)))

    @property
    def _speed_fraction(self):
        return self._speed / 100

    @property
    def _run_speed(self):
        if self._enable is not None:
            return 1
        return self._speed_fraction


class StepperMotor:
    def __init__(
        self,
        step_pin,
        dir_pin,
        enable_pin,
        steps_per_rev,
        step_delay,
        fast_delay,
    ):
        self._step_pin = step_pin
        self._dir_pin = dir_pin
        self._enable_pin = enable_pin
        self._steps_per_rev = steps_per_rev
        self._step_delay = step_delay
        self._fast_delay = fast_delay

        GPIO.setmode(GPIO.BCM)
        GPIO.setup([step_pin, dir_pin, enable_pin], GPIO.OUT)
        self.disable()

    @classmethod
    def from_config(cls, config):
        return cls(
            step_pin=config["step_pin"],
            dir_pin=config["dir_pin"],
            enable_pin=config["enable_pin"],
            steps_per_rev=config["steps_per_rev"],
            step_delay=config["step_delay"],
            fast_delay=config["fast_delay"],
        )

    def enable(self):
        GPIO.output(self._enable_pin, GPIO.LOW)  

    def disable(self):
        GPIO.output(self._enable_pin, GPIO.HIGH)

    def move_steps(self, steps, clockwise=True):
        GPIO.output(self._dir_pin, GPIO.LOW if clockwise else GPIO.HIGH)
        self.enable()
        for _ in range(steps):
            GPIO.output(self._step_pin, GPIO.HIGH)
            time.sleep(self._step_delay)
            GPIO.output(self._step_pin, GPIO.LOW)
            time.sleep(self._step_delay)
        self.disable()

    def move_degrees(self, degrees, clockwise=True):
        steps = round(self._steps_per_rev * degrees / 360)
        self.move_steps(steps, clockwise)

    def cleanup(self):
        self.disable()
        GPIO.cleanup([self._step_pin, self._dir_pin, self._enable_pin])
