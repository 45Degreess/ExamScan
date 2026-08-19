import threading
import time

from gpiozero import AngularServo


class ServoMotor:
    def __init__(
        self,
        pin,
        min_angle,
        max_angle,
        min_pulse_width,
        max_pulse_width,
        frame_width,
        step_degrees=3.0,
        step_delay=0.015,
        approach_degrees=40.0,
        approach_step_degrees=1.0,
        approach_step_delay=0.04,
        departure_degrees=10.0,
        departure_step_degrees=0.5,
        departure_step_delay=0.08,
        max_hold_seconds=10.0,
        default_settle_time=0.4,
        detach_after_move=False,
        pin_factory="default",
        servo_class=AngularServo,
    ):
        self.pin = pin
        self.step_degrees = step_degrees
        self.step_delay = step_delay
        self.approach_degrees = approach_degrees
        self.approach_step_degrees = approach_step_degrees
        self.approach_step_delay = approach_step_delay
        self.departure_degrees = departure_degrees
        self.departure_step_degrees = departure_step_degrees
        self.departure_step_delay = departure_step_delay
        self.max_hold_seconds = max_hold_seconds
        self.default_settle_time = default_settle_time
        self.detach_after_move = detach_after_move
        self._config = {
            "pin": pin,
            "min_angle": min_angle,
            "max_angle": max_angle,
            "min_pulse_width": min_pulse_width,
            "max_pulse_width": max_pulse_width,
            "frame_width": frame_width,
            "step_degrees": step_degrees,
            "step_delay": step_delay,
            "approach_degrees": approach_degrees,
            "approach_step_degrees": approach_step_degrees,
            "approach_step_delay": approach_step_delay,
            "departure_degrees": departure_degrees,
            "departure_step_degrees": departure_step_degrees,
            "departure_step_delay": departure_step_delay,
            "max_hold_seconds": max_hold_seconds,
            "default_settle_time": default_settle_time,
            "detach_after_move": detach_after_move,
            "pin_factory": pin_factory,
        }
        # AngularServo's initial_angle defaults to 0.0, so that is where the
        # shaft actually parks on construction. Tracked here rather than read
        # back from the device because a detached servo reports angle None,
        # which would lose the ramp's starting point after the first move.
        self._last_angle = 0.0
        self._hold_timer = None
        self._servo = servo_class(
            pin,
            min_angle=min_angle,
            max_angle=max_angle,
            min_pulse_width=min_pulse_width,
            max_pulse_width=max_pulse_width,
            frame_width=frame_width,
            pin_factory=self._make_pin_factory(pin_factory),
        )

    @classmethod
    def from_config(cls, config):
        return cls(
            pin=config["pin"],
            min_angle=config["min_angle"],
            max_angle=config["max_angle"],
            min_pulse_width=config["min_pulse_width"],
            max_pulse_width=config["max_pulse_width"],
            frame_width=config["frame_width"],
            step_degrees=config["step_degrees"],
            step_delay=config["step_delay"],
            approach_degrees=config["approach_degrees"],
            approach_step_degrees=config["approach_step_degrees"],
            approach_step_delay=config["approach_step_delay"],
            departure_degrees=config["departure_degrees"],
            departure_step_degrees=config["departure_step_degrees"],
            departure_step_delay=config["departure_step_delay"],
            max_hold_seconds=config["max_hold_seconds"],
            default_settle_time=config["default_settle_time"],
            detach_after_move=config["detach_after_move"],
            pin_factory=config["pin_factory"],
        )

    def _steps(self, start, target, slow_start=False):
        """Yield (angle, delay) stepping from start to target.

        Steps shrink and slow once within approach_degrees of the target, so the
        arm creeps into position instead of slamming into it and overshooting.
        With slow_start, the first departure_degrees are crawled as well, so the
        arm peels off the page rather than flicking it.
        """
        direction = 1 if target >= start else -1
        angle = start
        while angle != target:
            remaining = abs(target - angle)
            departing = slow_start and abs(angle - start) < self.departure_degrees
            approaching = remaining <= self.approach_degrees
            # Departure wins where the two overlap, so a move shorter than
            # departure_degrees crawls throughout instead of picking up speed.
            if departing:
                size = self.departure_step_degrees
                delay = self.departure_step_delay
            elif approaching:
                size = self.approach_step_degrees
                delay = self.approach_step_delay
            else:
                size = self.step_degrees
                delay = self.step_delay
            # Snapping to target on the final step keeps float drift from
            # leaving the arm a fraction short or past the mark.
            angle = target if remaining <= size else angle + direction * size
            yield angle, delay

    def set_angle(self, degrees, settle_time=None, slow_start=False, hold=False):
        steps = list(self._steps(self._last_angle, degrees, slow_start))
        if not steps:
            # Already there - still command it, so a detached servo re-engages.
            steps = [(degrees, 0.0)]

        for angle, delay in steps:
            self._servo.angle = angle
            time.sleep(delay)

        self._last_angle = degrees
        time.sleep(self.default_settle_time if settle_time is None else settle_time)
        # Only after the whole ramp - detaching between steps would let the arm
        # go limp mid-move.
        if hold:
            self._start_hold()
        elif self.detach_after_move:
            self.detach()

    def _start_hold(self):
        """Stay powered so the servo actually grips, with a safety cut-off.

        A held servo draws near-stall current and warms up, so the timer is a
        backstop for a release that never comes. detach() cancels it, so the
        normal path - hold, then lift - never waits for the timeout.
        """
        self._cancel_hold()
        self._hold_timer = threading.Timer(self.max_hold_seconds, self.detach)
        # Daemon, or a pending timer keeps the interpreter alive after a script
        # has finished.
        self._hold_timer.daemon = True
        self._hold_timer.start()

    def _cancel_hold(self):
        if self._hold_timer is not None:
            self._hold_timer.cancel()
            self._hold_timer = None

    def detach(self):
        self._cancel_hold()
        self._servo.detach()

    def cleanup(self):
        self._cancel_hold()
        self._servo.close()

    @staticmethod
    def _make_pin_factory(pin_factory):
        if pin_factory == "default":
            return None
        if pin_factory == "pigpio":
            from gpiozero.pins.pigpio import PiGPIOFactory

            return PiGPIOFactory()
        raise ValueError("pin_factory must be 'default' or 'pigpio'")


class ServoController:
    def __init__(self, servos):
        self._servos = servos

    @classmethod
    def from_config(cls, config):
        return cls(
            {
                name: ServoMotor.from_config(servo_config)
                for name, servo_config in config.items()
            }
        )

    @property
    def page_drop(self):
        return self._servos["page_drop"]

    @property
    def page_clamp_left(self):
        return self._servos["page_clamp_left"]

    def get(self, name):
        return self._servos[name]

    def reload_config(self, old_config, new_config):
        for name, servo_config in new_config.items():
            if name not in self._servos:
                continue
            if old_config.get(name, {}).get("pin") != servo_config["pin"]:
                continue
            if old_config.get(name) != servo_config:
                self._servos[name].cleanup()
                self._servos[name] = ServoMotor.from_config(servo_config)

    def cleanup(self):
        for servo in self._servos.values():
            servo.cleanup()
