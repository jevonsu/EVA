"""Persistent multi-endpoint webhook configuration.

Stored at ``data/webhooks/endpoints.json`` (legacy: ``data/webhooks.json``)::

    {
      "endpoints": [
        {
          "id": "...",
          "name": "飞书客服",
          "slug": "feishu-cs",
          "enabled": true,
          "token": "...",
          "platform": "feishu",
          "session_mode": "fixed",   # fixed | map | new
          "session_id": "",
          "use_tools": true,
          "use_memory": true,
          "note": "",
          "created_at": "...",
          "updated_at": "..."
        }
      ]
    }

Also migrates legacy ``integrations.webhook`` once.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger("app.webhook.store")

SESSION_MODES = frozenset({"fixed", "map", "new"})
_SLUG_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,47}$")

_store: "WebhookStore | None" = None
_store_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_token() -> str:
    return secrets.token_urlsafe(24)


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


_RESERVED_SLUGS = frozenset({"chat", "health", "sessions", "api", "webhook", "webhooks"})


def normalize_slug(raw: str | None, *, fallback: str = "") -> str:
    s = (raw or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9_-]+", "", s)
    s = s.strip("-_")
    if not s:
        s = re.sub(r"[^a-z0-9_-]+", "", (fallback or "hook").lower()) or "hook"
    if not re.match(r"^[a-z]", s):
        s = "w-" + s
    s = s[:48]
    if s in _RESERVED_SLUGS:
        s = f"ch-{s}"[:48]
    return s


def public_endpoint(row: dict[str, Any]) -> dict[str, Any]:
    """Mask token for UI/API list."""
    out = deepcopy(row)
    tok = str(out.get("token") or "").strip()
    out["token_set"] = bool(tok)
    out["token"] = ""  # never send raw
    out["token_hint"] = (tok[:4] + "…" + tok[-4:]) if len(tok) >= 12 else ("已设置" if tok else "")
    slug = str(out.get("slug") or out.get("id") or "")
    out["url_path"] = f"/api/webhook/{slug}/chat" if slug else "/api/webhook/chat"
    out["health_path"] = f"/api/webhook/{slug}/health" if slug else "/api/webhook/health"
    return out


class WebhookStore:
    def __init__(self, path: Path | None = None) -> None:
        settings = get_settings()
        self.path = path or settings.paths().webhooks_endpoints
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {"endpoints": []}
        self.load()

    def load(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                self._data = {"endpoints": []}
                self._maybe_migrate_legacy_unlocked()
                self._write_unlocked()
            else:
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
                except (OSError, json.JSONDecodeError):
                    logger.exception("Failed to load webhooks.json")
                    raw = {}
                if not isinstance(raw, dict):
                    raw = {}
                eps = raw.get("endpoints")
                if not isinstance(eps, list):
                    eps = []
                self._data = {"endpoints": [e for e in eps if isinstance(e, dict)]}
                if not self._data["endpoints"]:
                    self._maybe_migrate_legacy_unlocked()
                    self._write_unlocked()
            return deepcopy(self._data)

    def _write_unlocked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _maybe_migrate_legacy_unlocked(self) -> None:
        """One-shot: integrations.webhook → first endpoint."""
        if self._data.get("endpoints"):
            return
        try:
            from app.config_store import get_config_store

            integ = get_config_store().get_integrations_raw().get("webhook") or {}
        except Exception:
            integ = {}
        if not isinstance(integ, dict):
            return
        token = str(integ.get("token") or "").strip()
        if not token and not str(integ.get("default_session_id") or "").strip():
            return
        now = _now()
        ep = {
            "id": _new_id(),
            "name": "默认 Webhook（已迁移）",
            "slug": "default",
            "enabled": str(integ.get("enabled") or "true").strip().lower()
            not in ("0", "false", "no", "off"),
            "token": token or _new_token(),
            "platform": "custom",
            "session_mode": "fixed"
            if str(integ.get("default_session_id") or "").strip()
            else "map",
            "session_id": str(integ.get("default_session_id") or "").strip(),
            "use_tools": str(integ.get("use_tools") or "true").strip().lower()
            not in ("0", "false", "no", "off"),
            "use_memory": str(integ.get("use_memory") or "true").strip().lower()
            not in ("0", "false", "no", "off"),
            "note": "从 integrations.webhook 自动迁移",
            "created_at": now,
            "updated_at": now,
        }
        self._data["endpoints"] = [ep]
        logger.info("Migrated legacy integrations.webhook → endpoint %s", ep["id"])

    def list_raw(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self._data.get("endpoints") or [])

    def list_public(self) -> list[dict[str, Any]]:
        return [public_endpoint(e) for e in self.list_raw()]

    def get_raw(self, endpoint_id: str) -> dict[str, Any] | None:
        eid = (endpoint_id or "").strip()
        if not eid:
            return None
        with self._lock:
            for e in self._data.get("endpoints") or []:
                if str(e.get("id")) == eid:
                    return deepcopy(e)
        return None

    def get_by_slug_raw(self, slug: str) -> dict[str, Any] | None:
        s = normalize_slug(slug)
        with self._lock:
            for e in self._data.get("endpoints") or []:
                if normalize_slug(str(e.get("slug") or e.get("id") or "")) == s:
                    return deepcopy(e)
        return None

    def find_by_token(self, token: str) -> dict[str, Any] | None:
        tok = (token or "").strip()
        if not tok:
            return None
        with self._lock:
            for e in self._data.get("endpoints") or []:
                if str(e.get("token") or "").strip() == tok:
                    return deepcopy(e)
        return None

    def _slug_taken(self, slug: str, *, exclude_id: str | None = None) -> bool:
        s = normalize_slug(slug)
        for e in self._data.get("endpoints") or []:
            if exclude_id and str(e.get("id")) == exclude_id:
                continue
            if normalize_slug(str(e.get("slug") or e.get("id") or "")) == s:
                return True
        return False

    def create(self, fields: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            name = str(fields.get("name") or "").strip() or "未命名通道"
            slug = normalize_slug(fields.get("slug"), fallback=name)
            if self._slug_taken(slug):
                base = slug
                for i in range(2, 50):
                    cand = f"{base}-{i}"[:48]
                    if not self._slug_taken(cand):
                        slug = cand
                        break
            mode = str(fields.get("session_mode") or "fixed").strip().lower()
            if mode not in SESSION_MODES:
                mode = "fixed"
            now = _now()
            row = {
                "id": _new_id(),
                "name": name[:80],
                "slug": slug,
                "enabled": bool(fields.get("enabled", True)),
                "token": str(fields.get("token") or "").strip() or _new_token(),
                "platform": str(fields.get("platform") or "custom").strip()[:40]
                or "custom",
                "session_mode": mode,
                "session_id": str(fields.get("session_id") or "").strip(),
                "use_tools": bool(fields.get("use_tools", True)),
                "use_memory": bool(fields.get("use_memory", True)),
                "note": str(fields.get("note") or "").strip()[:500],
                "created_at": now,
                "updated_at": now,
            }
            self._data.setdefault("endpoints", []).append(row)
            self._write_unlocked()
            return public_endpoint(row)

    def update(self, endpoint_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        eid = (endpoint_id or "").strip()
        with self._lock:
            rows: list[dict[str, Any]] = self._data.setdefault("endpoints", [])
            idx = next((i for i, e in enumerate(rows) if str(e.get("id")) == eid), -1)
            if idx < 0:
                return None
            cur = dict(rows[idx])
            if "name" in fields and fields["name"] is not None:
                cur["name"] = str(fields["name"]).strip()[:80] or cur.get("name") or "未命名"
            if "slug" in fields and fields["slug"] is not None:
                slug = normalize_slug(fields["slug"], fallback=cur.get("name") or "hook")
                if self._slug_taken(slug, exclude_id=eid):
                    raise ValueError(f"slug 已被占用: {slug}")
                cur["slug"] = slug
            if "enabled" in fields and fields["enabled"] is not None:
                cur["enabled"] = bool(fields["enabled"])
            if "token" in fields:
                tok = str(fields["token"] or "").strip()
                # empty = keep existing
                if tok and tok not in ("********", "••••••••"):
                    cur["token"] = tok
            if "platform" in fields and fields["platform"] is not None:
                cur["platform"] = str(fields["platform"]).strip()[:40] or "custom"
            if "session_mode" in fields and fields["session_mode"] is not None:
                mode = str(fields["session_mode"]).strip().lower()
                if mode not in SESSION_MODES:
                    raise ValueError("session_mode 须为 fixed | map | new")
                cur["session_mode"] = mode
            if "session_id" in fields:
                cur["session_id"] = str(fields.get("session_id") or "").strip()
            if "use_tools" in fields and fields["use_tools"] is not None:
                cur["use_tools"] = bool(fields["use_tools"])
            if "use_memory" in fields and fields["use_memory"] is not None:
                cur["use_memory"] = bool(fields["use_memory"])
            if "note" in fields and fields["note"] is not None:
                cur["note"] = str(fields["note"]).strip()[:500]
            cur["updated_at"] = _now()
            rows[idx] = cur
            self._write_unlocked()
            return public_endpoint(cur)

    def regenerate_token(self, endpoint_id: str) -> dict[str, Any] | None:
        eid = (endpoint_id or "").strip()
        with self._lock:
            rows: list[dict[str, Any]] = self._data.setdefault("endpoints", [])
            for i, e in enumerate(rows):
                if str(e.get("id")) != eid:
                    continue
                e = dict(e)
                e["token"] = _new_token()
                e["updated_at"] = _now()
                rows[i] = e
                self._write_unlocked()
                # return once with plaintext token for copy
                pub = public_endpoint(e)
                pub["token"] = e["token"]
                pub["token_set"] = True
                return pub
        return None

    def delete(self, endpoint_id: str) -> bool:
        eid = (endpoint_id or "").strip()
        with self._lock:
            rows: list[dict[str, Any]] = self._data.setdefault("endpoints", [])
            n = len(rows)
            self._data["endpoints"] = [e for e in rows if str(e.get("id")) != eid]
            if len(self._data["endpoints"]) == n:
                return False
            self._write_unlocked()
            return True

    def reveal_token(self, endpoint_id: str) -> str | None:
        row = self.get_raw(endpoint_id)
        if not row:
            return None
        return str(row.get("token") or "")


def get_webhook_store() -> WebhookStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = WebhookStore()
        return _store
