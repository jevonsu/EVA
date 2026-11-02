"""Read / write / edit / delete office files inside the Eva workspace.

Formats: Word (.docx), Excel (.xlsx), PowerPoint (.pptx), PDF (.pdf), Markdown (.md).
Hub HTTP mode is rejected: binaries need a local or shared-folder workspace.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("app.services.document_ops")

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TEXT = 12_000
MAX_EXCEL_ROWS = 200
MAX_PPT_SLIDES = 50
MAX_PDF_PAGES = 40
MAX_BATCH = 40

KIND_EXT = {
    "word": ".docx",
    "excel": ".xlsx",
    "ppt": ".pptx",
    "pdf": ".pdf",
    "markdown": ".md",
}
EXT_KIND = {
    ".docx": "word",
    ".xlsx": "excel",
    ".xlsm": "excel",
    ".pptx": "ppt",
    ".pdf": "pdf",
    ".md": "markdown",
    ".markdown": "markdown",
}
LEGACY = {
    ".doc": "请另存为 .docx",
    ".xls": "请另存为 .xlsx",
    ".ppt": "请另存为 .pptx",
}


def _meta() -> dict[str, str]:
    try:
        from app.services.workspace_bind import binding_public

        pub = binding_public()
        if pub.get("shared"):
            return {
                "file_source": "hub",
                "file_source_label": "Hub 公司工作区（所有员工共用）",
            }
    except Exception:
        pass
    return {
        "file_source": "eva_local",
        "file_source_label": "本机 Eva 独立工作区",
    }


def _err(msg: str, **extra: Any) -> dict[str, Any]:
    out = {"ok": False, "error": msg, **_meta(), **extra}
    return out


def _ok(**extra: Any) -> dict[str, Any]:
    extra.setdefault("ok", True)
    extra.update(_meta())
    return extra


def _clip(text: str, limit: int = MAX_TEXT) -> tuple[str, bool]:
    t = text or ""
    if len(t) <= limit:
        return t, False
    return t[:limit] + "\n…(截断)", True


def detect_kind(path: str, kind: str = "") -> str:
    k = (kind or "").strip().lower()
    if k in ("word", "doc", "docx", "工作", "word文档"):
        return "word"
    if k in ("excel", "xlsx", "xls", "表格"):
        return "excel"
    if k in ("ppt", "pptx", "powerpoint", "幻灯片"):
        return "ppt"
    if k in ("pdf",):
        return "pdf"
    if k in ("md", "markdown", "markdown文档"):
        return "markdown"
    ext = Path(path or "").suffix.lower()
    if ext in EXT_KIND:
        return EXT_KIND[ext]
    return ""


def _resolve(path: str) -> tuple[Path | None, str]:
    from app.tools.safety import (
        get_workspace_root,
        normalize_workspace_relpath,
        resolve_workspace_path,
        workspace_relpath,
    )

    rel = normalize_workspace_relpath(path)
    target = resolve_workspace_path(rel)
    if target is None:
        return None, rel
    return target, workspace_relpath(target) if target.exists() or rel != "." else rel


def _hub_http_block() -> dict[str, Any] | None:
    try:
        from app.services.workspace_bind import uses_hub_http

        if uses_hub_http():
            return _err(
                "Hub HTTP 模式下不能直接改 Word/Excel/PPT/PDF（二进制）。"
                "请改用共享文件夹接入，或把文件放到本机工作区后再操作。"
            )
    except Exception:
        pass
    return None


def _ensure_ext(path: str, kind: str) -> str:
    p = Path(path or "")
    if p.suffix.lower() in EXT_KIND:
        return path
    ext = KIND_EXT.get(kind) or ""
    if not ext:
        return path
    if str(path).endswith("."):
        return str(path) + ext.lstrip(".")
    return str(path) + ext


def _parse_rows(content: str, rows_json: str) -> list[list[str]]:
    raw = (rows_json or "").strip()
    if raw:
        data = json.loads(raw)
        if isinstance(data, dict):
            data = data.get("rows") or data.get("data") or []
        if not isinstance(data, list):
            raise ValueError("rows_json 须为二维数组或 {rows: [...]}")
        out: list[list[str]] = []
        for row in data:
            if isinstance(row, dict):
                out.append([str(v) for v in row.values()])
            elif isinstance(row, (list, tuple)):
                out.append(["" if v is None else str(v) for v in row])
            else:
                out.append([str(row)])
        return out
    text = (content or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return _parse_rows("", json.dumps(data, ensure_ascii=False))
    except json.JSONDecodeError:
        pass
    rows: list[list[str]] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if cells and all(set(c) <= set("-: ") and c for c in cells):
                continue
            rows.append(cells)
        elif "\t" in s:
            rows.append(s.split("\t"))
        elif "," in s:
            rows.append([c.strip() for c in s.split(",")])
        else:
            rows.append([s])
    return rows


def _md_blocks(content: str) -> list[str]:
    text = (content or "").replace("\r\n", "\n")
    if not text.strip():
        return []
    if "\n---\n" in text:
        return [p.strip() for p in text.split("\n---\n") if p.strip()]
    parts = re.split(r"\n(?=#{1,3}\s)", text)
    return [p.strip() for p in parts if p.strip()] or [text.strip()]


def _parse_paths_json(raw: str) -> list[str]:
    s = (raw or "").strip()
    if not s:
        return []
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return [ln.strip() for ln in s.splitlines() if ln.strip()]
    if isinstance(data, str):
        return [data.strip()] if data.strip() else []
    if isinstance(data, list):
        out: list[str] = []
        for item in data:
            if isinstance(item, dict):
                p = str(item.get("path") or item.get("file") or "").strip()
            else:
                p = str(item or "").strip()
            if p:
                out.append(p)
        return out
    return []


def _glob_office(pattern: str) -> list[str]:
    from app.tools.safety import get_workspace_root, workspace_relpath

    root = get_workspace_root()
    pat = (pattern or "").replace("\\", "/").lstrip("/")
    if not pat:
        return []
    name_only = "/" not in pat.rstrip("/")
    hits: list[str] = []
    for p in root.rglob("*"):
        if not p.is_file() or p.name.startswith("."):
            continue
        if p.suffix.lower() not in EXT_KIND:
            continue
        rel = workspace_relpath(p).replace("\\", "/")
        ok = fnmatch.fnmatch(rel.lower(), pat.lower())
        if not ok and name_only:
            ok = fnmatch.fnmatch(p.name.lower(), pat.lower())
        if ok:
            hits.append(rel)
        if len(hits) >= MAX_BATCH:
            break
    return hits


def collect_targets(
    path: str = "",
    paths: Any = None,
    paths_json: str = "",
) -> list[str]:
    raw: list[str] = []
    if isinstance(paths, str) and paths.strip():
        raw.extend(_parse_paths_json(paths))
    elif isinstance(paths, (list, tuple)):
        for item in paths:
            if isinstance(item, dict):
                p = str(item.get("path") or item.get("file") or "").strip()
            else:
                p = str(item or "").strip()
            if p:
                raw.append(p)
    raw.extend(_parse_paths_json(paths_json))
    p0 = (path or "").strip()
    if p0:
        if "\n" in p0:
            raw.extend(ln.strip() for ln in p0.splitlines() if ln.strip())
        else:
            raw.append(p0)
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        piece = item.replace("\\", "/").strip()
        if not piece or piece in (".", "./"):
            continue
        expanded = _glob_office(piece) if ("*" in piece or "?" in piece) else [piece]
        for rel in expanded:
            key = rel.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(rel)
            if len(out) >= MAX_BATCH:
                return out
    return out


def run(
    *,
    action: str,
    path: str = "",
    paths: Any = None,
    paths_json: str = "",
    content: str = "",
    kind: str = "",
    find: str = "",
    replace: str = "",
    sheet: str = "",
    cell: str = "",
    value: str = "",
    rows_json: str = "",
    slide: int = 0,
    append: bool = False,
    overwrite: bool = False,
    max_chars: int = MAX_TEXT,
) -> dict[str, Any]:
    blocked = _hub_http_block()
    if blocked:
        return blocked
    act = (action or "read").strip().lower()
    if act in ("info", "formats", "help"):
        from app.tools.safety import get_workspace_root

        return _ok(
            action="info",
            workspace_root=str(get_workspace_root()),
            formats={
                "word": ".docx",
                "excel": ".xlsx",
                "ppt": ".pptx",
                "pdf": ".pdf",
                "markdown": ".md",
            },
            batch_limit=MAX_BATCH,
            hint=(
                "写入 path 须在 uploads/docs/exports/scratch/images/videos/skills 下；"
                "新建默认 docs/ 或 exports/ 或 scratch/；禁止根目录。"
                "覆盖已有文件须 ask_user 后 overwrite=true。"
                "批量：paths=['docs/a.docx','exports/b.xlsx']，或 path='docs/*.xlsx'。"
                "旧版 .doc/.xls/.ppt 请另存为新格式。"
            ),
            write_buckets=[
                "uploads",
                "docs",
                "exports",
                "scratch",
                "images",
                "videos",
                "skills",
            ],
        )
    if act in ("list", "ls"):
        return _list(kind=kind)
    targets = collect_targets(path, paths, paths_json)
    if not targets:
        return _err(
            "需要 path 或 paths。单文件如 docs/notes.md 或 exports/a.xlsx；"
            "批量如 paths 数组或 docs/*.xlsx。禁止工作区根目录。"
        )
    if len(targets) == 1:
        return _run_one(
            act,
            targets[0],
            content=content,
            kind=kind,
            find=find,
            replace=replace,
            sheet=sheet,
            cell=cell,
            value=value,
            rows_json=rows_json,
            slide=slide,
            append=append,
            overwrite=overwrite,
            max_chars=max_chars,
        )
    per = max(800, min(int(max_chars or MAX_TEXT), MAX_TEXT // min(len(targets), 8)))
    results: list[dict[str, Any]] = []
    ok_n = 0
    for rel in targets:
        row = _run_one(
            act,
            rel,
            content=content,
            kind=kind,
            find=find,
            replace=replace,
            sheet=sheet,
            cell=cell,
            value=value,
            rows_json=rows_json,
            slide=slide,
            append=append,
            overwrite=overwrite,
            max_chars=per,
        )
        row.setdefault("path", rel)
        results.append(row)
        if row.get("ok"):
            ok_n += 1
    fail_n = len(results) - ok_n
    out = _ok(
        action=act,
        batch=True,
        count=len(results),
        ok_count=ok_n,
        fail_count=fail_n,
        truncated_batch=len(targets) >= MAX_BATCH,
        results=results,
    )
    if fail_n:
        out["ok"] = False
        out["error"] = f"{fail_n}/{len(results)} 个失败"
    return out


def _run_one(
    act: str,
    path: str,
    *,
    content: str,
    kind: str,
    find: str,
    replace: str,
    sheet: str,
    cell: str,
    value: str,
    rows_json: str,
    slide: int,
    append: bool,
    overwrite: bool = False,
    max_chars: int,
) -> dict[str, Any]:
    if act in ("delete", "rm", "remove"):
        return _delete(path)
    kind_n = detect_kind(path, kind)
    if act in ("write", "create", "save") and not kind_n:
        return _err(
            "write 需要 path 带扩展名，或传 kind=word|excel|ppt|pdf|markdown",
            path=path,
        )
    if kind_n:
        path = _ensure_ext(path, kind_n)
        kind_n = detect_kind(path, kind_n)
    ext = Path(path).suffix.lower()
    if ext in LEGACY:
        return _err(LEGACY[ext], path=path)
    if not kind_n:
        return _err(
            "只支持 .docx / .xlsx / .pptx / .pdf / .md",
            path=path,
        )
    if act in ("read", "open", "get"):
        return _read(path, kind_n, max_chars=max_chars, sheet=sheet, slide=slide)
    if act in ("write", "create", "save"):
        return _write(
            path,
            kind_n,
            content=content,
            rows_json=rows_json,
            append=False,
            overwrite=bool(overwrite),
        )
    if act in ("edit", "update", "patch"):
        return _edit(
            path,
            kind_n,
            content=content,
            find=find,
            replace=replace,
            sheet=sheet,
            cell=cell,
            value=value,
            rows_json=rows_json,
            slide=slide,
            append=append,
        )
    return _err("action 须为 info|list|read|write|edit|delete", path=path)


def _list(*, kind: str = "") -> dict[str, Any]:
    from app.tools.safety import get_workspace_root, workspace_relpath

    root = get_workspace_root()
    want = (kind or "").strip().lower()
    if want:
        want = detect_kind("x." + want, want) or want
    files: list[dict[str, Any]] = []
    for p in root.rglob("*"):
        if not p.is_file() or p.name.startswith("."):
            continue
        k = EXT_KIND.get(p.suffix.lower())
        if not k:
            continue
        if want and k != want:
            continue
        try:
            sz = p.stat().st_size
        except OSError:
            sz = None
        files.append(
            {"path": workspace_relpath(p), "kind": k, "size": sz}
        )
        if len(files) >= 400:
            break
    return _ok(action="list", count=len(files), files=files)


def _delete(path: str) -> dict[str, Any]:
    target, rel = _resolve(path)
    if target is None:
        return _err("路径越出工作区", path=path)
    if not target.exists():
        return _err(f"文件不存在：{rel}", path=rel)
    if target.is_dir():
        return _err("不能删除目录，只删文件", path=rel)
    ext = target.suffix.lower()
    if ext not in EXT_KIND and ext not in LEGACY:
        return _err("只能删除 Word/Excel/PPT/PDF/Markdown 文件", path=rel)
    sz = target.stat().st_size
    target.unlink()
    return _ok(action="delete", deleted=rel, bytes=sz)


def _read(
    path: str,
    kind: str,
    *,
    max_chars: int,
    sheet: str,
    slide: int,
) -> dict[str, Any]:
    target, rel = _resolve(path)
    if target is None:
        return _err("路径越出工作区", path=path)
    if not target.is_file():
        return _err(f"不是文件：{rel}", path=rel)
    try:
        size = target.stat().st_size
    except OSError as exc:
        return _err(str(exc), path=rel)
    if size > MAX_FILE_BYTES:
        return _err(f"文件过大（>{MAX_FILE_BYTES} 字节）", path=rel, size=size)
    try:
        if kind == "markdown":
            text = target.read_text(encoding="utf-8", errors="replace")
            clipped, trunc = _clip(text, max_chars)
            return _ok(
                action="read",
                path=rel,
                kind=kind,
                content=clipped,
                truncated=trunc,
                chars=len(text),
            )
        if kind == "word":
            return _read_word(target, rel, max_chars)
        if kind == "excel":
            return _read_excel(target, rel, sheet=sheet, max_chars=max_chars)
        if kind == "ppt":
            return _read_ppt(target, rel, slide=slide, max_chars=max_chars)
        if kind == "pdf":
            return _read_pdf(target, rel, max_chars=max_chars)
    except Exception as extra:
        logger.exception("document read failed")
        return _err(f"读取失败：{extra}", path=rel, kind=kind)
    return _err("未知类型", kind=kind)


def _write(
    path: str,
    kind: str,
    *,
    content: str,
    rows_json: str,
    append: bool,
    overwrite: bool = False,
) -> dict[str, Any]:
    from app.tools.safety import (
        WRITE_BUCKETS,
        enforce_write_relpath,
        normalize_workspace_relpath,
    )

    rel_enforced, err, rewritten = enforce_write_relpath(path, rewrite=True)
    if err or not rel_enforced:
        return _err(
            err or "非法写路径",
            path=path,
            allowed_buckets=sorted(WRITE_BUCKETS),
            hint="新建默认 docs/ 或 exports/ 或 scratch/；禁止工作区根目录。",
        )
    target, rel = _resolve(rel_enforced)
    if target is None:
        return _err("路径越出工作区", path=rel_enforced)
    if target.exists() and target.is_file() and not append and not overwrite:
        extra = (
            {"rewritten_from": normalize_workspace_relpath(path)} if rewritten else {}
        )
        return _err(
            f"文件已存在：{rel}。覆盖前须 ask_user 确认，再带 overwrite=true 重试。",
            path=rel,
            action_required="confirm_overwrite",
            hint=(
                "调用 ask_user 让用户选「覆盖」或「换路径」；"
                "确认覆盖后再 document write overwrite=true。"
            ),
            **extra,
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        if kind == "markdown":
            if append and target.is_file():
                old = target.read_text(encoding="utf-8", errors="replace")
                target.write_text(
                    old.rstrip() + "\n\n" + (content or ""), encoding="utf-8"
                )
            else:
                target.write_text(content or "", encoding="utf-8")
        elif kind == "word":
            _write_word(target, content or "", append=append and target.is_file())
        elif kind == "excel":
            _write_excel(target, content=content, rows_json=rows_json, append=append)
        elif kind == "ppt":
            _write_ppt(target, content or "", append=append and target.is_file())
        elif kind == "pdf":
            _write_pdf(target, content or "", append=append and target.is_file())
        else:
            return _err("未知类型", kind=kind)
    except Exception as exc:
        logger.exception("document write failed")
        return _err(f"写入失败：{exc}", path=rel, kind=kind)
    sz = target.stat().st_size if target.is_file() else 0
    out_extra: dict[str, Any] = {}
    if rewritten:
        out_extra["rewritten_from"] = normalize_workspace_relpath(path)
        out_extra["hint"] = "路径已自动归入白名单目录（默认 scratch/）。"
    return _ok(action="write", path=rel, kind=kind, bytes=sz, **out_extra)



def _edit(
    path: str,
    kind: str,
    *,
    content: str,
    find: str,
    replace: str,
    sheet: str,
    cell: str,
    value: str,
    rows_json: str,
    slide: int,
    append: bool,
) -> dict[str, Any]:
    target, rel = _resolve(path)
    if target is None:
        return _err("路径越出工作区", path=path)
    if not target.is_file():
        return _err(f"文件不存在，请用 write 新建：{rel}", path=rel)
    try:
        if kind == "markdown":
            text = target.read_text(encoding="utf-8", errors="replace")
            if find:
                text = text.replace(find, replace)
            elif append:
                text = text.rstrip() + "\n\n" + (content or "")
            elif content:
                text = content
            else:
                return _err("edit Markdown 需要 find/replace，或 content，或 append=true")
            target.write_text(text, encoding="utf-8")
            return _ok(action="edit", path=rel, kind=kind, bytes=target.stat().st_size)
        if kind == "word":
            return _edit_word(
                target, rel, content=content, find=find, replace=replace, append=append
            )
        if kind == "excel":
            return _edit_excel(
                target,
                rel,
                content=content,
                find=find,
                replace=replace,
                sheet=sheet,
                cell=cell,
                value=value,
                rows_json=rows_json,
                append=append,
            )
        if kind == "ppt":
            return _edit_ppt(
                target,
                rel,
                content=content,
                find=find,
                replace=replace,
                slide=slide,
                append=append,
            )
        if kind == "pdf":
            return _edit_pdf(
                target, rel, content=content, find=find, replace=replace, append=append
            )
    except Exception as extra:
        logger.exception("document edit failed")
        return _err(f"编辑失败：{extra}", path=rel, kind=kind)
    return _err("未知类型", kind=kind)


def _read_word(path: Path, rel: str, max_chars: int) -> dict[str, Any]:
    from docx import Document

    doc = Document(str(path))
    parts: list[str] = []
    for p in doc.paragraphs:
        t = (p.text or "").rstrip()
        if t:
            parts.append(t)
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join((c.text or "").strip() for c in row.cells))
    text = "\n".join(parts)
    clipped, trunc = _clip(text, max_chars)
    return _ok(
        action="read",
        path=rel,
        kind="word",
        content=clipped,
        truncated=trunc,
        paragraphs=len(doc.paragraphs),
        tables=len(doc.tables),
    )


def _write_word(path: Path, content: str, *, append: bool) -> None:
    from docx import Document

    doc = Document(str(path)) if append and path.is_file() else Document()
    blocks = _md_blocks(content) or [content or ""]
    if append:
        blocks = [content or ""]
    for block in blocks:
        for line in (block or "").splitlines() or [""]:
            s = line.rstrip()
            if s.startswith("### "):
                doc.add_heading(s[4:].strip(), level=3)
            elif s.startswith("## "):
                doc.add_heading(s[3:].strip(), level=2)
            elif s.startswith("# "):
                doc.add_heading(s[2:].strip(), level=1)
            elif s.startswith("- "):
                doc.add_paragraph(s[2:].strip(), style="List Bullet")
            else:
                doc.add_paragraph(s)
    doc.save(str(path))


def _edit_word(
    path: Path,
    rel: str,
    *,
    content: str,
    find: str,
    replace: str,
    append: bool,
) -> dict[str, Any]:
    from docx import Document

    if find:
        doc = Document(str(path))
        n = 0
        for p in doc.paragraphs:
            if find in (p.text or ""):
                for run in p.runs:
                    if find in (run.text or ""):
                        run.text = (run.text or "").replace(find, replace)
                        n += 1
                if find in (p.text or ""):
                    p.text = (p.text or "").replace(find, replace)
                    n += 1
        doc.save(str(path))
        return _ok(action="edit", path=rel, kind="word", replaced=n)
    if append or content:
        _write_word(path, content or "", append=append or not content)
        return _ok(action="edit", path=rel, kind="word", bytes=path.stat().st_size)
    return _err("edit Word 需要 find/replace，或 content / append")


def _read_excel(
    path: Path, rel: str, *, sheet: str, max_chars: int
) -> dict[str, Any]:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), data_only=True, read_only=True)
    names = list(wb.sheetnames)
    pick = (sheet or "").strip() or (names[0] if names else "")
    if pick not in names:
        wb.close()
        return _err(f"没有工作表 {pick}", path=rel, sheets=names)
    ws = wb[pick]
    rows: list[list[str]] = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i >= MAX_EXCEL_ROWS:
            break
        rows.append(["" if c is None else str(c) for c in row])
    wb.close()
    text = "\n".join("\t".join(r) for r in rows)
    clipped, trunc = _clip(text, max_chars)
    return _ok(
        action="read",
        path=rel,
        kind="excel",
        sheet=pick,
        sheets=names,
        rows=rows[:MAX_EXCEL_ROWS],
        content=clipped,
        truncated=trunc or len(rows) >= MAX_EXCEL_ROWS,
    )


def _write_excel(
    path: Path, *, content: str, rows_json: str, append: bool
) -> None:
    from openpyxl import Workbook, load_workbook

    rows = _parse_rows(content, rows_json)
    if append and path.is_file():
        wb = load_workbook(str(path))
        ws = wb.active
        for row in rows:
            ws.append(row)
        wb.save(str(path))
        return
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    if not rows:
        rows = [[""]]
    for row in rows:
        ws.append(row)
    wb.save(str(path))


def _edit_excel(
    path: Path,
    rel: str,
    *,
    content: str,
    find: str,
    replace: str,
    sheet: str,
    cell: str,
    value: str,
    rows_json: str,
    append: bool,
) -> dict[str, Any]:
    from openpyxl import load_workbook

    wb = load_workbook(str(path))
    names = list(wb.sheetnames)
    pick = (sheet or "").strip() or (names[0] if names else "")
    if pick not in wb.sheetnames:
        wb.close()
        return _err(f"没有工作表 {pick}", path=rel, sheets=names)
    ws = wb[pick]
    changed = 0
    if cell:
        ws[(cell or "").strip().upper()] = value if value != "" else (content or "")
        changed = 1
    elif find:
        for row in ws.iter_rows():
            for c in row:
                if c.value is not None and find in str(c.value):
                    c.value = str(c.value).replace(find, replace)
                    changed += 1
    elif rows_json or (content and (append or content.strip().startswith(("|", "[", "{")))):
        rows = _parse_rows(content, rows_json)
        if append:
            for row in rows:
                ws.append(row)
            changed = len(rows)
        else:
            ws.delete_rows(1, ws.max_row or 1)
            for row in rows:
                ws.append(row)
            changed = len(rows)
    elif content:
        ws.append([content])
        changed = 1
    else:
        wb.close()
        return _err("edit Excel 需要 cell+value，或 find/replace，或 rows_json/content")
    wb.save(str(path))
    return _ok(action="edit", path=rel, kind="excel", sheet=pick, changed=changed)


def _read_ppt(
    path: Path, rel: str, *, slide: int, max_chars: int
) -> dict[str, Any]:
    from pptx import Presentation

    prs = Presentation(str(path))
    slides: list[dict[str, Any]] = []
    for i, s in enumerate(prs.slides, start=1):
        if slide and i != int(slide):
            continue
        texts: list[str] = []
        for shape in s.shapes:
            if getattr(shape, "has_text_frame", False):
                t = (shape.text or "").strip()
                if t:
                    texts.append(t)
        slides.append({"index": i, "text": "\n".join(texts)})
        if len(slides) >= MAX_PPT_SLIDES:
            break
    blob = "\n\n".join(f"# 幻灯片 {x['index']}\n{x['text']}" for x in slides)
    clipped, trunc = _clip(blob, max_chars)
    return _ok(
        action="read",
        path=rel,
        kind="ppt",
        slides=slides,
        content=clipped,
        truncated=trunc,
        count=len(prs.slides),
    )


def _add_ppt_slide(prs: Any, text: str) -> None:
    from pptx.util import Inches, Pt

    layout = prs.slide_layouts[1] if len(prs.slide_layouts) > 1 else prs.slide_layouts[0]
    slide = prs.slides.add_slide(layout)
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    title = ""
    body_lines: list[str] = []
    for ln in lines:
        s = ln.strip()
        if s.startswith("#"):
            s = s.lstrip("#").strip()
        if not title and s:
            title = s
        else:
            body_lines.append(ln)
    if slide.shapes.title is not None:
        slide.shapes.title.text = title
    body = "\n".join(body_lines).strip()
    if len(slide.placeholders) > 1 and body:
        try:
            slide.placeholders[1].text = body
            return
        except Exception:
            pass
    if body:
        box = slide.shapes.add_textbox(Inches(0.8), Inches(1.8), Inches(8.4), Inches(5))
        tf = box.text_frame
        tf.word_wrap = True
        tf.text = body
        for p in tf.paragraphs:
            p.font.size = Pt(18)


def _write_ppt(path: Path, content: str, *, append: bool) -> None:
    from pptx import Presentation

    prs = Presentation(str(path)) if append and path.is_file() else Presentation()
    blocks = _md_blocks(content) or [content or "空白页"]
    for block in blocks:
        _add_ppt_slide(prs, block)
    prs.save(str(path))


def _edit_ppt(
    path: Path,
    rel: str,
    *,
    content: str,
    find: str,
    replace: str,
    slide: int,
    append: bool,
) -> dict[str, Any]:
    from pptx import Presentation

    prs = Presentation(str(path))
    if append or (content and not find and not slide):
        _add_ppt_slide(prs, content or "新幻灯片")
        prs.save(str(path))
        return _ok(action="edit", path=rel, kind="ppt", added=True, count=len(prs.slides))
    n = 0
    for i, s in enumerate(prs.slides, start=1):
        if slide and i != int(slide):
            continue
        for shape in s.shapes:
            if not getattr(shape, "has_text_frame", False):
                continue
            for para in shape.text_frame.paragraphs:
                for run in para.runs:
                    t = run.text or ""
                    if find and find in t:
                        run.text = t.replace(find, replace)
                        n += 1
                    elif content and slide and i == int(slide) and not find:
                        run.text = content if n == 0 else ""
                        n += 1
    if not n and content and slide:
        return _err("该页没有可改的文本框", path=rel, slide=slide)
    if not n and find:
        prs.save(str(path))
        return _ok(action="edit", path=rel, kind="ppt", replaced=0)
    prs.save(str(path))
    return _ok(action="edit", path=rel, kind="ppt", replaced=n)


def _read_pdf(path: Path, rel: str, *, max_chars: int) -> dict[str, Any]:
    pages: list[str] = []
    try:
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            for i, page in enumerate(pdf.pages):
                if i >= MAX_PDF_PAGES:
                    break
                pages.append((page.extract_text() or "").strip())
    except Exception:
        from PyPDF2 import PdfReader

        reader = PdfReader(str(path))
        for i, page in enumerate(reader.pages):
            if i >= MAX_PDF_PAGES:
                break
            pages.append((page.extract_text() or "").strip())
    blob = "\n\n".join(f"# 第 {i+1} 页\n{t}" for i, t in enumerate(pages) if t)
    clipped, trunc = _clip(blob, max_chars)
    return _ok(
        action="read",
        path=rel,
        kind="pdf",
        pages=len(pages),
        content=clipped,
        truncated=trunc,
    )


def _pdf_font() -> str:
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont

        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        return "STSong-Light"
    except Exception:
        return "Helvetica"


def _write_pdf(path: Path, content: str, *, append: bool) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    font = _pdf_font()
    w, h = A4
    if append and path.is_file():
        # Recreate is lossy; append by merging a new page file.
        from PyPDF2 import PdfReader, PdfWriter

        extra = path.with_suffix(".eva-append.pdf")
        _write_pdf(extra, content, append=False)
        writer = PdfWriter()
        for p in PdfReader(str(path)).pages:
            writer.add_page(p)
        for p in PdfReader(str(extra)).pages:
            writer.add_page(p)
        with path.open("wb") as fh:
            writer.write(fh)
        extra.unlink(missing_ok=True)
        return
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont(font, 11)
    x, y = 48, h - 56
    leading = 16
    for line in (content or "").splitlines() or [""]:
        if y < 48:
            c.showPage()
            c.setFont(font, 11)
            y = h - 56
        # simple wrap
        chunk = line
        while len(chunk) > 42:
            c.drawString(x, y, chunk[:42])
            chunk = chunk[42:]
            y -= leading
            if y < 48:
                c.showPage()
                c.setFont(font, 11)
                y = h - 56
        c.drawString(x, y, chunk)
        y -= leading
    c.save()


def _edit_pdf(
    path: Path,
    rel: str,
    *,
    content: str,
    find: str,
    replace: str,
    append: bool,
) -> dict[str, Any]:
    if append or (content and not find):
        _write_pdf(path, content or "", append=True)
        return _ok(
            action="edit",
            path=rel,
            kind="pdf",
            note="已追加文本页。PDF 不能原地改版式。",
        )
    if find:
        got = _read_pdf(path, rel, max_chars=200_000)
        text = str(got.get("content") or "")
        text = text.replace(find, replace)
        _write_pdf(path, text, append=False)
        return _ok(
            action="edit",
            path=rel,
            kind="pdf",
            note="已按纯文本重写 PDF，原版式不保留。需要保版式请用 Word 再导出。",
        )
    return _err("edit PDF 需要 append 文本，或 find/replace（会重写成纯文本 PDF）")
