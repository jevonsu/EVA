"""主备模型自动切换（LLM failover）。

配置（data/config.json → ``llm_failover``）::

    "llm_failover": {
        "enabled": false,
        "primary_llm_id": "",          # 空 = 设定→模型 的默认模型
        "backup_llm_ids": ["deepseek"],# 按顺序尝试
        "connect_timeout": 10,         # 主模型连接超时（秒）
        "first_token_timeout": 30,     # 主模型流式首字超时（秒）
        "stream_idle_timeout": 60,     # 主模型流式中途卡顿超时（秒）
        "response_timeout": 120,       # 主模型非流式（含工具调用）整体超时（秒）
        "cooldown_s": 60,              # 熔断初始冷却，连续失败指数增长
        "cooldown_max_s": 600,
        "tools_use_backup": false,     # 工具调用/复杂任务始终用备用模型
        "push_token": ""               # 推送新主模型地址用的令牌（只存服务端）
    }

适用范围：默认模型客户端（get_llm_client）以及任何 llm_id 等于主模型的客户端
（模型路由命中主模型时同样生效）。主模型失败（连接/DNS/隧道断开、超时、
401/403/404/429/5xx、Cloudflare 错误页、空回复）且尚未输出任何内容时，在同一
请求内透明改用备用模型；流式中途断开时由备用模型续写。主模型失败后熔断，冷却期内
直接走备用，后台探测 ``{base}/models`` 恢复后自动切回。

日志与状态接口从不包含 API Key。
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
import secrets
import time
from collections import deque
from typing import Any, AsyncIterator
from urllib.parse import urlparse

logger = logging.getLogger("app.llm.failover")

CFG_KEY = "llm_failover"
DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "primary_llm_id": "",
    "backup_llm_ids": [],
    "connect_timeout": 10,
    "first_token_timeout": 30,
    "stream_idle_timeout": 60,
    "response_timeout": 120,
    "cooldown_s": 60,
    "cooldown_max_s": 600,
    "tools_use_backup": False,
    "push_token": "",
}
_NUM_LIMITS = {
    "connect_timeout": (2, 120),
    "first_token_timeout": (5, 600),
    "stream_idle_timeout": (5, 900),
    "response_timeout": (10, 1800),
    "cooldown_s": (5, 3600),
    "cooldown_max_s": (10, 86400),
}
CONTINUE_PROMPT = "（上一条回复因连接中断被截断。请从中断处直接接着写完剩余内容，不要重复已输出部分，也不要解释中断。）"


# ---------------------------------------------------------------- config

def normalize_cfg(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULTS)
    out["enabled"] = data.get("enabled") is True or str(data.get("enabled")).lower() in ("1", "true")
    out["primary_llm_id"] = str(data.get("primary_llm_id") or "").strip()
    backs: list[str] = []
    for b in data.get("backup_llm_ids") or []:
        s = str(b or "").strip()
        if s and s not in backs:
            backs.append(s)
    out["backup_llm_ids"] = backs[:6]
    for k, (lo, hi) in _NUM_LIMITS.items():
        try:
            v = float(data.get(k, DEFAULTS[k]))
        except (TypeError, ValueError):
            v = float(DEFAULTS[k])
        out[k] = max(lo, min(hi, v))
    if out["cooldown_max_s"] < out["cooldown_s"]:
        out["cooldown_max_s"] = out["cooldown_s"]
    out["tools_use_backup"] = data.get("tools_use_backup") is True or str(data.get("tools_use_backup")).lower() in ("1", "true")
    out["push_token"] = str(data.get("push_token") or "").strip()
    return out


def _store():
    from app.config_store import get_config_store

    return get_config_store()


def get_cfg() -> dict[str, Any]:
    try:
        return normalize_cfg(_store().get_raw().get(CFG_KEY))
    except Exception:
        return normalize_cfg(None)


def public_cfg(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    c = dict(cfg or get_cfg())
    c["push_token_set"] = bool(c.pop("push_token", ""))
    return c


def save_cfg(incoming: dict[str, Any]) -> dict[str, Any]:
    """Save user-editable fields; push_token is kept unless explicitly given."""
    cur = get_cfg()
    merged = dict(cur)
    for k in DEFAULTS:
        if k == "push_token":
            continue
        if k in incoming:
            merged[k] = incoming[k]
    if "push_token" in incoming and incoming["push_token"] is not None and not _looks_masked(str(incoming["push_token"])):
        merged["push_token"] = str(incoming["push_token"])
    value = normalize_cfg(merged)
    _store().update_section(CFG_KEY, value)
    reset_runtime(keep_health=True)
    return value


def _looks_masked(s: str) -> bool:
    return "*" in s or "•" in s


def new_push_token() -> str:
    tok = "evapush_" + secrets.token_urlsafe(24)
    cfg = get_cfg()
    cfg["push_token"] = tok
    _store().update_section(CFG_KEY, normalize_cfg(cfg))
    return tok


def check_push_token(given: str) -> bool:
    want = get_cfg().get("push_token") or ""
    if not want or not given:
        return False
    return hmac.compare_digest(want.encode(), given.strip().encode())


def _row(llm_id: str) -> dict[str, Any] | None:
    if not llm_id:
        return None
    try:
        row = _store().get_llm(llm_id)
    except Exception:
        return None
    if not row or row.get("enabled", True) is False:
        return None
    return row


def primary_row(cfg: dict[str, Any] | None = None) -> dict[str, Any] | None:
    cfg = cfg or get_cfg()
    if cfg["primary_llm_id"]:
        return _row(cfg["primary_llm_id"])
    try:
        return _store().get_default_llm()
    except Exception:
        return None


def backup_rows(cfg: dict[str, Any], primary_id: str) -> list[dict[str, Any]]:
    out = []
    for bid in cfg["backup_llm_ids"]:
        if bid == primary_id:
            continue
        r = _row(bid)
        if r:
            out.append(r)
    return out


# ---------------------------------------------------------------- runtime state

class _Health:
    __slots__ = ("fails", "down_until", "last_error", "last_error_at", "last_ok_at", "probe_at", "probing")

    def __init__(self) -> None:
        self.fails = 0
        self.down_until = 0.0
        self.last_error = ""
        self.last_error_at = 0.0
        self.last_ok_at = 0.0
        self.probe_at = 0.0
        self.probing = False


_HEALTH: dict[str, _Health] = {}
_EVENTS: deque = deque(maxlen=40)
_STATE: dict[str, Any] = {"active_id": "", "last_switch": None}
_CLIENTS: dict[tuple, Any] = {}
_PROBES: dict[str, asyncio.Task] = {}
_now = time.time  # patchable in tests


def health(llm_id: str) -> _Health:
    h = _HEALTH.get(llm_id)
    if h is None:
        h = _HEALTH[llm_id] = _Health()
    return h


def reset_runtime(*, keep_health: bool = False) -> None:
    for c in list(_CLIENTS.values()):
        _close_later(c)
    _CLIENTS.clear()
    if not keep_health:
        _HEALTH.clear()
        _EVENTS.clear()
        _STATE.update({"active_id": "", "last_switch": None})
        for t in list(_PROBES.values()):
            t.cancel()
        _PROBES.clear()


def _close_later(client: Any) -> None:
    http = getattr(client, "_http", None)
    if http is None:
        return
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(http.aclose())
    except RuntimeError:
        pass
    except Exception:
        pass


def _name(row: dict[str, Any] | None) -> str:
    if not row:
        return "?"
    return str(row.get("name") or row.get("model") or row.get("id") or "?")


def _host(base: str) -> str:
    try:
        return urlparse(base or "").netloc or ""
    except Exception:
        return ""


_SECRET_RX = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+|\b(sk|evapush)[-_][A-Za-z0-9._\-]{6,}")


def scrub(text: str, *secrets_: str) -> str:
    t = str(text or "")
    for s in secrets_:
        if s and len(s) >= 6:
            t = t.replace(s, "***")
    t = _SECRET_RX.sub(lambda m: (m.group(1) or "") + "***", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:300]


def _event(kind: str, msg: str, **extra: Any) -> None:
    ev = {"at": _now(), "kind": kind, "msg": msg}
    ev.update(extra)
    _EVENTS.appendleft(ev)


def _set_active(row: dict[str, Any], reason: str, cfg: dict[str, Any]) -> None:
    rid = str(row.get("id") or "")
    prev = _STATE.get("active_id") or ""
    if rid != prev:
        prow = _row(prev) if prev else None
        if prev:
            _STATE["last_switch"] = {"at": _now(), "from": prev, "from_name": _name(prow), "to": rid, "to_name": _name(row), "reason": reason}
            logger.warning("LLM failover: active model %s -> %s (%s)", _name(prow), _name(row), reason)
            _event("switch", f"{_name(prow)} → {_name(row)}：{reason}")
        _STATE["active_id"] = rid


def _mark_ok(row: dict[str, Any]) -> None:
    rid = str(row.get("id") or "")
    h = health(rid)
    was_down = h.fails > 0
    h.fails = 0
    h.down_until = 0.0
    h.last_ok_at = _now()
    if was_down:
        logger.info("LLM failover: %s recovered", _name(row))
        _event("recover", f"{_name(row)} 已恢复")


def _mark_fail(row: dict[str, Any], reason: str, *, trip: bool, cfg: dict[str, Any], is_primary: bool) -> None:
    rid = str(row.get("id") or "")
    h = health(rid)
    h.last_error = reason
    h.last_error_at = _now()
    if not trip:
        return
    h.fails += 1
    cd = min(cfg["cooldown_s"] * (2 ** (h.fails - 1)), cfg["cooldown_max_s"])
    h.down_until = _now() + cd
    logger.warning("LLM failover: %s marked down for %ds (fail #%d): %s", _name(row), int(cd), h.fails, reason)
    _event("down", f"{_name(row)} 不可用，冷却 {int(cd)} 秒：{reason}")
    if is_primary:
        ensure_probe(row, cfg)


# ---------------------------------------------------------------- classification

class BadResponse(Exception):
    """Model answered 2xx but with an unusable body (HTML page / empty)."""


def _looks_html(text: str) -> bool:
    t = (text or "").lstrip()[:600].lower()
    return t.startswith("<!doctype html") or t.startswith("<html") or ("<html" in t and ("cloudflare" in t or "<head" in t))


def _cf_reason(body: str, status: int) -> str:
    low = (body or "").lower()
    code = re.search(r"error\s*(?:code)?\s*[:#]?\s*(10\d\d|5\d\d)", low)
    if "cloudflare" in low or "trycloudflare" in low or status == 530:
        return f"Cloudflare 隧道错误页（HTTP {status}{'，' + code.group(1) if code else ''}）"
    return f"返回了 HTML 错误页（HTTP {status}）"


def classify(exc: BaseException) -> tuple[bool, bool, str]:
    """Return (failover, trip_breaker, reason_zh)."""
    try:
        import openai
    except Exception:  # pragma: no cover
        openai = None  # type: ignore
    import httpx

    if isinstance(exc, BadResponse):
        return True, True, str(exc)
    if isinstance(exc, asyncio.TimeoutError):
        return True, True, "超时（主模型无响应）"
    if openai is not None:
        if isinstance(exc, openai.APITimeoutError):
            return True, True, "请求超时"
        if isinstance(exc, openai.APIConnectionError):
            cause = exc.__cause__ or exc.__context__
            return True, True, "连接失败（网络/DNS/隧道断开）" + (f"：{type(cause).__name__}" if cause else "")
        if isinstance(exc, openai.APIStatusError):
            st = int(getattr(exc, "status_code", 0) or 0)
            body = ""
            try:
                body = exc.response.text or ""
            except Exception:
                body = str(exc)
            if _looks_html(body) or st == 530:
                return True, True, _cf_reason(body, st)
            low = (str(exc) + " " + body).lower()
            if st == 400 and "context" in low and ("exceed" in low or "length" in low or "too long" in low):
                return True, False, "上下文超出主模型窗口"
            if st in (401, 403):
                return True, True, f"鉴权失败（HTTP {st}，Key 无效或已更换）"
            if st == 404:
                return True, True, "地址或模型不存在（HTTP 404）"
            if st == 408:
                return True, True, "请求超时（HTTP 408）"
            if st == 429:
                return True, True, "频率/额度受限（HTTP 429）"
            if st >= 500:
                return True, True, f"服务端错误（HTTP {st}）"
            return False, False, f"HTTP {st}"
    if isinstance(exc, (httpx.TimeoutException,)):
        return True, True, "请求超时"
    if isinstance(exc, (httpx.TransportError,)):
        return True, True, f"连接中断（{type(exc).__name__}）"
    if isinstance(exc, (ConnectionError, OSError)):
        return True, True, f"连接失败（{type(exc).__name__}）"
    msg = str(exc or "")
    low = msg.lower()
    if isinstance(exc, RuntimeError) and ("未配置" in msg or "未填写" in msg):
        return True, True, "主模型配置不完整"
    if "exceed" in low and "context" in low:
        return True, False, "上下文超出主模型窗口"
    for key in ("connection", "timed out", "timeout", "bad gateway", "service unavailable", "server disconnected", "remoteprotocolerror", "readerror", "status code 5", "cloudflare"):
        if key in low:
            return True, True, f"调用失败（{type(exc).__name__}）"
    return False, False, type(exc).__name__


def check_result(res: dict[str, Any]) -> None:
    content = res.get("content")
    if isinstance(content, str) and _looks_html(content):
        raise BadResponse(_cf_reason(content, 200))
    if not res.get("tool_calls") and not (isinstance(content, str) and content.strip()) and not res.get("media_paths"):
        raise BadResponse("空回复")


# ---------------------------------------------------------------- chain

def applies_to(owner: Any, cfg: dict[str, Any]) -> dict[str, Any] | None:
    """Primary row if failover should wrap calls made through ``owner``."""
    if not cfg["enabled"] or getattr(owner, "_no_failover", False):
        return None
    prow = primary_row(cfg)
    if not prow:
        return None
    pid = str(prow.get("id") or "")
    if getattr(owner, "_is_store_default", False) or (pid and str(getattr(owner, "llm_id", "") or "") == pid):
        if not backup_rows(cfg, pid):
            return None
        return prow
    return None


def plan(prow: dict[str, Any], cfg: dict[str, Any], *, tools: bool) -> tuple[list[tuple[dict[str, Any], str]], str]:
    pid = str(prow.get("id") or "")
    backs = backup_rows(cfg, pid)
    h = health(pid)
    note = ""
    if tools and cfg["tools_use_backup"]:
        order = [(b, "backup") for b in backs] + [(prow, "primary")]
        note = "工具调用设置为走备用模型"
    elif h.down_until > _now():
        order = [(b, "backup") for b in backs] + [(prow, "primary")]
        note = f"主模型熔断中（剩余 {int(h.down_until - _now())} 秒）：{h.last_error}"
    else:
        order = [(prow, "primary")] + [(b, "backup") for b in backs]
    return order, note


def member_client(row: dict[str, Any], role: str, cfg: dict[str, Any]):
    from app.llm.client import LLMClient

    key_h = hashlib.sha256(str(row.get("api_key") or "").encode()).hexdigest()[:12]
    ck = (str(row.get("id")), str(row.get("base_url")), str(row.get("model")), key_h, bool(row.get("use_proxy")), role, cfg["connect_timeout"], cfg["response_timeout"])
    cli = _CLIENTS.get(ck)
    if cli is None:
        cli = LLMClient.from_llm_config(row)
        cli._no_failover = True
        if role == "primary":
            cli._connect_timeout = float(cfg["connect_timeout"])
            cli._read_timeout = float(max(cfg["response_timeout"], cfg["stream_idle_timeout"]))
            cli._max_retries = 0
        # drop stale clients of the same row/role
        for k in [k for k in _CLIENTS if k[0] == ck[0] and k[5] == role]:
            _close_later(_CLIENTS.pop(k))
        _CLIENTS[ck] = cli
    return cli


def _fail_text(row: dict[str, Any], reason: str) -> str:
    return f"{_name(row)}：{reason}"


async def run_chat(owner: Any, prow: dict[str, Any], cfg: dict[str, Any], messages, *, tools, model, temperature, tool_choice) -> dict[str, Any]:
    order, note = plan(prow, cfg, tools=bool(tools))
    if note:
        logger.info("LLM failover: %s", note)
    errors: list[str] = []
    last_exc: BaseException | None = None
    prev_reason = note
    for row, role in order:
        cli = member_client(row, role, cfg)
        if not cli.is_configured:
            reason = "配置不完整（缺 base_url / model / Key）"
            _mark_fail(row, reason, trip=role == "primary", cfg=cfg, is_primary=role == "primary")
            errors.append(_fail_text(row, reason))
            prev_reason = reason
            continue
        use_model = model if (model and str(row.get("id")) == str(getattr(owner, "llm_id", "") or "")) else None
        t0 = _now()
        try:
            coro = cli._raw_chat(messages, tools=tools, model=use_model, temperature=temperature, tool_choice=tool_choice)
            if role == "primary":
                res = await asyncio.wait_for(coro, timeout=cfg["response_timeout"])
            else:
                res = await coro
            check_result(res)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001
            fo, trip, reason = classify(exc)
            reason = scrub(reason, str(row.get("api_key") or ""))
            if not fo:
                raise _explain(exc) from exc
            _mark_fail(row, reason, trip=trip, cfg=cfg, is_primary=role == "primary")
            logger.warning("LLM failover: %s failed after %.1fs: %s", _name(row), _now() - t0, reason)
            errors.append(_fail_text(row, reason))
            last_exc = exc
            prev_reason = reason
            continue
        _mark_ok(row)
        _set_active(row, prev_reason or ("主模型可用" if role == "primary" else "切换"), cfg)
        res.setdefault("llm_id", row.get("id"))
        return res
    raise RuntimeError("主备模型均不可用：" + "；".join(errors)) from last_exc


async def run_stream(owner: Any, prow: dict[str, Any], cfg: dict[str, Any], messages, *, model, temperature) -> AsyncIterator[str]:
    order, note = plan(prow, cfg, tools=False)
    if note:
        logger.info("LLM failover: %s", note)
    emitted: list[str] = []
    errors: list[str] = []
    prev_reason = note
    for row, role in order:
        cli = member_client(row, role, cfg)
        if not cli.is_configured:
            reason = "配置不完整（缺 base_url / model / Key）"
            _mark_fail(row, reason, trip=role == "primary", cfg=cfg, is_primary=role == "primary")
            errors.append(_fail_text(row, reason))
            prev_reason = reason
            continue
        msgs = list(messages)
        if emitted:
            msgs = msgs + [{"role": "assistant", "content": "".join(emitted)}, {"role": "user", "content": CONTINUE_PROMPT}]
        use_model = model if (model and str(row.get("id")) == str(getattr(owner, "llm_id", "") or "")) else None
        agen = cli._raw_stream(msgs, model=use_model, temperature=temperature)
        got = 0
        first = True
        head: str | None = ""
        try:
            while True:
                if role == "primary":
                    tmo = cfg["first_token_timeout"] if first else cfg["stream_idle_timeout"]
                    chunk = await asyncio.wait_for(agen.__anext__(), timeout=tmo)
                else:
                    chunk = await agen.__anext__()
                first = False
                if not chunk:
                    continue
                if head is not None:
                    head += chunk
                    lead = head.lstrip()
                    if lead.startswith("<"):
                        if _looks_html(head):
                            raise BadResponse(_cf_reason(head, 200))
                        if len(head) < 200:
                            continue  # keep buffering a possible HTML error page
                    chunk, head = head, None
                got += 1
                emitted.append(chunk)
                yield chunk
        except StopAsyncIteration:
            if head and got == 0:  # stream ended while still buffering
                if _looks_html(head):
                    reason = _cf_reason(head, 200)
                    _mark_fail(row, reason, trip=True, cfg=cfg, is_primary=role == "primary")
                    errors.append(_fail_text(row, reason))
                    prev_reason = reason
                    continue
                emitted.append(head)
                got += 1
                yield head
            if got == 0 and not emitted:
                reason = "空回复"
                _mark_fail(row, reason, trip=True, cfg=cfg, is_primary=role == "primary")
                errors.append(_fail_text(row, reason))
                prev_reason = reason
                continue
            _mark_ok(row)
            _set_active(row, prev_reason or ("主模型可用" if role == "primary" else "切换"), cfg)
            return
        except asyncio.CancelledError:
            await _aclose(agen)
            raise
        except BaseException as exc:  # noqa: BLE001
            await _aclose(agen)
            fo, trip, reason = classify(exc)
            reason = scrub(reason, str(row.get("api_key") or ""))
            if not fo:
                if got or emitted:
                    raise RuntimeError(f"回复中途中断：{reason}") from exc
                raise _explain(exc) from exc
            if got:
                reason = "流式中途断开：" + reason
            _mark_fail(row, reason, trip=trip, cfg=cfg, is_primary=role == "primary")
            logger.warning("LLM failover (stream): %s failed after %d chunks: %s", _name(row), got, reason)
            errors.append(_fail_text(row, reason))
            prev_reason = reason
            continue
    if emitted:
        raise RuntimeError("回复中途中断，备用模型也无法续写：" + "；".join(errors))
    raise RuntimeError("主备模型均不可用：" + "；".join(errors))


async def _aclose(agen: Any) -> None:
    try:
        await agen.aclose()
    except BaseException:  # noqa: BLE001
        pass


def _explain(exc: BaseException) -> BaseException:
    from app.llm.client import _explain_llm_http_error

    if isinstance(exc, RuntimeError):
        return exc
    return _explain_llm_http_error(exc)


# ---------------------------------------------------------------- probe / recovery

async def probe(row: dict[str, Any], cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET {base}/models (then {origin}/health) with the row's key. Never returns the key."""
    import httpx

    cfg = cfg or get_cfg()
    base = str(row.get("base_url") or "").strip().rstrip("/")
    key = str(row.get("api_key") or "").strip()
    if not base:
        return {"ok": False, "error": "未填写 base_url"}
    kw: dict[str, Any] = {"trust_env": False, "follow_redirects": True, "timeout": httpx.Timeout(15.0, connect=float(cfg["connect_timeout"]))}
    if row.get("use_proxy"):
        try:
            from app.services.model_meta import resolve_app_proxy_url

            p = resolve_app_proxy_url()
            if p:
                kw["proxy"] = p
        except Exception:
            pass
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    pu = urlparse(base)
    urls = [base + "/models", f"{pu.scheme}://{pu.netloc}/health"]
    t0 = _now()
    last = ""
    try:
        async with httpx.AsyncClient(**kw) as c:
            for u in urls:
                try:
                    r = await c.get(u, headers=headers)
                except httpx.HTTPError as exc:
                    last = f"连接失败（{type(exc).__name__}）"
                    break
                text = r.text[:2000]
                if _looks_html(text) or r.status_code == 530:
                    last = _cf_reason(text, r.status_code)
                    break
                if r.status_code in (401, 403):
                    last = f"鉴权失败（HTTP {r.status_code}）"
                    break
                if r.status_code == 200:
                    models = []
                    try:
                        j = r.json()
                        for m in (j.get("data") or j.get("models") or []) if isinstance(j, dict) else []:
                            if isinstance(m, dict):
                                models.append(str(m.get("id") or m.get("name") or m.get("model") or ""))
                    except Exception:
                        pass
                    return {"ok": True, "url_path": urlparse(u).path, "ms": int((_now() - t0) * 1000), "models": [m for m in models if m][:20]}
                last = f"HTTP {r.status_code}"
    except Exception as exc:  # noqa: BLE001
        last = f"探测异常（{type(exc).__name__}）"
    return {"ok": False, "error": scrub(last, key), "ms": int((_now() - t0) * 1000)}


def ensure_probe(row: dict[str, Any], cfg: dict[str, Any]) -> None:
    rid = str(row.get("id") or "")
    t = _PROBES.get(rid)
    if t is not None and not t.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _PROBES[rid] = loop.create_task(_probe_loop(rid))


async def _probe_loop(rid: str) -> None:
    try:
        while True:
            h = health(rid)
            if h.down_until <= 0:
                return
            wait = max(1.0, h.down_until - _now())
            await asyncio.sleep(min(wait, 600))
            cfg = get_cfg()
            prow = primary_row(cfg)
            if not cfg["enabled"] or not prow or str(prow.get("id")) != rid:
                return
            if health(rid).down_until <= 0:
                return
            h.probing = True
            res = await probe(prow, cfg)
            h.probing = False
            h.probe_at = _now()
            if res.get("ok"):
                _mark_ok(prow)
                _event("probe", f"{_name(prow)} 探测成功，恢复为主模型")
                return
            _mark_fail(prow, "探测失败：" + str(res.get("error") or ""), trip=True, cfg=cfg, is_primary=False)
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception("LLM failover probe loop crashed")
    finally:
        _PROBES.pop(rid, None)


# ---------------------------------------------------------------- status

def _row_status(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    rid = str(row.get("id") or "")
    h = health(rid)
    now = _now()
    if h.down_until > now:
        st = "down"
    elif h.fails > 0:
        st = "retrying"
    elif h.last_ok_at:
        st = "up"
    else:
        st = "unknown"
    return {
        "id": rid,
        "name": _name(row),
        "model": str(row.get("model") or ""),
        "host": _host(str(row.get("base_url") or "")),
        "state": st,
        "fails": h.fails,
        "down_for_s": max(0, int(h.down_until - now)) if h.down_until > now else 0,
        "last_error": h.last_error,
        "last_error_at": h.last_error_at or None,
        "last_ok_at": h.last_ok_at or None,
        "probing": h.probing or (rid in _PROBES and not _PROBES[rid].done()),
    }


def status() -> dict[str, Any]:
    cfg = get_cfg()
    prow = primary_row(cfg)
    pid = str((prow or {}).get("id") or "")
    backs = backup_rows(cfg, pid) if prow else []
    aid = _STATE.get("active_id") or ""
    active = None
    if aid:
        ar = _row(aid)
        active = {"id": aid, "name": _name(ar)} if ar else None
    if active is None and prow:
        h = health(pid)
        if cfg["enabled"] and h.down_until > _now() and backs:
            active = {"id": str(backs[0].get("id")), "name": _name(backs[0])}
        else:
            active = {"id": pid, "name": _name(prow)}
    # lazy: primary cooldown expired but still flagged → probe in background
    if cfg["enabled"] and prow and health(pid).fails > 0:
        ensure_probe(prow, cfg)
    return {
        "enabled": cfg["enabled"],
        "ready": bool(cfg["enabled"] and prow and backs),
        "tools_use_backup": cfg["tools_use_backup"],
        "primary": _row_status(prow),
        "backups": [_row_status(b) for b in backs],
        "active": active,
        "last_switch": _STATE.get("last_switch"),
        "events": list(_EVENTS)[:15],
        "now": _now(),
    }
