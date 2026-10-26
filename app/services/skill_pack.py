"""Export / import Eva business skill packages (.evaskill zip).

A pack must round-trip: extra .py / references / routing meta travel with
handler.py so the imported skill registers and can be called.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.services.skill_lifecycle import (
    live_skill_dir,
    normalize_skill_id,
    skills_root,
)
from app.tools.protection import is_protected_skill, is_reserved_name

PACK_KIND = "eva-skills"
PACK_FORMAT = 2
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")

_SKIP_DIR_NAMES = frozenset(
    {
        "__pycache__",
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        ".idea",
        ".vs",
    }
)
_SKIP_NAMES = frozenset({".ds_store", "thumbs.db", ".env", ".env.local"})
_SKIP_SUFFIXES = frozenset(
    {".pyc", ".pyo", ".pyd", ".dll", ".exe", ".so", ".dylib", ".key", ".pem", ".p12", ".pfx"}
)
_MAX_FILE_BYTES = 2 * 1024 * 1024


def is_business_skill(skill_id: str) -> bool:
    n = normalize_skill_id(skill_id)
    return bool(n) and not is_protected_skill(n) and not is_reserved_name(n)


def list_exportable_ids(requested: list[str] | None = None) -> list[str]:
    root = skills_root()
    if not root.is_dir():
        return []
    live = [
        p.name
        for p in sorted(root.iterdir())
        if p.is_dir() and not p.name.startswith((".", "_")) and is_business_skill(p.name)
    ]
    if not requested:
        return live
    want = {normalize_skill_id(x) for x in requested if normalize_skill_id(x)}
    return [i for i in live if i in want]


def collect_skill_overrides(skill_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Local description / trigger overrides only — never integration secrets."""
    if not skill_ids:
        return {}
    try:
        from app.config_store import get_config_store, normalize_prompt_override

        bucket = get_config_store().prompt_overrides().get("skills") or {}
    except Exception:
        return {}
    if not isinstance(bucket, dict):
        return {}
    want = {str(s).strip() for s in skill_ids if str(s).strip()}
    want_l = {k.lower(): k for k in want}
    out: dict[str, dict[str, Any]] = {}
    for k, v in bucket.items():
        sid = str(k or "").strip()
        if not sid:
            continue
        canon = sid if sid in want else want_l.get(sid.lower())
        if not canon:
            continue
        meta = normalize_prompt_override(v)
        if meta:
            out[canon] = meta
    return out


def apply_skill_overrides(overrides: dict[str, Any] | None) -> list[str]:
    """Write imported prompt_overrides onto this machine. No secrets."""
    if not isinstance(overrides, dict) or not overrides:
        return []
    applied: list[str] = []
    try:
        from app.config_store import get_config_store, normalize_prompt_override

        store = get_config_store()
    except Exception:
        return []
    for raw_id, raw_meta in overrides.items():
        sid = normalize_skill_id(str(raw_id or ""))
        if not sid or is_protected_skill(sid) or is_reserved_name(sid):
            continue
        meta = normalize_prompt_override(raw_meta)
        if not meta:
            continue
        try:
            store.set_skill_prompt_meta(
                sid,
                description=meta.get("description") or "",
                how_to_call=meta.get("how_to_call") or "",
                scene_keywords=meta.get("scene_keywords") or [],
            )
            applied.append(sid)
        except Exception:
            continue
    return applied


def _posix(name: str) -> str:
    return (name or "").replace("\\", "/").lstrip("/")


def _is_safe_rel(rel: str) -> bool:
    rel = _posix(rel)
    if not rel or rel.endswith("/"):
        return False
    parts = Path(rel).parts
    if any(p in _SKIP_DIR_NAMES or p in (".", "..") for p in parts):
        return False
    name = Path(rel).name.lower()
    if name in _SKIP_NAMES or name.startswith(".env"):
        return False
    if ".bak" in name:
        return False
    suf = Path(rel).suffix.lower()
    if suf in _SKIP_SUFFIXES:
        return False
    return True


def _iter_skill_files(src: Path) -> list[tuple[Path, str]]:
    if not src.is_dir():
        return []
    out: list[tuple[Path, str]] = []
    for fp in src.rglob("*"):
        if not fp.is_file():
            continue
        try:
            rel = fp.relative_to(src).as_posix()
        except ValueError:
            continue
        if not _is_safe_rel(rel):
            continue
        try:
            if fp.stat().st_size > _MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        out.append((fp, rel))
    return out


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def collect_skill_routing_meta(skill_id: str) -> dict[str, Any]:
    """Routing bits the importer needs so the skill is callable after install."""
    sid = normalize_skill_id(skill_id)
    man = _read_json(live_skill_dir(sid) / "manifest.json")
    am = man.get("agentos_meta") if isinstance(man.get("agentos_meta"), dict) else {}
    spec = am.get("spec") if isinstance(am.get("spec"), dict) else {}
    kws: list[str] = []
    for src in (
        am.get("scene_keywords"),
        spec.get("scene_keywords"),
    ):
        if isinstance(src, list):
            for k in src:
                s = str(k).strip()
                if s and s not in kws:
                    kws.append(s)
    try:
        from app.tools.tool_meta import builtin_scene_keywords, meta_for

        dyn = meta_for(sid) or {}
        for k in dyn.get("scene_keywords") or []:
            s = str(k).strip()
            if s and s not in kws:
                kws.append(s)
        for k in builtin_scene_keywords(sid):
            s = str(k).strip()
            if s and s not in kws:
                kws.append(s)
        role = str(dyn.get("role") or am.get("role") or "primary")
        tag = str(dyn.get("tag") or am.get("tag") or "")
        group = str(dyn.get("group") or am.get("group") or "")
        how = str(
            am.get("how_to_call") or spec.get("trigger") or dyn.get("how_to_call") or ""
        ).strip()
        desc = str(man.get("description") or dyn.get("description_hint") or "").strip()
    except Exception:
        role = str(am.get("role") or "primary")
        tag = str(am.get("tag") or "")
        group = str(am.get("group") or "")
        how = str(am.get("how_to_call") or spec.get("trigger") or "").strip()
        desc = str(man.get("description") or "").strip()
    iid = str(am.get("integration_id") or spec.get("integration_id") or "").strip()
    return {
        "role": role or "primary",
        "tag": tag,
        "group": group,
        "scene_keywords": kws,
        "how_to_call": how,
        "description": desc,
        "integration_id": iid,
        "version": str(man.get("version") or am.get("version") or ""),
    }


_INTEG_CALL_RE = re.compile(
    r"""integration_config\(\s*['\"]([A-Za-z][\w-]{0,39})['\"]"""
)
_CFG_GET_RE = re.compile(
    r"""(?:_cfg\(\)|cfg|c|config|integ)\.get\(\s*['\"]([A-Za-z_][\w]*)['\"]"""
)
_CFG_INDEX_RE = re.compile(
    r"""(?:_cfg\(\)|cfg|c|config)\[\s*['\"]([A-Za-z_][\w]*)['\"]\s*\]"""
)
_FIELD_META: dict[str, tuple[str, str]] = {
    "base_url": ("服务地址", "url"),
    "rpc_url": ("RPC 地址", "url"),
    "url": ("地址", "url"),
    "host": ("主机", "text"),
    "port": ("端口", "number"),
    "user": ("用户名", "text"),
    "username": ("用户名", "text"),
    "email": ("邮箱", "text"),
    "password": ("密码", "password"),
    "token": ("Token", "password"),
    "api_key": ("API Key", "password"),
    "key": ("密钥", "password"),
    "rpc_secret": ("RPC 密钥", "password"),
    "player": ("默认播放器", "text"),
    "share": ("默认共享", "text"),
}


def _copy_integ_field(f: dict[str, Any], key: str) -> dict[str, Any]:
    """Keep layout keys so 设定→集成 can honor full / rows / options."""
    from app.services.integrations_meta import is_secret_key

    row: dict[str, Any] = {
        "key": key,
        "label": str(f.get("label") or key),
        "type": str(f.get("type") or "text"),
        "secret": bool(f.get("secret") or is_secret_key(key)),
        "placeholder": str(f.get("placeholder") or ""),
        "hint": str(f.get("hint") or ""),
    }
    span = f.get("span")
    if f.get("full") is True or span in ("full", 2, "2"):
        row["full"] = True
    try:
        rows_n = int(f.get("rows") or 0)
    except (TypeError, ValueError):
        rows_n = 0
    if rows_n > 0:
        row["rows"] = max(1, min(12, rows_n))
    opts = f.get("options")
    if isinstance(opts, list) and opts:
        clean: list[dict[str, str]] = []
        for opt in opts[:24]:
            if isinstance(opt, dict):
                val = str(
                    opt.get("value") if opt.get("value") is not None else opt.get("label") or ""
                )
                lab = str(opt.get("label") or val)
            else:
                val = str(opt or "").strip()
                lab = val
            if val or lab:
                clean.append({"value": val, "label": lab})
        if clean:
            row["options"] = clean
    return row


def _field_def(key: str) -> dict[str, Any]:
    from app.services.integrations_meta import is_secret_key

    label, typ = _FIELD_META.get(key, (key, "password" if is_secret_key(key) else "text"))
    secret = is_secret_key(key) or typ == "password"
    return {
        "key": key,
        "label": label,
        "type": "password" if secret else typ,
        "secret": secret,
    }


def _handler_integration_keys(handler_py: Path) -> tuple[str, list[str]]:
    if not handler_py.is_file():
        return "", []
    try:
        text = handler_py.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", []
    iid = ""
    m = _INTEG_CALL_RE.search(text)
    if m:
        iid = m.group(1)
    keys: list[str] = []
    for rx in (_CFG_GET_RE, _CFG_INDEX_RE):
        for hit in rx.finditer(text):
            k = hit.group(1)
            if k not in keys:
                keys.append(k)
    return iid, keys


def collect_integration_schema(skill_id: str, routing: dict[str, Any] | None) -> dict[str, Any] | None:
    """Form schema only — never secret values. Used so import can create the editor."""
    from app.services.integrations_meta import (
        INTEGRATION_CATALOG,
        get_schema,
        is_record_key,
        items_table_field,
        schema_looks_content,
    )

    sid = normalize_skill_id(skill_id)
    iid = str((routing or {}).get("integration_id") or "").strip()
    handler = live_skill_dir(sid) / "handler.py"
    inferred_id, inferred_keys = _handler_integration_keys(handler)
    handler_text = ""
    try:
        if handler.is_file():
            handler_text = handler.read_text(encoding="utf-8", errors="replace")
    except OSError:
        handler_text = ""
    if not iid:
        iid = inferred_id
    if not iid:
        return None
    raw: dict[str, Any] = {}
    try:
        from app.config_store import get_config_store

        blob = get_config_store().get_integrations_raw().get(iid)
        if isinstance(blob, dict):
            raw = blob
    except Exception:
        raw = {}
    cat = get_schema(iid, raw)
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    in_catalog = iid in INTEGRATION_CATALOG
    if cat:
        for f in cat.get("fields") or []:
            if not isinstance(f, dict):
                continue
            k = str(f.get("key") or "").strip()
            if not k or k in seen:
                continue
            if not in_catalog and is_record_key(k):
                continue
            seen.add(k)
            fields.append(_copy_integ_field(f, k))
        name = str(cat.get("name") or iid)
        desc = str(cat.get("description") or "")
        required = list(cat.get("required_for_ready") or [])
        builtin = bool(cat.get("builtin"))
    else:
        name = str(raw.get("_label") or (routing or {}).get("description") or iid)
        desc = str(raw.get("_description") or f"技能 {sid} 的连接配置（导入后请填写）")
        required = []
        builtin = False
        for k in list(raw.keys()) + inferred_keys:
            if not k or k.startswith("_") or k in seen or is_record_key(k):
                continue
            seen.add(k)
            fields.append(_field_def(k))
        if not required:
            for cand in ("rpc_url", "base_url", "url", "host"):
                if cand in seen:
                    required.append(cand)
                    break
        if not required:
            for f in fields:
                if f.get("secret"):
                    required.append(f["key"])
                    break
    wants_content = (not in_catalog) and (
        schema_looks_content(cat, raw)
        or "items" in inferred_keys
        or "groups" in inferred_keys
        or "members" in inferred_keys
        or (".get(\"items\")" in handler_text or ".get('items')" in handler_text)
    )
    if wants_content and not any(
        str(f.get("type") or "") == "items_table" or str(f.get("key") or "") == "items"
        for f in fields
    ):
        fields.append(items_table_field(iid))
        seen.add("items")
    if not fields:
        return None
    skills = [sid]
    if cat:
        for s in cat.get("skills") or []:
            x = str(s).strip()
            if x and x not in skills:
                skills.append(x)
    out = {
        "id": iid,
        "name": name or iid,
        "description": desc,
        "builtin": builtin,
        "skills": skills,
        "fields": fields,
        "required_for_ready": required,
    }
    if not in_catalog:
        out["layout"] = "content" if wants_content else str((cat or {}).get("layout") or "single")
    return out


def ensure_imported_integration(
    schema: dict[str, Any] | None, skill_id: str
) -> dict[str, Any] | None:
    """Create an empty custom integration so 设定→集成 shows a form. No secrets copied."""
    from app.services.integrations_meta import (
        OPTIONAL_INTEGRATIONS,
        get_schema,
        is_secret_key,
    )

    if not isinstance(schema, dict):
        return None
    iid = str(schema.get("id") or "").strip()
    if not iid:
        return None
    try:
        from app.config_store import get_config_store

        store = get_config_store()
    except Exception:
        return None
    raw = store.get_integrations_raw()
    existed = iid in raw
    builtin = bool(schema.get("builtin") or get_schema(iid))
    skills = [str(s) for s in (schema.get("skills") or []) if str(s).strip()]
    if skill_id and skill_id not in skills:
        skills.append(skill_id)
    if not builtin:
        payload: dict[str, Any] = {
            "_label": str(schema.get("name") or iid),
            "_description": str(schema.get("description") or ""),
            "_schema": {
                "id": iid,
                "name": str(schema.get("name") or iid),
                "description": str(schema.get("description") or ""),
                "skills": skills,
                "fields": list(schema.get("fields") or []),
                "required_for_ready": list(schema.get("required_for_ready") or []),
                "builtin": False,
                "layout": str(schema.get("layout") or "single"),
            },
            "_skills": skills,
        }
        if not existed:
            for f in schema.get("fields") or []:
                k = str((f or {}).get("key") or "").strip()
                if not k or k.startswith("_") or is_secret_key(k):
                    continue
                payload[k] = ""
        try:
            store.upsert_integration(iid, payload)
        except Exception:
            return None
    pub = store.get_integration_public(iid) or {}
    status = str(pub.get("status") or "empty")
    optional = iid in OPTIONAL_INTEGRATIONS
    return {
        "id": iid,
        "name": pub.get("name") or schema.get("name") or iid,
        "created": (not existed) and (not builtin),
        "builtin": builtin,
        "optional": optional,
        "status": status,
        "skill_ids": skills,
        "needs_setup": (not optional) and status != "ready",
    }


def _safe_members(zf: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, str]]:
    out: list[tuple[zipfile.ZipInfo, str]] = []
    for info in zf.infolist():
        name = _posix(info.filename)
        if not name:
            continue
        if name.startswith("/") or ".." in Path(name).parts:
            raise ValueError(f"非法路径: {info.filename}")
        out.append((info, name))
    return out


def build_export_zip(skill_ids: list[str] | None = None) -> tuple[bytes, str, list[str]]:
    ids = list_exportable_ids(skill_ids)
    if not ids:
        raise ValueError("没有可导出的业务技能（系统技能不能导出；请勾选业务技能）")
    root = skills_root()
    buf = io.BytesIO()
    packed: list[str] = []
    routing: dict[str, Any] = {}
    integrations: dict[str, Any] = {}
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for sid in ids:
            src = root / sid
            files = _iter_skill_files(src)
            if not files:
                continue
            for fp, rel in files:
                zf.write(fp, f"{sid}/{rel}")
            meta = collect_skill_routing_meta(sid)
            routing[sid] = meta
            integ = collect_integration_schema(sid, meta)
            if integ:
                iid = str(integ.get("id") or "")
                if iid:
                    prev = integrations.get(iid)
                    if isinstance(prev, dict):
                        skills = list(prev.get("skills") or [])
                        for s in integ.get("skills") or []:
                            if s not in skills:
                                skills.append(s)
                        integ["skills"] = skills
                    integrations[iid] = integ
            packed.append(sid)
        if not packed:
            raise ValueError("没有可导出的业务技能（目录是空的）")
        pack = {
            "kind": PACK_KIND,
            "format": PACK_FORMAT,
            "skills": packed,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "skill_meta": routing,
        }
        if integrations:
            pack["integrations"] = integrations
        overrides = collect_skill_overrides(packed)
        if overrides:
            pack["prompt_overrides"] = overrides
        zf.writestr("pack.json", json.dumps(pack, ensure_ascii=False, indent=2) + "\n")
    label = packed[0] if len(packed) == 1 else f"eva-skills-{len(packed)}"
    fname = f"{label}-{datetime.now().strftime('%Y%m%d')}.evaskill"
    return buf.getvalue(), fname, packed


def export_content_disposition(fname: str) -> str:
    ascii_name = fname if fname.isascii() else "eva-skills.evaskill"
    return (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(fname)}"
    )


def _discover_skill_dirs(extract_root: Path) -> list[Path]:
    pack_file = extract_root / "pack.json"
    declared: list[str] = []
    if pack_file.is_file():
        try:
            meta = json.loads(pack_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"pack.json 无效: {e}") from e
        if not isinstance(meta, dict) or meta.get("kind") not in (PACK_KIND, "eva-skill"):
            raise ValueError("这不是 Eva 技能包（缺少 pack.json kind=eva-skills）")
        raw = meta.get("skills")
        if isinstance(raw, list):
            declared = [normalize_skill_id(str(x)) for x in raw if str(x).strip()]

    dirs: list[Path] = []
    if declared:
        for sid in declared:
            p = extract_root / sid
            if p.is_dir():
                dirs.append(p)
        if dirs:
            return dirs

    if (extract_root / "manifest.json").is_file() or (extract_root / "handler.py").is_file():
        return [extract_root]

    for p in sorted(extract_root.iterdir()):
        if p.is_dir() and not p.name.startswith((".", "_")):
            if (p / "manifest.json").is_file() or (p / "handler.py").is_file():
                dirs.append(p)
    return dirs


def _read_skill_id(skill_dir: Path) -> str:
    man = skill_dir / "manifest.json"
    if man.is_file():
        data = _read_json(man)
        if data.get("id"):
            return normalize_skill_id(str(data["id"]))
    if skill_dir.name not in (".", ""):
        return normalize_skill_id(skill_dir.name)
    raise ValueError("无法识别技能 id")


def _copy_safe_tree(src: Path, dest: Path) -> list[str]:
    copied: list[str] = []
    dest.mkdir(parents=True, exist_ok=True)
    for fp, rel in _iter_skill_files(src):
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fp, target)
        copied.append(rel)
    return copied


def _ensure_manifest(dest: Path, sid: str, routing: dict[str, Any] | None) -> None:
    man_path = dest / "manifest.json"
    data = _read_json(man_path) if man_path.is_file() else {}
    data.setdefault("id", sid)
    data.setdefault("name", sid)
    data.setdefault("version", "0.1.0")
    data.setdefault("description", "")
    data.setdefault("tools", data.get("tools") if isinstance(data.get("tools"), list) else [])
    am = data.get("agentos_meta") if isinstance(data.get("agentos_meta"), dict) else {}
    meta = routing or {}
    if meta.get("role"):
        am.setdefault("role", meta.get("role"))
    if meta.get("tag"):
        am.setdefault("tag", meta.get("tag"))
    if meta.get("group"):
        am.setdefault("group", meta.get("group"))
    if meta.get("how_to_call"):
        am.setdefault("how_to_call", meta.get("how_to_call"))
    if meta.get("integration_id"):
        am.setdefault("integration_id", meta.get("integration_id"))
    kws = list(am.get("scene_keywords") or [])
    for k in meta.get("scene_keywords") or []:
        s = str(k).strip()
        if s and s not in kws:
            kws.append(s)
    if kws:
        am["scene_keywords"] = kws
    if not str(data.get("description") or "").strip() and meta.get("description"):
        data["description"] = meta["description"]
    if am:
        data["agentos_meta"] = am
    man_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _validate_imported_dir(skill_dir: Path, sid: str) -> dict[str, Any]:
    """Import-time check: syntax / entrypoint. Extra files must already be in *skill_dir*."""
    warnings: list[str] = []
    handler = skill_dir / "handler.py"
    man = _read_json(skill_dir / "manifest.json")
    tools = man.get("tools") if isinstance(man.get("tools"), list) else []
    if handler.is_file():
        from app.services.skill_lifecycle import validate_skill_code

        code = handler.read_text(encoding="utf-8", errors="replace")
        check = validate_skill_code(sid, code)
        issues = list(check.get("issues") or [])
        warnings.extend(check.get("warnings") or [])
        # Import from this folder so sibling modules are visible.
        try:
            from app.services.skill_lifecycle import _preflight_import

            pre = _preflight_import(handler, sid)
            if pre and "import failed" in pre.lower():
                issues.append(pre)
            elif pre:
                warnings.append(pre)
        except Exception as exc:
            warnings.append(f"preflight skipped: {exc}")
        hard = [
            i
            for i in issues
            if "SyntaxError" in str(i) or "缺少 register" in str(i) or "import failed" in str(i)
        ]
        warnings.extend(i for i in issues if i not in hard)
        if hard:
            return {"ok": False, "error": hard[0], "issues": issues, "warnings": warnings}
        if check.get("error") and "SyntaxError" in str(check.get("error")):
            return {
                "ok": False,
                "error": check.get("error"),
                "issues": issues,
                "warnings": warnings,
            }
        return {"ok": True, "warnings": warnings, "issues": issues}
    if tools:
        return {"ok": True, "warnings": warnings}
    if man.get("id") or (skill_dir / "SKILL.md").is_file():
        warnings.append("没有 handler.py，也没有 manifest.tools；导入后可能无法调用")
        return {"ok": True, "warnings": warnings}
    return {"ok": False, "error": "缺少 handler.py 或 manifest.json", "warnings": warnings}


def _restore_routing(sid: str, routing: dict[str, Any] | None) -> None:
    meta = routing if isinstance(routing, dict) else {}
    try:
        from app.tools.tool_meta import upsert_dynamic_meta

        upsert_dynamic_meta(
            sid,
            role=str(meta.get("role") or "primary"),
            tag=str(meta.get("tag") or ""),
            group=str(meta.get("group") or "other"),
            scene_keywords=list(meta.get("scene_keywords") or []),
            description_hint=str(meta.get("description") or ""),
            version=str(meta.get("version") or ""),
        )
    except Exception:
        pass


def preview_and_install(
    zip_bytes: bytes,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    if not zip_bytes:
        raise ValueError("空文件")
    tmp = Path(tempfile.mkdtemp(prefix="eva-skill-import-"))
    installed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    imported_overrides: dict[str, Any] = {}
    routing_all: dict[str, Any] = {}
    imported_integs: dict[str, Any] = {}
    try:
        try:
            zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        except zipfile.BadZipFile as e:
            raise ValueError("不是有效的 zip / .evaskill 文件") from e
        with zf:
            for info, name in _safe_members(zf):
                dest = (tmp / name).resolve()
                if not str(dest).startswith(str(tmp.resolve())):
                    raise ValueError(f"非法路径: {info.filename}")
                if info.is_dir() or name.endswith("/"):
                    dest.mkdir(parents=True, exist_ok=True)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, dest.open("wb") as out:
                    out.write(src.read())

        skill_dirs = _discover_skill_dirs(tmp)
        if not skill_dirs:
            raise ValueError("包里没有可用的技能目录（需要 manifest.json 或 handler.py）")

        pack_file = tmp / "pack.json"
        if pack_file.is_file():
            try:
                pack_meta = json.loads(pack_file.read_text(encoding="utf-8"))
                if isinstance(pack_meta, dict):
                    raw_po = pack_meta.get("prompt_overrides")
                    if isinstance(raw_po, dict):
                        imported_overrides = raw_po
                    raw_sm = pack_meta.get("skill_meta")
                    if isinstance(raw_sm, dict):
                        routing_all = raw_sm
                    raw_ig = pack_meta.get("integrations")
                    if isinstance(raw_ig, dict):
                        imported_integs = raw_ig
            except Exception:
                pass

        root = skills_root()
        root.mkdir(parents=True, exist_ok=True)

        for sdir in skill_dirs:
            try:
                sid = _read_skill_id(sdir)
                if not _ID_RE.match(sid):
                    failed.append({"id": sid or sdir.name, "error": "技能 id 不合法"})
                    continue
                if is_reserved_name(sid):
                    failed.append({"id": sid, "error": "系统保留名，不能作为技能安装"})
                    continue
                if is_protected_skill(sid):
                    skipped.append({"id": sid, "reason": "受保护的系统技能，跳过"})
                    continue
                dest = live_skill_dir(sid)
                if dest.is_dir() and not overwrite:
                    skipped.append({"id": sid, "reason": "已安装（勾选覆盖后再导入）"})
                    continue
                check = _validate_imported_dir(sdir, sid)
                if not check.get("ok"):
                    failed.append(
                        {
                            "id": sid,
                            "error": check.get("error") or "校验失败",
                            "issues": check.get("issues") or [],
                        }
                    )
                    continue
                backup = None
                if dest.is_dir():
                    backup = dest.with_name(dest.name + ".__bak__")
                    if backup.exists():
                        shutil.rmtree(backup, ignore_errors=True)
                    dest.rename(backup)
                try:
                    copied = _copy_safe_tree(sdir, dest)
                    if not copied and not (dest / "manifest.json").is_file():
                        raise ValueError("技能目录是空的")
                    routing = routing_all.get(sid) if isinstance(routing_all.get(sid), dict) else {}
                    _ensure_manifest(dest, sid, routing)
                    _restore_routing(sid, routing)
                except Exception:
                    if dest.exists():
                        shutil.rmtree(dest, ignore_errors=True)
                    if backup is not None and backup.exists():
                        backup.rename(dest)
                    raise
                else:
                    if backup is not None and backup.exists():
                        shutil.rmtree(backup, ignore_errors=True)
                row: dict[str, Any] = {
                    "id": sid,
                    "files": copied,
                    "warnings": list(check.get("warnings") or []),
                }
                if (dest / "requirements.txt").is_file():
                    row["warnings"].append(
                        "含 requirements.txt；如缺依赖请在本机 pip 安装（不会随包自动装）"
                    )
                try:
                    man = _read_json(dest / "manifest.json")
                    am = man.get("agentos_meta") if isinstance(man.get("agentos_meta"), dict) else {}
                    spec = am.get("spec") if isinstance(am.get("spec"), dict) else {}
                    iid = str(
                        am.get("integration_id") or spec.get("integration_id") or ""
                    ).strip()
                    if iid:
                        schema = imported_integs.get(iid) if isinstance(
                            imported_integs.get(iid), dict
                        ) else None
                        if not schema:
                            schema = collect_integration_schema(sid, routing)
                        ensured = ensure_imported_integration(schema, sid)
                        from app.services.skill_spec import integration_status

                        _, st = integration_status(iid)
                        row["integration_id"] = iid
                        row["integration_status"] = st or "empty"
                        if ensured:
                            row["integration"] = ensured
                        if (ensured and ensured.get("needs_setup")) or st not in ("ready",):
                            label = (ensured or {}).get("name") or iid
                            row["warnings"].append(
                                f"请到设定→集成填写「{label}」（账号密码不会随包导入）"
                            )
                except Exception:
                    pass
                installed.append(row)
            except Exception as e:
                failed.append({"id": sdir.name, "error": str(e)})

        # Extra integrations in pack.json (not only the skill's primary id).
        installed_ids = {str(r.get("id") or "") for r in installed if r.get("id")}
        seen_iid = {
            str(r.get("integration_id") or "")
            for r in installed
            if r.get("integration_id")
        }
        for raw_id, schema in imported_integs.items():
            if not isinstance(schema, dict):
                continue
            iid = str(schema.get("id") or raw_id or "").strip()
            if not iid or iid in seen_iid:
                continue
            linked = [
                str(s).strip()
                for s in (schema.get("skills") or [])
                if str(s).strip() in installed_ids
            ]
            sid = linked[0] if linked else next(iter(installed_ids), "")
            if not sid:
                continue
            try:
                extra = ensure_imported_integration(schema, sid)
            except Exception:
                extra = None
            seen_iid.add(iid)
            if extra and extra.get("needs_setup"):
                label = extra.get("name") or iid
                msg = f"请到设定→集成填写「{label}」（账号密码不会随包导入）"
                for row in installed:
                    rid = str(row.get("id") or "")
                    if linked and rid not in linked:
                        continue
                    warns = list(row.get("warnings") or [])
                    if msg not in warns:
                        warns.append(msg)
                    row["warnings"] = warns
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    applied = []
    if installed and imported_overrides:
        want = {str(r.get("id") or "") for r in installed}
        subset = {
            k: v
            for k, v in imported_overrides.items()
            if normalize_skill_id(str(k or "")) in want
        }
        applied = apply_skill_overrides(subset)

    need_setup: list[dict[str, Any]] = []
    seen_setup: set[str] = set()
    for row in installed:
        info = row.get("integration") if isinstance(row.get("integration"), dict) else None
        if not info or not info.get("needs_setup"):
            continue
        iid = str(info.get("id") or "")
        if not iid or iid in seen_setup:
            continue
        seen_setup.add(iid)
        need_setup.append(
            {
                "id": iid,
                "name": info.get("name") or iid,
                "created": bool(info.get("created")),
                "skill_ids": list(info.get("skill_ids") or [row.get("id")]),
            }
        )
    return {
        "ok": bool(installed) and not failed,
        "installed": installed,
        "skipped": skipped,
        "failed": failed,
        "prompt_overrides": applied,
        "need_setup": need_setup,
    }


def uninstall_skill(skill_id: str) -> dict[str, Any]:
    n = normalize_skill_id(skill_id)
    if not n:
        return {"ok": False, "error": "缺少技能 id"}
    if is_protected_skill(n) or is_reserved_name(n):
        return {"ok": False, "error": f"[{n}] 是系统技能，不能卸载"}
    dest = live_skill_dir(n)
    if not dest.is_dir():
        return {"ok": False, "error": f"未安装 [{n}]"}
    shutil.rmtree(dest)
    try:
        from app.tools.tool_meta import remove_dynamic_meta

        remove_dynamic_meta(n)
    except Exception:
        pass
    return {"ok": True, "id": n}
