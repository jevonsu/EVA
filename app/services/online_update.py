"""Online program update from a private GitHub repo (source tree or frozen zip)."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("app.services.online_update")

DEFAULT_REPO = "jevonsu/EVA"
UA = "Eva-updater"
KEEP_DIRS = {"data", "workspace", ".venv", "venv", "env", ".git"}
KEEP_FILES = {".env", ".env.local"}
SKIP_COPY = {"tests", "scripts"}
DROP_LEFTOVER = ("tests", "scripts", "publish-github.bat")
ASSET_NAME = "EVA-update.zip"
CREATE_NO_WINDOW = 0x08000000


def _runtime_root() -> Path:
    from app.config import PROJECT_ROOT

    return Path(PROJECT_ROOT)


def _data_dir() -> Path:
    try:
        from app.config import get_settings

        p = Path(get_settings().data_dir)
        if not p.is_absolute():
            p = _runtime_root() / p
        return p
    except Exception:
        return _runtime_root() / "data"


def _state_path() -> Path:
    return _data_dir() / "update_state.json"


def _channel_path() -> Path:
    return _data_dir() / "update_channel.json"


def _pending_dir() -> Path:
    d = _data_dir() / "updates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pending_zip() -> Path:
    return _pending_dir() / "pending.zip"


def parse_github_repo(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if raw.endswith(".git"):
        raw = raw[:-4]
    if "github.com:" in raw:
        raw = raw.split("github.com:", 1)[1]
    elif "github.com/" in raw:
        raw = raw.split("github.com/", 1)[1]
    raw = raw.strip().strip("/")
    if raw.count("/") != 1:
        return ""
    owner, name = raw.split("/", 1)
    if not owner or not name:
        return ""
    return f"{owner}/{name}"


def _git_origin_repo(root: Path | None = None) -> str:
    cwd = str(root or _runtime_root())
    try:
        proc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=8,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    return parse_github_repo(proc.stdout.strip())


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_version_file(root: Path | None = None) -> dict[str, Any]:
    return _read_json((root or _runtime_root()) / "version.json")


def configured_repo() -> str:
    env = (os.environ.get("EVA_UPDATE_REPO") or "").strip()
    parsed = parse_github_repo(env) if env else ""
    if parsed:
        return parsed
    if "/" in env and env.count("/") == 1:
        return env
    ch = load_channel()
    repo = parse_github_repo(str(ch.get("repo") or "")) or str(ch.get("repo") or "").strip()
    if repo.count("/") == 1:
        return repo
    ver = load_version_file()
    repo = parse_github_repo(str(ver.get("repo") or "")) or str(ver.get("repo") or "").strip()
    if repo.count("/") == 1:
        return repo
    origin = _git_origin_repo()
    if origin:
        return origin
    return DEFAULT_REPO


def load_channel() -> dict[str, Any]:
    return _read_json(_channel_path())


def save_channel(*, repo: str | None = None, token: str | None = None) -> dict[str, Any]:
    cur = load_channel()
    if repo is not None:
        cleaned = parse_github_repo(repo) or repo.strip()
        cur["repo"] = cleaned
    if token is not None:
        tok = token.strip()
        if tok:
            cur["token"] = tok
        elif "token" in cur and tok == "" and token == "":
            # explicit empty string from the form means keep existing unless caller
            # sent a single space to clear — keep existing on blank.
            pass
    path = _channel_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cur


def channel_public() -> dict[str, Any]:
    ch = load_channel()
    return {
        "repo": configured_repo(),
        "has_token": bool(str(ch.get("token") or "").strip()),
    }


def _git_credential_token() -> str:
    try:
        proc = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True,
            text=True,
            timeout=8,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    for line in (proc.stdout or "").splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    return ""


def _gh_cli_token() -> str:
    try:
        proc = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=8,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def resolve_token(explicit: str = "", *, interactive: bool = True) -> str:
    tok = (explicit or "").strip()
    if tok:
        return tok
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "EVA_GITHUB_TOKEN"):
        tok = (os.environ.get(key) or "").strip()
        if tok:
            return tok
    tok = str(load_channel().get("token") or "").strip()
    if tok:
        return tok
    tok = _gh_cli_token()
    if tok:
        return tok
    if not interactive:
        return ""
    return _git_credential_token()


def local_info() -> dict[str, Any]:
    root = _runtime_root()
    version = ""
    build = ""
    vfile = load_version_file(root)
    version = str(vfile.get("version") or "")
    build = str(vfile.get("build") or "")
    if not version:
        try:
            from app import __version__

            version = str(__version__)
        except Exception:
            version = "0.0.0"
    if not build:
        stamp = root / "eva_build.txt"
        if stamp.is_file():
            build = stamp.read_text(encoding="utf-8", errors="replace").strip()
    st = _read_state()
    return {
        "version": version,
        "build": build,
        "tag": str(st.get("applied_tag") or ""),
        "frozen": bool(getattr(sys, "frozen", False)),
        "root": str(root),
        "repo": configured_repo(),
    }


def _read_state() -> dict[str, Any]:
    return _read_json(_state_path())


def _write_state(patch: dict[str, Any]) -> None:
    cur = _read_state()
    cur.update(patch)
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _headers(*, token: str = "", interactive: bool = True) -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "User-Agent": UA}
    tok = resolve_token(token, interactive=interactive)
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _api(path: str, *, token: str = "", interactive: bool = True) -> tuple[int, Any]:
    import httpx

    repo = configured_repo()
    url = path if path.startswith("http") else f"https://api.github.com/repos/{repo}{path}"
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        r = client.get(url, headers=_headers(token=token, interactive=interactive))
    try:
        data = r.json()
    except Exception:
        data = {"message": (r.text or "")[:240]}
    return r.status_code, data


def _parse_ver(raw: str) -> tuple[int, int, int]:
    s = (raw or "").strip().lstrip("vV")
    nums = re.findall(r"\d+", s)
    parts = [int(x) for x in nums[:3]]
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def _is_newer(remote: dict[str, Any], local: dict[str, Any]) -> bool:
    tag = str(remote.get("tag") or "")
    applied = str(local.get("tag") or "")
    if tag and applied and tag == applied:
        return False
    rv = _parse_ver(str(remote.get("version") or tag))
    lv = _parse_ver(str(local.get("version") or ""))
    if rv != (0, 0, 0) and lv != (0, 0, 0) and rv != lv:
        return rv > lv
    if tag and applied and tag != applied:
        return True
    pub = str(remote.get("published_at") or "")
    build = str(local.get("build") or "")
    if pub and build:
        try:
            rp = pub.replace("Z", "+00:00")
            rdt = datetime.fromisoformat(rp)
            bs = build.replace("eva-update", "").strip()
            ldt = datetime.strptime(bs[:16], "%Y-%m-%d %H:%M")
            ldt = ldt.replace(tzinfo=timezone.utc)
            return rdt > ldt
        except Exception:
            return tag != build
    return bool(tag) and tag.lstrip("vV") != str(local.get("version") or "").lstrip("vV")


def _auth_error(status: int, data: Any) -> str:
    msg = ""
    if isinstance(data, dict):
        msg = str(data.get("message") or "")
    if status in (401, 403):
        return (
            "GitHub 拒绝访问（私有仓库需要 Token）。"
            "在设定 → 更新填写，或设置环境变量 GITHUB_TOKEN。"
            + (f" {msg}" if msg else "")
        )
    if status == 404:
        return (
            f"GitHub 上还没有发布（{configured_repo()}）。"
            "预览：python scripts/publish_github.py ；确认后再 --publish。"
        )
    return f"GitHub 检查失败 HTTP {status}" + (f"：{msg}" if msg else "")


def fetch_latest_release(*, token: str = "", interactive: bool = True) -> dict[str, Any]:
    repo = configured_repo()
    status, data = _api("/releases/latest", token=token, interactive=interactive)
    if status == 404:
        tstatus, tags = _api("/tags?per_page=1", token=token, interactive=interactive)
        if tstatus >= 400:
            raise RuntimeError(_auth_error(tstatus, tags))
        if not isinstance(tags, list) or not tags:
            raise RuntimeError(
                f"GitHub 上还没有发布（{repo}）。"
                "预览：python scripts/publish_github.py ；确认后再 --publish。"
            )
        tag = str((tags[0] or {}).get("name") or "")
        if not tag:
            raise RuntimeError("GitHub 标签异常")
        return {
            "tag": tag,
            "name": tag,
            "notes": "",
            "published_at": "",
            "download_url": f"https://api.github.com/repos/{repo}/zipball/{tag}",
            "size": 0,
            "html_url": f"https://github.com/{repo}/tree/{tag}",
            "version": tag.lstrip("vV"),
            "source": "tag",
        }
    if status >= 400:
        raise RuntimeError(_auth_error(status, data))
    if not isinstance(data, dict):
        raise RuntimeError("GitHub 返回异常")
    tag = str(data.get("tag_name") or "")
    assets = data.get("assets") if isinstance(data.get("assets"), list) else []
    asset_url = ""
    size = 0
    for a in assets:
        if not isinstance(a, dict):
            continue
        name = str(a.get("name") or "")
        url = str(a.get("browser_download_url") or "")
        if not url:
            continue
        if name == ASSET_NAME or name.endswith(".zip"):
            asset_url = url
            size = int(a.get("size") or 0)
            if name == ASSET_NAME:
                break
    zipball = str(data.get("zipball_url") or "")
    download = asset_url or zipball
    if not download:
        if not tag:
            raise RuntimeError("最新发布没有下载地址")
        download = f"https://api.github.com/repos/{repo}/zipball/{tag}"
    return {
        "tag": tag,
        "name": str(data.get("name") or tag),
        "notes": str(data.get("body") or ""),
        "published_at": str(data.get("published_at") or ""),
        "download_url": download,
        "size": size,
        "html_url": str(data.get("html_url") or ""),
        "version": tag.lstrip("vV"),
        "source": "release",
    }


def check(*, force: bool = False, token: str = "", interactive: bool = True) -> dict[str, Any]:
    local = local_info()
    st = _read_state()
    now = time.time()
    last = float(st.get("checked_at") or 0)
    cached = st.get("latest") if isinstance(st.get("latest"), dict) else None
    if not force and cached and (now - last) < 3600 and st.get("latest_ok"):
        remote = cached
    else:
        remote = fetch_latest_release(token=token, interactive=interactive)
        _write_state(
            {
                "checked_at": now,
                "latest": remote,
                "latest_ok": True,
            }
        )
    newer = _is_newer(remote, local)
    return {
        "ok": True,
        "repo": configured_repo(),
        "local": local,
        "remote": remote,
        "newer": newer,
        "pending": pending_zip().is_file(),
        "channel": channel_public(),
    }


def due_for_daily_check() -> bool:
    st = _read_state()
    last = float(st.get("checked_at") or 0)
    return (time.time() - last) >= 86400


def download_to_pending(url: str, *, token: str = "") -> Path:
    import httpx

    dest = pending_zip()
    tmp = dest.with_suffix(".part")
    headers = _headers(token=token)
    if "api.github.com" in url and "zipball" in url:
        headers["Accept"] = "application/vnd.github+json"
    else:
        headers["Accept"] = "application/octet-stream"
    with httpx.Client(timeout=None, follow_redirects=True) as client:
        with client.stream("GET", url, headers=headers) as r:
            if r.status_code >= 400:
                raise RuntimeError(f"下载失败 HTTP {r.status_code}")
            with tmp.open("wb") as fh:
                for chunk in r.iter_bytes(1024 * 256):
                    fh.write(chunk)
    tmp.replace(dest)
    return dest


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in Path(name).parts:
            continue
        target = dest / name
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, target.open("wb") as out:
            shutil.copyfileobj(src, out)


def _exe_locked(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        fd = os.open(str(path), os.O_RDWR)
        os.close(fd)
        return False
    except OSError:
        return True


def _looks_frozen_payload(src: Path) -> bool:
    return (src / "EVA.exe").is_file() and (src / "_internal").is_dir()


def _find_payload_root(extracted: Path) -> Path:
    if _looks_frozen_payload(extracted) or (extracted / "run.py").is_file() or (extracted / "app").is_dir():
        return extracted
    subs = [p for p in extracted.iterdir() if p.is_dir()]
    if len(subs) == 1:
        return subs[0]
    for p in subs:
        if _looks_frozen_payload(p) or (p / "run.py").is_file() or (p / "app").is_dir():
            return p
    return extracted


def _replace_dir(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".new")
    old = dest.with_name(dest.name + ".old")
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(src, tmp, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))
    try:
        if old.exists():
            shutil.rmtree(old, ignore_errors=True)
        if dest.exists():
            dest.rename(old)
        tmp.rename(dest)
        shutil.rmtree(old, ignore_errors=True)
    except OSError:
        _copy_tree_over(tmp, dest)
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(old, ignore_errors=True)


def _copy_tree_over(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dest / item.name
        if item.is_dir():
            _copy_tree_over(item, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def apply_source_tree(src: Path, dest: Path) -> list[str]:
    """Overlay program files. Never touch data/, workspace/, .env, .venv."""
    src = _find_payload_root(src)
    if not (src / "app").is_dir() and not (src / "run.py").is_file():
        raise RuntimeError("更新包不是 Eva 源码（缺少 app/ 或 run.py）")
    changed: list[str] = []
    for item in src.iterdir():
        name = item.name
        if name in KEEP_DIRS or name in KEEP_FILES or name in SKIP_COPY:
            continue
        if name.startswith(".git"):
            continue
        target = dest / name
        if name == "skills" and item.is_dir():
            dest_skills = dest / "skills"
            dest_skills.mkdir(parents=True, exist_ok=True)
            for pack in item.iterdir():
                if not pack.is_dir():
                    continue
                pack_dest = dest_skills / pack.name
                if pack_dest.exists():
                    shutil.rmtree(pack_dest, ignore_errors=True)
                shutil.copytree(
                    pack,
                    pack_dest,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
                changed.append(f"skills/{pack.name}")
            continue
        if item.is_dir():
            _replace_dir(item, target)
            changed.append(name + "/")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            changed.append(name)
    app_dir = dest / "app"
    if app_dir.is_dir():
        for pyc in app_dir.rglob("__pycache__"):
            shutil.rmtree(pyc, ignore_errors=True)
    src_names = {p.name for p in src.iterdir()}
    for leftover in DROP_LEFTOVER:
        p = dest / leftover
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            changed.append(f"-{leftover}/")
        elif p.is_file():
            p.unlink(missing_ok=True)
            changed.append(f"-{leftover}")
    for bat in dest.glob("*.bat"):
        if bat.name.lower() in {"run.bat", "start.bat"}:
            continue
        if bat.name not in src_names:
            bat.unlink(missing_ok=True)
            changed.append(f"-{bat.name}")
    return changed


def apply_extracted(src: Path, dest: Path) -> None:
    exe = src / "EVA.exe"
    internal = src / "_internal"
    if not exe.is_file() or not internal.is_dir():
        raise RuntimeError("更新包不完整（缺少 EVA.exe 或 _internal）")
    dest_exe = dest / "EVA.exe"
    if _exe_locked(dest_exe):
        raise RuntimeError("EVA.exe 正在运行。请先在启动器点「停止」，再更新。")

    shutil.copy2(exe, dest / "EVA.exe")
    dest_internal = dest / "_internal"
    tmp_internal = dest / "_internal.new"
    old_internal = dest / "_internal.old"
    if tmp_internal.exists():
        shutil.rmtree(tmp_internal, ignore_errors=True)
    shutil.copytree(internal, tmp_internal)
    if old_internal.exists():
        shutil.rmtree(old_internal, ignore_errors=True)
    if dest_internal.exists():
        dest_internal.rename(old_internal)
    tmp_internal.rename(dest_internal)
    shutil.rmtree(old_internal, ignore_errors=True)

    src_skills = src / "skills"
    if src_skills.is_dir():
        dest_skills = dest / "skills"
        dest_skills.mkdir(parents=True, exist_ok=True)
        try:
            from app.tools.protection import PROTECTED_SKILLS

            keep = set(PROTECTED_SKILLS)
        except Exception:
            keep = {
                "reload_runtime",
                "list_api_models",
                "server_health_check",
                "terminal",
                "document",
            }
        for name in keep:
            pack = src_skills / name
            if not pack.is_dir():
                continue
            target = dest_skills / name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(pack, target)

    for name in ("version.json", "eva_build.txt", "使用说明.txt"):
        p = src / name
        if p.is_file():
            shutil.copy2(p, dest / name)


def _maybe_install_requirements(dest: Path) -> str:
    req = dest / "requirements.txt"
    if sys.platform == "win32":
        py = dest / ".venv" / "Scripts" / "python.exe"
    else:
        py = dest / ".venv" / "bin" / "python"
    if not req.is_file() or not py.is_file():
        return ""
    kwargs: dict[str, Any] = {
        "args": [str(py), "-m", "pip", "install", "-r", str(req)],
        "cwd": str(dest),
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": 180,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    try:
        proc = subprocess.run(**kwargs)
    except (OSError, subprocess.TimeoutExpired) as extra:
        return f"依赖安装未完成：{extra}"
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = err[-1] if err else f"exit {proc.returncode}"
        return f"依赖安装未完成：{tail[:200]}"
    return "已按 requirements.txt 安装依赖"


def apply_pending_zip() -> dict[str, Any]:
    zpath = pending_zip()
    if not zpath.is_file():
        raise RuntimeError("没有已下载的更新包")
    dest = _runtime_root()
    tmp = Path(tempfile.mkdtemp(prefix="eva-upd-"))
    try:
        with zipfile.ZipFile(zpath, "r") as zf:
            _safe_extract(zf, tmp)
        src = _find_payload_root(tmp)
        if _looks_frozen_payload(src):
            apply_extracted(src, dest)
            changed = ["EVA.exe", "_internal/"]
            kind = "frozen"
        else:
            changed = apply_source_tree(src, dest)
            kind = "source"
        pip_msg = _maybe_install_requirements(dest) if kind == "source" else ""
        zpath.unlink(missing_ok=True)
        info = local_info()
        st = _read_state()
        tag = str((st.get("latest") or {}).get("tag") or "")
        _write_state({"applied_tag": tag, "applied_at": time.time()})
        info = local_info()
        return {
            "ok": True,
            "applied_tag": tag,
            "root": str(dest),
            "local": info,
            "changed": changed,
            "kind": kind,
            "pip": pip_msg,
            "kept": sorted(KEEP_DIRS | KEEP_FILES),
            "restart_required": True,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def download_and_stage(*, force: bool = False, token: str = "") -> dict[str, Any]:
    status = check(force=True, token=token)
    if not status.get("newer") and not force:
        return {**status, "downloaded": False, "message": "已是最新"}
    url = str((status.get("remote") or {}).get("download_url") or "")
    if not url:
        raise RuntimeError("没有下载地址")
    path = download_to_pending(url, token=token)
    return {
        **status,
        "downloaded": True,
        "pending": True,
        "path": str(path),
        "message": "已下载更新包。请停止服务后在启动器点「更新」，或关闭启动器再打开后点「更新」。",
    }


def apply_now(*, force: bool = False, token: str = "") -> dict[str, Any]:
    pending = pending_zip()
    if not pending.is_file():
        staged = download_and_stage(force=force, token=token)
        if not staged.get("downloaded") and not pending.is_file():
            return staged
    return apply_pending_zip()
