"""Eva workspace binding: local / Hub shared path / Hub HTTP.

Memory, knowledge and skills stay on this Eva.
Workspace files can be the Hub office share after linking.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MODES = ("local", "shared_path", "hub_http")
_HUB_OK_TTL = 20.0
_HUB_DOWN_TTL = 45.0
_hub_cache: dict[str, Any] = {"ok": None, "until": 0.0}


def blank_workspace_binding() -> dict[str, str]:
    return {"mode": "local", "root": "", "hub_url": ""}


def _store_binding() -> dict[str, str]:
    out = blank_workspace_binding()
    try:
        from app.config_store import get_config_store

        raw = get_config_store().get_raw().get("workspace")
        if isinstance(raw, dict):
            mode = str(raw.get("mode") or "local").strip().lower()
            if mode not in MODES:
                mode = "local"
            out["mode"] = mode
            out["root"] = str(raw.get("root") or "").strip()
            out["hub_url"] = str(raw.get("hub_url") or "").strip().rstrip("/")
    except Exception:
        logger.debug("workspace binding read failed", exc_info=True)
    env_root = (os.environ.get("EVA_WORKSPACE_DIR") or "").strip()
    if env_root:
        out["root"] = env_root
        if out["mode"] == "local":
            out["mode"] = "shared_path"
    return out


def local_default_root() -> Path:
    from app.config import PROJECT_ROOT

    return (Path(PROJECT_ROOT) / "workspace").resolve()


def _paths_equal(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def is_self_shared_binding(b: dict[str, str] | None = None) -> bool:
    """True when leftover Hub bind points at this Eva's own default workspace."""
    data = b if isinstance(b, dict) else _store_binding()
    if str(data.get("mode") or "") != "shared_path":
        return False
    raw = str(data.get("root") or "").strip()
    if not raw:
        return False
    try:
        return _paths_equal(Path(raw).expanduser(), local_default_root())
    except OSError:
        return False


def binding_public() -> dict[str, Any]:
    b = _store_binding()
    root = resolved_root()
    hub_live = uses_hub_http()
    mode = b["mode"]
    if mode == "hub_http" and not hub_live:
        mode = "local"
    self_shared = is_self_shared_binding(b)
    if self_shared:
        mode = "local"
    shared = (mode == "shared_path" and not self_shared) or hub_live
    return {
        "ok": True,
        "mode": mode,
        "configured_mode": b["mode"],
        "root": str(root),
        "configured_root": b["root"],
        "default_root": str(local_default_root()),
        "hub_url": b["hub_url"] if hub_live else "",
        "shared": shared,
        "hub_reachable": hub_live,
        "root_exists": root.is_dir(),
    }


def resolved_root() -> Path:
    """Disk path Eva writes to. Unlinked / local / hub_http → this Eva's workspace.

    Leftover ``root`` from an old Hub bind must not apply in ``local`` mode,
    otherwise same-machine Hub folders (often dated) show up as Eva's files.
    """
    b = _store_binding()
    if b["mode"] == "shared_path":
        raw = b["root"]
        if raw:
            try:
                p = Path(raw).expanduser().resolve()
                if p.is_dir():
                    return p
            except OSError:
                logger.warning("workspace root not usable: %s", raw)
    return local_default_root()


def _local_hosts() -> set[str]:
    found = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
    try:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.2)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        if ip and not ip.startswith("127."):
            found.add(ip.lower())
    except OSError:
        pass
    try:
        import socket

        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                found.add(ip.lower())
    except OSError:
        pass
    return found


def _listen_port() -> int:
    try:
        port = int((os.environ.get("PORT") or "0").strip() or 0)
    except ValueError:
        port = 0
    if port:
        return port
    try:
        from app.config import get_settings

        return int(getattr(get_settings(), "port", 0) or 0)
    except Exception:
        return 0


def _is_self_url(url: str) -> bool:
    """True if *url* points at this Eva process (must not treat as Hub)."""
    try:
        from urllib.parse import urlparse

        u = urlparse(url)
        host = (u.hostname or "").lower()
        if not host:
            return False
        port = int(u.port or (443 if u.scheme == "https" else 80))
        mine = _listen_port()
        if not mine or port != mine:
            return False
        return host in _local_hosts()
    except Exception:
        return False


def _probe_hub(url: str) -> bool:
    """Hub workspace is live only if Hub's list API returns ``items``.

    Eva itself serves ``/api/workspace/browse`` with ``entries`` — that must
    not count as Hub. ``/api/health`` is also too weak (same-machine Eva).
    """
    if _is_self_url(url):
        return False
    try:
        import httpx

        target = url.rstrip("/") + "/api/workspace/list"
        with httpx.Client(
            timeout=httpx.Timeout(2.0, connect=1.2),
            follow_redirects=True,
            trust_env=False,
        ) as client:
            r = client.get(target, params={"path": ""})
            if r.status_code >= 400:
                return False
            data = r.json() if r.content else {}
            items = data.get("items") if isinstance(data, dict) else None
            return isinstance(items, list)
    except Exception:
        return False


def binding_snapshot() -> dict[str, Any]:
    """Persisted binding without probing Hub (safe to call on save/start)."""
    b = _store_binding()
    root = local_default_root()
    if b["mode"] == "shared_path" and b["root"]:
        try:
            p = Path(b["root"]).expanduser().resolve()
            if p.is_dir():
                root = p
        except OSError:
            pass
    self_shared = is_self_shared_binding(b)
    mode = "local" if self_shared else b["mode"]
    shared = (mode == "shared_path" and not self_shared) or mode == "hub_http"
    return {
        "ok": True,
        "mode": mode,
        "configured_mode": b["mode"],
        "root": str(root),
        "configured_root": b["root"],
        "default_root": str(local_default_root()),
        "hub_url": b["hub_url"],
        "shared": shared,
        "hub_reachable": None,
        "root_exists": root.is_dir(),
    }


def mark_hub_reachable() -> None:
    _hub_cache["ok"] = True
    _hub_cache["until"] = time.monotonic() + _HUB_OK_TTL


def mark_hub_unreachable() -> None:
    _hub_cache["ok"] = False
    _hub_cache["until"] = time.monotonic() + _HUB_DOWN_TTL


def clear_hub_reachability() -> None:
    _hub_cache["ok"] = None
    _hub_cache["until"] = 0.0


def uses_hub_http() -> bool:
    """True only when Hub workspace is configured *and* Hub is reachable.

    Standalone Eva (or a leftover hub_url whose Hub is down) uses the local
    workspace. Never treat a dead Hub as the active file store.
    """
    b = _store_binding()
    if b["mode"] != "hub_http" or not b["hub_url"]:
        return False
    now = time.monotonic()
    if _hub_cache["ok"] is not None and now < float(_hub_cache["until"] or 0):
        return bool(_hub_cache["ok"])
    ok = _probe_hub(b["hub_url"])
    if ok:
        mark_hub_reachable()
    else:
        mark_hub_unreachable()
        logger.info(
            "Hub workspace unreachable (%s); using local workspace",
            b["hub_url"],
        )
    return ok


def hub_url() -> str:
    return _store_binding()["hub_url"]


def apply_binding(
    *,
    mode: str = "",
    root: str = "",
    hub_url: str = "",
) -> dict[str, Any]:
    """Validate and persist binding. Returns public view or raises ValueError."""
    from app.config_store import get_config_store

    cur = _store_binding()
    mode_n = (mode or cur["mode"] or "local").strip().lower()
    if mode_n not in MODES:
        raise ValueError("mode 必须是 local / shared_path / hub_http")
    root_n = (root if root is not None else cur["root"]).strip()
    hub_n = (hub_url if hub_url is not None else cur["hub_url"]).strip().rstrip("/")

    if mode_n == "shared_path":
        if not root_n:
            raise ValueError("shared_path 需要 root（Hub 工作区绝对路径）")
        p = Path(root_n).expanduser()
        try:
            p = p.resolve()
        except OSError as exc:
            raise ValueError(f"无法解析工作区路径: {exc}") from exc
        if not p.is_dir():
            raise ValueError(f"Hub 工作区路径不存在或不可用: {p}")
        if _paths_equal(p, local_default_root()):
            mode_n = "local"
            root_n = ""
            hub_n = ""
        else:
            root_n = str(p)
    elif mode_n == "hub_http":
        if not hub_n.startswith("http://") and not hub_n.startswith("https://"):
            raise ValueError("hub_http 需要可访问的 hub_url")
        root_n = root_n or ""
    else:
        mode_n = "local"
        root_n = ""
        hub_n = ""

    get_config_store().update_section(
        "workspace",
        {"mode": mode_n, "root": root_n, "hub_url": hub_n},
    )
    clear_hub_reachability()
    return binding_snapshot()
