"""Drive a servo between angles interactively, to find the ones you want.

Step through the angles with the number keys or space, and press q to move on
to the next servo (or finish, on the last one).

Angles here are hardcoded on purpose - config.toml supplies only the pin and
the pulse widths, so you can hunt for a good angle without editing config.

Run from the project root:
    uv run python hardware/test_servo.py

If uv is not on PATH:
    ~/.local/bin/uv run python hardware/test_servo.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import CONFIG_PATH, ConfigManager
from hardware.console import ConsoleError, key_input, read_key
from hardware.servo import ServoMotor



# Which servos to move, in order. Names come from [servos.*] in config.toml.
SERVO_NAMES = ["page_clamp_big"]

# Angles to step through, in degrees. This is what you are tuning.
# Keys 1-9 pick one directly.
ANGLES = [0,90, 110, 80,0]

# Moves to these angles creep out of their starting position, using the
# departure_* profile in config.toml. The arm's up position is 0, so this is
# what makes it peel off the page slowly instead of flicking it.
SLOW_START_ANGLES = [0]

# Seconds to hold each angle before moving on.
SETTLE_TIME = 0.5

# Whether hold starts on. Press HOLD_KEY to toggle it live.
#
# With hold on, the servo stays powered after each move so it grips - push the
# arm by hand and it should resist. With it off it detaches and goes limp.
# config.toml's max_hold_seconds releases it anyway if nothing lifts it, so a
# held servo cannot sit stalled indefinitely.
HOLD_ON_START = False

# Press this to toggle hold, which re-applies the current angle immediately.
HOLD_KEY = "h"

# Fine adjustment. A servo only pushes while it has positional error, so to
# actually clamp you have to command it past where the arm touches the page.
# Hold, then nudge until it grips, then copy the angle into config.toml.
NUDGE_DEGREES = 1.0
# Both the shifted and unshifted keys, so nudging works one-handed at the rig.
NUDGE_UP_KEYS = ("+", "=")
NUDGE_DOWN_KEYS = ("-", "_")

# Press this to move on to the next servo, or finish.
QUIT_KEY = "q"

# ===============================================================


def move_to(servo: ServoMotor, angle: float, hold: bool) -> None:
    slow_start = angle in SLOW_START_ANGLES
    notes = []
    if slow_start:
        notes.append("slow start")
    if hold:
        notes.append("holding")
    suffix = f" ({', '.join(notes)})" if notes else ""
    print(f"  -> {angle:g} degrees{suffix}")
    servo.set_angle(angle, settle_time=SETTLE_TIME, slow_start=slow_start, hold=hold)


def run_console(servo: ServoMotor, low: float, high: float) -> None:
    hold = HOLD_ON_START
    # Tracked separately from ANGLES so nudging never edits the preset list and
    # stepping to another preset still works.
    angle = ANGLES[0]
    index = 0
    move_to(servo, angle, hold)

    while True:
        key = read_key()

        if key == QUIT_KEY:
            # Release before moving on, so nothing is left powered.
            servo.detach()
            return

        if key == HOLD_KEY:
            hold = not hold
            if hold:
                print(f"  hold ON at {time.strftime('%H:%M:%S')} - "
                      f"releases after {servo.max_hold_seconds:g}s if nothing lifts it")
            else:
                print("  hold OFF")
            # Re-issue so the change is felt now, not at the next move.
            move_to(servo, angle, hold)
            continue

        if key in NUDGE_UP_KEYS or key in NUDGE_DOWN_KEYS:
            step = NUDGE_DEGREES if key in NUDGE_UP_KEYS else -NUDGE_DEGREES
            # Clamped to the configured range, or gpiozero raises.
            nudged = min(high, max(low, angle + step))
            if nudged == angle:
                print(f"  at the {'top' if step > 0 else 'bottom'} of the range ({angle:g})")
            else:
                angle = nudged
                move_to(servo, angle, hold)
            continue

        if key in {" ", "\r", "\n"}:
            index = (index + 1) % len(ANGLES)
            angle = ANGLES[index]
            move_to(servo, angle, hold)
        elif key is not None and key.isdigit() and 1 <= int(key) <= len(ANGLES):
            index = int(key) - 1
            angle = ANGLES[index]
            move_to(servo, angle, hold)


def sweep(name: str, servo_config: dict) -> None:
    print(f"\nServo: {name} on GPIO {servo_config['pin']}")
    print(f"Configured range: {servo_config['min_angle']} to {servo_config['max_angle']} degrees")
    if servo_config["min_angle"] > servo_config["max_angle"]:
        print("Range is reversed, so this servo's rotation is mirrored.")
    print(
        f"Motion profile: {servo_config['step_degrees']} deg every "
        f"{servo_config['step_delay']}s, slowing to "
        f"{servo_config['approach_step_degrees']} deg every "
        f"{servo_config['approach_step_delay']}s within "
        f"{servo_config['approach_degrees']} deg of the target"
    )
    if SLOW_START_ANGLES:
        print(
            f"Slow start for {SLOW_START_ANGLES}: "
            f"{servo_config['departure_step_degrees']} deg every "
            f"{servo_config['departure_step_delay']}s for the first "
            f"{servo_config['departure_degrees']} deg"
        )

    low = min(servo_config["min_angle"], servo_config["max_angle"])
    high = max(servo_config["min_angle"], servo_config["max_angle"])

    servo = ServoMotor.from_config(servo_config)
    try:
        run_console(servo, low, high)
    finally:
        servo.cleanup()
        print(f"{name} cleaned up.")


def main() -> int:
    config = ConfigManager(CONFIG_PATH).load()

    print("Stop the ExamScan backend before running this test.")
    print("Keep clear of moving parts.\n")

    for name in SERVO_NAMES:
        servo_config = config["servos"].get(name)
        if servo_config is None:
            print(f"No servo named '{name}' in config.toml", file=sys.stderr)
            return 2

        low = min(servo_config["min_angle"], servo_config["max_angle"])
        high = max(servo_config["min_angle"], servo_config["max_angle"])
        out_of_range = [angle for angle in ANGLES if not low <= angle <= high]
        if out_of_range:
            print(
                f"ANGLES {out_of_range} are outside {name}'s configured range "
                f"{low} to {high}. Widen min_angle/max_angle in config.toml or "
                f"pick different angles.",
                file=sys.stderr,
            )
            return 2

    choices = "  ".join(f"{i}={angle:g}deg" for i, angle in enumerate(ANGLES, start=1))
    print(f"Keys: {choices}")
    print(f"      space = next angle, {HOLD_KEY} = toggle hold, {QUIT_KEY} = next servo")
    print(f"      {NUDGE_UP_KEYS[0]}/{NUDGE_DOWN_KEYS[0]} = nudge {NUDGE_DEGREES:g} deg "
          f"(hold, then nudge until it grips)")
    print(f"      hold starts {'ON' if HOLD_ON_START else 'OFF'}\n")

    try:
        with key_input():
            for name in SERVO_NAMES:
                sweep(name, config["servos"][name])
    except ConsoleError as exc:
        print(exc, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 1

    print("\nServo sweep finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
