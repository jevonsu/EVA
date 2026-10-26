"""Persisted storage backend settings (local file — chicken-and-egg free)."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote_plus

from app.config import get_settings

logger = logging.getLogger("app.storage.settings")

BackendKind = Literal["sqlite", "postgresql", "mysql", "mariadb", "mssql"]

SUPPORTED_BACKENDS: tuple[str, ...] = (
    "sqlite",
    "postgresql",
    "mysql",
    "mariadb",
    "mssql",
)

_lock = threading.RLock()
_cached: StorageSettings | None = None


@dataclass
class StorageSettings:
    """User-selectable backend. Default: local SQLite under data/eva.db."""

    backend: BackendKind = "sqlite"
    # remote only
    host: str = "127.0.0.1"
    port: int = 0  # 0 → dialect default
    database: str = "eva"
    username: str = ""
    password: str = ""
    # optional extras
    ssl: bool = False
    # sqlite path relative to data_dir or absolute
    sqlite_path: str = "eva.db"
    # migration
    migrated_from_json: bool = False

    def dialect_default_port(self) -> int:
        if self.port and self.port > 0:
            return int(self.port)
        return {
            "postgresql": 5432,
            "mysql": 3306,
            "mariadb": 3306,
            "mssql": 1433,
            "sqlite": 0,
        }.get(self.backend, 0)

    def public_dict(self) -> dict[str, Any]:
        """Safe for API / UI (password masked)."""
        d = asdict(self)
        if d.get("password"):
            d["password"] = "********"
            d["password_set"] = True
        else:
            d["password_set"] = False
        d["port_effective"] = self.dialect_default_port()
        d["supported_backends"] = list(SUPPORTED_BACKENDS)
        return d

    def sqlalchemy_url(self) -> str:
        if self.backend == "sqlite":
            path = Path(self.sqlite_path)
            if not path.is_absolute():
                path = (get_settings().data_dir / path).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            # four slashes for absolute Windows/Unix paths
            return f"sqlite+pysqlite:///{path.as_posix()}"

        user = quote_plus(self.username or "")
        pwd = quote_plus(self.password or "")
        auth = f"{user}:{pwd}@" if (user or pwd) else ""
        host = (self.host or "127.0.0.1").strip()
        port = self.dialect_default_port()
        db = quote_plus(self.database or "eva")
        q = "?charset=utf8mb4" if self.backend in ("mysql", "mariadb") else ""
        if self.backend == "postgresql":
            # use psycopg (v3) driver
            return f"postgresql+psycopg://{auth}{host}:{port}/{db}"
        if self.backend in ("mysql", "mariadb"):
            return f"mysql+pymysql://{auth}{host}:{port}/{db}{q}"
        if self.backend == "mssql":
            # ODBC Driver 18 recommended; FreeTDS also possible
            odbc = quote_plus(
                f"DRIVER={{ODBC Driver 18 for SQL Server}};"
                f"SERVER={host},{port};DATABASE={self.database or 'eva'};"
                f"UID={self.username};PWD={self.password};"
                f"TrustServerCertificate=yes;"
                + ("Encrypt=yes;" if self.ssl else "Encrypt=no;")
            )
            return f"mssql+pyodbc:///?odbc_connect={odbc}"
        raise ValueError(f"Unsupported backend: {self.backend}")


def _path() -> Path:
    return get_settings().paths().root / "storage.json"


def default_storage_settings() -> StorageSettings:
    return StorageSettings()


def load_storage_settings() -> StorageSettings:
    p = _path()
    if not p.is_file():
        return default_storage_settings()
    try:
        raw = json.loads(p.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        logger.exception("Failed to load storage.json")
        return default_storage_settings()
    if not isinstance(raw, dict):
        return default_storage_settings()
    backend = str(raw.get("backend") or "sqlite").lower().strip()
    if backend not in SUPPORTED_BACKENDS:
        backend = "sqlite"
    return StorageSettings(
        backend=backend,  # type: ignore[arg-type]
        host=str(raw.get("host") or "127.0.0.1"),
        port=int(raw.get("port") or 0),
        database=str(raw.get("database") or "eva"),
        username=str(raw.get("username") or ""),
        password=str(raw.get("password") or ""),
        ssl=bool(raw.get("ssl")),
        sqlite_path=str(raw.get("sqlite_path") or "eva.db"),
        migrated_from_json=bool(raw.get("migrated_from_json")),
    )


def save_storage_settings(cfg: StorageSettings) -> StorageSettings:
    global _cached
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(cfg)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with _lock:
        _cached = cfg
    return cfg


def get_storage_settings(*, force: bool = False) -> StorageSettings:
    global _cached
    with _lock:
        if _cached is None or force:
            _cached = load_storage_settings()
        return _cached


def update_storage_settings(patch: dict[str, Any]) -> StorageSettings:
    """Merge patch into current settings. Password '********' keeps old."""
    cur = get_storage_settings(force=True)
    data = asdict(cur)
    for k, v in (patch or {}).items():
        if k not in data:
            continue
        if k == "password" and (v is None or v == "" or v == "********"):
            continue
        if k == "backend":
            v = str(v or "sqlite").lower().strip()
            if v not in SUPPORTED_BACKENDS:
                raise ValueError(f"unsupported backend: {v}")
        data[k] = v
    cfg = StorageSettings(**data)
    return save_storage_settings(cfg)
