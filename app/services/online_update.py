"""Online program update from a private GitHub Release portable zip (EVA.exe)."""

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
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
_GIT_CANDIDATES = (
    r"C:\Program Files\Git\cmd\git.exe",
    r"C:\Program Files\Git\bin\git.exe",
    r"C:\Program Files (x86)\Git\cmd\git.exe",
)


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
    git = _git_executable()
    if not git:
        return ""
    cwd = str(root or _runtime_root())
    try:
        proc = subprocess.run(
            [git, "remote", "get-url", "origin"],
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


def _win_no_window() -> dict[str, Any]:
    if sys.platform != "win32":
        return {}
    return {"creationflags": CREATE_NO_WINDOW}


def _git_executable() -> str:
    found = shutil.which("git")
    if found:
        return found
    for raw in _GIT_CANDIDATES:
        p = Path(raw)
        if p.is_file():
            return str(p)
    return ""


def _dotenv_token(root: Path | None = None) -> str:
    path = (root or _runtime_root()) / ".env"
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    keys = ("GITHUB_TOKEN", "GH_TOKEN", "EVA_GITHUB_TOKEN")
    found: dict[str, str] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, val = s.split("=", 1)
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key in keys and val:
            found[key] = val
    for key in keys:
        if found.get(key):
            return found[key]
    return ""


def _httpx_client(**kwargs: Any):
    import httpx

    kwargs.setdefault("trust_env", False)
    kwargs.setdefault("follow_redirects", True)
    return httpx.Client(**kwargs)


def _git_credential_token(*, allow_prompt: bool = False) -> str:
    git = _git_executable()
    if not git:
        return ""
    env = os.environ.copy()
    if not allow_prompt:
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GCM_INTERACTIVE"] = "never"
    try:
        proc = subprocess.run(
            [git, "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True,
            text=True,
            timeout=8,
            encoding="utf-8",
            errors="replace",
            env=env,
            **_win_no_window(),
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
            **_win_no_window(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


BUNDLED_TOKEN_FILE = "bundled_update.json"
_BUNDLED_KEY = b"EVA-bundled-update-v1"


def _bundled_token() -> str:
    """发布程序打包时内置的只读 Token（优先级低于环境变量与启动器填写）。"""
    import base64

    path = _runtime_root() / BUNDLED_TOKEN_FILE
    if not path.is_file():
        return ""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        b = base64.b64decode(str(raw.get("t") or ""))
        return bytes(c ^ _BUNDLED_KEY[i % len(_BUNDLED_KEY)] for i, c in enumerate(b)).decode("utf-8").strip()
    except Exception:
        logger.warning("bundled_update.json 无法解析，已忽略")
        return ""


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
    tok = _bundled_token()
    if tok:
        return tok
    tok = _dotenv_token()
    if tok:
        return tok
    tok = _gh_cli_token()
    if tok:
        return tok
    tok = _git_credential_token(allow_prompt=False)
    if tok:
        return tok
    if not interactive:
        return ""
    return _git_credential_token(allow_prompt=True)


def _remember_token(tok: str) -> None:
    if tok and tok == _bundled_token():
        return  # 内置 Token 不写入用户 data，换包后自动随新包更新
    tok = (tok or "").strip()
    if not tok:
        return
    if str(load_channel().get("token") or "").strip():
        return
    try:
        save_channel(token=tok)
    except OSError:
        pass


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
    with _httpx_client(timeout=20.0) as client:
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
        if not resolve_token(interactive=False):
            return (
                "GitHub 拒绝访问（私有仓库需要 Token）。"
                "在启动器「更多设定 → Token」填写，或设置环境变量 GITHUB_TOKEN。"
            )
        return (
            f"GitHub 上还没有发布（{configured_repo()}）。"
            "确认仓库地址与 Token 权限后重试。"
        )
    return f"GitHub 检查失败 HTTP {status}" + (f"：{msg}" if msg else "")


def pick_portable_asset(assets: list[Any]) -> dict[str, Any] | None:
    """Prefer EVA-update.zip, then EVA-*.zip. Never a source zipball."""
    named: dict[str, Any] | None = None
    eva_zip: dict[str, Any] | None = None
    other_zip: dict[str, Any] | None = None
    for a in assets:
        if not isinstance(a, dict):
            continue
        name = str(a.get("name") or "")
        lower = name.lower()
        api_url = str(a.get("url") or "")
        browser = str(a.get("browser_download_url") or "")
        if not api_url and not browser:
            continue
        if not lower.endswith(".zip"):
            continue
        if lower in {"source.zip", "src.zip"} or lower.endswith("-source.zip"):
            continue
        row = a
        if name == ASSET_NAME:
            named = row
            break
        if lower.startswith("eva"):
            eva_zip = eva_zip or row
        else:
            other_zip = other_zip or row
    return named or eva_zip or other_zip


def _asset_download_url(asset: dict[str, Any]) -> str:
    return str(asset.get("url") or asset.get("browser_download_url") or "")


def fetch_latest_release(*, token: str = "", interactive: bool = True) -> dict[str, Any]:
    repo = configured_repo()
    status, data = _api("/releases/latest", token=token, interactive=interactive)
    if status == 404:
        raise RuntimeError(_auth_error(status, data))
    if status >= 400:
        raise RuntimeError(_auth_error(status, data))
    if not isinstance(data, dict):
        raise RuntimeError("GitHub 返回异常")
    tag = str(data.get("tag_name") or "")
    assets = data.get("assets") if isinstance(data.get("assets"), list) else []
    asset = pick_portable_asset(assets)
    if not asset:
        raise RuntimeError(
            f"最新发布 {tag or '(无标签)'} 没有便携包 zip（需要 {ASSET_NAME}）。"
            "源码 zipball 不能用来更新打包版 Eva。"
        )
    download = _asset_download_url(asset)
    if not download:
        raise RuntimeError("最新发布没有下载地址")
    return {
        "tag": tag,
        "name": str(data.get("name") or tag),
        "notes": str(data.get("body") or ""),
        "published_at": str(data.get("published_at") or ""),
        "download_url": download,
        "asset": str(asset.get("name") or ASSET_NAME),
        "size": int(asset.get("size") or 0),
        "html_url": str(data.get("html_url") or ""),
        "version": tag.lstrip("vV"),
        "source": "portable",
    }


def check(*, force: bool = False, token: str = "", interactive: bool = True) -> dict[str, Any]:
    local = local_info()
    st = _read_state()
    now = time.time()
    last = float(st.get("checked_at") or 0)
    cached = st.get("latest") if isinstance(st.get("latest"), dict) else None
    if not force and cached and (now - last) < 300 and st.get("latest_ok"):
        remote = cached
    else:
        remote = fetch_latest_release(token=token, interactive=interactive)
        got = resolve_token(token, interactive=False)
        if got:
            _remember_token(got)
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


def download_to_pending(url: str, *, token: str = "", progress: Any = None) -> Path:
    import httpx

    dest = pending_zip()
    tmp = dest.with_suffix(".part")
    headers = _headers(token=token)
    if "/releases/assets/" in url:
        headers["Accept"] = "application/octet-stream"
    elif "api.github.com" in url and "zipball" in url:
        headers["Accept"] = "application/vnd.github+json"
    else:
        headers["Accept"] = "application/octet-stream"
    with _httpx_client(timeout=None) as client:
        with client.stream("GET", url, headers=headers) as r:
            if r.status_code >= 400:
                raise RuntimeError(f"下载失败 HTTP {r.status_code}")
            try:
                total = int(r.headers.get("content-length") or 0)
            except ValueError:
                total = 0
            done = 0
            _progress(progress, "download", 0, total)
            with tmp.open("wb") as fh:
                for chunk in r.iter_bytes(1024 * 256):
                    fh.write(chunk)
                    done += len(chunk)
                    _progress(progress, "download", done, total)
    tmp.replace(dest)
    return dest


def _progress(cb: Any, stage: str, done: int, total: int) -> None:
    if cb is None:
        return
    try:
        cb(stage, done, total)
    except Exception:
        pass


def _safe_extract(zf: zipfile.ZipFile, dest: Path, progress: Any = None) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    infos = zf.infolist()
    n = len(infos)
    _progress(progress, "extract", 0, n)
    for i, info in enumerate(infos, 1):
        _progress(progress, "extract", i, n)
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


def schedule_frozen_update(src: Path, dest: Path) -> None:
    """Replace EVA.exe after this process exits (Windows frozen launcher)."""
    exe = src / "EVA.exe"
    internal = src / "_internal"
    if not exe.is_file() or not internal.is_dir():
        raise RuntimeError("更新包不完整（缺少 EVA.exe 或 _internal）")
    payload = _pending_dir() / "payload"
    if payload.exists():
        shutil.rmtree(payload, ignore_errors=True)
    payload.mkdir(parents=True, exist_ok=True)
    shutil.copy2(exe, payload / "EVA.exe")
    shutil.copytree(internal, payload / "_internal")
    src_skills = src / "skills"
    if src_skills.is_dir():
        shutil.copytree(src_skills, payload / "skills")
    for name in ("version.json", "eva_build.txt", "使用说明.txt", "start.bat", ".env.example"):
        p = src / name
        if p.is_file():
            shutil.copy2(p, payload / name)
    ps1 = _pending_dir() / "apply_update.ps1"
    dest_s = json.dumps(str(dest), ensure_ascii=False)
    src_s = json.dumps(str(payload), ensure_ascii=False)
    exe_s = json.dumps(str(dest / "EVA.exe"), ensure_ascii=False)
    pid = os.getpid()
    script = f"""$ErrorActionPreference = "Stop"
$dest = {dest_s}
$src = {src_s}
$exe = {exe_s}
$waitPid = {pid}
Write-Host "Eva update: waiting for launcher to exit..."
try {{ Wait-Process -Id $waitPid -Timeout 120 -ErrorAction SilentlyContinue }} catch {{}}
Start-Sleep -Seconds 1
Copy-Item -LiteralPath (Join-Path $src "EVA.exe") -Destination (Join-Path $dest "EVA.exe") -Force
$internal = Join-Path $dest "_internal"
$new = Join-Path $dest "_internal.new"
$old = Join-Path $dest "_internal.old"
if (Test-Path -LiteralPath $new) {{ Remove-Item -LiteralPath $new -Recurse -Force }}
Copy-Item -LiteralPath (Join-Path $src "_internal") -Destination $new -Recurse -Force
if (Test-Path -LiteralPath $old) {{ Remove-Item -LiteralPath $old -Recurse -Force }}
if (Test-Path -LiteralPath $internal) {{ Rename-Item -LiteralPath $internal -NewName "_internal.old" }}
Rename-Item -LiteralPath $new -NewName "_internal"
if (Test-Path -LiteralPath $old) {{ Remove-Item -LiteralPath $old -Recurse -Force }}
$skillSrc = Join-Path $src "skills"
if (Test-Path -LiteralPath $skillSrc) {{
  $keep = @("document","terminal","list_api_models","reload_runtime","server_health_check")
  $skillDest = Join-Path $dest "skills"
  New-Item -ItemType Directory -Force -Path $skillDest | Out-Null
  foreach ($n in $keep) {{
    $from = Join-Path $skillSrc $n
    if (Test-Path -LiteralPath $from) {{
      $to = Join-Path $skillDest $n
      if (Test-Path -LiteralPath $to) {{ Remove-Item -LiteralPath $to -Recurse -Force }}
      Copy-Item -LiteralPath $from -Destination $to -Recurse -Force
    }}
  }}
}}
foreach ($n in @("version.json","eva_build.txt","start.bat","使用说明.txt",".env.example")) {{
  $p = Join-Path $src $n
  if (Test-Path -LiteralPath $p) {{ Copy-Item -LiteralPath $p -Destination (Join-Path $dest $n) -Force }}
}}
Start-Process -FilePath $exe -WorkingDirectory $dest
"""
    ps1.write_text(script, encoding="utf-8-sig")
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ps1),
        ],
        cwd=str(dest),
        creationflags=flags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


def apply_extracted(src: Path, dest: Path) -> None:
    exe = src / "EVA.exe"
    internal = src / "_internal"
    if not exe.is_file() or not internal.is_dir():
        raise RuntimeError("更新包不完整（缺少 EVA.exe 或 _internal）")
    dest_exe = dest / "EVA.exe"
    if _exe_locked(dest_exe):
        raise RuntimeError("EVA.exe 正在运行。请先关闭启动器，再更新。")

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

    for name in ("version.json", "eva_build.txt", "使用说明.txt", "start.bat", ".env.example"):
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


def apply_pending_zip(progress: Any = None) -> dict[str, Any]:
    zpath = pending_zip()
    if not zpath.is_file():
        raise RuntimeError("没有已下载的更新包")
    dest = _runtime_root()
    tmp = Path(tempfile.mkdtemp(prefix="eva-upd-"))
    try:
        with zipfile.ZipFile(zpath, "r") as zf:
            _safe_extract(zf, tmp, progress)
        src = _find_payload_root(tmp)
        _progress(progress, "apply", 0, 0)
        frozen_install = bool(getattr(sys, "frozen", False))
        frozen_payload = _looks_frozen_payload(src)
        if frozen_install and not frozen_payload:
            raise RuntimeError(
                "当前是打包版 Eva，更新包必须是 EVA.exe + _internal，不能是源码。"
            )
        if not frozen_install and frozen_payload:
            raise RuntimeError(
                "当前是源码运行，收到的是打包版更新包。"
                "请使用 OPC/员工/EVA.exe，或继续用 git 更新源码。"
            )
        if frozen_payload:
            if frozen_install:
                schedule_frozen_update(src, dest)
                changed = ["EVA.exe", "_internal/"]
                kind = "frozen"
                restarting = True
            else:
                apply_extracted(src, dest)
                changed = ["EVA.exe", "_internal/"]
                kind = "frozen"
                restarting = False
        else:
            changed = apply_source_tree(src, dest)
            kind = "source"
            restarting = False
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
            "restarting": restarting,
            "pip": pip_msg,
            "kept": sorted(KEEP_DIRS | KEEP_FILES),
            "restart_required": True,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def download_and_stage(*, force: bool = False, token: str = "", progress: Any = None) -> dict[str, Any]:
    status = check(force=True, token=token)
    if not status.get("newer") and not force:
        return {**status, "downloaded": False, "message": "已是最新"}
    url = str((status.get("remote") or {}).get("download_url") or "")
    if not url:
        raise RuntimeError("没有下载地址")
    path = download_to_pending(url, token=token, progress=progress)
    return {
        **status,
        "downloaded": True,
        "pending": True,
        "path": str(path),
        "message": "已下载更新包。请停止服务后在启动器点「更新」，或关闭启动器再打开后点「更新」。",
    }


def apply_now(*, force: bool = False, token: str = "", progress: Any = None) -> dict[str, Any]:
    pending = pending_zip()
    if not pending.is_file():
        staged = download_and_stage(force=force, token=token, progress=progress)
        if not staged.get("downloaded") and not pending.is_file():
            return staged
    return apply_pending_zip(progress)


# ---------------------------------------------------------------------------
# Cross-platform update (Web UI): win portable / linux source / docker context
# ---------------------------------------------------------------------------

PLATFORM_ASSETS = {
    "win": ("EVA-update.zip",),
    "linux": ("EVA-linux-src.tar.gz",),
    "docker": ("EVA-docker-context.zip", "EVA-linux-src.tar.gz"),
}
_apply_lock = __import__("threading").Lock()


def deploy_platform() -> str:
    """win | linux | docker | dev (source checkout — never auto-overwritten)."""
    env = (os.environ.get("EVA_DEPLOY") or "").strip().lower()
    if env in {"win", "linux", "docker", "dev"}:
        return env
    if getattr(sys, "frozen", False):
        return "win"
    if Path("/.dockerenv").exists():
        return "docker"
    root = _runtime_root()
    if (root / ".git").exists() or sys.platform == "win32":
        return "dev"
    return "linux"


def _pick_platform_asset(assets: list[Any], plat: str) -> dict[str, Any] | None:
    by_name = {str(a.get("name") or ""): a for a in assets if isinstance(a, dict)}
    for name in PLATFORM_ASSETS.get(plat, ()):
        if name in by_name:
            return by_name[name]
    if plat == "win":
        return pick_portable_asset(assets)
    return None


def fetch_latest_for_platform(plat: str, *, token: str = "") -> dict[str, Any]:
    status, data = _api("/releases/latest", token=token, interactive=False)
    if status >= 400 or not isinstance(data, dict):
        raise RuntimeError(_auth_error(status, data))
    tag = str(data.get("tag_name") or "")
    assets = data.get("assets") if isinstance(data.get("assets"), list) else []
    asset = _pick_platform_asset(assets, plat) if plat != "dev" else None
    return {
        "tag": tag,
        "name": str(data.get("name") or tag),
        "notes": str(data.get("body") or ""),
        "published_at": str(data.get("published_at") or ""),
        "html_url": str(data.get("html_url") or ""),
        "version": tag.lstrip("vV"),
        "download_url": _asset_download_url(asset) if asset else "",
        "asset": str(asset.get("name") or "") if asset else "",
        "size": int(asset.get("size") or 0) if asset else 0,
    }


def web_status(*, force: bool = False) -> dict[str, Any]:
    """Lightweight, non-interactive check for the Web UI (cached 1h)."""
    plat = deploy_platform()
    local = local_info()
    st = _read_state()
    key = f"web_latest_{plat}"
    cached = st.get(key) if isinstance(st.get(key), dict) else None
    now = time.time()
    if not force and cached and now - float(st.get(key + "_at") or 0) < 300:
        remote = cached
    else:
        remote = fetch_latest_for_platform(plat)
        _write_state({key: remote, key + "_at": now})
    rv = _parse_ver(str(remote.get("version") or ""))
    lv = _parse_ver(str(local.get("version") or ""))
    if not remote.get("tag"):
        newer = False
    elif rv != (0, 0, 0) and lv != (0, 0, 0):
        newer = rv > lv
    else:
        newer = _is_newer(remote, local)
    can_apply = bool(newer and remote.get("download_url") and plat in {"win", "linux", "docker"})
    hint = ""
    if plat == "dev":
        hint = "当前是开发源码目录（git），不会自动覆盖；请 git pull 或用发布程序。"
    elif newer and not remote.get("download_url"):
        hint = f"该版本没有 {PLATFORM_ASSETS.get(plat, ('?',))[0]}，无法自动更新。"
    elif plat == "docker":
        hint = (
            "容器内会直接替换代码并重启进程；若之后重建/重新创建容器，会回到镜像里的旧版本。"
            "要永久升级，请在宿主机 eva_docker 目录更新 app/ 后执行 docker compose build && docker compose up -d。"
        )
    return {
        "ok": True,
        "platform": plat,
        "local": {"version": local.get("version"), "tag": local.get("tag")},
        "remote": remote,
        "newer": newer,
        "can_apply": can_apply,
        "hint": hint,
    }


def _download_asset(url: str, dest: Path) -> Path:
    import httpx

    headers = _headers(interactive=False)
    headers["Accept"] = "application/octet-stream"
    tmp = dest.with_suffix(dest.suffix + ".part")
    with _httpx_client(timeout=None, follow_redirects=True) as client:
        with client.stream("GET", url, headers=headers) as r:
            if r.status_code >= 400:
                raise RuntimeError(f"下载失败 HTTP {r.status_code}")
            with tmp.open("wb") as fh:
                for chunk in r.iter_bytes(1024 * 256):
                    fh.write(chunk)
    tmp.replace(dest)
    return dest


def _extract_any(archive: Path, dest: Path) -> None:
    if archive.name.endswith((".tar.gz", ".tgz")):
        import tarfile

        with tarfile.open(archive, "r:gz") as tf:
            base = dest.resolve()
            safe = []
            for m in tf.getmembers():
                if not (m.isfile() or m.isdir()):
                    continue
                target = (dest / m.name).resolve()
                if base not in target.parents and target != base:
                    continue
                safe.append(m)
            tf.extractall(dest, members=safe)
    else:
        with zipfile.ZipFile(archive, "r") as zf:
            _safe_extract(zf, dest)


def _find_source_root(extracted: Path) -> Path:
    """Locate the directory holding run.py + app/ (handles src/, app/ wrappers)."""
    cands = [extracted] + sorted(p for p in extracted.rglob("run.py"))
    for c in cands:
        d = c if c.is_dir() else c.parent
        if (d / "run.py").is_file() and (d / "app" / "__init__.py").is_file():
            if "__pycache__" not in d.parts:
                return d
    raise RuntimeError("更新包里找不到 Eva 源码（run.py + app/）")


def _pip_install_current(dest: Path, plat: str) -> str:
    req = dest / "requirements.txt"
    if not req.is_file():
        return ""
    lines = req.read_text(encoding="utf-8", errors="replace").splitlines()
    lines = [x for x in lines if not x.strip().lower().startswith("pystray")]
    tmp_req = _pending_dir() / "requirements.update.txt"
    tmp_req.write_text("\n".join(lines) + "\n", encoding="utf-8")
    args = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", str(tmp_req)]
    if plat == "docker":
        args.insert(4, "--no-cache-dir")
    try:
        proc = subprocess.run(args, cwd=str(dest), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=900)
    except (OSError, subprocess.TimeoutExpired) as extra:
        return f"依赖安装未完成：{extra}"
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        return f"依赖安装未完成：{(err[-1] if err else proc.returncode)}"[:240]
    return "依赖已更新"


def _restart_process_later(delay: float = 1.5) -> None:
    import threading

    def _go() -> None:
        time.sleep(delay)
        if sys.platform == "win32" and getattr(sys, "frozen", False):
            os._exit(0)  # apply_update.ps1 waits for exit, then relaunches EVA.exe
        try:
            logging.shutdown()
        except Exception:
            pass
        os.execv(sys.executable, [sys.executable] + sys.argv)

    threading.Thread(target=_go, name="eva-update-restart", daemon=True).start()


def web_apply() -> dict[str, Any]:
    """Download the platform asset and apply it. Restarts the process afterwards."""
    if not _apply_lock.acquire(blocking=False):
        raise RuntimeError("已有更新在进行中")
    try:
        status = web_status(force=True)
        plat = status["platform"]
        remote = status["remote"]
        if not status.get("newer"):
            return {"ok": True, "applied": False, "message": "已是最新版本"}
        if not status.get("can_apply"):
            raise RuntimeError(status.get("hint") or "当前部署方式不支持自动更新")
        tag = str(remote.get("tag") or "")
        if plat == "win":
            _download_asset(str(remote["download_url"]), pending_zip())
            _write_state({"latest": {**remote, "source": "portable"}})
            res = apply_pending_zip()
            if res.get("restarting"):
                _restart_process_later()
                return {"ok": True, "applied": True, "restarting": True, "tag": tag,
                        "message": "更新已下载，EVA 即将退出并自动替换、重新打开（约 10–30 秒）。"}
            return {"ok": True, "applied": True, "restarting": False, "tag": tag,
                    "message": "已应用更新，请重新启动 EVA。"}
        # linux / docker: source overlay
        dest = _runtime_root()
        name = str(remote.get("asset") or "update.bin")
        archive = _pending_dir() / name
        _download_asset(str(remote["download_url"]), archive)
        tmp = Path(tempfile.mkdtemp(prefix="eva-upd-"))
        try:
            _extract_any(archive, tmp)
            src = _find_source_root(tmp)
            changed = apply_source_tree(src, dest)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            archive.unlink(missing_ok=True)
        pip_msg = _pip_install_current(dest, plat)
        _write_state({"applied_tag": tag, "applied_at": time.time()})
        _restart_process_later()
        msg = f"已更新到 {tag}，服务正在重启，页面稍后会自动刷新。"
        if pip_msg:
            msg += " " + pip_msg
        if plat == "docker":
            msg += " 注意：重建容器会回到镜像版本，请在宿主机同步 eva_docker/app 并 docker compose build。"
        return {"ok": True, "applied": True, "restarting": True, "tag": tag,
                "changed": changed, "pip": pip_msg, "message": msg}
    finally:
        _apply_lock.release()
