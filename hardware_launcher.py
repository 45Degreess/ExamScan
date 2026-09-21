"""Compatibility launchers for running the isolated scanner service from the repo root."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


HARDWARE_PROJECT = Path(__file__).resolve().parent / "hardware" / "scanner-service"


def _launch(command: str) -> None:
    uv = shutil.which("uv")
    if uv is None:
        local_uv = Path.home() / ".local" / "bin" / "uv"
        uv = str(local_uv) if local_uv.is_file() else None
    if uv is None:
        raise SystemExit("uv is not installed or is not on PATH")
    if not (HARDWARE_PROJECT / "pyproject.toml").is_file():
        raise SystemExit(f"hardware project not found: {HARDWARE_PROJECT}")
    os.execv(
        uv,
        [uv, "run", "--project", str(HARDWARE_PROJECT), command, *sys.argv[1:]],
    )


def production() -> None:
    _launch("examscan")


def development() -> None:
    _launch("examscan-dev")


def rig() -> None:
    _launch("examscan-rig")
