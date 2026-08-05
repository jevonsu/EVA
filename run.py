"""Convenience launcher: python run.py

Always chdirs to the project root so relative paths and tooling behave the same
on Windows, Linux, and when launched via systemd / absolute path.
"""

from __future__ import annotations

import os
from pathlib import Path

# Project root = directory containing this file
_ROOT = Path(__file__).resolve().parent
os.chdir(_ROOT)

from app.main import run  # noqa: E402

if __name__ == "__main__":
    run()
