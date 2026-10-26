"""Canonical layout under ``data/`` + one-shot migration from flat legacy paths.

Target layout::

    data/
      config.json                 # app runtime config (primary)
      auth/
        offline_grants.json
        auth.db                   # local AuthStore only if used
      sessions/                   # chat sessions
      memory/
        long_term.json
      tasks/
        tasks.json
      kb/
        index.json
        catalog.json
        pages/
      workflows/
        definitions/
        runs/
        removed_builtins.json
      webhooks/
        endpoints.json            # was data/webhooks.json
        sessions.json             # was data/webhook_sessions.json
      tools/
        meta_dynamic.json         # was data/tool_meta_dynamic.json
      cache/                      # runtime cache
      persona_packs/              # optional user persona packs
      logs/                       # optional runtime logs

Legacy root files are moved (not copied) on first startup when the new path
is missing. Existing new-layout installs are left untouched.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger("app.paths")


class DataPaths:
    """Resolved paths for one ``data_dir`` root."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

        # Config
        self.config_json = self.root / "config.json"
        self.storage_json = self.root / "storage.json"
        self.eva_db = self.root / "eva.db"

        # Auth
        self.auth_dir = self.root / "auth"
        self.auth_db = self.auth_dir / "auth.db"
        self.offline_grants = self.auth_dir / "offline_grants.json"
        self.hub_pairing = self.auth_dir / "hub_pairing.json"
        self.local_session = self.auth_dir / "local_session.enc"
        self.local_session_key = self.auth_dir / "local_session.key"
        self.instance_json = self.auth_dir / "instance.json"

        # Conversations & memory
        self.sessions_dir = self.root / "sessions"
        self.memory_dir = self.root / "memory"
        self.long_term_memory = self.memory_dir / "long_term.json"

        # Jobs
        self.tasks_dir = self.root / "tasks"
        self.tasks_json = self.tasks_dir / "tasks.json"

        # Knowledge
        self.kb_dir = self.root / "kb"
        self.kb_pages = self.kb_dir / "pages"
        self.kb_index = self.kb_dir / "index.json"
        self.kb_catalog = self.kb_dir / "catalog.json"

        # Workflows
        self.workflows_dir = self.root / "workflows"
        self.workflow_defs = self.workflows_dir / "definitions"
        self.workflow_runs = self.workflows_dir / "runs"
        self.workflow_removed_builtins = self.workflows_dir / "removed_builtins.json"

        # Webhooks (grouped)
        self.webhooks_dir = self.root / "webhooks"
        self.webhooks_endpoints = self.webhooks_dir / "endpoints.json"
        self.webhooks_sessions = self.webhooks_dir / "sessions.json"

        # Tool meta from create_tool
        self.tools_dir = self.root / "tools"
        self.tool_meta_dynamic = self.tools_dir / "meta_dynamic.json"
        self.capability_groups = self.tools_dir / "capability_groups.json"

        # Runtime cache (volatile)
        self.cache_dir = self.root / "cache"

        # Optional packs & logs
        self.persona_packs_dir = self.root / "persona_packs"
        self.logs_dir = self.root / "logs"

    def ensure(self) -> None:
        """Create directory tree and empty seed files; migrate legacy paths."""
        self.migrate_legacy()

        for d in (
            self.root,
            self.auth_dir,
            self.sessions_dir,
            self.memory_dir,
            self.tasks_dir,
            self.kb_dir,
            self.kb_pages,
            self.workflows_dir,
            self.workflow_defs,
            self.workflow_runs,
            self.webhooks_dir,
            self.tools_dir,
            self.cache_dir,
            self.persona_packs_dir,
            self.logs_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

        # Small empty seeds so first open never 404s on missing files
        _seed_json_file(self.long_term_memory, "[]")
        _seed_json_file(self.tasks_json, "[]")
        _seed_json_file(self.webhooks_endpoints, '{"endpoints": []}\n')
        _seed_json_file(self.webhooks_sessions, "{}\n")
        _seed_json_file(self.tool_meta_dynamic, "{}\n")
        _seed_json_file(self.kb_index, "[]\n")
        if not self.kb_catalog.exists():
            self.kb_catalog.write_text(
                '{\n  "collections": ["default", "sop", "product", "handbook", "daily", "reference"],\n'
                '  "hidden": []\n}\n',
                encoding="utf-8",
            )
        if not self.workflow_removed_builtins.exists():
            self.workflow_removed_builtins.write_text(
                '{\n  "ids": [],\n  "updated_at": null\n}\n',
                encoding="utf-8",
            )
        if not self.offline_grants.exists():
            self.offline_grants.write_text("{}\n", encoding="utf-8")

    def migrate_legacy(self) -> None:
        """Move flat / old paths into the grouped layout (idempotent)."""
        moves: list[tuple[Path, Path]] = [
            # Webhooks
            (self.root / "webhooks.json", self.webhooks_endpoints),
            (self.root / "webhook_sessions.json", self.webhooks_sessions),
            # Tool meta
            (self.root / "tool_meta_dynamic.json", self.tool_meta_dynamic),
            # Stray logs at data root
            (self.root / "eva.log", self.logs_dir / "eva.log"),
            (self.root / "_start_out.log", self.logs_dir / "_start_out.log"),
            (self.root / "_start_err.log", self.logs_dir / "_start_err.log"),
        ]
        for src, dst in moves:
            _migrate_path(src, dst)


def _seed_json_file(path: Path, content: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")


def _migrate_path(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if src.resolve() == dst.resolve():
        return
    if dst.exists():
        # New location already present — drop leftover legacy file/dir
        try:
            if src.is_dir():
                shutil.rmtree(src, ignore_errors=True)
            else:
                try:
                    src.unlink()
                except FileNotFoundError:
                    pass
            logger.info("data layout: removed legacy leftover %s (kept %s)", src, dst)
        except OSError as e:
            logger.warning("data layout: could not remove legacy %s: %s", src, e)
        return
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        logger.info("data layout: migrated %s → %s", src, dst)
    except OSError as e:
        logger.warning("data layout: migrate failed %s → %s: %s", src, dst, e)


_paths_cache: dict[str, DataPaths] = {}


def get_data_paths(root: Path | None = None) -> DataPaths:
    """Return cached DataPaths for the active data_dir (or given root)."""
    if root is None:
        from app.config import get_settings

        root = get_settings().data_dir
    key = str(Path(root).resolve())
    hit = _paths_cache.get(key)
    if hit is not None:
        return hit
    paths = DataPaths(Path(root))
    _paths_cache[key] = paths
    return paths
