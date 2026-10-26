"""Small helpers for sync SQL ops from async store methods."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, TypeVar

T = TypeVar("T")


async def run_db(fn: Callable[[], T]) -> T:
    """Run blocking DB work off the event loop."""
    return await asyncio.to_thread(fn)


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def loads(raw: str | None, default: Any = None) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default
