#!/usr/bin/env python3
"""Generate a random 7-digit number that hasn't been used before.

Used numbers are tracked in used_numbers.txt (one per line, same folder
as this script). Run it as many times as you like.
"""

import argparse
import random
from pathlib import Path

USED_FILE = Path(__file__).with_name("used_numbers.txt")


def load_used() -> set[str]:
    if USED_FILE.exists():
        return set(USED_FILE.read_text().split())
    return set()


def generate_unique(used: set[str]) -> str:
    while True:
        candidate = str(random.randint(1_000_000, 9_999_999))
        if candidate not in used:
            return candidate


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate unique random 7-digit numbers.")
    parser.add_argument("count", type=int, nargs="?", default=1,
                         help="how many numbers to generate (default: 1)")
    args = parser.parse_args()

    used = load_used()
    new_numbers = []
    for _ in range(args.count):
        number = generate_unique(used)
        used.add(number)
        new_numbers.append(number)

    with USED_FILE.open("a") as f:
        f.write("\n".join(new_numbers) + "\n")

    for number in new_numbers:
        print(number)


if __name__ == "__main__":
    main()
