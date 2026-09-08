"""Single-keypress terminal input, shared by the manual hardware scripts.

Normal terminal input only arrives after Enter, which is no use for driving
hardware live. These helpers switch the terminal to cbreak mode so each key
arrives on its own, and put the original settings back afterwards.
"""

from __future__ import annotations

import select
import sys
import termios
import tty
from contextlib import contextmanager


class ConsoleError(RuntimeError):
    pass


@contextmanager
def key_input():
    """Deliver keypresses unbuffered for the duration of the block.

    cbreak rather than raw mode, so Ctrl+C still interrupts.
    """
    if not sys.stdin.isatty():
        raise ConsoleError("stdin is not a terminal - run this directly, not through a pipe")

    stdin_fd = sys.stdin.fileno()
    saved_term = termios.tcgetattr(stdin_fd)
    try:
        tty.setcbreak(stdin_fd)
        yield
    finally:
        # TCSADRAIN so pending output still lands before the mode switches back.
        termios.tcsetattr(stdin_fd, termios.TCSADRAIN, saved_term)


def read_key(timeout=None):
    """Return one keypress, or None if timeout passes first.

    A timeout of None waits indefinitely.
    """
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if not ready:
        return None
    return sys.stdin.read(1)
