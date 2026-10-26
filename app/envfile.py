"""Read / surgically update .env without touching unrelated keys or comments."""

from __future__ import annotations

from pathlib import Path


def env_path() -> Path:
    from app.config import PROJECT_ROOT

    return Path(PROJECT_ROOT) / ".env"


def parse_env(path: Path | None = None) -> dict[str, str]:
    p = path or env_path()
    out: dict[str, str] = {}
    if not p.is_file():
        return out
    try:
        text = p.read_text(encoding="utf-8-sig")
    except OSError:
        return out
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        key = k.strip()
        if key:
            out[key] = v.strip()
    return out


def upsert_env(updates: dict[str, str], path: Path | None = None) -> list[str]:
    """Replace existing keys in place; append any missing. Returns keys written."""
    p = path or env_path()
    wanted = {str(k).strip(): _one_line(v) for k, v in updates.items() if str(k).strip()}
    if not wanted:
        return []
    raw = ""
    if p.is_file():
        try:
            raw = p.read_text(encoding="utf-8-sig")
        except OSError:
            raw = ""
    lines = raw.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k = s.split("=", 1)[0].strip()
            if k in wanted:
                out.append(f"{k}={wanted[k]}")
                seen.add(k)
                continue
        out.append(line)
    missing = [k for k in wanted if k not in seen]
    if missing:
        if out and out[-1].strip():
            out.append("")
        for k in missing:
            out.append(f"{k}={wanted[k]}")
            seen.add(k)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    return list(wanted)


def _one_line(value: object) -> str:
    text = str(value if value is not None else "")
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ").strip()
