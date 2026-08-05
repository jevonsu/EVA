"""Helpers: detect vision-capable main LLM and build multimodal chat content."""

from __future__ import annotations

import base64
import logging
import re
from io import BytesIO
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_IMAGE_EXT = re.compile(r"\.(png|jpe?g|gif|webp|bmp|jfif)$", re.I)
_PATH_IN_TEXT = re.compile(
    r"(?:uploads|images|workspace)/[\w./\\-]+\.(?:png|jpe?g|gif|webp|bmp|jfif)",
    re.I,
)
_BULLET_IMAGE = re.compile(
    r"^[-*]\s*(?:图片|image)\s*[:：]\s*(.+)$",
    re.I,
)


def main_llm_supports_vision(
    *,
    model: str = "",
    base_url: str = "",
    name: str = "",
) -> bool:
    from app.services.credentials import looks_like_vision_model

    return looks_like_vision_model(model or "", base_url=base_url or "", name=name or "")


def extract_image_paths_from_message(text: str, *, max_paths: int = 6) -> list[str]:
    """Collect workspace-relative image paths mentioned in a user message."""
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        p = (raw or "").strip().strip("\"'`").replace("\\", "/")
        while p.startswith("./"):
            p = p[2:]
        if p.lower().startswith("workspace/"):
            p = p[len("workspace/") :]
        p = p.lstrip("/")
        if not p or ".." in p.split("/"):
            return
        if not _IMAGE_EXT.search(p):
            return
        key = p.lower()
        if key in seen:
            return
        seen.add(key)
        found.append(p)

    for line in text.splitlines():
        m = _BULLET_IMAGE.match(line.strip())
        if m:
            _add(m.group(1))
    for m in _PATH_IN_TEXT.finditer(text.replace("\\", "/")):
        _add(m.group(0))
    return found[:max_paths]


def _compress_to_jpeg(img_path: Path, max_dim: int = 1280, quality: int = 80) -> bytes:
    from PIL import Image

    img = Image.open(img_path)
    w, h = img.size
    if max(w, h) > max_dim:
        ratio = max_dim / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def resolve_workspace_image(rel: str) -> Path | None:
    from app.tools.safety import get_workspace_root, resolve_workspace_path

    p = resolve_workspace_path(rel)
    if p is not None and p.is_file():
        return p
    # basename under uploads/
    root = get_workspace_root()
    name = Path(rel).name
    if name and (root / "uploads").is_dir():
        for cand in (root / "uploads").rglob(name):
            if cand.is_file():
                return cand
    return None


def build_user_content_with_images(
    text: str,
    *,
    max_images: int = 4,
    force_paths: list[str] | None = None,
) -> tuple[str | list[dict[str, Any]], list[str]]:
    """Return (message content for chat API, resolved relative paths attached).

    If images are found and readable, content is a multimodal list; otherwise plain text.
    """
    paths = list(force_paths or [])
    if not paths:
        paths = extract_image_paths_from_message(text)
    if not paths:
        return text, []

    parts: list[dict[str, Any]] = [{"type": "text", "text": text or "(image)"}]
    attached: list[str] = []
    for rel in paths[:max_images]:
        fp = resolve_workspace_image(rel)
        if fp is None:
            logger.warning("Vision attach skip missing file: %s", rel)
            continue
        try:
            data = _compress_to_jpeg(fp)
            data_uri = "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": data_uri, "detail": "auto"},
                }
            )
            attached.append(rel.replace("\\", "/"))
        except Exception:
            logger.exception("Vision attach failed for %s", rel)

    if len(parts) == 1:
        return text, []
    return parts, attached
