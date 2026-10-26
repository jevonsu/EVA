"""Skill JSON-schema helpers for create_tool / validate / read.

Keeps LLM-built skills callable: empty register() schemas are the main
failure mode (model cannot pass action/path/url).
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any

_EMPTY_OBJECT = {"type": "object", "properties": {}}

_EMPTY_PROPS_RE = re.compile(
    r"\{\s*['\"]type['\"]\s*:\s*['\"]object['\"]\s*,\s*"
    r"['\"]properties['\"]\s*:\s*\{\s*\}"
    r"(?:\s*,\s*['\"]required['\"]\s*:\s*\[\s*\])?"
    r"\s*\}",
    re.I,
)

_KWARGS_GET_RE = re.compile(
    r"""kwargs\.get\(\s*['\"]([A-Za-z_][\w]*)['\"]""",
)


def is_empty_schema(params: Any) -> bool:
    if not isinstance(params, dict):
        return True
    props = params.get("properties")
    return not isinstance(props, dict) or len(props) == 0


def spec_inputs_to_schema(spec: dict[str, Any] | None) -> dict[str, Any]:
    spec = spec if isinstance(spec, dict) else {}
    inputs = spec.get("inputs") or []
    if not isinstance(inputs, list) or not inputs:
        return dict(_EMPTY_OBJECT)
    props: dict[str, Any] = {}
    required: list[str] = []
    for item in inputs:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("key") or "").strip()
        if not name or not name.isidentifier():
            continue
        typ = str(item.get("type") or "string").strip() or "string"
        if typ not in ("string", "integer", "number", "boolean", "array", "object"):
            typ = "string"
        field: dict[str, Any] = {"type": typ}
        note = str(item.get("note") or item.get("description") or "").strip()
        example = str(item.get("example") or "").strip()
        if note:
            field["description"] = note
        if example:
            field["description"] = (
                (field.get("description") or "") + (f" 例：{example}" if note else f"例：{example}")
            ).strip()
        props[name] = field
        if item.get("required", True):
            required.append(name)
    if not props:
        return dict(_EMPTY_OBJECT)
    out: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        out["required"] = required
    return out


def kwargs_get_keys(code: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for m in _KWARGS_GET_RE.finditer(code or ""):
        k = m.group(1)
        if k not in seen:
            seen.add(k)
            found.append(k)
    return found


def keys_to_schema(keys: list[str]) -> dict[str, Any]:
    props = {k: {"type": "string"} for k in keys if k.isidentifier()}
    if not props:
        return dict(_EMPTY_OBJECT)
    return {"type": "object", "properties": props}


_ACTION_EQ_RE = re.compile(
    r"""(?:action|\bact)\s*==\s*['\"]([A-Za-z_][\w-]*)['\"]"""
)
_ACTION_IN_RE = re.compile(r"""(?:action|\bact)\s+in\s*\(([^)]*)\)""")
_STR_LIT_RE = re.compile(r"""['\"]([A-Za-z_][\w-]*)['\"]""")
_LISTISH_ACTIONS = frozenset(
    {
        "list",
        "query",
        "search",
        "list_torrents",
        "list_tables",
        "list_fields",
        "orders",
    }
)

ACTION_SKILL_HINT = (
    "多操作技能必须：parameters.properties.action.enum 列出全部动作；"
    "每个动作会用到的字段写进 properties；list/query/search 必须有 limit（默认 50）。"
    "禁止 register(..., {\"type\":\"object\",\"properties\":{}})。"
)


def extract_action_names(code: str) -> list[str]:
    """Pull action literals from `if action == 'query'` / `action in (...)`."""
    src = code or ""
    found: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        n = (name or "").strip()
        if n and n not in seen and n.isidentifier():
            seen.add(n)
            found.append(n)

    for m in _ACTION_EQ_RE.finditer(src):
        _add(m.group(1))
    for m in _ACTION_IN_RE.finditer(src):
        for lit in _STR_LIT_RE.findall(m.group(1) or ""):
            _add(lit)
    return found


def enrich_action_schema(schema: dict[str, Any], code: str) -> dict[str, Any]:
    """Add action enum + default list limit inferred from handler code."""
    if not isinstance(schema, dict):
        schema = dict(_EMPTY_OBJECT)
    actions = extract_action_names(code)
    props = dict(schema.get("properties") or {})
    if not actions and "action" not in props:
        return schema
    out = dict(schema)
    out["type"] = "object"
    if actions:
        act = dict(props.get("action") or {"type": "string"})
        act["type"] = "string"
        merged: list[str] = []
        for x in list(act.get("enum") or []) + actions:
            s = str(x).strip()
            if s and s not in merged:
                merged.append(s)
        if merged:
            act["enum"] = merged
            act.setdefault("description", "操作：" + "/".join(merged))
        props["action"] = act
        req = [str(x) for x in (out.get("required") or [])]
        if "action" not in req:
            req.insert(0, "action")
        out["required"] = req
    if actions and any(
        a in _LISTISH_ACTIONS or a.startswith("list_") for a in actions
    ):
        if "limit" not in props:
            props["limit"] = {
                "type": "integer",
                "description": "列表/查询条数，默认 50",
            }
    out["properties"] = props
    return out


def _literal_to_obj(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Dict):
        out: dict[str, Any] = {}
        for k, v in zip(node.keys, node.values, strict=False):
            if k is None:
                continue
            key = _literal_to_obj(k)
            if isinstance(key, str):
                out[key] = _literal_to_obj(v)
        return out
    if isinstance(node, ast.List):
        return [_literal_to_obj(x) for x in node.elts]
    if isinstance(node, ast.Tuple):
        return [_literal_to_obj(x) for x in node.elts]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        v = _literal_to_obj(node.operand)
        if isinstance(v, (int, float)):
            return -v
    if isinstance(node, ast.Name) and node.id in ("True", "False", "None"):
        return {"True": True, "False": False, "None": None}[node.id]
    return None


def schema_from_handler_code(code: str) -> dict[str, Any] | None:
    """Best schema found in handler: SCHEMA = {...} or register 4th arg."""
    src = (code or "").strip()
    if not src:
        return None
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    schema_assign: dict[str, Any] | None = None
    register_arg: dict[str, Any] | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "SCHEMA":
                    obj = _literal_to_obj(node.value)
                    if isinstance(obj, dict):
                        schema_assign = obj
        if isinstance(node, ast.Call):
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "register"):
                continue
            arg_node = None
            if len(node.args) >= 4:
                arg_node = node.args[3]
            for kw in node.keywords or []:
                if kw.arg in ("parameters", "params"):
                    arg_node = kw.value
            if arg_node is None:
                continue
            if isinstance(arg_node, ast.Name) and arg_node.id == "SCHEMA" and schema_assign:
                register_arg = schema_assign
                continue
            obj = _literal_to_obj(arg_node)
            if isinstance(obj, dict):
                register_arg = obj
    if schema_assign and not is_empty_schema(schema_assign):
        return schema_assign
    if register_arg and not is_empty_schema(register_arg):
        return register_arg
    return schema_assign or register_arg


def resolve_skill_parameters(
    params: Any,
    *,
    spec: dict[str, Any] | None = None,
    handler_code: str = "",
    old_params: dict[str, Any] | None = None,
    no_params: bool = False,
) -> tuple[dict[str, Any], list[str], str | None]:
    """Pick a non-empty schema. Returns (params, notes, error)."""
    notes: list[str] = []
    spec = spec if isinstance(spec, dict) else {}
    if no_params or spec.get("no_params"):
        if not isinstance(params, dict):
            params = dict(_EMPTY_OBJECT)
        notes.append("no_params=true，允许空 schema")
        return params, notes, None

    candidates: list[tuple[str, dict[str, Any]]] = []
    if isinstance(params, dict) and not is_empty_schema(params):
        candidates.append(("create_tool.parameters", params))
    from_code = schema_from_handler_code(handler_code)
    if from_code and not is_empty_schema(from_code):
        candidates.append(("handler SCHEMA/register", from_code))
    from_spec = spec_inputs_to_schema(spec)
    if not is_empty_schema(from_spec):
        candidates.append(("spec.inputs", from_spec))
    from_kwargs = keys_to_schema(kwargs_get_keys(handler_code))
    if not is_empty_schema(from_kwargs):
        candidates.append(("kwargs.get keys", from_kwargs))
    if old_params and not is_empty_schema(old_params):
        candidates.append(("previous register schema", old_params))

    if candidates:
        label, chosen = candidates[0]
        notes.append(f"parameters 来自 {label}")
        if (
            label != "previous register schema"
            and old_params
            and not is_empty_schema(old_params)
            and is_empty_schema(params if isinstance(params, dict) else {})
        ):
            notes.append("提交的 parameters 为空，未覆盖已有 schema")
        enriched = enrich_action_schema(chosen, handler_code or "")
        if extract_action_names(handler_code or ""):
            notes.append("已按 handler 动作补全 action.enum / limit")
        return enriched, notes, None

    return (
        dict(_EMPTY_OBJECT),
        notes,
        "parameters 不能为空：请提供 JSON schema，或在 spec_json.inputs 列出字段，"
        "或 handler 里定义 SCHEMA / kwargs.get('字段')。"
        "确需无参工具时 spec.no_params=true。",
    )


def strip_duplicate_scaffold_header(code: str) -> tuple[str, list[str]]:
    """Drop a repeated auto-scaffolded import preamble (LLM update artifact)."""
    src = code or ""
    notes: list[str] = []
    marker = "from app.tools.registry import ToolRegistry"
    if src.count(marker) < 2:
        return src, notes
    # Keep from the last skill docstring or the second ToolRegistry import block's body
    parts = src.split(marker)
    # Reconstruct: first occurrence preamble is junk if it is the short scaffold
    rest = marker.join(parts[1:]).lstrip("\n")
    # If rest still starts with logger = ... then another docstring, drop until second docstring
    m = re.search(r'"""Skill:', rest)
    if m and m.start() > 0:
        # first leftover logger line then real file
        head = rest[: m.start()]
        if "auto-scaffolded" in src[:800] or "logger = logging.getLogger" in head:
            rest = rest[m.start() :]
            notes.append("removed duplicate auto-scaffold header")
            return rest, notes
    notes.append("removed duplicate ToolRegistry import preamble")
    # Keep a minimal import if rest doesn't import ToolRegistry at top
    if "from app.tools.registry import ToolRegistry" not in rest[:400]:
        rest = (
            "from app.tools.registry import ToolRegistry\n"
            + rest
        )
    return rest, notes


def ensure_register_schema(code: str, schema: dict[str, Any]) -> tuple[str, list[str]]:
    """If register() uses an empty properties dict, point it at SCHEMA / inject SCHEMA."""
    notes: list[str] = []
    src = code or ""
    if is_empty_schema(schema):
        return src, notes
    idx = src.rfind("registry.register(")
    if idx < 0:
        return src, notes
    # Only patch the register() call region
    end = src.find("source=", idx)
    if end < 0:
        end = min(len(src), idx + 4000)
    else:
        end = min(len(src), end + 80)
    chunk = src[idx:end]
    if not _EMPTY_PROPS_RE.search(chunk):
        return src, notes
    has_schema_assign = bool(re.search(r"^SCHEMA\s*=", src, re.M))
    if not has_schema_assign:
        block = "SCHEMA = " + json.dumps(schema, ensure_ascii=False, indent=4) + "\n\n"
        m = re.search(r"^def register\s*\(", src, re.M)
        if m:
            src = src[: m.start()] + block + src[m.start() :]
            notes.append("injected SCHEMA before register()")
            idx = src.rfind("registry.register(")
            end = src.find("source=", idx)
            end = min(len(src), (end + 80) if end >= 0 else idx + 4000)
            chunk = src[idx:end]
        else:
            return src, notes
    new_chunk, nsub = _EMPTY_PROPS_RE.subn("SCHEMA", chunk, count=1)
    if nsub:
        src = src[:idx] + new_chunk + src[end:]
        notes.append("register() empty schema → SCHEMA")
    return src, notes
