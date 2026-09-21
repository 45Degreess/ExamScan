from __future__ import annotations

import shutil
import tomllib
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any


SERVICE_ROOT = Path(__file__).resolve().parents[2]
# Kept as a compatibility alias for run/model path resolution.
PROJECT_ROOT = SERVICE_ROOT
CONFIG_PATH = SERVICE_ROOT / "config" / "default.toml"


DEFAULT_CONFIG: dict[str, Any] = {
    "server": {
        "host": "0.0.0.0",
        "port": 8000,
        "cors_enabled": True,
        "cors_allowed_origins": ["*"],
    },
    "paths": {
        "runs_dir": "runs",
    },
    "camera": {
        "lens_position": 0.94,
        "preview_width": 1920,
        "preview_height": 1080,
        "capture_width": 4608,
        "capture_height": 2592,
        "frame_rate": 30,
        "buffer_count": 6,
        "lores_width": 960,
        "lores_height": 540,
        "exposure_mode": "short",
        "recording_start_delay": 3.0,
        "capture_stop_delay": 0.2,
        "capture_settle_delay": 0.5,
        "capture_restart_delay": 0.2,
    },
    "motor": {
        "step_pin": 21,
        "dir_pin": 20,
        "enable_pin": 16,
        "steps_per_rev": 1600,
        "step_delay": 0.002,
        "fast_delay": 0.001,
        "default_turn_seconds": 3.0,
        "default_degrees": 190.0,
        "default_clockwise": False,
        "invert_direction": False,
        "page_turn_degrees": 115.0,
        "shared_degrees": 80.0,
        "return_short_degrees": 10.0,
    },
    "motor2": {
        "step_pin": 24,
        "dir_pin": 23,
        "enable_pin": 25,
        # DRV8825 with MS1/MS2/MS3 unconnected: full step, 200 per revolution.
        # The TMC2209 on [motor] runs 1/8 microstepping, hence its 1600.
        "steps_per_rev": 200,
        "step_delay": 0.004,
        "fast_delay": 0.001,
        "default_degrees": 190.0,
        "default_clockwise": False,
        "invert_direction": True,
        "page_turn_degrees": 90.0,
        "preposition_degrees": 60.0,
        "shared_degrees": 80.0,
        "return_short_degrees": 0.0,
    },
    "servos": {
        "page_drop": {
            "pin": 22,
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
            "down_angle": 95,
            "up_angle": 0,
            "default_settle_time": 0.4,
            "detach_after_move": True,
            "pin_factory": "pigpio",
        },
        "page_clamp_big": {
            "pin": 13,
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
            "down_angle": 73,
            "up_angle": 0,
            "contact_angle": 105,
            "hold_angle": 102,
            "use_hold": True,
            "default_settle_time": 0.4,
            "detach_after_move": True,
            "pin_factory": "pigpio",
        },
        "page_clamp_small": {
            "pin": 27,
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
            "down_angle": 90,
            "up_angle": 0,
            "contact_angle": 85,
            "hold_angle": 82,
            "use_hold": True,
            "default_settle_time": 0.4,
            "detach_after_move": True,
            "pin_factory": "pigpio",
        },
    },
    "fan": {
        "pin": 19,
        "frequency_hz": 25000,
        "min_start_duty_pct": 10,
        "tach_pin": 17,
        "tach_pulses_per_rev": 2,
        "duty_pct": 100,
        "spinup_seconds": 3.0,
    },
    "obstruction": {
        "enabled": False,
        "mode": "full",
        "model_path": "models/hand_detector.tflite",
        "landmark_model_path": "models/hand_landmarks_detector.tflite",
        "min_confidence": 0.3,
        "min_presence_confidence": 0.5,
        "min_candidate_presence_confidence": 0.01,
        "max_hands": 2,
        "inference_threads": 4,
        "poll_interval": 0.1,
        "target_interval": 0.1,
        "source_width": 960,
        "source_height": 540,
        # A full-frame default is deliberately fail-safe. Calibrate this from a
        # known-safe preview before narrowing it to the physical scan bed.
        "bed_roi": [0.0, 0.0, 1.0, 1.0],
        "region_schedule": ["bed", "bed", "full"],
        "debug_overlay": False,
        "clear_frames": 5,
        "stale_after_seconds": 3.0,
        "wait_timeout_seconds": 30.0,
    },
    "workflow": {
        "turn_sequence": "shared",
        "clamp_down_pause": 1.0,
        "servo_down_pause": 1.0,
        "clamp_up_pause": 0.5,
        "stepper_pause": 1.0,
        "servo_up_pause": 1.0,
        "small_clamp_hold_seconds": 3.0,
        "motor_pause": 1.0,
        "default_pages": 6,
    },
}


REQUIRED_SECTIONS = set(DEFAULT_CONFIG)
LIVE_SECTIONS = {"server", "paths", "workflow"}
RESTART_FIELDS = {
    "motor": {"step_pin", "dir_pin", "enable_pin"},
    "motor2": {"step_pin", "dir_pin", "enable_pin"},
    "fan": {"pin", "tach_pin"},
}


class ConfigError(ValueError):
    pass


class ConfigManager:
    def __init__(self, path: Path = CONFIG_PATH):
        self.path = path

    def ensure_exists(self) -> None:
        if not self.path.exists():
            self.path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")

    def load(self) -> dict[str, Any]:
        self.ensure_exists()
        return self.parse(self.path.read_bytes())

    def read_bytes(self) -> bytes:
        self.ensure_exists()
        return self.path.read_bytes()

    def parse(self, data: bytes) -> dict[str, Any]:
        try:
            loaded = tomllib.loads(data.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise ConfigError("config must be UTF-8 TOML") from exc
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"invalid TOML: {exc}") from exc

        missing = REQUIRED_SECTIONS.difference(loaded)
        if missing:
            raise ConfigError(f"missing required section(s): {', '.join(sorted(missing))}")

        config = deepcopy(DEFAULT_CONFIG)
        for section, values in loaded.items():
            if section not in DEFAULT_CONFIG:
                raise ConfigError(f"unknown section: {section}")
            if not isinstance(values, dict):
                raise ConfigError(f"section [{section}] must be a table")
            config[section] = self._deep_merge(config[section], values)

        self._validate(config)
        return config

    def save_uploaded(self, data: bytes) -> dict[str, Any]:
        config = self.parse(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            backup = self.path.with_name(
                f"{self.path.name}.{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak"
            )
            shutil.copy2(self.path, backup)
        self.path.write_bytes(data)
        return config

    def restart_required(
        self, old_config: dict[str, Any], new_config: dict[str, Any]
    ) -> bool:
        for field in ("lores_width", "lores_height", "exposure_mode"):
            if old_config["camera"][field] != new_config["camera"][field]:
                return True
        if old_config["obstruction"] != new_config["obstruction"]:
            return True
        for section, fields in RESTART_FIELDS.items():
            for field in fields:
                if old_config[section][field] != new_config[section][field]:
                    return True
        for name in set(old_config["servos"]) | set(new_config["servos"]):
            old_pin = old_config["servos"].get(name, {}).get("pin")
            new_pin = new_config["servos"].get(name, {}).get("pin")
            if old_pin != new_pin:
                return True
        return False

    def applied_live_sections(
        self, old_config: dict[str, Any], new_config: dict[str, Any]
    ) -> list[str]:
        applied = [
            section
            for section in sorted(LIVE_SECTIONS)
            if section != "server" and old_config.get(section) != new_config.get(section)
        ]
        if (
            old_config["server"]["cors_enabled"] != new_config["server"]["cors_enabled"]
            or old_config["server"]["cors_allowed_origins"]
            != new_config["server"]["cors_allowed_origins"]
        ):
            applied.append("server.cors")
        if (
            old_config["motor"]["default_turn_seconds"]
            != new_config["motor"]["default_turn_seconds"]
            or old_config["motor"]["default_clockwise"]
            != new_config["motor"]["default_clockwise"]
        ):
            applied.append("motor.defaults")
        if (
            old_config["motor2"]["default_degrees"]
            != new_config["motor2"]["default_degrees"]
            or old_config["motor2"]["default_clockwise"]
            != new_config["motor2"]["default_clockwise"]
        ):
            applied.append("motor2.defaults")
        if (
            old_config["fan"]["min_start_duty_pct"]
            != new_config["fan"]["min_start_duty_pct"]
            or old_config["fan"]["tach_pulses_per_rev"]
            != new_config["fan"]["tach_pulses_per_rev"]
        ):
            applied.append("fan.defaults")
        for name in sorted(set(old_config["servos"]) | set(new_config["servos"])):
            old_servo = old_config["servos"].get(name)
            new_servo = new_config["servos"].get(name)
            if not old_servo or not new_servo:
                continue
            old_live = {key: value for key, value in old_servo.items() if key != "pin"}
            new_live = {key: value for key, value in new_servo.items() if key != "pin"}
            if old_servo["pin"] == new_servo["pin"] and old_live != new_live:
                applied.append(f"servos.{name}")
        return applied

    def _validate(self, config: dict[str, Any]) -> None:
        server = config["server"]
        self._require_str(server, "host", "server")
        self._require_int(server, "port", "server", minimum=1, maximum=65535)
        self._require_bool(server, "cors_enabled", "server")
        origins = server.get("cors_allowed_origins")
        if not isinstance(origins, list) or not all(isinstance(item, str) for item in origins):
            raise ConfigError("server.cors_allowed_origins must be a list of strings")

        paths = config["paths"]
        self._require_str(paths, "runs_dir", "paths")

        camera = config["camera"]
        for key in ("preview_width", "preview_height", "capture_width", "capture_height"):
            self._require_int(camera, key, "camera", minimum=1)
        self._require_int(camera, "frame_rate", "camera", minimum=1)
        self._require_int(camera, "buffer_count", "camera", minimum=1)
        for key in ("lores_width", "lores_height"):
            self._require_int(camera, key, "camera", minimum=1)
        self._require_str(camera, "exposure_mode", "camera")
        if camera["exposure_mode"] not in {"normal", "short"}:
            raise ConfigError("camera.exposure_mode must be 'normal' or 'short'")
        self._require_number(camera, "lens_position", "camera", minimum=0)
        for key in (
            "recording_start_delay",
            "capture_stop_delay",
            "capture_settle_delay",
            "capture_restart_delay",
        ):
            self._require_number(camera, key, "camera", minimum=0)

        obstruction = config["obstruction"]
        self._require_bool(obstruction, "enabled", "obstruction")
        self._require_str(obstruction, "mode", "obstruction")
        if obstruction["mode"] not in {"full", "palm"}:
            raise ConfigError("obstruction.mode must be 'full' or 'palm'")
        self._require_str(obstruction, "model_path", "obstruction")
        self._require_str(obstruction, "landmark_model_path", "obstruction")
        self._require_number(
            obstruction, "min_confidence", "obstruction", minimum=0, maximum=1
        )
        self._require_number(
            obstruction,
            "min_presence_confidence",
            "obstruction",
            minimum=0,
            maximum=1,
        )
        self._require_number(
            obstruction,
            "min_candidate_presence_confidence",
            "obstruction",
            minimum=0,
            maximum=1,
        )
        if (
            obstruction["min_candidate_presence_confidence"]
            > obstruction["min_presence_confidence"]
        ):
            raise ConfigError(
                "obstruction.min_candidate_presence_confidence cannot exceed "
                "obstruction.min_presence_confidence"
            )
        self._require_int(obstruction, "max_hands", "obstruction", minimum=1, maximum=2)
        self._require_int(
            obstruction, "inference_threads", "obstruction", minimum=1, maximum=4
        )
        for key in (
            "poll_interval",
            "target_interval",
            "stale_after_seconds",
            "wait_timeout_seconds",
        ):
            self._require_number(obstruction, key, "obstruction", minimum=0)
        for key in ("source_width", "source_height"):
            self._require_int(obstruction, key, "obstruction", minimum=1)
        if (
            obstruction["source_width"] != camera["lores_width"]
            or obstruction["source_height"] != camera["lores_height"]
        ):
            raise ConfigError(
                "obstruction source size must match camera lores_width/lores_height"
            )
        roi = obstruction.get("bed_roi")
        if (
            not isinstance(roi, list)
            or len(roi) != 4
            or not all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in roi
            )
        ):
            raise ConfigError("obstruction.bed_roi must contain four numbers")
        left, top, right, bottom = roi
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ConfigError(
                "obstruction.bed_roi must be normalized [left, top, right, bottom]"
            )
        schedule = obstruction.get("region_schedule")
        if (
            not isinstance(schedule, list)
            or not schedule
            or not all(region in {"bed", "full"} for region in schedule)
        ):
            raise ConfigError(
                "obstruction.region_schedule must be a non-empty list of 'bed'/'full'"
            )
        if "full" not in schedule:
            raise ConfigError("obstruction.region_schedule must include 'full'")
        self._require_bool(obstruction, "debug_overlay", "obstruction")
        self._require_int(obstruction, "clear_frames", "obstruction", minimum=1)
        # A reading older than the staleness cut-off is never treated as clear,
        # so polling slower than that cut-off would keep the gate permanently
        # shut on a rig that is working perfectly.
        if obstruction["target_interval"] >= obstruction["stale_after_seconds"]:
            raise ConfigError(
                "obstruction.target_interval must be shorter than "
                "obstruction.stale_after_seconds, or every reading is stale"
            )

        self._validate_stepper("motor", config["motor"])
        self._validate_stepper("motor2", config["motor2"])
        self._require_number(
            config["motor2"], "preposition_degrees", "motor2", minimum=0
        )
        if (
            config["motor2"]["preposition_degrees"]
            > config["motor2"]["page_turn_degrees"]
        ):
            raise ConfigError(
                "motor2.preposition_degrees cannot exceed "
                "motor2.page_turn_degrees"
            )

        # Only [motor] paces the page turn, so this one is not shared.
        self._require_number(
            config["motor"], "default_turn_seconds", "motor", minimum=0
        )

        servos = config["servos"]
        if not isinstance(servos, dict):
            raise ConfigError("section [servos] must be a table")
        # Both are driven by the page turn, so both must exist.
        for required in ("page_drop", "page_clamp_big", "page_clamp_small"):
            if required not in servos:
                raise ConfigError(f"servos.{required} is required")
        for name, servo in servos.items():
            if not isinstance(servo, dict):
                raise ConfigError(f"servos.{name} must be a table")
            self._validate_servo(name, servo)

        fan = config["fan"]
        self._require_int(fan, "pin", "fan", minimum=0)
        self._require_int(fan, "frequency_hz", "fan", minimum=12000, maximum=50000)
        self._require_int(fan, "min_start_duty_pct", "fan", minimum=0, maximum=100)
        self._require_int(fan, "duty_pct", "fan", minimum=0, maximum=100)
        self._require_number(fan, "spinup_seconds", "fan", minimum=0)
        self._require_int(fan, "tach_pin", "fan", minimum=0)
        self._require_int(fan, "tach_pulses_per_rev", "fan", minimum=1)

        workflow = config["workflow"]
        self._require_str(workflow, "turn_sequence", "workflow")
        if workflow["turn_sequence"] not in {"motor2_only", "shared"}:
            raise ConfigError(
                "workflow.turn_sequence must be 'motor2_only' or 'shared'"
            )
        for pause in (
            "clamp_down_pause",
            "servo_down_pause",
            "clamp_up_pause",
            "stepper_pause",
            "servo_up_pause",
        ):
            self._require_number(workflow, pause, "workflow", minimum=0)
        self._require_int(workflow, "default_pages", "workflow", minimum=1)

    def _require_str(self, section: dict[str, Any], key: str, name: str) -> None:
        if not isinstance(section.get(key), str) or not section[key]:
            raise ConfigError(f"{name}.{key} must be a non-empty string")

    def _require_bool(self, section: dict[str, Any], key: str, name: str) -> None:
        if not isinstance(section.get(key), bool):
            raise ConfigError(f"{name}.{key} must be true or false")

    def _require_int(
        self,
        section: dict[str, Any],
        key: str,
        name: str,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> None:
        value = section.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ConfigError(f"{name}.{key} must be an integer")
        if minimum is not None and value < minimum:
            raise ConfigError(f"{name}.{key} must be at least {minimum}")
        if maximum is not None and value > maximum:
            raise ConfigError(f"{name}.{key} must be at most {maximum}")

    def _require_number(
        self,
        section: dict[str, Any],
        key: str,
        name: str,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> None:
        value = section.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ConfigError(f"{name}.{key} must be a number")
        if minimum is not None and value < minimum:
            raise ConfigError(f"{name}.{key} must be at least {minimum}")
        if maximum is not None and value > maximum:
            raise ConfigError(f"{name}.{key} must be at most {maximum}")

    def _validate_stepper(self, name: str, motor: dict[str, Any]) -> None:
        """Shared by [motor] and [motor2] - both drive a step/dir stepper."""
        for key in ("step_pin", "dir_pin", "enable_pin"):
            self._require_int(motor, key, name, minimum=0)
        self._require_int(motor, "steps_per_rev", name, minimum=1)
        self._require_number(motor, "step_delay", name, minimum=0)
        self._require_number(motor, "fast_delay", name, minimum=0)
        self._require_number(motor, "default_degrees", name, minimum=0)
        if motor["default_degrees"] <= 0:
            raise ConfigError(f"{name}.default_degrees must be greater than 0")
        self._require_bool(motor, "default_clockwise", name)
        self._require_bool(motor, "invert_direction", name)
        self._require_number(motor, "page_turn_degrees", name, minimum=0)
        self._require_number(motor, "shared_degrees", name, minimum=0)
        self._require_number(motor, "return_short_degrees", name, minimum=0)
        outward = motor["page_turn_degrees"] + motor["shared_degrees"]
        if motor["return_short_degrees"] > outward:
            raise ConfigError(
                f"{name}.return_short_degrees ({motor['return_short_degrees']}) "
                f"cannot exceed the {outward} degrees the motor goes out"
            )

    def _validate_servo(self, name: str, servo: dict[str, Any]) -> None:
        section = f"servos.{name}"
        self._require_int(servo, "pin", section, minimum=0)
        self._require_number(servo, "min_angle", section)
        self._require_number(servo, "max_angle", section)
        self._require_number(servo, "min_pulse_width", section, minimum=0)
        self._require_number(servo, "max_pulse_width", section, minimum=0)
        self._require_number(servo, "frame_width", section, minimum=0)
        self._require_number(servo, "step_degrees", section, minimum=0)
        self._require_number(servo, "step_delay", section, minimum=0)
        self._require_number(servo, "approach_degrees", section, minimum=0)
        self._require_number(servo, "approach_step_degrees", section, minimum=0)
        self._require_number(servo, "approach_step_delay", section, minimum=0)
        self._require_number(servo, "departure_degrees", section, minimum=0)
        self._require_number(servo, "departure_step_degrees", section, minimum=0)
        self._require_number(servo, "departure_step_delay", section, minimum=0)
        self._require_number(servo, "max_hold_seconds", section, minimum=0)
        if servo["max_hold_seconds"] <= 0:
            raise ConfigError(f"{section}.max_hold_seconds must be greater than 0")

        if "contact_angle" in servo or "hold_angle" in servo:
            self._require_number(servo, "contact_angle", section)
            self._require_number(servo, "hold_angle", section)
            self._require_bool(servo, "use_hold", section)
            low = min(servo["min_angle"], servo["max_angle"])
            high = max(servo["min_angle"], servo["max_angle"])
            for key in ("contact_angle", "hold_angle"):
                if not low <= servo[key] <= high:
                    raise ConfigError(
                        f"{section}.{key} ({servo[key]}) is outside the servo's "
                        f"range {low} to {high}"
                    )
        # Strictly positive, or the ramp loop in ServoMotor._steps would never
        # close the gap. Set the delays to 0 for full speed instead.
        for key in ("step_degrees", "approach_step_degrees", "departure_step_degrees"):
            if servo[key] <= 0:
                raise ConfigError(f"{section}.{key} must be greater than 0")
        self._require_number(servo, "down_angle", section)
        self._require_number(servo, "up_angle", section)
        self._require_number(servo, "default_settle_time", section, minimum=0)
        self._require_bool(servo, "detach_after_move", section)
        self._require_str(servo, "pin_factory", section)
        if servo["pin_factory"] not in {"default", "pigpio"}:
            raise ConfigError(f"{section}.pin_factory must be 'default' or 'pigpio'")
        if servo["min_pulse_width"] >= servo["max_pulse_width"]:
            raise ConfigError(
                f"{section}.min_pulse_width must be less than {section}.max_pulse_width"
            )
        if servo["frame_width"] <= servo["max_pulse_width"]:
            raise ConfigError(f"{section}.frame_width must be greater than max_pulse_width")
        low_angle = min(servo["min_angle"], servo["max_angle"])
        high_angle = max(servo["min_angle"], servo["max_angle"])
        for key in ("down_angle", "up_angle"):
            if not low_angle <= servo[key] <= high_angle:
                raise ConfigError(f"{section}.{key} must be within the configured angle range")

    def _deep_merge(self, base: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(base)
        for key, value in values.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = self._deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged

##Default incase the config file is missing or corrupted, this will be written to the default.toml file
DEFAULT_CONFIG_TOML = """[server]
host = "0.0.0.0"
port = 8000
cors_enabled = true
cors_allowed_origins = ["*"]

[paths]
runs_dir = "runs"

[camera]
lens_position = 0.94
preview_width = 1920
preview_height = 1080
capture_width = 4608
capture_height = 2592
frame_rate = 30
buffer_count = 6
lores_width = 960
lores_height = 540
exposure_mode = "short"
recording_start_delay = 3.0
capture_stop_delay = 0.2
capture_settle_delay = 0.5
capture_restart_delay = 0.2

[motor]
step_pin = 21
dir_pin = 20
enable_pin = 16
steps_per_rev = 1600
step_delay = 0.002
fast_delay = 0.001
default_turn_seconds = 3.0
default_degrees = 190.0
default_clockwise = false
invert_direction = false
page_turn_degrees = 115.0
shared_degrees = 80.0
return_short_degrees = 10.0

[motor2]
step_pin = 24
dir_pin = 23
enable_pin = 25
steps_per_rev = 200
step_delay = 0.004
fast_delay = 0.001
default_degrees = 190.0
default_clockwise = false
invert_direction = true
page_turn_degrees = 90.0
preposition_degrees = 60.0
shared_degrees = 80.0
return_short_degrees = 0.0

[servos.page_drop]
pin = 22
min_angle = 0
max_angle = 180
min_pulse_width = 0.0005
max_pulse_width = 0.0025
frame_width = 0.02
step_degrees = 3.0
step_delay = 0.015
approach_degrees = 40.0
approach_step_degrees = 1.0
approach_step_delay = 0.04
departure_degrees = 10.0
departure_step_degrees = 0.5
departure_step_delay = 0.08
max_hold_seconds = 10.0
down_angle = 95
up_angle = 0
default_settle_time = 0.4
detach_after_move = true
pin_factory = "pigpio"

[servos.page_clamp_big]
pin = 13
min_angle = 0
max_angle = 180
min_pulse_width = 0.0005
max_pulse_width = 0.0025
frame_width = 0.02
step_degrees = 3.0
step_delay = 0.015
approach_degrees = 40.0
approach_step_degrees = 1.0
approach_step_delay = 0.04
departure_degrees = 10.0
departure_step_degrees = 0.5
departure_step_delay = 0.08
max_hold_seconds = 10.0
down_angle = 73
up_angle = 0
contact_angle = 105
hold_angle = 102
use_hold = true
default_settle_time = 0.4
detach_after_move = true
pin_factory = "pigpio"

[servos.page_clamp_small]
pin = 27
min_angle = 0
max_angle = 180
min_pulse_width = 0.0005
max_pulse_width = 0.0025
frame_width = 0.02
step_degrees = 3.0
step_delay = 0.015
approach_degrees = 40.0
approach_step_degrees = 1.0
approach_step_delay = 0.04
departure_degrees = 10.0
departure_step_degrees = 0.5
departure_step_delay = 0.08
max_hold_seconds = 10.0
down_angle = 90
up_angle = 0
contact_angle = 85
hold_angle = 82
use_hold = true
default_settle_time = 0.4
detach_after_move = true
pin_factory = "pigpio"

[fan]
pin = 19
frequency_hz = 25000
min_start_duty_pct = 10
tach_pin = 17
tach_pulses_per_rev = 2
duty_pct = 100
spinup_seconds = 3.0

[obstruction]
enabled = false
mode = "full"
model_path = "models/hand_detector.tflite"
landmark_model_path = "models/hand_landmarks_detector.tflite"
min_confidence = 0.3
min_presence_confidence = 0.5
min_candidate_presence_confidence = 0.01
max_hands = 2
inference_threads = 4
poll_interval = 0.1
target_interval = 0.1
source_width = 960
source_height = 540
bed_roi = [0.0, 0.0, 1.0, 1.0]
region_schedule = ["bed", "bed", "full"]
debug_overlay = false
clear_frames = 5
stale_after_seconds = 3.0
wait_timeout_seconds = 30.0

[workflow]
turn_sequence = "shared"
clamp_down_pause = 1.0
servo_down_pause = 1.0
clamp_up_pause = 0.5
stepper_pause = 1.0
servo_up_pause = 1.0
small_clamp_hold_seconds = 3.0
motor_pause = 1.0
default_pages = 6
"""
