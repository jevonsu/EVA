"""Knowledge-base portable pack: export/import .evakb (zip) with pages + catalog.

Format (format=1):
  manifest.json  — kind=eva-kb, format, exported_at, eva_version, page_count, collections, filters
  catalog.json   — {collections, hidden}
  pages/<id>.json — one page object (source text + metadata; no embeddings/secrets)

Conflict strategies on import: skip | overwrite | keep_both
"""

from __future__ import annotations

import io
import json
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

PACK_KIND = "eva-kb"
PACK_FORMAT = 1
PACK_EXT = ".evakb"

_MAX_ZIP_BYTES = 32 * 1024 * 1024  # 32 MiB upload
_MAX_MEMBER_BYTES = 4 * 1024 * 1024  # 4 MiB per entry
_MAX_PAGES = 5000
_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")

_PAGE_KEYS = (
    "id",
    "title",
    "slug",
    "collection",
    "tags",
    "content",
    "version",
    "pinned",
    "archived",
    "versions",
    "created_at",
    "updated_at",
    "status",
    "valid_from",
    "valid_to",
    "confidence",
    "supersedes_id",
)

_SECRET_KEY_HINTS = (
    "api_key",
    "apikey",
    "password",
    "secret",
    "token",
    "authorization",
    "private_key",
    "access_key",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _posix(name: str) -> str:
    return (name or "").replace("\\", "/").lstrip("/")


def _safe_zip_name(name: str) -> str:
    """Return normalized relative name or raise on zip-slip / absolute paths."""
    n = _posix(name)
    if not n or n.endswith("/"):
        raise ValueError(f"非法路径: {name!r}")
    if n.startswith("/") or n.startswith("\\"):
        raise ValueError(f"非法路径: {name!r}")
    parts = Path(n).parts
    if any(p in (".", "..") for p in parts):
        raise ValueError(f"非法路径: {name!r}")
    if Path(n).is_absolute():
        raise ValueError(f"非法路径: {name!r}")
    return n


def _strip_secrets(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            lk = str(k).lower().replace("-", "_")
            if any(h in lk for h in _SECRET_KEY_HINTS):
                continue
            out[k] = _strip_secrets(v)
        return out
    if isinstance(obj, list):
        return [_strip_secrets(x) for x in obj]
    return obj


def _page_public(page: dict[str, Any]) -> dict[str, Any]:
    raw = {k: page.get(k) for k in _PAGE_KEYS if k in page or k in (
        "id", "title", "content", "collection", "tags"
    )}
    # Always include core fields even if missing
    out = {
        "id": str(raw.get("id") or ""),
        "title": str(raw.get("title") or ""),
        "slug": str(raw.get("slug") or ""),
        "collection": str(raw.get("collection") or "default") or "default",
        "tags": list(raw.get("tags") or []) if isinstance(raw.get("tags"), list) else [],
        "content": str(raw.get("content") or ""),
        "version": int(raw.get("version") or 1),
        "pinned": bool(raw.get("pinned")),
        "archived": bool(raw.get("archived")),
        "versions": list(raw.get("versions") or []) if isinstance(raw.get("versions"), list) else [],
        "created_at": str(raw.get("created_at") or ""),
        "updated_at": str(raw.get("updated_at") or ""),
        "status": str(raw.get("status") or "active"),
        "valid_from": raw.get("valid_from"),
        "valid_to": raw.get("valid_to"),
        "confidence": float(raw.get("confidence") if raw.get("confidence") is not None else 1.0),
        "supersedes_id": raw.get("supersedes_id"),
    }
    return _strip_secrets(out)


def export_content_disposition(fname: str) -> str:
    ascii_name = fname if fname.isascii() else "eva-kb.evakb"
    return (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(fname)}"
    )


def _eva_version() -> str:
    try:
        from app import __version__

        return str(__version__)
    except Exception:
        return ""


async def collect_pages(
    store: Any,
    *,
    collection: str | None = None,
    page_ids: list[str] | None = None,
    include_archived: bool = True,
) -> list[dict[str, Any]]:
    want: set[str] | None = None
    if page_ids:
        want = {str(x).strip() for x in page_ids if str(x).strip()}
    index = await store.list_pages(
        collection=collection or None,
        include_archived=include_archived,
        limit=_MAX_PAGES,
    )
    out: list[dict[str, Any]] = []
    for row in index:
        pid = str(row.get("id") or "")
        if want is not None and pid not in want:
            continue
        page = await store.get(pid)
        if not page:
            continue
        out.append(_page_public(page))
    # If specific ids missing from index (e.g. archived filtered), try direct get
    if want is not None:
        have = {p["id"] for p in out}
        for pid in want - have:
            page = await store.get(pid)
            if page:
                out.append(_page_public(page))
    return out


async def build_export_zip(
    store: Any,
    *,
    collection: str | None = None,
    page_ids: list[str] | None = None,
    include_archived: bool = True,
    include_catalog: bool = True,
) -> tuple[bytes, str, dict[str, Any]]:
    pages = await collect_pages(
        store,
        collection=collection,
        page_ids=page_ids,
        include_archived=include_archived,
    )
    catalog: dict[str, Any] = {"collections": [], "hidden": []}
    if include_catalog:
        try:
            pub = await store.collections_public()
            opts = pub.get("options") or pub.get("collections") or []
            catalog = {
                "collections": [str(x) for x in opts if str(x).strip()],
                "hidden": list(pub.get("hidden") or []),
            }
        except Exception:
            catalog = {"collections": [], "hidden": []}

    coll_names = sorted(
        {
            *(str(c) for c in (catalog.get("collections") or []) if c),
            *(str(p.get("collection") or "default") for p in pages),
        }
    )
    manifest = {
        "kind": PACK_KIND,
        "format": PACK_FORMAT,
        "exported_at": _now_iso(),
        "eva_version": _eva_version(),
        "page_count": len(pages),
        "collections": coll_names,
        "filters": {
            "collection": collection or None,
            "page_ids": list(page_ids) if page_ids else None,
            "include_archived": bool(include_archived),
        },
        "notes": "Source wiki pages only; keyword index rebuilt on import. No API keys.",
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )
        zf.writestr(
            "catalog.json",
            json.dumps(
                {
                    "collections": list(catalog.get("collections") or coll_names),
                    "hidden": list(catalog.get("hidden") or []),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )
        for p in pages:
            pid = p["id"] or uuid.uuid4().hex
            if not _ID_RE.match(pid):
                pid = re.sub(r"[^A-Za-z0-9_\-]", "_", pid)[:64] or uuid.uuid4().hex
            p = dict(p)
            p["id"] = pid
            zf.writestr(
                f"pages/{pid}.json",
                json.dumps(p, ensure_ascii=False, indent=2) + "\n",
            )

    stamp = datetime.now().strftime("%Y%m%d")
    if page_ids and len(page_ids) == 1:
        label = f"eva-kb-page-{page_ids[0][:12]}"
    elif collection:
        label = f"eva-kb-{collection}"
    else:
        label = "eva-kb"
    fname = f"{label}-{stamp}{PACK_EXT}"
    return buf.getvalue(), fname, manifest


def _parse_json_bytes(data: bytes, label: str) -> Any:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ValueError(f"{label} 不是 UTF-8 文本: {e}") from e
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"{label} JSON 无效: {e}") from e


def _read_zip_members(zip_bytes: bytes) -> dict[str, bytes]:
    if len(zip_bytes) > _MAX_ZIP_BYTES:
        raise ValueError(f"压缩包过大（上限 {_MAX_ZIP_BYTES // (1024 * 1024)}MB）")
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as e:
        raise ValueError(f"不是有效的 ZIP/知识库包: {e}") from e
    out: dict[str, bytes] = {}
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = _safe_zip_name(info.filename)
            if info.file_size > _MAX_MEMBER_BYTES:
                raise ValueError(f"条目过大: {name}（上限 {_MAX_MEMBER_BYTES // (1024 * 1024)}MB）")
            # Guard against zip bombs via compressed vs uncompressed ratio is soft;
            # hard cap is member + total zip size.
            data = zf.read(info)
            if len(data) > _MAX_MEMBER_BYTES:
                raise ValueError(f"条目过大: {name}")
            out[name] = data
    return out


def _validate_manifest(man: Any) -> dict[str, Any]:
    if not isinstance(man, dict):
        raise ValueError("manifest.json 必须是对象")
    kind = str(man.get("kind") or "")
    if kind and kind != PACK_KIND:
        raise ValueError(f"不是知识库包（kind={kind!r}，期望 {PACK_KIND}）")
    fmt = man.get("format")
    if fmt is None:
        # Allow packs that forgot format but have pages/ — treat as 1
        fmt = 1
    try:
        fmt_i = int(fmt)
    except (TypeError, ValueError) as e:
        raise ValueError(f"manifest.format 无效: {fmt!r}") from e
    if fmt_i > PACK_FORMAT:
        raise ValueError(
            f"包格式版本过新（format={fmt_i}，本机支持 ≤{PACK_FORMAT}），请先升级 EVA"
        )
    if fmt_i < 1:
        raise ValueError(f"manifest.format 无效: {fmt_i}")
    return man


def _normalize_page(raw: Any, *, fallback_id: str = "") -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("页面必须是 JSON 对象")
    title = str(raw.get("title") or "").strip()
    content = str(raw.get("content") or "")
    if not title and not content:
        raise ValueError("页面缺少 title/content")
    if not title:
        title = (fallback_id or "未命名")[:80]
    pid = str(raw.get("id") or fallback_id or "").strip()
    if not pid or not _ID_RE.match(pid):
        pid = uuid.uuid4().hex
    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.replace("，", ",").split(",") if t.strip()]
    if not isinstance(tags, list):
        tags = []
    tags = [str(t).strip() for t in tags if str(t).strip()][:40]
    versions = raw.get("versions") or []
    if not isinstance(versions, list):
        versions = []
    try:
        confidence = float(raw.get("confidence") if raw.get("confidence") is not None else 1.0)
    except (TypeError, ValueError):
        confidence = 1.0
    page = {
        "id": pid,
        "title": title[:300],
        "slug": str(raw.get("slug") or "")[:300],
        "collection": (str(raw.get("collection") or "default").strip() or "default")[:80],
        "tags": tags,
        "content": content,
        "version": max(1, int(raw.get("version") or 1)),
        "pinned": bool(raw.get("pinned")),
        "archived": bool(raw.get("archived")),
        "versions": versions[-10:],
        "created_at": str(raw.get("created_at") or _now_iso()),
        "updated_at": str(raw.get("updated_at") or _now_iso()),
        "status": str(raw.get("status") or "active"),
        "valid_from": raw.get("valid_from"),
        "valid_to": raw.get("valid_to"),
        "confidence": confidence,
        "supersedes_id": raw.get("supersedes_id"),
    }
    return _page_public(page)


async def _find_slug_conflict(
    store: Any, *, collection: str, slug: str, exclude_id: str
) -> dict[str, Any] | None:
    slug_l = (slug or "").strip().lower()
    if not slug_l:
        return None
    for row in await store.list_pages(
        collection=collection, include_archived=True, limit=_MAX_PAGES
    ):
        rid = str(row.get("id") or "")
        if rid == exclude_id:
            continue
        if str(row.get("slug") or "").strip().lower() == slug_l:
            return await store.get(rid)
    return None


async def _write_imported_page(store: Any, page: dict[str, Any]) -> None:
    """Persist imported page preserving id/status (bypass UI staging gate)."""
    # Ensure slug
    if not (page.get("slug") or "").strip():
        from app.knowledge.store import _slugify

        page["slug"] = _slugify(page.get("title") or "page")
    await store._write_page(page)


async def import_pack_bytes(
    store: Any,
    raw: bytes,
    *,
    filename: str = "",
    conflict: str = "skip",
    merge_catalog: bool = True,
) -> dict[str, Any]:
    """Import a .evakb/.zip pack or a plain md/txt/json file.

    Returns counts + per-item details. Never raises for per-page failures —
    those go into ``failed`` with reasons. Raises ValueError for whole-pack errors.
    """
    conflict_l = (conflict or "skip").strip().lower()
    if conflict_l not in ("skip", "overwrite", "keep_both"):
        raise ValueError("conflict 仅支持 skip / overwrite / keep_both")

    name = (filename or "").lower()
    installed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    catalog_merged: list[str] = []

    is_zip = raw[:2] == b"PK" or name.endswith((".zip", PACK_EXT, ".evakb"))
    pages_in: list[dict[str, Any]] = []
    catalog_in: dict[str, Any] | None = None

    if is_zip:
        members = _read_zip_members(raw)
        man_raw = members.get("manifest.json")
        if man_raw is None:
            # allow missing manifest if pages/ present
            man = {"kind": PACK_KIND, "format": 1}
        else:
            man = _validate_manifest(_parse_json_bytes(man_raw, "manifest.json"))
            if not man.get("kind"):
                man["kind"] = PACK_KIND
            _validate_manifest(man)

        cat_raw = members.get("catalog.json")
        if cat_raw is not None:
            cat_obj = _parse_json_bytes(cat_raw, "catalog.json")
            if isinstance(cat_obj, dict):
                catalog_in = cat_obj

        page_files = sorted(
            n for n in members if n.startswith("pages/") and n.endswith(".json")
        )
        if not page_files and "pages.json" in members:
            blob = _parse_json_bytes(members["pages.json"], "pages.json")
            if isinstance(blob, list):
                for i, item in enumerate(blob):
                    try:
                        pages_in.append(_normalize_page(item, fallback_id=f"import_{i}"))
                    except ValueError as e:
                        failed.append({"id": f"pages.json[{i}]", "reason": str(e)})
            elif isinstance(blob, dict):
                pages_in.append(_normalize_page(blob))
        else:
            if not page_files:
                raise ValueError("包内没有 pages/*.json，也不是有效的知识库包")
            if len(page_files) > _MAX_PAGES:
                raise ValueError(f"页面数超过上限 {_MAX_PAGES}")
            for n in page_files:
                stem = Path(n).stem
                try:
                    obj = _parse_json_bytes(members[n], n)
                    pages_in.append(_normalize_page(obj, fallback_id=stem))
                except ValueError as e:
                    failed.append({"id": n, "reason": str(e)})
    else:
        # Plain files
        if name.endswith(".json") or (raw.lstrip()[:1] in (b"{", b"[")):
            obj = _parse_json_bytes(raw, filename or "upload.json")
            if isinstance(obj, dict) and obj.get("kind") == PACK_KIND:
                raise ValueError("请上传 .evakb/.zip 知识库包（不要只传 manifest）")
            if isinstance(obj, list):
                for i, item in enumerate(obj):
                    try:
                        pages_in.append(_normalize_page(item, fallback_id=f"import_{i}"))
                    except ValueError as e:
                        failed.append({"id": f"item[{i}]", "reason": str(e)})
            elif isinstance(obj, dict) and (
                "content" in obj or "title" in obj or "pages" in obj
            ):
                if isinstance(obj.get("pages"), list):
                    for i, item in enumerate(obj["pages"]):
                        try:
                            pages_in.append(
                                _normalize_page(item, fallback_id=f"import_{i}")
                            )
                        except ValueError as e:
                            failed.append({"id": f"pages[{i}]", "reason": str(e)})
                    if isinstance(obj.get("catalog"), dict):
                        catalog_in = obj["catalog"]
                else:
                    pages_in.append(_normalize_page(obj))
            else:
                raise ValueError("JSON 无法识别为知识页（需要 title/content 或 pages 数组）")
        else:
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError as e:
                raise ValueError(f"文件不是 UTF-8 文本: {e}") from e
            title = Path(filename or "导入文档").stem.strip() or "导入文档"
            # First markdown H1 as title
            m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
            if m:
                title = m.group(1).strip()[:300] or title
            pages_in.append(
                _normalize_page(
                    {
                        "title": title,
                        "content": text,
                        "collection": "default",
                        "tags": ["导入"],
                    }
                )
            )

    # Merge catalog collections first (additive)
    if merge_catalog and catalog_in:
        for cname in catalog_in.get("collections") or []:
            c = str(cname).strip()
            if not c:
                continue
            try:
                await store.add_collection(c)
                catalog_merged.append(c)
            except ValueError:
                # already exists / invalid — ignore
                pass
            except Exception as e:
                failed.append({"id": f"catalog:{c}", "reason": f"合并分类失败: {e}"})

    for page in pages_in:
        pid = page["id"]
        try:
            existing = await store.get(pid)
            # Also detect same collection+slug with different id
            slug_hit = None
            if not existing:
                slug_hit = await _find_slug_conflict(
                    store,
                    collection=page["collection"],
                    slug=page.get("slug") or "",
                    exclude_id=pid,
                )

            if existing:
                if conflict_l == "skip":
                    skipped.append(
                        {
                            "id": pid,
                            "title": page.get("title"),
                            "reason": "同 ID 已存在（skip）",
                        }
                    )
                    continue
                if conflict_l == "keep_both":
                    new_id = uuid.uuid4().hex
                    page = dict(page)
                    page["id"] = new_id
                    page["title"] = f"{page.get('title') or '未命名'}（导入副本）"
                    from app.knowledge.store import _slugify

                    page["slug"] = _slugify(page["title"])
                    page["created_at"] = _now_iso()
                    page["updated_at"] = _now_iso()
                    page["version"] = 1
                    await _write_imported_page(store, page)
                    installed.append(
                        {
                            "id": new_id,
                            "title": page["title"],
                            "action": "keep_both",
                            "from_id": pid,
                        }
                    )
                    continue
                # overwrite
                page = dict(page)
                page["id"] = pid
                # preserve created_at if existing has one
                if existing.get("created_at") and not page.get("created_at"):
                    page["created_at"] = existing["created_at"]
                page["updated_at"] = _now_iso()
                await _write_imported_page(store, page)
                installed.append(
                    {"id": pid, "title": page.get("title"), "action": "overwrite"}
                )
                continue

            if slug_hit and conflict_l == "skip":
                skipped.append(
                    {
                        "id": pid,
                        "title": page.get("title"),
                        "reason": (
                            f"同分类下 slug 已存在（已有 id={slug_hit.get('id')}，"
                            f"title={slug_hit.get('title')}）"
                        ),
                    }
                )
                continue
            if slug_hit and conflict_l == "overwrite":
                # overwrite the slug collision target
                page = dict(page)
                page["id"] = str(slug_hit.get("id") or pid)
                page["updated_at"] = _now_iso()
                await _write_imported_page(store, page)
                installed.append(
                    {
                        "id": page["id"],
                        "title": page.get("title"),
                        "action": "overwrite_slug",
                        "from_id": pid,
                    }
                )
                continue
            if slug_hit and conflict_l == "keep_both":
                page = dict(page)
                page["id"] = uuid.uuid4().hex
                page["title"] = f"{page.get('title') or '未命名'}（导入副本）"
                from app.knowledge.store import _slugify

                page["slug"] = _slugify(page["title"])
                page["created_at"] = _now_iso()
                page["updated_at"] = _now_iso()
                await _write_imported_page(store, page)
                installed.append(
                    {
                        "id": page["id"],
                        "title": page["title"],
                        "action": "keep_both",
                        "from_id": pid,
                    }
                )
                continue

            await _write_imported_page(store, page)
            installed.append(
                {"id": page["id"], "title": page.get("title"), "action": "create"}
            )
        except Exception as e:
            failed.append(
                {
                    "id": pid,
                    "title": page.get("title"),
                    "reason": f"{type(e).__name__}: {e}",
                }
            )

    return {
        "ok": True,
        "conflict": conflict_l,
        "installed": installed,
        "skipped": skipped,
        "failed": failed,
        "counts": {
            "installed": len(installed),
            "skipped": len(skipped),
            "failed": len(failed),
            "total_input": len(pages_in),
        },
        "catalog_merged": catalog_merged,
    }


# Re-export size caps for API layer
MAX_ZIP_BYTES = _MAX_ZIP_BYTES
MAX_MEMBER_BYTES = _MAX_MEMBER_BYTES