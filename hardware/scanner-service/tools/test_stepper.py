"""Rotate the stepper wheel one way, then the same amount back.

Ends where it started, so it is safe to repeat without the wheel creeping
round. The driver is de-energised between the two moves and at the end.

Run from hardware/scanner-service:
    uv run python tools/test_stepper.py

If uv is not on PATH:
    ~/.local/bin/uv run python tools/test_stepper.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = SERVICE_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from examscan_scanner.config import CONFIG_PATH, ConfigManager
from examscan_scanner.drivers.motor import StepperMotor


# ==================== SETTINGS - edit these ====================

# Which motor to drive. "motor" is the TMC2209 page wheel (1/8 microstepping,
# 1600 steps/rev); "motor2" is the DRV8825 on GPIO 23/24/25 (full step, 200).
MOTOR_SECTION = "motor"

# How far to turn in each direction. 360 is one full revolution.
DEGREES = 120
# Direction of the first move. The second move is always the opposite.
CLOCKWISE = False

# Seconds to sit still between the two moves, with the driver switched off.
PAUSE_BETWEEN = 1.0

# True releases the GPIO pins on exit. False leaves ENABLE driven HIGH
# (de-energised) and does not release them.
#
# Worth knowing: on the TMC2209 the EN input is active LOW, so a released or
# floating pin can re-energise the driver. If the motor still holds torque or
# warms up after this script exits, set this to False and see whether that
# changes it.
RELEASE_PINS = True

# ===============================================================


def move(motor: StepperMotor, clockwise: bool, label: str) -> None:
    direction = "clockwise" if clockwise else "counterclockwise"
    print(f"{label} {DEGREES} degrees {direction}")
    motor.move_degrees(DEGREES, clockwise=clockwise)
    # move_degrees already disables at the end of the move; this is explicit so
    # the intent is visible, and cheap to repeat.
    motor.disable()
    print("      driver de-energised")


def main() -> int:
    if DEGREES <= 0:
        print("DEGREES must be greater than 0", file=sys.stderr)
        return 2

    config = ConfigManager(CONFIG_PATH).load()
    motor_config = config.get(MOTOR_SECTION)
    if motor_config is None:
        print(f"No [{MOTOR_SECTION}] section in config/default.toml", file=sys.stderr)
        return 2
    steps = round(motor_config["steps_per_rev"] * DEGREES / 360)
    first = "clockwise" if CLOCKWISE else "counterclockwise"
    second = "counterclockwise" if CLOCKWISE else "clockwise"

    print("Stop the ExamScan backend before running this test.")
    print("Keep clear of moving parts.\n")
    print(f"Motor: [{MOTOR_SECTION}] at {motor_config['steps_per_rev']} steps/rev")
    print(f"Step pin: {motor_config['step_pin']}")
    print(f"Direction pin: {motor_config['dir_pin']}")
    print(f"Enable pin: {motor_config['enable_pin']}")
    print(f"Degrees: {DEGREES} each way ({first}, then {second})")
    print(f"Calculated steps: {steps} each way\n")

    motor = StepperMotor.from_config(motor_config)
    try:
        move(motor, CLOCKWISE, "[1/2]")
        time.sleep(PAUSE_BETWEEN)
        move(motor, not CLOCKWISE, "[2/2]")

        print("\nStepper test finished - back at the starting position.")
        return 0
    finally:
        motor.disable()
        if RELEASE_PINS:
            motor.cleanup()
            print("Stepper cleaned up, pins released.")
        else:
            print("Stepper disabled, pins left driven (ENABLE held HIGH).")


if __name__ == "__main__":
    raise SystemExit(main())
