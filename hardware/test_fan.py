"""Drive the PWM fan interactively and watch the tachometer.

Step through the speeds with the number keys or space, and press q to stop.
Measured RPM is printed every REPORT_INTERVAL seconds.

Requires pigpiod:
    sudo systemctl start pigpiod

Run from the project root:
    uv run python hardware/test_fan.py

If uv is not on PATH:
    ~/.local/bin/uv run python hardware/test_fan.py
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
from hardware.fan import FanController, FanError




# Duty cycles to step through, 0 to 100. Keys 1-9 pick one directly.
SPEEDS = [0, 70,100]

# Seconds between RPM readings.
REPORT_INTERVAL = 3.0

# Press this to stop the fan and exit.
QUIT_KEY = "q"



def apply_speed(fan: FanController, duty: float) -> None:
    applied = fan.set_duty(duty)
    note = f" (raised from {duty:g})" if applied != duty else ""
    print(f"duty -> {applied:g}%{note}")


def run_console(fan: FanController) -> None:
    index = 0
    apply_speed(fan, SPEEDS[index])
    next_report = time.monotonic() + REPORT_INTERVAL

    while True:
        key = read_key(max(0.0, next_report - time.monotonic()))

        if key is None:
            rpm = fan.read_rpm()
            # None means no tach is wired; the fan may well still be spinning.
            reading = "no tach" if rpm is None else f"{rpm:7.0f} RPM"
            print(f"  {reading}   (duty {fan.duty_pct:g}%)")
            next_report = time.monotonic() + REPORT_INTERVAL
            continue

        if key == QUIT_KEY:
            print("\nStopping.")
            return
        if key in {" ", "\r", "\n"}:
            index = (index + 1) % len(SPEEDS)
            apply_speed(fan, SPEEDS[index])
        elif key.isdigit() and 1 <= int(key) <= len(SPEEDS):
            index = int(key) - 1
            apply_speed(fan, SPEEDS[index])


def main() -> int:
    config = ConfigManager(CONFIG_PATH).load()
    fan_config = config["fan"]

    print("Stop the ExamScan backend before running this test.")
    print("Keep clear of the fan blades.\n")
    print(f"PWM pin: {fan_config['pin']}")
    print(f"Tach pin: {fan_config['tach_pin']}")
    print(f"Frequency: {fan_config['frequency_hz']} Hz")
    print(f"Minimum start duty: {fan_config['min_start_duty_pct']}%\n")

    choices = "  ".join(f"{i}={speed:g}%" for i, speed in enumerate(SPEEDS, start=1))
    print(f"Keys: {choices}")
    print(f"      space = next speed, {QUIT_KEY} = quit\n")

    try:
        fan = FanController.from_config(fan_config)
    except FanError as exc:
        print(f"Could not start the fan: {exc}", file=sys.stderr)
        return 2

    try:
        with key_input():
            run_console(fan)
        return 0
    except ConsoleError as exc:
        print(exc, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 1
    finally:
        fan.cleanup()
        print("Fan cleaned up.")


if __name__ == "__main__":
    raise SystemExit(main())
