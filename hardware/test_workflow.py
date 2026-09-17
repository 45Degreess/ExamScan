"""Run the full page-turn sequence: two clamps, the arm, the fan, two steppers.

    small clamp down (hold 5s) -> fan on -> arm down -> big clamp down (hold)
      -> small clamp up -> motor 1 out (stays energised) -> motor 2 pre-position
      -> arm up -> fan off -> motor 1 home -> small clamp down (hold)
      -> big clamp up -> motor 2 out remainder -> motor 2 continues alone
      -> motor 2 home -> small clamp up

Motor 1 stays energised from its first move onwards so it holds position while
the clamps work around it. Set TURN_SEQUENCE to "shared" to exercise the
previous parallel-movement sequence instead.

The angles are hardcoded here on purpose. config.toml supplies only each servo's
pin and pulse widths, so you can tune the angles by editing this file and
re-running, then copy whatever works into config.toml.

Needs pigpiod for the fan:
    sudo systemctl start pigpiod

Run from the project root:
    uv run python hardware/test_workflow.py

If uv is not on PATH:
    ~/.local/bin/uv run python hardware/test_workflow.py
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import CONFIG_PATH, ConfigManager
from hardware.fan import FanController, FanError
from hardware.motor import StepperMotor
from hardware.servo import ServoMotor


# ==================== SETTINGS - edit these ====================

# --- the arm (servo) ---
# Name from [servos.*] in config.toml - supplies the pin and pulse widths only.
SERVO_NAME = "page_drop"
# Hardcoded angles. These are what you are tuning.
DOWN_ANGLE = 90
UP_ANGLE = 0
SERVO_SETTLE = 0.4

# --- the small clamp (servo) ---
# Drops first and holds, lifts before motor 1 goes out, then drops again to
# grip while the big clamp releases.
SMALL_CLAMP_NAME = "page_clamp_small"
# Drive in to CONTACT, then ease back to HOLD and stay powered there. Held hard
# against a stop it cannot reach, the servo stalls - near-stall current, buzz,
# and a sagging supply. Backing off a few degrees keeps the clamp's pressure
# while the servo sits somewhere it can actually hold. Set them equal to hold
# right at the contact angle.
SMALL_CLAMP_CONTACT_ANGLE = 88
SMALL_CLAMP_HOLD_ANGLE = 86
SMALL_CLAMP_UP_ANGLE = 0
SMALL_CLAMP_SETTLE = 0.1
SMALL_CLAMP_HOLD = 5.0       # seconds to dwell on the first drop
# False drops the clamp and lets it go limp instead of holding it powered - no
# stall, no buzz, no 10s cut-off. If the clamp grips under its own weight, that
# is the simpler answer.
SMALL_CLAMP_USE_HOLD = True

# --- the big clamp (servo) ---
# Takes over the grip while the small clamp is lifted.
CLAMP_NAME = "page_clamp_big"
# Same contact/hold split as the small clamp - this one bottoms out too.
CLAMP_CONTACT_ANGLE = 105
CLAMP_HOLD_ANGLE = 102
CLAMP_UP_ANGLE = 0
CLAMP_SETTLE = 0.4
CLAMP_USE_HOLD = True

# --- the stepper wheels ---
# Keep this in step with workflow.turn_sequence in config.toml. "motor2_only"
# returns motor 1 early and makes motor 2 perform the continuation alone;
# "shared" is the previous sequence and is kept as a rollback.
TURN_SEQUENCE = "motor2_only"
M1_FIRST_DEGREES = 105
M2_FIRST_DEGREES = 90
M2_PREPOSITION_DEGREES = 60
SHARED_DEGREES = 80
M1_CLOCKWISE = False         # outward direction; returns are the opposite
M2_CLOCKWISE = False
# Each motor's final return stops this far short of where it started. Set to 0
# for an exact round trip. Anything above 0 leaves the wheel this much further
# round on every cycle, so it is a correction for a rig that over-travels, not
# something to leave in by accident.
RETURN_SHORT_DEGREES = 10

# --- the fan ---
FAN_DUTY = 100               # percent, while the arm is down
# The fan is still spinning up when set_duty returns, so the arm waits for it
# to reach speed before dropping onto the page.
FAN_SPINUP = 3.0

# --- pacing ---
START_DELAY = 3.0            # seconds to step back before anything moves
PAUSE_AFTER_CLAMP_DOWN = 1.0
PAUSE_AFTER_DROP = 1.0
PAUSE_AFTER_CLAMP_UP = 0.5
PAUSE_AFTER_STEPPER = 1.0
PAUSE_AFTER_LIFT = 1.0

# ===============================================================


def release(label: str, close) -> None:
    """Release one device, never letting a failure skip the others."""
    try:
        close()
        print(f"{label} cleaned up.")
    except Exception as exc:
        print(f"{label} cleanup failed: {exc}", file=sys.stderr)


def check_angles(name: str, servo_config: dict, angles: list[tuple[str, float]]) -> bool:
    """gpiozero raises if an angle falls outside the servo's configured range.

    Caught up front rather than mid-sequence with the arm already down. Uses
    min/max so a reversed range (min_angle > max_angle) is handled too.
    """
    low = min(servo_config["min_angle"], servo_config["max_angle"])
    high = max(servo_config["min_angle"], servo_config["max_angle"])
    for label, angle in angles:
        if not low <= angle <= high:
            print(
                f"{label} is {angle}, outside {name}'s configured range "
                f"{low} to {high}. Widen min_angle/max_angle in config.toml or "
                f"pick a different angle.",
                file=sys.stderr,
            )
            return False
    return True


def hold_clamp(servo: ServoMotor, contact: float, hold_angle: float,
               settle: float, use_hold: bool) -> float:
    """Seat a clamp, then hold it just off the stop, returning when it started.

    Driving in to contact and holding there leaves the servo pushing at a stop
    it cannot reach, which stalls it - it buzzes, warms up, and drags the supply
    down. Easing back a few degrees first keeps the clamp's pressure while the
    servo sits at an angle it can actually hold.

    With use_hold False the clamp is dropped and left limp, which is what
    detach_after_move already does. Pair with lift_clamp() to get the elapsed
    hold printed: a hold outlasting max_hold_seconds detaches on a timer rather
    than raising, so timing it is the only way to see it go limp.
    """
    servo.set_angle(contact, settle_time=settle)
    if not use_hold:
        servo.detach()
        return time.monotonic()
    # Equal angles still need the hold=True command, so the servo re-engages
    # rather than staying detached from the seating move above.
    servo.set_angle(hold_angle, settle_time=settle, hold=True)
    return time.monotonic()


def lift_clamp(servo: ServoMotor, angle: float, settle: float,
               held_since: float, label: str) -> None:
    """Lift a clamp, reporting how long it was asked to hold."""
    elapsed = time.monotonic() - held_since
    if elapsed > servo.max_hold_seconds:
        print(
            f"  {label} held {elapsed:.1f}s, past its "
            f"{servo.max_hold_seconds:g}s cut-off - it went limp before this "
            f"lift. Shorten the sequence or raise max_hold_seconds.",
            file=sys.stderr,
        )
    else:
        print(f"  {label} held {elapsed:.1f}s "
              f"(cut-off {servo.max_hold_seconds:g}s)")
    servo.set_angle(angle, settle_time=settle)
    servo.detach()


def move_both(motor_a: StepperMotor, steps_a: int, clockwise_a: bool,
              motor_b: StepperMotor, steps_b: int, clockwise_b: bool) -> None:
    """Step two motors at once, surfacing a failure in either.

    The two StepperMotors share no state and drive different pins, so they need
    no locking. A thread that raises would otherwise die unnoticed while the
    other motor ran on, so the error is captured and re-raised here.
    """
    errors: list[BaseException] = []

    def run(motor, steps, clockwise):
        try:
            motor.move_steps(steps, clockwise=clockwise)
        except BaseException as exc:  # noqa: BLE001 - re-raised after the join
            errors.append(exc)

    threads = [
        threading.Thread(target=run, args=(motor_a, steps_a, clockwise_a)),
        threading.Thread(target=run, args=(motor_b, steps_b, clockwise_b)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if errors:
        raise errors[0]


def main() -> int:
    config = ConfigManager(CONFIG_PATH).load()
    servo_config = config["servos"].get(SERVO_NAME)
    small_config = config["servos"].get(SMALL_CLAMP_NAME)
    clamp_config = config["servos"].get(CLAMP_NAME)
    for label, cfg in ((SERVO_NAME, servo_config),
                       (SMALL_CLAMP_NAME, small_config),
                       (CLAMP_NAME, clamp_config)):
        if cfg is None:
            print(f"No servo named '{label}' in config.toml", file=sys.stderr)
            return 2
    motor1_config = config["motor"]
    motor2_config = config["motor2"]

    if not check_angles(SERVO_NAME, servo_config,
                        [("DOWN_ANGLE", DOWN_ANGLE), ("UP_ANGLE", UP_ANGLE)]):
        return 2
    if not check_angles(SMALL_CLAMP_NAME, small_config,
                        [("SMALL_CLAMP_CONTACT_ANGLE", SMALL_CLAMP_CONTACT_ANGLE),
                         ("SMALL_CLAMP_HOLD_ANGLE", SMALL_CLAMP_HOLD_ANGLE),
                         ("SMALL_CLAMP_UP_ANGLE", SMALL_CLAMP_UP_ANGLE)]):
        return 2
    if not check_angles(CLAMP_NAME, clamp_config,
                        [("CLAMP_CONTACT_ANGLE", CLAMP_CONTACT_ANGLE),
                         ("CLAMP_HOLD_ANGLE", CLAMP_HOLD_ANGLE),
                         ("CLAMP_UP_ANGLE", CLAMP_UP_ANGLE)]):
        return 2

    # Converted to steps once, then reused, so each motor's moves cancel exactly.
    # Going back through degrees a second time can round to one step more or
    # less than the outward move and leave the wheel short of where it started.
    m1_first = round(motor1_config["steps_per_rev"] * M1_FIRST_DEGREES / 360)
    m1_shared = round(motor1_config["steps_per_rev"] * SHARED_DEGREES / 360)
    m2_first = round(motor2_config["steps_per_rev"] * M2_FIRST_DEGREES / 360)
    m2_preposition = round(
        motor2_config["steps_per_rev"] * M2_PREPOSITION_DEGREES / 360
    )
    m2_first_remainder = m2_first - m2_preposition
    m2_shared = round(motor2_config["steps_per_rev"] * SHARED_DEGREES / 360)
    # Motor 2 unwinds both of its outward moves in one go.
    m2_return = m2_first + m2_shared
    if TURN_SEQUENCE not in {"motor2_only", "shared"}:
        print("TURN_SEQUENCE must be 'motor2_only' or 'shared'", file=sys.stderr)
        return 2
    if not 0 <= M2_PREPOSITION_DEGREES <= M2_FIRST_DEGREES:
        print("M2_PREPOSITION_DEGREES must be between 0 and "
              "M2_FIRST_DEGREES", file=sys.stderr)
        return 2
    if min(m1_first, m1_shared, m2_first, m2_shared) < 1:
        print("A configured rotation is too small to make a single step",
              file=sys.stderr)
        return 2

    # The last return of each motor stops short by this much.
    m1_short = round(motor1_config["steps_per_rev"] * RETURN_SHORT_DEGREES / 360)
    m2_short = round(motor2_config["steps_per_rev"] * RETURN_SHORT_DEGREES / 360)
    m1_home = m1_first - m1_short
    m2_home = m2_return - m2_short
    if min(m1_home, m2_home) < 0:
        print(f"RETURN_SHORT_DEGREES of {RETURN_SHORT_DEGREES} is larger than "
              f"a motor's final return", file=sys.stderr)
        return 2

    m1_out = "clockwise" if M1_CLOCKWISE else "counterclockwise"
    m1_back = "counterclockwise" if M1_CLOCKWISE else "clockwise"
    m2_out = "clockwise" if M2_CLOCKWISE else "counterclockwise"
    m2_back = "counterclockwise" if M2_CLOCKWISE else "clockwise"

    print("Stop the ExamScan backend before running this test.")
    print("Keep clear of moving parts.\n")
    print(f"Small clamp: {SMALL_CLAMP_NAME} on GPIO {small_config['pin']}, "
          f"contact {SMALL_CLAMP_CONTACT_ANGLE} / hold {SMALL_CLAMP_HOLD_ANGLE}"
          f" / up {SMALL_CLAMP_UP_ANGLE} degrees"
          f"{'' if SMALL_CLAMP_USE_HOLD else ' (hold off)'}")
    print(f"Big clamp:   {CLAMP_NAME} on GPIO {clamp_config['pin']}, "
          f"contact {CLAMP_CONTACT_ANGLE} / hold {CLAMP_HOLD_ANGLE}"
          f" / up {CLAMP_UP_ANGLE} degrees"
          f"{'' if CLAMP_USE_HOLD else ' (hold off)'}")
    print(f"Arm:         {SERVO_NAME} on GPIO {servo_config['pin']}, "
          f"down {DOWN_ANGLE} / up {UP_ANGLE} degrees")
    print(f"Fan:         GPIO {config['fan']['pin']} at {FAN_DUTY}%")
    print(f"Motor 1:     step {motor1_config['step_pin']}, "
          f"dir {motor1_config['dir_pin']}, "
          f"enable {motor1_config['enable_pin']}")
    if TURN_SEQUENCE == "motor2_only":
        print(f"             {M1_FIRST_DEGREES} deg {m1_out} = {m1_first} "
              "steps, then exact return after motor 2 pre-positions")
    else:
        print(f"             {M1_FIRST_DEGREES} + {SHARED_DEGREES} deg "
              f"{m1_out} = {m1_first} + {m1_shared} steps, then back")
    print(f"Motor 2:     step {motor2_config['step_pin']}, "
          f"dir {motor2_config['dir_pin']}, "
          f"enable {motor2_config['enable_pin']}")
    print(f"             {M2_PREPOSITION_DEGREES} + "
          f"{M2_FIRST_DEGREES - M2_PREPOSITION_DEGREES} + {SHARED_DEGREES} "
          f"deg {m2_out} = {m2_preposition} + {m2_first_remainder} + "
          f"{m2_shared} steps, home in {m2_home}")
    if RETURN_SHORT_DEGREES:
        if TURN_SEQUENCE == "motor2_only":
            print(f"Motor 1 returns exactly; motor 2 stops "
                  f"{RETURN_SHORT_DEGREES} deg short ({m2_home} not "
                  f"{m2_return} steps)")
        else:
            print(f"Both motors stop {RETURN_SHORT_DEGREES} deg short on "
                  f"their final return (motor 1 {m1_home} not {m1_first} "
                  f"steps, motor 2 {m2_home} not {m2_return})")
    print(f"\nStarting in {START_DELAY}s...")
    time.sleep(START_DELAY)

    servo = None
    small = None
    clamp = None
    motor1 = None
    motor2 = None
    fan = None
    try:
        try:
            fan = FanController.from_config(config["fan"])
        except FanError as exc:
            print(exc, file=sys.stderr)
            return 2

        servo = ServoMotor.from_config(servo_config)
        small = ServoMotor.from_config(small_config)
        clamp = ServoMotor.from_config(clamp_config)
        motor1 = StepperMotor.from_config(motor1_config)
        motor2 = StepperMotor.from_config(motor2_config)

        print(f"\n[1/16] Dropping small clamp to {SMALL_CLAMP_CONTACT_ANGLE} "
              f"degrees, holding at {SMALL_CLAMP_HOLD_ANGLE} for "
              f"{SMALL_CLAMP_HOLD:g}s")
        small_held = hold_clamp(small, SMALL_CLAMP_CONTACT_ANGLE,
                                SMALL_CLAMP_HOLD_ANGLE, SMALL_CLAMP_SETTLE,
                                SMALL_CLAMP_USE_HOLD)
        time.sleep(SMALL_CLAMP_HOLD)

        print(f"[2/16] Fan to {FAN_DUTY}%")
        applied = fan.set_duty(FAN_DUTY)
        if applied != FAN_DUTY:
            print(f"  duty raised to {applied:g}% (min start duty)")
        print(f"  letting the fan reach speed for {FAN_SPINUP:g}s")
        time.sleep(FAN_SPINUP)

        print(f"[3/16] Dropping arm to {DOWN_ANGLE} degrees")
        servo.set_angle(DOWN_ANGLE, settle_time=SERVO_SETTLE)
        servo.detach()
        time.sleep(PAUSE_AFTER_DROP)

        print(f"[4/16] Dropping big clamp to {CLAMP_CONTACT_ANGLE} degrees, "
              f"holding at {CLAMP_HOLD_ANGLE}")
        clamp_held = hold_clamp(clamp, CLAMP_CONTACT_ANGLE, CLAMP_HOLD_ANGLE,
                                CLAMP_SETTLE, CLAMP_USE_HOLD)
        time.sleep(PAUSE_AFTER_CLAMP_DOWN)

        print(f"[5/16] Lifting small clamp to {SMALL_CLAMP_UP_ANGLE} degrees")
        lift_clamp(small, SMALL_CLAMP_UP_ANGLE, SMALL_CLAMP_SETTLE,
                   small_held, SMALL_CLAMP_NAME)
        time.sleep(PAUSE_AFTER_CLAMP_UP)

        print(f"[6/16] Motor 1 {m1_first} steps {m1_out}, staying energised")
        motor1.move_steps(m1_first, clockwise=M1_CLOCKWISE)
        # move_steps() always de-energises on the way out, so power goes back on
        # here to hold the wheel against the clamps working around it.
        motor1.enable()
        time.sleep(PAUSE_AFTER_STEPPER)

        print(f"[7/16] Motor 2 pre-position {m2_preposition} steps {m2_out}")
        if m2_preposition:
            motor2.move_steps(m2_preposition, clockwise=M2_CLOCKWISE)
            time.sleep(PAUSE_AFTER_STEPPER)

        print(f"[8/16] Lifting arm to {UP_ANGLE} degrees")
        servo.set_angle(UP_ANGLE, settle_time=SERVO_SETTLE)
        servo.detach()
        time.sleep(PAUSE_AFTER_LIFT)

        print("[9/16] Fan off")
        fan.set_duty(0)

        if TURN_SEQUENCE == "motor2_only":

            print(f"[10/16] Motor 1 exact return, {m1_first} steps {m1_back}")
            motor1.move_steps(m1_first, clockwise=not M1_CLOCKWISE)
            time.sleep(PAUSE_AFTER_STEPPER)

            print(f"[11/16] Dropping small clamp to "
                  f"{SMALL_CLAMP_CONTACT_ANGLE} degrees, holding at "
                  f"{SMALL_CLAMP_HOLD_ANGLE}")
            small_held = hold_clamp(
                small, SMALL_CLAMP_CONTACT_ANGLE, SMALL_CLAMP_HOLD_ANGLE,
                SMALL_CLAMP_SETTLE, SMALL_CLAMP_USE_HOLD
            )
            time.sleep(PAUSE_AFTER_CLAMP_DOWN)

            print(f"[12/16] Lifting big clamp to {CLAMP_UP_ANGLE} degrees")
            lift_clamp(
                clamp, CLAMP_UP_ANGLE, CLAMP_SETTLE, clamp_held, CLAMP_NAME
            )
            time.sleep(PAUSE_AFTER_CLAMP_UP)

            print(f"[13/16] Motor 2 first-leg remainder "
                  f"{m2_first_remainder} steps {m2_out}")
            if m2_first_remainder:
                motor2.move_steps(m2_first_remainder, clockwise=M2_CLOCKWISE)
                time.sleep(PAUSE_AFTER_STEPPER)

            print(f"[14/16] Motor 2 continuation {m2_shared} steps {m2_out}")
            motor2.move_steps(m2_shared, clockwise=M2_CLOCKWISE)
            time.sleep(PAUSE_AFTER_STEPPER)

            print(f"[15/16] Motor 2 home, {m2_home} steps {m2_back}")
            motor2.move_steps(m2_home, clockwise=not M2_CLOCKWISE)
            time.sleep(PAUSE_AFTER_STEPPER)

            print(f"[16/16] Lifting small clamp to "
                  f"{SMALL_CLAMP_UP_ANGLE} degrees")
            lift_clamp(
                small, SMALL_CLAMP_UP_ANGLE, SMALL_CLAMP_SETTLE,
                small_held, SMALL_CLAMP_NAME
            )
            time.sleep(PAUSE_AFTER_CLAMP_UP)
        else:
            print(f"[10/16] Dropping small clamp to {SMALL_CLAMP_CONTACT_ANGLE} "
                  f"degrees, holding at {SMALL_CLAMP_HOLD_ANGLE}")
            small_held = hold_clamp(
                small, SMALL_CLAMP_CONTACT_ANGLE, SMALL_CLAMP_HOLD_ANGLE,
                SMALL_CLAMP_SETTLE, SMALL_CLAMP_USE_HOLD
            )
            time.sleep(PAUSE_AFTER_CLAMP_DOWN)

            print(f"[11/16] Lifting big clamp to {CLAMP_UP_ANGLE} degrees")
            lift_clamp(
                clamp, CLAMP_UP_ANGLE, CLAMP_SETTLE, clamp_held, CLAMP_NAME
            )
            time.sleep(PAUSE_AFTER_CLAMP_UP)

            print(f"[12/16] Motor 2 first-leg remainder "
                  f"{m2_first_remainder} steps {m2_out}")
            if m2_first_remainder:
                motor2.move_steps(m2_first_remainder, clockwise=M2_CLOCKWISE)
                time.sleep(PAUSE_AFTER_STEPPER)

            print(f"[13/16] Motor 1 {m1_shared} steps {m1_out} and motor 2 "
                  f"{m2_shared} steps {m2_out}, together")
            move_both(
                motor1, m1_shared, M1_CLOCKWISE,
                motor2, m2_shared, M2_CLOCKWISE
            )
            motor1.enable()
            time.sleep(PAUSE_AFTER_STEPPER)

            print(f"[14/16] Motor 2 home, {m2_home} steps {m2_back}")
            motor2.move_steps(m2_home, clockwise=not M2_CLOCKWISE)
            time.sleep(PAUSE_AFTER_STEPPER)

            print(f"[15/16] Motor 1 back {m1_shared} steps {m1_back}")
            motor1.move_steps(m1_shared, clockwise=not M1_CLOCKWISE)
            motor1.enable()
            time.sleep(PAUSE_AFTER_STEPPER)

            print(f"        Lifting small clamp to "
                  f"{SMALL_CLAMP_UP_ANGLE} degrees")
            lift_clamp(
                small, SMALL_CLAMP_UP_ANGLE, SMALL_CLAMP_SETTLE,
                small_held, SMALL_CLAMP_NAME
            )
            time.sleep(PAUSE_AFTER_CLAMP_UP)

            print(f"[16/16] Motor 1 home, {m1_home} steps {m1_back}")
            motor1.move_steps(m1_home, clockwise=not M1_CLOCKWISE)

        if RETURN_SHORT_DEGREES:
            if TURN_SEQUENCE == "motor2_only":
                print(f"\nWorkflow finished - motor 1 returned exactly and "
                      f"motor 2 stopped {RETURN_SHORT_DEGREES} deg short.")
            else:
                print(f"\nWorkflow finished - both wheels stopped "
                      f"{RETURN_SHORT_DEGREES} deg short of their starting "
                      "positions.")
        else:
            print("\nWorkflow finished - both wheels returned exactly.")
        return 0
    finally:
        # Order matters: StepperMotor.cleanup() resets RPi.GPIO channels, so the
        # steppers go last. The fan goes first so it stops even if a servo
        # release then fails.
        if fan is not None:
            release("Fan", fan.cleanup)
        if servo is not None:
            release(SERVO_NAME, servo.cleanup)
        if small is not None:
            release(SMALL_CLAMP_NAME, small.cleanup)
        if clamp is not None:
            release(CLAMP_NAME, clamp.cleanup)
        if motor1 is not None:
            release("Motor 1", motor1.cleanup)
        if motor2 is not None:
            release("Motor 2", motor2.cleanup)


if __name__ == "__main__":
    raise SystemExit(main())
