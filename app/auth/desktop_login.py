"""Card login from the Eva launcher (no web form)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("app.auth.desktop_login")


def launcher_login(
    *,
    card_code: str,
    control_url: str,
    control_key: str,
    port: int,
) -> tuple[bool, str]:
    """Verify card against CardServer and write the local session.

    Returns (ok, message). Secrets are not logged.
    """
    card = (card_code or "").strip()
    if len(card) < 8:
        return False, "请填写有效卡密（至少 8 位）"
    try:
        payload, err = asyncio.run(
            _remote(card=card, control_url=control_url, control_key=control_key, port=port)
        )
    except RuntimeError:
        # nested loop (shouldn't happen in launcher worker)
        payload, err = None, "登录失败：事件循环占用"
    except Exception as exc:
        logger.exception("launcher login failed")
        return False, str(exc)
    if not payload:
        return False, err or "登录失败"
    _persist(payload, control_key=control_key, control_url=control_url)
    hint = str(payload.get("card_hint") or "").strip()
    return True, ("登录成功" + (f" · {hint}" if hint else ""))


async def _remote(
    *,
    card: str,
    control_url: str,
    control_key: str,
    port: int,
) -> tuple[dict[str, Any] | None, str]:
    from app.auth.login_prefs import load_login_prefs
    from app.auth.remote import normalize_control_url, remote_login
    from app.config import get_settings

    settings = get_settings()
    prefs = load_login_prefs()
    device_id = str(prefs.get("device_id") or "").strip()
    node_base = (getattr(settings, "auth_node_id", None) or "eva").strip() or "eva"
    node_id = f"{node_base}:{int(port or getattr(settings, 'port', 0) or 0)}"
    url = normalize_control_url(control_url) or None
    key = (control_key or "").strip() or None
    return await remote_login(
        card_code=card,
        client_ip="127.0.0.1",
        user_agent="Eva-Launcher",
        node_id=node_id,
        device_id=device_id,
        device_label="Eva 启动器",
        control_url=url,
        control_key=key,
        try_fallbacks=True,
    )


def _persist(payload: dict[str, Any], *, control_key: str, control_url: str) -> None:
    from app.auth.hub_grant import issue_pairing
    from app.auth.instance import install_fingerprint
    from app.auth.local_session import save_local_session
    from app.auth.login_prefs import load_login_prefs, save_login_prefs
    from app.auth.offline import save_offline_grant
    from app.auth.remote import normalize_control_url
    from app.config import get_settings

    token = str(payload.get("session_token") or "")
    used_control = normalize_control_url(
        str(payload.get("control_url") or control_url or "")
    )
    prefs = load_login_prefs()
    device_id = str(prefs.get("device_id") or "")
    try:
        save_login_prefs(control_url=used_control, device_id=device_id, has_saved=True)
    except Exception:
        logger.exception("save_login_prefs failed")
    try:
        issue_pairing(
            session_token=token,
            device_id=device_id,
            control_url=used_control,
            expires_at=float(payload.get("expires_at") or 0),
        )
    except Exception:
        logger.exception("issue pairing after launcher login failed")
    if payload.get("allow_offline"):
        try:
            save_offline_grant(
                session_token=token,
                device_id=device_id,
                expires_at=float(payload.get("expires_at") or 0),
                card_expires_at=(
                    float(payload["card_expires_at"])
                    if payload.get("card_expires_at") is not None
                    else None
                ),
                card_id=payload.get("card_id"),
                card_hint=str(payload.get("card_hint") or ""),
                allow_offline=True,
                control_url=used_control,
                plan_name=str(payload.get("plan_name") or ""),
                instance_id=str(payload.get("instance_id") or ""),
                instance_fp=install_fingerprint(),
            )
        except Exception:
            logger.exception("save_offline_grant failed")
    used_key = (control_key or "").strip() or (
        getattr(get_settings(), "auth_control_key", None) or ""
    ).strip()
    save_local_session(
        session_token=token,
        device_id=device_id,
        control_key=used_key,
        expires_at=float(payload.get("expires_at") or 0),
    )


def session_ok() -> bool:
    try:
        from app.auth.local_session import load_local_session

        return bool(load_local_session())
    except Exception:
        return False
