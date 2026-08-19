import time

import RPi.GPIO as GPIO


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

    @property
    def steps_per_rev(self):
        return self._steps_per_rev

    def enable(self):
        GPIO.output(self._enable_pin, GPIO.LOW)

    def disable(self):
        GPIO.output(self._enable_pin, GPIO.HIGH)

    def move_steps(self, steps, clockwise=True, step_delay=None):
        delay = self._step_delay if step_delay is None else step_delay
        GPIO.output(self._dir_pin, GPIO.LOW if clockwise else GPIO.HIGH)
        self.enable()
        for _ in range(steps):
            GPIO.output(self._step_pin, GPIO.HIGH)
            time.sleep(delay)
            GPIO.output(self._step_pin, GPIO.LOW)
            time.sleep(delay)
        self.disable()

    def move_degrees(self, degrees, clockwise=True):
        steps = round(self._steps_per_rev * degrees / 360)
        self.move_steps(steps, clockwise)

    def cleanup(self):
        self.disable()
        GPIO.cleanup([self._step_pin, self._dir_pin, self._enable_pin])
