"""Run a user-configured CLI as an LLM backend.

The command template may include:
  {prompt}       flattened chat transcript (one argv token)
  {prompt_file}  temp file containing the same transcript
  {model}        the row's model id
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 600.0
_CREATE_NO_WINDOW = 0x08000000
_MAX_TURNS_ONE = re.compile(r"--max-turns\s+1\b", re.I)
_MAX_TURNS_ERR = re.compile(r"max[\s-]*turns?\s+reached", re.I)
_ZDR_VIDEO = re.compile(
    r"Video generation tools are unavailable under zero data retention\s*\(ZDR\)",
    re.I,
)
_ZDR_VIDEO_HINT = (
    "Grok 视频工具被零数据保留（ZDR /privacy）拦住了。"
    "Eva 对话里没法输入 /privacy。"
    "请在本机终端运行 grok，输入 /privacy，选择 Opt in（允许保留），"
    "然后再到 Eva 里生成短视频。"
    "也可以按 https://docs.x.ai/build/settings/zdr-video-storage 配置自托管存储桶。"
    "图片生成不受影响。"
)


def _relax_cli_args(args_tpl: str) -> str:
    """The Grok Build preset used --max-turns 1 (fine for ping, fatal for chat)."""
    raw = args_tpl or ""
    if _MAX_TURNS_ONE.search(raw):
        return _MAX_TURNS_ONE.sub("--max-turns 32", raw)
    return raw


def _strip_max_turns_banner(text: str) -> str:
    lines = []
    for ln in (text or "").splitlines():
        if _MAX_TURNS_ERR.search(ln):
            continue
        if ln.strip().lower().startswith("error:") and "max" in ln.lower():
            continue
        lines.append(ln)
    return "\n".join(lines).strip()


def _output_after_max_turns(stdout: str, stderr: str) -> str:
    blob = f"{stdout}\n{stderr}"
    if not _MAX_TURNS_ERR.search(blob):
        return ""
    return _strip_max_turns_banner(stdout) or _strip_max_turns_banner(stderr)


def _rewrite_cli_output(text: str) -> str:
    """Surface a Chinese next-step when Grok blocks video under /privacy ZDR."""
    raw = text or ""
    if not _ZDR_VIDEO.search(raw):
        return raw
    if "输入 /privacy" in raw:
        return raw
    return raw.rstrip() + "\n\n" + _ZDR_VIDEO_HINT


def _hidden_proc_kwargs() -> dict[str, Any]:
    """Windows: do not flash a console for grok.exe / other CLI backends."""
    kw: dict[str, Any] = {"stdin": asyncio.subprocess.DEVNULL}
    if os.name != "nt":
        return kw
    kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", _CREATE_NO_WINDOW)
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    kw["startupinfo"] = startupinfo
    return kw


def flatten_messages(messages: list[dict[str, Any]] | None) -> str:
    parts: list[str] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "user").strip() or "user"
        raw = msg.get("content")
        if isinstance(raw, list):
            bits = []
            for item in raw:
                if isinstance(item, dict) and item.get("type") in ("text", None):
                    bits.append(str(item.get("text") or ""))
                elif isinstance(item, str):
                    bits.append(item)
            text = "\n".join(x for x in bits if x)
        else:
            text = "" if raw is None else str(raw)
        text = text.strip()
        if not text:
            continue
        parts.append(f"{role}: {text}")
    return "\n\n".join(parts).strip()


def _split_args(args_tpl: str) -> list[str]:
    raw = (args_tpl or "").strip()
    if not raw:
        return []
    posix = os.name != "nt"
    try:
        return shlex.split(raw, posix=posix)
    except ValueError:
        return raw.split()


def _cli_search_dirs() -> list[str]:
    home = os.path.expanduser("~")
    dirs = [
        os.path.join(home, ".grok", "bin"),
        os.path.join(home, "AppData", "Local", "Programs"),
    ]
    return [d for d in dirs if d and os.path.isdir(d)]


def _with_cli_path(env: dict[str, str] | None = None) -> dict[str, str]:
    out = dict(env or os.environ)
    extra = [d for d in _cli_search_dirs() if d]
    path = out.get("PATH") or out.get("Path") or ""
    parts = path.split(os.pathsep)
    for d in reversed(extra):
        if d not in parts:
            parts.insert(0, d)
    joined = os.pathsep.join(parts)
    out["PATH"] = joined
    if "Path" in out:
        out["Path"] = joined
    return out


def _resolve_command(command: str) -> str:
    cmd = (command or "").strip().strip('"')
    if not cmd:
        raise RuntimeError("未填写 CLI 命令")
    if os.path.isfile(cmd):
        return cmd
    search_env = _with_cli_path()
    found = shutil.which(cmd, path=search_env.get("PATH"))
    if found:
        return found
    if os.name == "nt" and not cmd.lower().endswith(".exe"):
        found = shutil.which(cmd + ".exe", path=search_env.get("PATH")) or shutil.which(
            cmd + ".cmd", path=search_env.get("PATH")
        )
        if found:
            return found
    base = os.path.basename(cmd)
    for folder in _cli_search_dirs():
        for name in (base, base + ".exe", base + ".cmd"):
            cand = os.path.join(folder, name)
            if os.path.isfile(cand):
                return cand
    raise RuntimeError(
        f"找不到命令 {cmd}。请填写可执行文件的完整路径，或确认它已在 PATH 中。"
    )


def build_argv(
    command: str,
    args_tpl: str,
    *,
    prompt: str,
    model: str = "",
    prompt_file: str = "",
) -> list[str]:
    exe = _resolve_command(command)
    mapping = {
        "prompt": prompt or "",
        "model": (model or "").strip(),
        "prompt_file": prompt_file or "",
    }
    argv = [exe]
    tokens = _split_args(args_tpl)
    if not tokens:
        tokens = ["-p", "{prompt}"]
    for tok in tokens:
        out = tok
        for key, val in mapping.items():
            out = out.replace("{" + key + "}", val)
        argv.append(out)
    tpl = args_tpl or ""
    model_s = (model or "").strip()
    if model_s and "{model}" not in tpl and "-m" not in tokens:
        argv.extend(["-m", model_s])
    return argv


async def run_cli_completion(
    *,
    command: str,
    args_tpl: str = "",
    cwd: str = "",
    messages: list[dict[str, Any]] | None = None,
    model: str = "",
    timeout: float | None = None,
) -> str:
    prompt = flatten_messages(messages)
    if not prompt:
        prompt = "ping"
    wait = float(timeout or os.environ.get("EVA_LLM_CLI_TIMEOUT") or _DEFAULT_TIMEOUT)
    if wait < 5:
        wait = 5.0

    tmp_path = ""
    fd, tmp_path = tempfile.mkstemp(prefix="eva_llm_cli_", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(prompt)
        argv = build_argv(
            command,
            _relax_cli_args(args_tpl),
            prompt=prompt,
            model=model,
            prompt_file=tmp_path,
        )
        workdir = (cwd or "").strip() or None
        if not workdir:
            try:
                from app.tools.safety import get_workspace_root

                workdir = str(get_workspace_root())
            except Exception:
                workdir = None
        if workdir and not os.path.isdir(workdir):
            raise RuntimeError(f"工作目录不存在：{workdir}")

        logger.info("LLM CLI: %s", " ".join(argv[:4]))
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=workdir,
            env=_with_cli_path(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **_hidden_proc_kwargs(),
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=wait
            )
        except asyncio.TimeoutError as exc:
            try:
                proc.kill()
            except Exception:
                pass
            raise RuntimeError(f"CLI 超时（{int(wait)}s）：{argv[0]}") from exc

        stdout = _rewrite_cli_output(
            (stdout_b or b"").decode("utf-8", "replace").strip()
        )
        stderr = _rewrite_cli_output(
            (stderr_b or b"").decode("utf-8", "replace").strip()
        )
        if proc.returncode not in (0, None):
            recovered = _output_after_max_turns(stdout, stderr)
            if recovered:
                logger.warning("CLI max-turns (exit %s); using captured output", proc.returncode)
                return _rewrite_cli_output(recovered)
            detail = stderr or stdout or f"exit {proc.returncode}"
            if len(detail) > 400:
                detail = detail[:400] + "…"
            raise RuntimeError(f"CLI 失败（exit {proc.returncode}）：{detail}")
        if not stdout:
            recovered = _output_after_max_turns("", stderr)
            if recovered:
                return _rewrite_cli_output(recovered)
            raise RuntimeError(
                "CLI 没有输出。" + (f" stderr：{stderr[:240]}" if stderr else "")
            )
        return stdout
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
