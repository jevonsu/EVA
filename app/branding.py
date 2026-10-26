"""Brand assets: logo.png is the single Eva mark (window, exe, sidebar, login)."""

from __future__ import annotations

from pathlib import Path


def logo_png() -> Path:
    from app.config import RESOURCE_ROOT

    p = Path(RESOURCE_ROOT) / "app" / "static" / "logo.png"
    if p.is_file():
        return p
    return Path(__file__).resolve().parent / "static" / "logo.png"


def logo_ico() -> Path:
    from app.config import RESOURCE_ROOT

    p = Path(RESOURCE_ROOT) / "app" / "static" / "logo.ico"
    if p.is_file():
        return p
    return Path(__file__).resolve().parent / "static" / "logo.ico"
