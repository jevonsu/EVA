"""Normalize ask_user / deputy prompts into a compact bubble form."""

from __future__ import annotations

import json
import re
from typing import Any

_MAX_OPTIONS = 8
_MAX_FIELDS = 6
_MAX_LABEL = 80

_SKIP_LABELS = frozenset({"补充", "补充说明", "请选择", "单选", "多选"})


def _strip(v: Any) -> str:
    return str(v or "").strip()


def _split_lines(raw: str) -> list[str]:
    t = _strip(raw)
    if not t:
        return []
    if t.startswith("["):
        try:
            parsed = json.loads(t)
            if isinstance(parsed, list):
                return [_strip(x) for x in parsed if _strip(x)]
        except json.JSONDecodeError:
            pass
    parts: list[str] = []
    for line in re.split(r"[\n|;；]+", t):
        s = _strip(line)
        s = re.sub(r"^(?:[0-9]{1,2}|[A-Fa-f])[.\、\)\]]\s*", "", s)
        s = re.sub(r"^[-*•]\s*", "", s)
        if s:
            parts.append(s[:_MAX_LABEL])
    return parts


def _split_choices(raw: str) -> list[str]:
    t = _strip(raw)
    if not t:
        return []
    if "\n" in t:
        lines = [_strip(x) for x in t.split("\n") if _strip(x)]
        if len(lines) >= 2:
            return [p[:_MAX_LABEL] for p in lines][:_MAX_OPTIONS]
    # 不要用裸 `/` 切开「播/停/切歌」；只用「 / 」、顿号、竖线
    parts = re.split(r"\s+/\s+|\s*[|｜、]\s+", t)
    return [p[:_MAX_LABEL] for p in (_strip(x) for x in parts) if p][:_MAX_OPTIONS]


def _field_id(prefix: str, index: int, label: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", label).strip("_").lower()
    if not slug or slug.isdigit():
        slug = f"{prefix}{index}"
    return slug[:32]


def _choice_options(labels: list[str]) -> list[dict[str, str]]:
    return [{"value": str(i + 1), "label": lab} for i, lab in enumerate(labels)]


def _parse_spec_line(line: str) -> dict[str, Any] | None:
    s = _strip(line)
    if not s:
        return None
    m = re.match(
        r"^(单选|多选|输入|填写|文本|长文|多行)\s*[：:]?\s*(.*)$",
        s,
    )
    if not m:
        return None
    kind, rest = m.group(1), _strip(m.group(2))
    label = ""
    choices_raw = rest
    if kind in ("单选", "多选") and "：" in rest:
        label, choices_raw = rest.split("：", 1)
        label, choices_raw = _strip(label), _strip(choices_raw)
    elif kind in ("单选", "多选") and ":" in rest:
        label, choices_raw = rest.split(":", 1)
        label, choices_raw = _strip(label), _strip(choices_raw)
    if kind in ("单选", "多选"):
        opts = _split_choices(choices_raw)
        if not opts and label:
            opts = _split_choices(label)
            label = ""
        if not opts:
            return None
        return {
            "type": "multi" if kind == "多选" else "single",
            "label": label or ("多选" if kind == "多选" else "单选"),
            "options": _choice_options(opts),
            "required": True,
        }
    if kind in ("长文", "多行"):
        return {
            "type": "textarea",
            "label": rest or "补充",
            "required": False,
            "placeholder": "点这里输入",
        }
    return {
        "type": "text",
        "label": rest or "输入",
        "required": False,
        "placeholder": "点这里输入",
    }


def _normalize_field(raw: dict[str, Any], index: int) -> dict[str, Any] | None:
    ftype = _strip(raw.get("type")).lower()
    if ftype in ("choice", "radio", "select", "单选"):
        ftype = "single"
    elif ftype in ("checkbox", "checkboxes", "多选"):
        ftype = "multi"
    elif ftype in ("input", "string", "输入", "url"):
        ftype = "text"
    elif ftype in ("password", "secret", "密钥"):
        ftype = "password"
    elif ftype in ("note", "long", "长文"):
        ftype = "textarea"
    if ftype not in ("single", "multi", "text", "textarea", "password"):
        return None
    label = _strip(raw.get("label"))[:_MAX_LABEL] or ftype
    fid = _strip(raw.get("id")) or _field_id("f", index, label)
    out: dict[str, Any] = {
        "id": fid[:32],
        "type": ftype,
        "label": label,
        "required": bool(raw.get("required")),
        "placeholder": _strip(raw.get("placeholder"))[:_MAX_LABEL],
        "secret": bool(raw.get("secret")) or ftype == "password",
    }
    if ftype in ("single", "multi"):
        opts_raw = raw.get("options") or []
        labels: list[str] = []
        if isinstance(opts_raw, str):
            labels = _split_lines(opts_raw) or _split_choices(opts_raw)
        elif isinstance(opts_raw, list):
            for o in opts_raw:
                if isinstance(o, dict):
                    lab = _strip(o.get("label") or o.get("value"))
                    if lab:
                        labels.append(lab[:_MAX_LABEL])
                else:
                    lab = _strip(o)
                    if lab:
                        labels.append(lab[:_MAX_LABEL])
        if not labels:
            return None
        out["options"] = _choice_options(labels[:_MAX_OPTIONS])
        out["required"] = True if raw.get("required") is None else bool(raw.get("required"))
    return out


def build_form(
    *,
    title: str = "",
    prompt: str = "",
    options: str | list[str] = "",
    multi: str | list[str] = "",
    fields: str | list[str] = "",
    spec: str = "",
    kind: str = "ask",
    submit_label: str = "发送",
) -> dict[str, Any] | None:
    title = _strip(title)[:_MAX_LABEL]
    prompt = _strip(prompt)[:400]
    out_fields: list[dict[str, Any]] = []

    for line in _split_lines(spec):
        parsed = _parse_spec_line(line)
        if not parsed:
            continue
        parsed["id"] = _field_id("f", len(out_fields) + 1, parsed.get("label") or "")
        out_fields.append(parsed)
        if len(out_fields) >= _MAX_FIELDS:
            break

    opt_labels = (
        [_strip(x)[:_MAX_LABEL] for x in options if _strip(x)]
        if isinstance(options, list)
        else _split_lines(options)
    )[:_MAX_OPTIONS]
    if opt_labels and not any(f.get("type") == "single" for f in out_fields):
        out_fields.append(
            {
                "id": "choice",
                "type": "single",
                "label": "单选",
                "required": True,
                "options": _choice_options(opt_labels),
            }
        )

    multi_labels = (
        [_strip(x)[:_MAX_LABEL] for x in multi if _strip(x)]
        if isinstance(multi, list)
        else _split_lines(multi)
    )[:_MAX_OPTIONS]
    if multi_labels and not any(f.get("type") == "multi" for f in out_fields):
        out_fields.append(
            {
                "id": "multi",
                "type": "multi",
                "label": "多选",
                "required": False,
                "options": _choice_options(multi_labels),
            }
        )

    field_labels = (
        [_strip(x)[:_MAX_LABEL] for x in fields if _strip(x)]
        if isinstance(fields, list)
        else _split_lines(fields)
    )[:_MAX_FIELDS]
    for i, lab in enumerate(field_labels, start=1):
        out_fields.append(
            {
                "id": _field_id("f", i, lab),
                "type": "textarea" if len(lab) >= 12 else "text",
                "label": lab,
                "required": False,
                "placeholder": "点这里输入",
            }
        )

    if not out_fields and not (title or prompt):
        return None
    if not title:
        title = "还需要你补充一下"
    form = {
        "kind": kind if kind in ("ask", "deputy", "integ", "skill") else "ask",
        "title": title,
        "prompt": prompt,
        "submit_label": _strip(submit_label)[:20] or "发送",
        "fields": out_fields[: _MAX_FIELDS + 2],
    }
    if kind != "deputy":
        attach_other_and_cancel(form)
    return form


_OTHER_IDS = frozenset({"other", "note", "_cancel"})
_OTHER_LABELS = frozenset({"其他", "其它", "补充"})


def attach_other_and_cancel(form: dict[str, Any] | None) -> dict[str, Any]:
    """Every intake form: an 其他 box plus a cancel flag. Not a clone of 补充."""
    form = form if isinstance(form, dict) else {}
    fields = [f for f in (form.get("fields") or []) if isinstance(f, dict)]
    fields = [
        f
        for f in fields
        if _strip(f.get("id")) not in _OTHER_IDS
        and _strip(f.get("label")) not in _OTHER_LABELS
    ]
    fields.append(
        {
            "id": "other",
            "type": "textarea",
            "label": "其他",
            "required": False,
            "placeholder": "上面没有的、或想改的，写在这里",
        }
    )
    form["fields"] = fields
    form["cancellable"] = True
    return form


def skill_facts_already_collected(
    message: str,
    history: list[dict[str, Any]] | None = None,
    form_reply: Any = None,
) -> bool:
    """User already gave purpose/address this thread — do not ask again."""
    if is_form_cancel(form_reply):
        return False
    texts = [_strip(message)]
    for m in reversed(history or []):
        if m.get("role") != "user":
            continue
        texts.append(_strip(m.get("content")))
        if len(texts) >= 5:
            break
    blob = "\n".join(texts)
    has_facts = bool(
        "原需求：" in blob
        or _IP_RE.search(blob)
        or _URL_RE.search(blob)
        or "地址或端口" in blob
        or "接口地址" in blob
    )
    if not has_facts:
        prev = last_assistant_form(history)
        if prev and prev.get("kind") == "skill" and isinstance(form_reply, dict):
            return True
        return False
    if skill_authoring_mode(message) in {"create", "update"}:
        return True
    if isinstance(form_reply, dict):
        return True
    if re.search(r"确认|两个都要|按你建议|全套|开工|继续创建", message or ""):
        return True
    return "原需求：" in _strip(message)


def is_form_cancel(form_reply: Any) -> bool:
    if not isinstance(form_reply, dict):
        return False
    raw = form_reply.get("_cancel")
    if raw is True or raw == 1:
        return True
    return _strip(raw).lower() in ("1", "true", "yes", "cancel")


def integration_form_fields(
    integration_id: str, error: str = ""
) -> list[dict[str, Any]]:
    """Fields to collect in-chat. Secrets never appear in labels as values."""
    from app.services.integrations_meta import get_schema, is_secret_key

    iid = _strip(integration_id)
    err = (error or "").lower()
    rows: list[dict[str, Any]] = []

    def _add(key: str, label: str, *, secret: bool, required: bool, placeholder: str = "") -> None:
        k = _strip(key)
        if not k or any(r.get("id") == k for r in rows):
            return
        rows.append(
            {
                "id": k[:32],
                "type": "password" if secret else "text",
                "label": _strip(label)[:_MAX_LABEL] or k,
                "required": required,
                "secret": secret,
                "placeholder": _strip(placeholder)[:_MAX_LABEL],
            }
        )

    schema = get_schema(iid) if iid else None
    if schema:
        required_keys = {
            str(x) for x in (schema.get("required_for_ready") or []) if str(x).strip()
        }
        for f in schema.get("fields") or []:
            if not isinstance(f, dict):
                continue
            key = _strip(f.get("key"))
            if not key or f.get("type") in ("hosts_table", "items_table") or key in ("hosts", "hosts_json", "items"):
                continue
            if str(f.get("type") or "").lower() == "llm":
                opts: list[dict[str, str]] = []
                try:
                    from app.services.credentials import list_llms_public

                    for row in list_llms_public():
                        if row.get("enabled") is False:
                            continue
                        rid = _strip(row.get("id"))
                        if not rid:
                            continue
                        labn = _strip(row.get("name") or row.get("model") or rid)
                        model = _strip(row.get("model"))
                        label = f"{labn} · {model}" if model and model != labn else labn
                        opts.append({"value": rid, "label": label[:_MAX_LABEL]})
                except Exception:
                    opts = []
                if opts:
                    rows.append(
                        {
                            "id": key[:32],
                            "type": "single",
                            "label": str(f.get("label") or "识图用的模型")[:_MAX_LABEL],
                            "required": True,
                            "options": opts[:_MAX_OPTIONS],
                        }
                    )
                else:
                    _add(
                        key,
                        str(f.get("label") or "识图用的模型"),
                        secret=False,
                        required=True,
                        placeholder="先到设定→模型添加一条",
                    )
                continue
            secret = bool(f.get("secret")) or is_secret_key(key)
            _add(
                key,
                str(f.get("label") or key),
                secret=secret,
                required=key in required_keys or secret,
                placeholder=str(f.get("placeholder") or ""),
            )
    if not rows:
        try:
            from app.config_store import get_config_store

            raw = get_config_store().get_integrations_raw().get(iid) or {}
        except Exception:
            raw = {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                key = _strip(k)
                if not key or key.startswith("_") or key in ("hosts", "hosts_json", "items"):
                    continue
                secret = is_secret_key(key)
                _add(key, key, secret=secret, required=secret)
    if not rows:
        if "host" in err or "主机" in err:
            _add("url", "地址", secret=False, required=True, placeholder="https://example.com")
            _add("user", "用户名", secret=False, required=False)
            _add("password", "密码", secret=True, required=False)
        if "app_key" in err:
            _add("app_key", "App Key", secret=True, required=True)
            _add("secret_key", "Secret", secret=True, required=True)
        if re.search(r"\bkey\b|api[ _-]?key|token|密钥", err) and not any(
            r["id"] in ("key", "token", "api_key", "app_key") for r in rows
        ):
            key_id = "key" if "key" in err else "token"
            _add(key_id, "API Key", secret=True, required=True)
        if "password" in err or "密码" in err or "账号" in err or "用户" in err:
            _add("user", "用户名", secret=False, required=False)
            _add("password", "密码", secret=True, required=False)
        # 不再塞一套通用 URL/主机/账号/Token。缺什么问什么；其余写「其他」。
    return rows[:_MAX_FIELDS]


def integration_needed_form(info: dict[str, Any] | None = None) -> dict[str, Any]:
    info = info or {}
    label = _strip(info.get("label") or info.get("integration_id") or "这项能力")
    iid = _strip(info.get("integration_id"))
    fields = integration_form_fields(iid, str(info.get("error") or ""))
    howto_bits: list[str] = []
    schema = None
    try:
        from app.services.integrations_meta import get_schema

        schema = get_schema(iid)
    except Exception:
        schema = None
    if schema:
        desc = _strip(schema.get("description"))
        if desc:
            howto_bits.append(desc)
        for f in schema.get("fields") or []:
            if not isinstance(f, dict):
                continue
            hint = _strip(f.get("hint"))
            lab = _strip(f.get("label") or f.get("key"))
            if hint:
                howto_bits.append(f"{lab}：{hint}" if lab else hint)
    if not howto_bits:
        howto_bits.append(
            "打开该服务的管理后台或说明书，找到连接地址和密钥，填在下面。只存在本机。"
        )
    form = {
        "kind": "integ",
        "title": f"「{label}」还没配好",
        "prompt": "按下面的方法拿到信息再填。用不到的留空；不对写在「其他」，或取消。",
        "howto": "\n".join(howto_bits),
        "submit_label": "保存并继续",
        "fields": fields,
        "integration_id": iid,
        "pending_user": _strip(info.get("pending_user"))[:400],
    }
    return attach_other_and_cancel(form)


def apply_integ_form_reply(
    form: dict[str, Any] | None, values: dict[str, Any] | None
) -> tuple[bool, str]:
    """Save bubble-form values into integrations. Returns (ok, error)."""
    form = form or {}
    values = values if isinstance(values, dict) else {}
    iid = _strip(form.get("integration_id"))
    if not iid:
        return False, "缺少集成 id"
    payload: dict[str, Any] = {}
    for f in form.get("fields") or []:
        if not isinstance(f, dict):
            continue
        fid = _strip(f.get("id"))
        if not fid:
            continue
        raw = values.get(fid)
        text = _strip(raw)
        if not text:
            continue
        if fid in _OTHER_IDS:
            continue
        payload[fid] = text
    if not payload:
        return False, "没有填写任何字段"
    try:
        from app.config_store import get_config_store

        get_config_store().upsert_integration(iid, payload)
    except Exception as exc:
        return False, str(exc)
    return True, ""


def deputy_choice_form(deputy_name: str) -> dict[str, Any]:
    name = _strip(deputy_name) or "副模型"
    return {
        "kind": "deputy",
        "title": "要用副模型做这一件吗？",
        "prompt": f"这件事更适合用副模型（{name}）来做，主模型保持不变。不会改掉默认模型。",
        "submit_label": "确定",
        "fields": [
            {
                "id": "choice",
                "type": "single",
                "label": "单选",
                "required": True,
                "options": [
                    {"value": "deputy", "label": "用副模型做这一件"},
                    {"value": "primary", "label": "继续用主模型"},
                ],
            }
        ],
    }


def form_from_tool_payload(args: dict[str, Any] | None, result: str = "") -> dict[str, Any] | None:
    payload: dict[str, Any] = {}
    raw = _strip(result)
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = {}
    if isinstance(payload.get("form"), dict):
        form = dict(payload["form"])
        cleaned: list[dict[str, Any]] = []
        for i, f in enumerate(form.get("fields") or [], start=1):
            if isinstance(f, dict):
                nf = _normalize_field(f, i)
                if nf:
                    cleaned.append(nf)
        if cleaned:
            form["fields"] = cleaned
            form.setdefault("kind", "ask")
            if form.get("kind") != "deputy":
                attach_other_and_cancel(form)
            return form
    src = args if isinstance(args, dict) else {}
    return build_form(
        title=_strip(src.get("title") or payload.get("title")),
        prompt=_strip(src.get("prompt") or payload.get("prompt") or src.get("question")),
        options=src.get("options") or payload.get("options") or "",
        multi=src.get("multi") or payload.get("multi") or "",
        fields=src.get("fields") or payload.get("fields") or "",
        spec=_strip(src.get("spec") or payload.get("spec")),
    )


def _labels_for(field: dict[str, Any], picked: list[str]) -> list[str]:
    opts = {
        _strip(o.get("value")): _strip(o.get("label"))
        for o in (field.get("options") or [])
        if isinstance(o, dict)
    }
    out: list[str] = []
    for p in picked:
        lab = opts.get(p, p)
        if lab:
            out.append(lab)
    return out


def format_form_reply(form: dict[str, Any] | None, values: dict[str, Any] | None) -> str:
    form = form or {}
    values = values or {}
    bits: list[str] = []
    for field in form.get("fields") or []:
        if not isinstance(field, dict):
            continue
        fid = _strip(field.get("id"))
        if not fid:
            continue
        ftype = _strip(field.get("type")) or "text"
        raw = values.get(fid)
        if ftype in ("single", "choice"):
            text = _strip(raw)
            if not text:
                continue
            labs = _labels_for(field, [text])
            bits.append(labs[0] if labs else text)
            continue
        if ftype == "multi":
            picked: list[str] = []
            if isinstance(raw, list):
                picked = [_strip(x) for x in raw if _strip(x)]
            else:
                picked = [p for p in re.split(r"[,，、]", _strip(raw)) if p]
            labs = _labels_for(field, picked)
            if not labs:
                continue
            label = _strip(field.get("label"))
            joined = "、".join(labs)
            if label and label not in _SKIP_LABELS:
                bits.append(f"{label} {joined}")
            else:
                bits.append(joined)
            continue
        text = _strip(raw)
        if not text:
            continue
        label = _strip(field.get("label"))
        if label and label not in _SKIP_LABELS:
            bits.append(f"{label} {text}")
        else:
            bits.append(text)
    return "，".join(bits).strip()


def last_assistant_form(history: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    for m in reversed(history or []):
        if m.get("role") != "assistant":
            continue
        meta = m.get("metadata") or {}
        if isinstance(meta, dict) and isinstance(meta.get("form"), dict):
            return meta.get("form")
        return None
    return None


_SKILL_LIST_MARKERS = (
    "你有什么技能",
    "有什么技能",
    "有哪些技能",
    "会什么技能",
    "会哪些技能",
    "列出技能",
    "技能列表",
    "全部技能",
    "所有技能",
    "什么技能",
    "哪些技能",
    "list skills",
    "what skills",
)

_SKILL_CREATE_MARKERS = (
    "创建技能",
    "新建技能",
    "写一个技能",
    "写技能",
    "做成技能",
    "封装成技能",
    "创建一个技能",
    "新建一个技能",
    "创建工具",
    "新建工具",
    "做成工具",
    "create_tool",
    "create skill",
    "new skill",
)

_SKILL_UPDATE_MARKERS = (
    "更新技能",
    "修改技能",
    "编辑技能",
    "改技能",
    "改一下技能",
    "修复技能",
    "修一下技能",
    "技能更新",
    "技能修改",
    "技能编辑",
    "update skill",
    "edit skill",
    "fix skill",
)


def skill_authoring_mode(message: str) -> str | None:
    """This-turn create/update only. Listing / chatting about 技能 must not match.

    Session-sticky create_tool must not be passed in — callers should use the
    raw user text, not the merged intent_force set.
    """
    t = _strip(message)
    if not t:
        return None
    tl = t.lower()
    compact = "".join(t.lower().split())
    is_list = any(k in t or k in tl or k.replace(" ", "") in compact for k in _SKILL_LIST_MARKERS)
    is_update = any(
        k in t or k in tl or k.replace(" ", "") in compact for k in _SKILL_UPDATE_MARKERS
    )
    is_create = any(
        k in t or k in tl or k.replace(" ", "") in compact for k in _SKILL_CREATE_MARKERS
    )
    try:
        from app.tools.intent_routing import match_intents

        ids = {h.intent_id for h in match_intents(t)}
    except Exception:
        ids = set()
    if "skill_update" in ids:
        is_update = True
    if "skill_create" in ids:
        is_create = True
    if "skill_delete" in ids and not is_create and not is_update:
        return None
    if is_list and not is_create and not is_update:
        return None
    if is_update:
        return "update"
    if is_create:
        return "create"
    return None


def skill_turn_kind(message: str) -> str | None:
    """This-turn skill intent: create | update | delete | list | None."""
    mode = skill_authoring_mode(message)
    if mode:
        return mode
    t = _strip(message)
    if not t:
        return None
    try:
        from app.tools.intent_routing import match_intents

        ids = {h.intent_id for h in match_intents(t)}
    except Exception:
        ids = set()
    if "skill_delete" in ids:
        return "delete"
    if "skill_list" in ids:
        return "list"
    tl = t.lower()
    compact = "".join(tl.split())
    if any(
        k in t or k in tl or k.replace(" ", "") in compact for k in _SKILL_LIST_MARKERS
    ):
        return "list"
    return None


def should_offer_skill_form(
    message: str,
    intent_force: set[str] | None,
    history: list[dict[str, Any]] | None,
    *,
    form_reply: Any = None,
) -> bool:
    if form_reply:
        return False
    t = (message or "").strip()
    if not t or len(t) > 360:
        return False
    prev = last_assistant_form(history)
    if prev and prev.get("kind") != "deputy":
        return False
    _ = intent_force
    mode = skill_authoring_mode(t)
    if mode not in {"create", "update"}:
        return False
    return bool(skill_intake_plan(t, mode=mode).get("offer"))


_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{2,5})?\b")
_URL_RE = re.compile(r"https?://[^\s，。]+", re.I)
_PORT_RE = re.compile(r"端口\s*[：:]?\s*(\d{2,5})", re.I)
_SKILL_NAME_RE = re.compile(
    r"(?:改|修|更新|编辑|修改)\s*(?:一下)?\s*[「\"']?([\w\u4e00-\u9fff]{1,24})[」\"']?\s*技能"
    r"|技能\s*[「\"']?([\w\u4e00-\u9fff]{1,24})",
    re.I,
)


def _strip_create_wrapper(message: str) -> str:
    t = _strip(message)
    t = re.sub(
        r"^(请|帮我|麻烦)?(创建|新建|写|做)(一个|个|一下)?",
        "",
        t,
    )
    t = re.sub(r"[，,。]?\s*(地址|主机|端口).*$", "", t)
    t = re.sub(r"(的)?(技能|工具|skill)\s*$", "", t, flags=re.I)
    return t.strip(" ，。,.")


_HOWTO_PURPOSE = (
    "用一句话写这个技能要帮你干什么。\n"
    "例如：把上传的 Excel 做成汇总表；按单号查快递。"
)

_HOWTO_LAN = (
    "这个技能要连你局域网里的设备，需要地址。\n"
    "1. 打开设备屏幕或设置页，看 IP。\n"
    "2. 或用电脑打开路由器（常见 192.168.1.1）→ 已连接的设备。\n"
    "3. 端口看说明书；播放器常见 9090，网页常见 80 或 8080。\n"
    "填在下面。不会的写「其他」，或点取消。"
)

_HOWTO_API = (
    "这个技能要连网上的服务，需要接口地址和密钥。\n"
    "1. 用浏览器登录该网站。\n"
    "2. 打开「开发者 / API / 开放平台 / 账号设置」。\n"
    "3. 新建应用，或复制已有的 API Key 和接口网址。\n"
    "密钥只存在本机，不会写进技能文件。不会的写「其他」，或点取消。"
)


def _has_addr(message: str) -> tuple[bool, str]:
    t = _strip(message)
    ip = _IP_RE.search(t)
    url = _URL_RE.search(t)
    port_m = _PORT_RE.search(t)
    if url:
        return True, url.group(0)
    if ip:
        addr = ip.group(0)
        if port_m and ":" not in addr:
            addr = f"{addr}:{port_m.group(1)}"
        return True, addr
    if port_m:
        return True, f"端口 {port_m.group(1)}"
    return False, ""


def _looks_file_skill(message: str) -> bool:
    t = _strip(message)
    return bool(
        re.search(
            r"excel|xlsx|docx|pptx|csv|pdf|表格|文件|汇总|转换|本地",
            t,
            re.I,
        )
    )


def _looks_lan_skill(message: str) -> bool:
    t = _strip(message)
    compact = "".join(t.lower().split())
    return bool(
        re.search(
            r"播放|控制|设备|nas|路由器|打印机|"
            r"播放器|ssh|端口|局域网",
            t,
            re.I,
        )
        or "lms" in compact
    )


def _looks_api_skill(message: str) -> bool:
    t = _strip(message)
    return bool(
        re.search(
            r"\bapi\b|接口|快递|天气|token|密钥|登录|云端|webhook|数据库",
            t,
            re.I,
        )
    )


def _has_secret_in_text(message: str) -> bool:
    t = _strip(message)
    return bool(re.search(r"key|token|密钥|密码|secret", t, re.I))


def skill_intake_plan(message: str, *, mode: str | None = None) -> dict[str, Any]:
    """Whether ordinary users must fetch extra info. No form = create this turn."""
    kind = (mode or skill_authoring_mode(message) or "create").strip().lower()
    t = _strip(message)
    known: list[str] = []
    spec: list[str] = []
    howto = ""
    title = "还需要你提供连接信息"
    prompt = ""

    if kind == "update":
        title = "改技能还缺一项"
        name = ""
        m = _SKILL_NAME_RE.search(t)
        if m:
            name = _strip(m.group(1) or m.group(2) or "")
        if name:
            known.append(f"技能：{name}")
        else:
            spec.append("输入 要改哪个技能")
        change = re.sub(
            r"^(请|帮我|麻烦)?(改|修|更新|编辑|修改)(一下)?",
            "",
            t,
        )
        if name:
            change = re.sub(re.escape(name) + r"\s*技能", "", change, count=1)
        else:
            change = re.sub(r"技能", "", change, count=1)
        change = change.strip(" 的，。,.")
        if len(change) < 2:
            spec.append("输入 要改什么")
        else:
            known.append(f"改动：{change[:80]}")
        if spec:
            howto = "写清改哪一个、改什么。不改连接就不用填地址或密钥。"
            prompt = (
                ("已经听到：" + "；".join(known) + "。") if known else ""
            ) + "补下面缺的即可，或取消。"
        return {
            "offer": bool(spec),
            "kind": kind,
            "title": title,
            "prompt": prompt.strip(),
            "howto": howto,
            "spec": "\n".join(spec),
            "known": known,
        }

    rest = _strip_create_wrapper(t)
    has_addr, addr = _has_addr(t)
    file_like = _looks_file_skill(t)
    lan_like = _looks_lan_skill(t)
    api_like = _looks_api_skill(t)
    if len(rest) >= 2:
        known.append(f"用途：{rest[:80]}")
    if has_addr:
        known.append(f"地址：{addr}")

    if len(rest) < 2:
        spec.append("输入 这个技能要做什么")
        howto = _HOWTO_PURPOSE
        prompt = "先写清要干什么，再创建。或点取消。"
        return {
            "offer": True,
            "kind": "create",
            "title": "这个技能要做什么？",
            "prompt": prompt,
            "howto": howto,
            "spec": "\n".join(spec),
            "known": known,
        }

    # 本地文件类：用户没有要填的连接信息，直接创建。
    if file_like and not lan_like and not api_like:
        return {
            "offer": False,
            "kind": "create",
            "title": "",
            "prompt": "",
            "howto": "",
            "spec": "",
            "known": known,
        }

    if lan_like and not has_addr:
        spec.append("输入 地址或端口")
        howto = _HOWTO_LAN
        prompt = "已经听到：" + "；".join(known) + "。按下面的方法找到地址再填。"
        return {
            "offer": True,
            "kind": "create",
            "title": "还差设备地址",
            "prompt": prompt,
            "howto": howto,
            "spec": "\n".join(spec),
            "known": known,
        }

    if api_like and not has_addr and not _has_secret_in_text(t):
        spec.append("输入 接口地址")
        spec.append("输入 API Key 或 Token")
        howto = _HOWTO_API
        prompt = "已经听到：" + "；".join(known) + "。按下面的方法拿到密钥再填。"
        return {
            "offer": True,
            "kind": "create",
            "title": "还差接口和密钥",
            "prompt": prompt,
            "howto": howto,
            "spec": "\n".join(spec),
            "known": known,
        }

    return {
        "offer": False,
        "kind": "create",
        "title": "",
        "prompt": "",
        "howto": "",
        "spec": "",
        "known": known,
    }


def skill_intake_form(user_message: str = "", *, mode: str | None = None) -> dict[str, Any]:
    kind = (mode or skill_authoring_mode(user_message) or "create").strip().lower()
    plan = skill_intake_plan(user_message, mode=kind)
    form = build_form(
        title=plan.get("title") or "还需要你提供信息",
        prompt=plan.get("prompt") or "",
        spec=str(plan.get("spec") or ""),
        kind="skill",
    ) or {}
    form["kind"] = "skill"
    form["skill_mode"] = kind
    form["howto"] = _strip(plan.get("howto"))
    msg = _strip(user_message)
    if msg:
        form["pending_user"] = msg[:400]
    if plan.get("known"):
        form["known"] = plan["known"]
    return attach_other_and_cancel(form)


_PROGRESS_MARKERS = (
    "已调用工具",
    "各阶段工具额度",
    "工具额度均已用完",
    "本轮工具调用已达",
    "已达最大工具调用",
    "请根据已执行的工具结果",
)

_Q_LINE_RE = re.compile(
    r"(?:^|\n)\s*(?:\d{1,2}[.、\)）]|[-*•]|Q\s*\d+[:：]?)\s+(.+)",
)

_ASKING_ADDR_RE = re.compile(
    r"(请.{0,12}(填|提供|告诉|给出).{0,16}(地址|端口|主机|IP\b)|"
    r"(地址|端口|主机|IP).{0,10}(是多少|填哪|是什么)|"
    r"地址或端口)",
    re.I,
)

_CONTINUE_Q_RE = re.compile(r"是否继续|要不要继续|需要我继续|要开始吗|要我接着")


def _quiz_question_lines(text: str) -> list[str]:
    """Numbered / bulleted lines that are actually questions, not task steps."""
    out: list[str] = []
    for m in _Q_LINE_RE.finditer(text or ""):
        q = _strip(m.group(1))
        q = re.sub(r"^[\s\*\#>]+", "", q)
        q = re.sub(r"\s+", " ", q).strip(" 。；;")
        if not q or _CONTINUE_Q_RE.search(q):
            continue
        if "？" not in q and "?" not in q and "还是" not in q:
            continue
        if 4 <= len(q) <= _MAX_LABEL + 24:
            out.append(q[:_MAX_LABEL])
        if len(out) >= _MAX_FIELDS:
            break
    return out


def _form_has_questions(form: dict[str, Any] | None) -> bool:
    if not isinstance(form, dict):
        return False
    return any(
        isinstance(f, dict) and _strip(f.get("id")) not in _OTHER_IDS
        for f in (form.get("fields") or [])
    )


def looks_like_user_quiz(text: str) -> bool:
    """True only when the text is a questionnaire we can turn into fields."""
    t = text or ""
    if not t.strip():
        return False
    if any(k in t for k in _PROGRESS_MARKERS):
        return False
    return _form_has_questions(quiz_to_form(t))


def _or_options(question: str) -> list[str] | None:
    s = re.sub(r"[？?]+$", "", _strip(question))
    m = re.search(r"(.+?)\s*还是\s+(.+)$", s)
    if not m:
        return None
    left, right = _strip(m.group(1)), _strip(m.group(2))
    left = re.split(r"[，,：:]\s*", left)[-1]
    left = re.sub(r"^(?:用|选|是)\s*", "", left).strip()
    right = right.strip()
    if not left or not right or left == right:
        return None
    if len(left) > 32 or len(right) > 32:
        return None
    return [left[:_MAX_LABEL], right[:_MAX_LABEL]]


def maybe_quiz_form(text: str, *, pending_user: str = "") -> dict[str, Any] | None:
    t = text or ""
    if not t.strip() or any(k in t for k in _PROGRESS_MARKERS):
        return None
    form = quiz_to_form(t, pending_user=pending_user)
    return form if _form_has_questions(form) else None


def quiz_to_form(text: str, *, pending_user: str = "") -> dict[str, Any] | None:
    """Turn a compact questionnaire into a bubble form that actually asks those questions."""
    t = text or ""
    spec_lines: list[str] = []
    checks = [
        re.sub(r"[*_`]+", "", _strip(x))
        for x in re.findall(r"\[\s*\]\s*(.+)", t)
        if _strip(x)
    ]
    checks = [c[:_MAX_LABEL] for c in checks if 1 < len(c) < 80][:_MAX_OPTIONS]

    or_line = re.search(
        r"((?:控制方式|接入|协议|方式)[^。\n]{0,20})(LMS[^\n]{0,40})还是([^\n？?]{2,40})",
        t,
    )
    if or_line:
        left = re.sub(r"https?://\S+", "", or_line.group(2))
        right = re.sub(r"https?://\S+", "", or_line.group(3))
        a = "LMS 协议" if "LMS" in left.upper() else _strip(left)[:24]
        b = "HTTP API" if "HTTP" in right.upper() else _strip(right)[:24]
        spec_lines.append(f"单选 控制方式：{a} / {b}")
    elif "还是" in t and "HTTP" in t.upper() and "LMS" in t.upper():
        spec_lines.append("单选 控制方式：LMS 协议 / HTTP API")

    if checks:
        spec_lines.append("多选 需要的功能：" + " / ".join(checks))

    has_lms_choice = any("LMS" in s.upper() and "HTTP" in s.upper() for s in spec_lines)
    seen_labels = {_strip(x.split("：", 1)[-1] if "：" in x else x) for x in spec_lines}
    for q in _quiz_question_lines(t):
        if has_lms_choice and "LMS" in q.upper() and "HTTP" in q.upper():
            continue
        opts = _or_options(q)
        label = re.sub(r"[？?]+$", "", q).strip() or q
        if label in seen_labels:
            continue
        seen_labels.add(label)
        if opts:
            spec_lines.append(f"单选 {label[:24]}：{' / '.join(opts)}")
        else:
            spec_lines.append(f"输入 {label}")

    if not spec_lines and _ASKING_ADDR_RE.search(t):
        spec_lines.append("输入 地址或端口")

    if not spec_lines:
        return None
    form = build_form(
        title="还差这几项才能继续",
        prompt="直接在下面选或填；上面的说明可以对照着看。",
        spec="\n".join(spec_lines),
    )
    if not form:
        return None
    if pending_user:
        form["pending_user"] = _strip(pending_user)[:400]
    return form
