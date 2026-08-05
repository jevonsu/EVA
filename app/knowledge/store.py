"""Wiki-style knowledge base: pages with versions, keyword search, prompt snippets."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles

from app.config import get_settings

_MIN_MATCH = 1.5
_MAX_VERSIONS = 10

# Managed collection catalog (dropdown options; pages still store one collection string)
DEFAULT_COLLECTIONS: list[str] = [
    "default",
    "sop",
    "product",
    "handbook",
    "daily",
    "reference",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tokenize(text: str) -> set[str]:
    tokens: set[str] = set()
    for t in re.split(r"[\s,.;:!?/\\|_+\-*=()\[\]{}\"'`#]+", (text or "").lower()):
        if len(t) >= 2 or (t and "\u4e00" <= t <= "\u9fff"):
            tokens.add(t)
    chn = re.findall(r"[一-鿿]", text or "")
    if not chn:
        return tokens
    tokens.update(chn)
    for i in range(len(chn) - 1):
        tokens.add(chn[i] + chn[i + 1])
    for seg in re.findall(r"[一-鿿]{3,}", text or ""):
        tokens.add(seg)
    return tokens


def _slugify(title: str) -> str:
    s = (title or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^\w\u4e00-\u9fff\-]+", "", s, flags=re.UNICODE)
    return (s[:80] or "page").strip("-")


class KnowledgeStore:
    def __init__(self, root: Path | None = None) -> None:
        settings = get_settings()
        self.root = root or (settings.data_dir / "kb")
        self.root.mkdir(parents=True, exist_ok=True)
        self.pages_dir = self.root / "pages"
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.json"
        self.catalog_path = self.root / "catalog.json"
        if not self.index_path.exists():
            self.index_path.write_text("[]", encoding="utf-8")
        if not self.catalog_path.exists():
            self.catalog_path.write_text(
                json.dumps(
                    {"collections": list(DEFAULT_COLLECTIONS), "hidden": []},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    async def _load_index(self) -> list[dict[str, Any]]:
        async with aiofiles.open(self.index_path, "r", encoding="utf-8") as f:
            raw = await f.read()
        try:
            data = json.loads(raw or "[]")
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    async def _save_index(self, rows: list[dict[str, Any]]) -> None:
        async with aiofiles.open(self.index_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(rows, ensure_ascii=False, indent=2))

    def _page_path(self, page_id: str) -> Path:
        return self.pages_dir / f"{page_id}.json"

    async def _load_page(self, page_id: str) -> dict[str, Any] | None:
        path = self._page_path(page_id)
        if not path.exists():
            return None
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            return json.loads(await f.read())

    async def _write_page(self, page: dict[str, Any]) -> None:
        path = self._page_path(page["id"])
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(page, ensure_ascii=False, indent=2))

    def _index_row(self, page: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": page["id"],
            "title": page.get("title") or "",
            "slug": page.get("slug") or "",
            "collection": page.get("collection") or "default",
            "tags": page.get("tags") or [],
            "version": page.get("version") or 1,
            "updated_at": page.get("updated_at") or "",
            "created_at": page.get("created_at") or "",
            "pinned": bool(page.get("pinned")),
            "archived": bool(page.get("archived")),
            "preview": (page.get("content") or "")[:160],
        }

    async def list_pages(
        self,
        *,
        collection: str | None = None,
        include_archived: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = await self._load_index()
        out: list[dict[str, Any]] = []
        for r in sorted(rows, key=lambda x: x.get("updated_at") or "", reverse=True):
            if not include_archived and r.get("archived"):
                continue
            if collection and (r.get("collection") or "default") != collection:
                continue
            out.append(r)
            if len(out) >= limit:
                break
        return out

    async def _load_catalog(self) -> dict[str, Any]:
        try:
            async with aiofiles.open(self.catalog_path, "r", encoding="utf-8") as f:
                raw = await f.read()
            data = json.loads(raw or "{}")
            if not isinstance(data, dict):
                data = {}
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        coll = data.get("collections")
        hidden = data.get("hidden")
        if not isinstance(coll, list) or not coll:
            coll = list(DEFAULT_COLLECTIONS)
        if not isinstance(hidden, list):
            hidden = []
        # normalize unique preserve order
        seen: set[str] = set()
        clean: list[str] = []
        for x in coll:
            t = str(x or "").strip()
            if not t:
                continue
            k = t.lower()
            if k in seen:
                continue
            seen.add(k)
            clean.append(t)
        hid: list[str] = []
        hseen: set[str] = set()
        for x in hidden:
            t = str(x or "").strip()
            if not t:
                continue
            k = t.lower()
            if k in hseen:
                continue
            hseen.add(k)
            hid.append(t)
        return {"collections": clean, "hidden": hid}

    async def _save_catalog(self, catalog: dict[str, Any]) -> None:
        async with aiofiles.open(self.catalog_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(catalog, ensure_ascii=False, indent=2))

    async def list_collection_options(self) -> list[str]:
        """Visible collection names for the editor dropdown."""
        cat = await self._load_catalog()
        hidden = {str(x).strip().lower() for x in cat.get("hidden") or []}
        # also include collections already used by pages (unless explicitly hidden)
        used: list[str] = []
        for r in await self._load_index():
            if r.get("archived"):
                continue
            c = (r.get("collection") or "default").strip() or "default"
            used.append(c)
        merged: list[str] = []
        seen: set[str] = set()
        for x in list(cat.get("collections") or []) + used:
            t = str(x or "").strip()
            if not t:
                continue
            k = t.lower()
            if k in seen or k in hidden:
                continue
            seen.add(k)
            merged.append(t)
        if not merged:
            merged = ["default"]
        return merged

    async def add_collection(self, name: str) -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise ValueError("collection name required")
        if len(name) > 40:
            raise ValueError("collection name too long (max 40)")
        cat = await self._load_catalog()
        coll = list(cat.get("collections") or [])
        hidden = [
            h
            for h in (cat.get("hidden") or [])
            if str(h).strip().lower() != name.lower()
        ]
        if not any(str(x).strip().lower() == name.lower() for x in coll):
            coll.append(name)
        cat = {"collections": coll, "hidden": hidden}
        await self._save_catalog(cat)
        return {
            "ok": True,
            "name": name,
            "options": await self.list_collection_options(),
        }

    async def remove_collection_option(self, name: str) -> dict[str, Any]:
        """Hide/remove from catalog (does not rewrite existing pages)."""
        name = (name or "").strip()
        if not name:
            raise ValueError("collection name required")
        if name.lower() == "default":
            raise ValueError("不能删除默认分类 default")
        cat = await self._load_catalog()
        coll = [
            x
            for x in (cat.get("collections") or [])
            if str(x).strip().lower() != name.lower()
        ]
        hidden = list(cat.get("hidden") or [])
        # presets stay in hidden so they don't reappear from DEFAULT merge
        if name.lower() in {p.lower() for p in DEFAULT_COLLECTIONS}:
            if not any(str(h).strip().lower() == name.lower() for h in hidden):
                hidden.append(name)
        # custom: just drop from list; also hide so "used by pages" doesn't re-add? 
        # used-by-pages still shows unless hidden — hide all removed
        if not any(str(h).strip().lower() == name.lower() for h in hidden):
            hidden.append(name)
        # ensure default always present in catalog list
        if not any(str(x).strip().lower() == "default" for x in coll):
            coll.insert(0, "default")
        await self._save_catalog({"collections": coll, "hidden": hidden})
        return {
            "ok": True,
            "removed": name,
            "options": await self.list_collection_options(),
            "note": "仅从下拉选项移除；已用该分类的页面不会自动改分类。",
        }

    async def list_collections(self) -> list[dict[str, Any]]:
        rows = await self._load_index()
        counts: dict[str, int] = {}
        for r in rows:
            if r.get("archived"):
                continue
            c = r.get("collection") or "default"
            counts[c] = counts.get(c, 0) + 1
        options = await self.list_collection_options()
        # ensure every option appears (page_count may be 0)
        for o in options:
            counts.setdefault(o, 0)
        out = [
            {"id": k, "name": k, "page_count": v}
            for k, v in sorted(counts.items(), key=lambda x: x[0].lower())
        ]
        return out

    async def collections_public(self) -> dict[str, Any]:
        """Full payload for the KB editor collection picker."""
        cat = await self._load_catalog()
        options = await self.list_collection_options()
        items = await self.list_collections()
        return {
            "options": options,
            "presets": list(DEFAULT_COLLECTIONS),
            "hidden": list(cat.get("hidden") or []),
            "items": items,
        }

    async def get(self, page_id: str) -> dict[str, Any] | None:
        return await self._load_page(page_id)

    async def get_by_title_or_slug(self, key: str) -> dict[str, Any] | None:
        k = (key or "").strip().lower()
        if not k:
            return None
        for r in await self._load_index():
            if r.get("id") == key:
                return await self._load_page(r["id"])
            if (r.get("slug") or "").lower() == k or (r.get("title") or "").lower() == k:
                return await self._load_page(r["id"])
        return None

    async def create(
        self,
        *,
        title: str,
        content: str = "",
        tags: list[str] | None = None,
        collection: str = "default",
        pinned: bool = False,
    ) -> dict[str, Any]:
        title = (title or "").strip()
        if not title:
            raise ValueError("title required")
        now = _now().isoformat()
        page_id = uuid.uuid4().hex
        page = {
            "id": page_id,
            "title": title,
            "slug": _slugify(title),
            "content": content or "",
            "tags": tags or [],
            "collection": (collection or "default").strip() or "default",
            "pinned": bool(pinned),
            "archived": False,
            "version": 1,
            "versions": [],
            "created_at": now,
            "updated_at": now,
        }
        await self._write_page(page)
        idx = await self._load_index()
        idx.append(self._index_row(page))
        await self._save_index(idx)
        return page

    async def update(
        self,
        page_id: str,
        *,
        title: str | None = None,
        content: str | None = None,
        tags: list[str] | None = None,
        collection: str | None = None,
        pinned: bool | None = None,
        archived: bool | None = None,
        changelog: str = "",
    ) -> dict[str, Any] | None:
        page = await self._load_page(page_id)
        if not page:
            return None
        # snapshot previous content
        snap = {
            "version": page.get("version") or 1,
            "title": page.get("title"),
            "content": page.get("content"),
            "at": page.get("updated_at"),
            "note": changelog or "update",
        }
        versions = list(page.get("versions") or [])
        versions.append(snap)
        page["versions"] = versions[-_MAX_VERSIONS:]

        if title is not None and title.strip():
            page["title"] = title.strip()
            page["slug"] = _slugify(page["title"])
        if content is not None:
            page["content"] = content
        if tags is not None:
            page["tags"] = tags
        if collection is not None:
            page["collection"] = (collection or "default").strip() or "default"
        if pinned is not None:
            page["pinned"] = bool(pinned)
        if archived is not None:
            page["archived"] = bool(archived)
        page["version"] = int(page.get("version") or 1) + 1
        page["updated_at"] = _now().isoformat()
        await self._write_page(page)

        idx = await self._load_index()
        new_idx = []
        found = False
        for r in idx:
            if r.get("id") == page_id:
                new_idx.append(self._index_row(page))
                found = True
            else:
                new_idx.append(r)
        if not found:
            new_idx.append(self._index_row(page))
        await self._save_index(new_idx)
        return page

    async def append(
        self,
        page_id: str,
        text: str,
        *,
        heading: str = "",
        changelog: str = "",
    ) -> dict[str, Any] | None:
        page = await self._load_page(page_id)
        if not page:
            return None
        block = (text or "").strip()
        if not block:
            raise ValueError("append text required")
        if heading.strip():
            block = f"\n\n## {heading.strip()}\n\n{block}"
        else:
            block = "\n\n" + block
        return await self.update(
            page_id,
            content=(page.get("content") or "") + block,
            changelog=changelog or "append",
        )

    async def delete(self, page_id: str) -> bool:
        path = self._page_path(page_id)
        if path.exists():
            path.unlink()
        idx = await self._load_index()
        new_idx = [r for r in idx if r.get("id") != page_id]
        if len(new_idx) == len(idx) and not path.exists():
            return False
        await self._save_index(new_idx)
        return True

    @staticmethod
    def _infer_prefer_collections(query: str, intent_text: str = "") -> list[str]:
        """Soft boost collections by intent (does not hard-filter)."""
        blob = f"{query or ''} {intent_text or ''}".lower()
        prefer: list[str] = []
        product_signals = (
            "产品",
            "商品",
            "识图",
            "电商",
            "爆款",
            "主图",
            "上传的产品",
            "阶段1",
            "产品辨识",
            "uploads/",
            "图片:",
            "image:",
        )
        if any(s.lower() in blob for s in product_signals):
            prefer.extend(["sop", "product", "handbook"])
        if any(s in blob for s in ("提示词", "prompt", "模板", "文案规范")):
            prefer.extend(["reference", "handbook"])
        if any(s in blob for s in ("红线", "合规", "禁止", "错误规制", "手册")):
            prefer.append("handbook")
        # de-dupe preserve order
        out: list[str] = []
        seen: set[str] = set()
        for c in prefer:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out

    def _score(
        self,
        page: dict[str, Any],
        q_tokens: set[str],
        query: str,
        *,
        prefer_collections: list[str] | None = None,
    ) -> float:
        title = str(page.get("title") or "")
        content = str(page.get("content") or "")
        tags = [str(t) for t in (page.get("tags") or [])]
        coll = (page.get("collection") or "default").strip() or "default"
        blob = f"{title} {' '.join(tags)} {content} {coll}"
        tokens = _tokenize(blob)
        score = 0.0
        for t in q_tokens & tokens:
            score += 2.0 if len(t) >= 2 else 0.35
        q_low = query.lower().strip()
        if q_low and q_low in title.lower():
            score += 5.0
        if q_low and q_low in content.lower():
            score += 3.0
        for tag in tags:
            if tag.lower() in q_low or any(tag.lower() in qt for qt in q_tokens if len(qt) >= 2):
                score += 2.5
        # collection name mentioned in query
        if coll != "default" and coll.lower() in q_low:
            score += 4.0
        # soft prefer (product → sop first, not reference noise)
        prefs = prefer_collections or []
        if prefs and coll in prefs:
            score += 6.0 + max(0, 3 - prefs.index(coll)) * 1.5
        # slight demote pure default when we have a strong topic prefer list
        if prefs and coll == "default" and any(p != "default" for p in prefs):
            score -= 0.5
        if page.get("pinned"):
            score += 1.0
        # recency mild
        try:
            updated = datetime.fromisoformat(page.get("updated_at", ""))
            age_days = max(0.0, (_now() - updated).total_seconds() / 86400.0)
            score += max(0.0, 1.0 - min(age_days, 90.0) / 90.0) * 0.5
        except Exception:
            pass
        return score

    async def search(
        self,
        query: str,
        *,
        collection: str | None = None,
        limit: int = 5,
        prefer_collections: list[str] | None = None,
        intent_text: str = "",
    ) -> list[dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return await self.list_pages(collection=collection, limit=limit)

        prefs = prefer_collections
        if prefs is None:
            prefs = self._infer_prefer_collections(q, intent_text)

        q_tokens = _tokenize(q)
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in await self._load_index():
            if row.get("archived"):
                continue
            if collection and (row.get("collection") or "default") != collection:
                continue
            page = await self._load_page(row["id"])
            if not page:
                continue
            s = self._score(page, q_tokens, q, prefer_collections=prefs)
            if s >= _MIN_MATCH:
                scored.append((s, page))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for s, page in scored[:limit]:
            item = dict(page)
            item["score"] = round(s, 2)
            item.pop("versions", None)
            content = page.get("content") or ""
            coll = (page.get("collection") or "default").strip() or "default"
            # SOP / handbook get a longer snippet for multi-stage procedures
            snip_len = 520 if coll in ("sop", "handbook", "product") else 400
            item["snippet"] = content[:snip_len] + ("…" if len(content) > snip_len else "")
            out.append(item)
        return out

    async def context_snippet(
        self,
        query: str,
        *,
        limit: int = 4,
        max_chars: int = 2500,
        intent_text: str = "",
    ) -> str:
        """Matched wiki pages for system prompt (not full dump)."""
        prefs = self._infer_prefer_collections(query, intent_text)
        hits = await self.search(
            query,
            limit=limit,
            prefer_collections=prefs,
            intent_text=intent_text,
        )
        if not hits and not (query or "").strip():
            return ""
        if not hits:
            pinned = [
                r
                for r in await self._load_index()
                if r.get("pinned") and not r.get("archived")
            ][:2]
            for r in pinned:
                p = await self._load_page(r["id"])
                if p:
                    hits.append(p)

        if not hits:
            return ""

        lines = ["Knowledge base (wiki pages, matched only):"]
        if prefs:
            lines.append(f"(prefer collections: {', '.join(prefs)})")
        used = 0
        count = 0
        budget = max(400, int(max_chars))
        for h in hits:
            title = h.get("title") or h.get("id")
            coll = (h.get("collection") or "default").strip() or "default"
            body = (h.get("snippet") or h.get("content") or "").strip()
            max_body = 480 if coll in ("sop", "handbook", "product") else 360
            if len(body) > max_body:
                body = body[:max_body] + "…"
            score = h.get("score")
            score_s = f" score={score}" if score is not None else ""
            line = f"- [[{title}]] coll={coll}{score_s} {body}"
            if used + len(line) + 1 > budget and count > 0:
                break
            lines.append(line)
            used += len(line) + 1
            count += 1
        if count == 0:
            return ""
        lines.append(
            "Use kb tool (search/get; optional collection=) for full pages. "
            "Do not invent steps missing from snippets — get the page first."
        )
        return "\n".join(lines)

    async def ensure_seed(self) -> None:
        """Create a starter page if KB is empty."""
        rows = await self._load_index()
        if rows:
            return
        await self.create(
            title="知识库使用说明",
            collection="default",
            tags=["kb", "wiki", "指南"],
            pinned=True,
            content=(
                "# 知识库（Wiki）使用说明\n\n"
                "这里是可读写的 Wiki 页面，与「长期记忆」不同：\n\n"
                "- **记忆**：短偏好/规则，对话匹配注入\n"
                "- **知识库**：成页文档，可建页/改页/检索/引用\n\n"
                "## 给 Agent\n\n"
                "- 查资料：`kb` action=search / get\n"
                "- 写资料：create_page / update_page / append\n"
                "- 长文档请写知识库，不要塞进 memory\n\n"
                "## 前端\n\n"
                "设定 → 知识库：新建、编辑、搜索页面。\n"
            ),
        )


_store: KnowledgeStore | None = None


def get_knowledge_store() -> KnowledgeStore:
    global _store
    if _store is None:
        _store = KnowledgeStore()
    return _store
