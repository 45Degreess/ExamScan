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
        default_settle_time=0.4,
        detach_after_move=False,
        pin_factory="default",
        servo_class=AngularServo,
    ):
        self.pin = pin
        self.default_settle_time = default_settle_time
        self.detach_after_move = detach_after_move
        self._config = {
            "pin": pin,
            "min_angle": min_angle,
            "max_angle": max_angle,
            "min_pulse_width": min_pulse_width,
            "max_pulse_width": max_pulse_width,
            "frame_width": frame_width,
            "default_settle_time": default_settle_time,
            "detach_after_move": detach_after_move,
            "pin_factory": pin_factory,
        }
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
            default_settle_time=config["default_settle_time"],
            detach_after_move=config["detach_after_move"],
            pin_factory=config["pin_factory"],
        )

    def set_angle(self, degrees, settle_time=None):
        self._servo.angle = degrees
        time.sleep(self.default_settle_time if settle_time is None else settle_time)
        if self.detach_after_move:
            self.detach()

    def detach(self):
        self._servo.detach()

    def cleanup(self):
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
