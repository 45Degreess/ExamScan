import time
import RPi.GPIO as GPIO

STEP_PIN = 21
DIR_PIN = 20
ENABLE_PIN = 16
STEPS_PER_REV = 200   # 200 for full step 
STEP_DELAY = 0.005    # seconds between pulses 


class StepperMotor:
    def __init__(
        self,
        step_pin=STEP_PIN,
        dir_pin=DIR_PIN,
        enable_pin=ENABLE_PIN,
        steps_per_rev=STEPS_PER_REV,
        step_delay=STEP_DELAY,
    ):
        self._step_pin = step_pin
        self._dir_pin = dir_pin
        self._enable_pin = enable_pin
        self._steps_per_rev = steps_per_rev
        self._step_delay = step_delay

        GPIO.setmode(GPIO.BCM)
        GPIO.setup([step_pin, dir_pin, enable_pin], GPIO.OUT)
        self.disable()

    def enable(self):
        GPIO.output(self._enable_pin, GPIO.LOW)  

    def disable(self):
        GPIO.output(self._enable_pin, GPIO.HIGH)

    def move_steps(self, steps, clockwise=True):
        GPIO.output(self._dir_pin, GPIO.HIGH if clockwise else GPIO.LOW)
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
        GPIO.cleanup()
