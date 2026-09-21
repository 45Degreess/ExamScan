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
        invert_direction=False,
    ):
        self._step_pin = step_pin
        self._dir_pin = dir_pin
        self._enable_pin = enable_pin
        self._steps_per_rev = steps_per_rev
        self._step_delay = step_delay
        self._fast_delay = fast_delay
        #Keeps direction consistent with the motor's physical orientation, so that clockwise is always clockwise.
        self._invert_direction = invert_direction

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
            invert_direction=config["invert_direction"],
        )

    @property
    def steps_per_rev(self):
        return self._steps_per_rev

    def enable(self):
        GPIO.output(self._enable_pin, GPIO.LOW)

    def disable(self):
        GPIO.output(self._enable_pin, GPIO.HIGH)

    def move_steps(
        self,
        steps,
        clockwise=True,
        step_delay=None,
        keep_enabled=False,
        abort_check=None,
    ):
        """Pulse out `steps`, returning how many were actually done.

        keep_enabled leaves the coils powered so the motor holds position
        against a load.

        abort_check is polled once per step; returning True stops the move
        where it stands. The count comes back so the caller can pick up the
        remainder later - re-issuing the whole move instead would turn the
        wheel by however far it already got, twice.
        """
        delay = self._step_delay if step_delay is None else step_delay
        turn_cw = clockwise != self._invert_direction
        GPIO.output(self._dir_pin, GPIO.LOW if turn_cw else GPIO.HIGH)
        self.enable()
        done = 0
        for _ in range(steps):
            if abort_check is not None and abort_check():
                break
            GPIO.output(self._step_pin, GPIO.HIGH)
            time.sleep(delay)
            GPIO.output(self._step_pin, GPIO.LOW)
            time.sleep(delay)
            done += 1
        if not keep_enabled and done == steps:
            self.disable()
        return done

    def move_degrees(self, degrees, clockwise=True, keep_enabled=False, abort_check=None):
        steps = round(self._steps_per_rev * degrees / 360)
        return self.move_steps(
            steps, clockwise, keep_enabled=keep_enabled, abort_check=abort_check
        )

    def cleanup(self):
        self.disable()
        GPIO.cleanup([self._step_pin, self._dir_pin, self._enable_pin])
