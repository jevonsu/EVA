"""In-process broadcast bus for sidebar session updates (IM-style push).

Thread-safe: publish() may be called from run_db worker threads.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

_subs: set[asyncio.Queue] = set()
_loop: asyncio.AbstractEventLoop | None = None


def subscribe() -> asyncio.Queue:
    global _loop
    _loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subs.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subs.discard(q)


def _deliver(evt: dict[str, Any]) -> None:
    for q in list(_subs):
        try:
            q.put_nowait(evt)
        except asyncio.QueueFull:
            try:
                q.get_nowait()
                q.put_nowait(evt)
            except Exception:
                pass


def publish(kind: str, session_id: str, **extra: Any) -> None:
    if not _subs or _loop is None or _loop.is_closed():
        return
    evt = {
        "type": kind,
        "session_id": session_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        **extra,
    }
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    try:
        if running is _loop:
            _deliver(evt)
        else:
            _loop.call_soon_threadsafe(_deliver, evt)
    except Exception:
        pass