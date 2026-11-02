"""Path safety utilities for tools and skills.

Canonical workspace root is always:
  <project_root>/workspace

Never depends on process CWD (avoids accidental nested workspace/workspace).
User paths are treated as relative to that root; a leading ``workspace/`` is stripped.
"""

from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    """Writable project root."""
    from app.config import PROJECT_ROOT

    return Path(PROJECT_ROOT)


def get_workspace_root() -> Path:
    """Absolute path to the agent workspace directory (created if missing).

    After linking to Agent Hub this may be the shared office workspace,
    not this Eva's private folder. Memory / KB / skills stay local.
    """
    try:
        from app.services.workspace_bind import resolved_root

        root = resolved_root()
    except Exception:
        root = (project_root() / "workspace").resolve()
    root.mkdir(parents=True, exist_ok=True)
    # Best-effort: keep canonical buckets present (P1). Avoid recursion via mkdir only.
    for name in (
        "uploads",
        "docs",
        "exports",
        "scratch",
        "images",
        "videos",
        "skills",
    ):
        try:
            (root / name).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return root



# Agent may create/write only under these top-level buckets (P1).
WRITE_BUCKETS: frozenset[str] = frozenset(
    {
        "uploads",
        "docs",
        "exports",
        "scratch",
        "images",
        "videos",
        "skills",
    }
)

# Preferred defaults for new agent-created files (P0 routing).
DEFAULT_WRITE_BUCKET = "scratch"
DEFAULT_EXPORT_BUCKET = "exports"


def ensure_workspace_buckets(root: Path | None = None) -> Path:
    """Create canonical write buckets under the workspace root."""
    base = (root or get_workspace_root()).resolve()
    for name in sorted(WRITE_BUCKETS):
        (base / name).mkdir(parents=True, exist_ok=True)
    return base


def enforce_write_relpath(
    user_path: str | None,
    *,
    rewrite: bool = True,
) -> tuple[str | None, str | None, bool]:
    """Normalize + enforce write whitelist.

    Returns ``(relpath, error, rewritten)``.
    - Bare root files (``notes.md``) → ``scratch/notes.md`` when rewrite=True.
    - Unknown first segment (``reports/a.docx``) → ``scratch/reports/a.docx``.
    - ``.`` / empty / directory-only → error.
    """
    rel = normalize_workspace_relpath(user_path)
    if not rel or rel in (".", "./"):
        return None, "write 需要具体文件 path（禁止写工作区根目录）", False
    parts = [p for p in rel.split("/") if p and p != "."]
    if not parts or any(p == ".." for p in parts):
        return None, f"非法路径: {rel}", False
    rewritten = False
    if len(parts) == 1:
        if rewrite:
            rel = f"{DEFAULT_WRITE_BUCKET}/{parts[0]}"
            rewritten = True
        else:
            buckets = "/".join(sorted(WRITE_BUCKETS))
            return None, (
                f"禁止在工作区根目录创建文件：{rel}。"
                f"请写到 {buckets}/ 下，默认 scratch/ 或 exports/。"
            ), False
    else:
        top = parts[0].lower()
        if top not in WRITE_BUCKETS:
            if rewrite:
                rel = f"{DEFAULT_WRITE_BUCKET}/{'/'.join(parts)}"
                rewritten = True
            else:
                return None, (
                    f"路径一级目录「{parts[0]}」不在白名单 "
                    f"{sorted(WRITE_BUCKETS)} 内。请改用 scratch/ 或 exports/，"
                    f"或 docs/images/videos/uploads/skills。"
                ), False
    return rel, None, rewritten


def normalize_workspace_relpath(user_path: str | None) -> str:
    """Normalize a user/LLM path to be relative to workspace root.

    Strips:
      - empty / "." / "workspace" → "."
      - leading ``workspace/`` (any case, repeated — fixes double nesting)
      - ``./`` prefixes
      - paths containing ``/workspace/`` (keep only the suffix)
      - backslashes → forward slashes
    """
    if user_path is None:
        return "."
    p = str(user_path).strip()
    if not p:
        return "."

    p = p.replace("\\", "/")

    lower = p.lower()
    marker = "/workspace/"
    if marker in lower:
        idx = lower.rfind(marker)
        p = p[idx + len(marker) :]
    elif lower.endswith("/workspace"):
        return "."

    while True:
        lower = p.lower()
        if lower in ("workspace", "./workspace", ".", "./", ""):
            return "."
        if lower.startswith("workspace/"):
            p = p[len("workspace/") :]
            continue
        if lower.startswith("./workspace/"):
            p = p[len("./workspace/") :]
            continue
        if p.startswith("./"):
            p = p[2:]
            continue
        break

    p = p.strip("/")
    if not p or p == ".":
        return "."

    while p.lower().startswith("workspace/"):
        p = p[len("workspace/") :].strip("/")
        if not p:
            return "."

    return p


def resolve_workspace_path(
    base_or_rel: Path | str | None = None,
    rel: str | None = None,
    *,
    base_dir: Path | None = None,
) -> Path | None:
    """Resolve a path under the workspace root; return None if outside.

    Call styles (all supported):

    1. New: ``resolve_workspace_path("uploads/a.jpg")``
    2. New: ``resolve_workspace_path("uploads/a.jpg", base_dir=root)``
    3. Legacy: ``resolve_workspace_path(root, "uploads/a.jpg")``
    """
    root: Path
    user_path: str

    if base_dir is not None:
        root = base_dir.resolve()
        user_path = str(base_or_rel) if base_or_rel is not None else (rel or ".")
    elif isinstance(base_or_rel, Path) and rel is not None:
        # legacy (base_dir, user_path)
        root = base_or_rel.resolve()
        user_path = str(rel)
    elif isinstance(base_or_rel, Path) and rel is None:
        root = get_workspace_root()
        try:
            resolved = base_or_rel.resolve()
            resolved.relative_to(root)
            return resolved
        except ValueError:
            return None
    else:
        root = get_workspace_root()
        user_path = str(base_or_rel) if base_or_rel is not None else "."

    norm = normalize_workspace_relpath(user_path)
    target = root if norm == "." else (root / norm).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    return target


def workspace_relpath(path: Path, *, base_dir: Path | None = None) -> str:
    """Return path relative to workspace root using forward slashes."""
    root = (base_dir or get_workspace_root()).resolve()
    try:
        s = str(path.resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)
    return "." if s in ("", ".") else s
