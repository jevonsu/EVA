"""Business data storage: local SQLite (default) or remote SQL databases.

Kept out of the hot path for secrets/config (still data/config.json) and
offline auth (always local files).
"""

from __future__ import annotations

from app.storage.bootstrap import ensure_storage, reset_storage
from app.storage.settings import StorageSettings, get_storage_settings, save_storage_settings

__all__ = [
    "StorageSettings",
    "ensure_storage",
    "get_storage_settings",
    "reset_storage",
    "save_storage_settings",
]
