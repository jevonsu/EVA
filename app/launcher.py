"""Windows control window: start / stop Eva, auth, embed logs."""

from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import webbrowser
from typing import Any, Callable, TextIO

from app import __version__
from app.branding import logo_ico, logo_png
from app.desktop import (
    EvaServer,
    health_url,
    local_url,
    next_free_port,
    port_busy,
    public_urls,
    load_launch_prefs,
    save_launch_port,
    save_launch_prefs,
)
from app.envfile import parse_env, upsert_env

BG = "#141414"
BG2 = "#1e1e1e"
BG3 = "#2a2a2a"
FG = "#f4f4f5"
MUTED = "#a1a1aa"
BORDER = "#3f3f46"
ACCENT = "#fafafa"
ACCENT_FG = "#171717"
DANGER = "#f87171"
DANGER_BG = "#7f1d1d"
SUCCESS = "#4ade80"
WARN = "#fbbf24"
LOG_BG = "#0c0c0c"
FONT_UI = ("Microsoft YaHei UI", 10)
FONT_UI_SM = ("Microsoft YaHei UI", 9)
FONT_TITLE = ("Microsoft YaHei UI", 16, "bold")
FONT_SEC = ("Microsoft YaHei UI", 9, "bold")
FONT_LOG = ("Consolas", 9)
FONT_MONO = ("Consolas", 10)

_STATUS = {
    "idle": ("未启动", MUTED),
    "starting": ("正在启动…", WARN),
    "running": ("运行中", SUCCESS),
    "stopping": ("正在停止…", WARN),
    "failed": ("启动失败", DANGER),
}

_HOST_LAN = "0.0.0.0"
_HOST_LOCAL = "127.0.0.1"
_HOST_CHOICES = (_HOST_LAN, _HOST_LOCAL)

_OFFICE_MODE_LABEL = {
    "local": "本机工作区",
    "shared_path": "共享文件夹",
    "hub_http": "Hub HTTP",
}
_OFFICE_MODE_KEY = {v: k for k, v in _OFFICE_MODE_LABEL.items()}
_OFFICE_MODE_CHOICES = tuple(_OFFICE_MODE_LABEL.values())

_DB_LABEL = {
    "sqlite": "本地 SQLite",
    "postgresql": "PostgreSQL",
    "mysql": "MySQL",
    "mariadb": "MariaDB",
    "mssql": "SQL Server",
}
_DB_KEY = {v: k for k, v in _DB_LABEL.items()}
_DB_CHOICES = tuple(_DB_LABEL.values())

_WH_PLATFORM_LABEL = {
    "custom": "自定义",
    "feishu": "飞书 / Lark",
    "wecom": "企业微信",
    "dingtalk": "钉钉",
    "telegram": "Telegram",
    "discord": "Discord",
    "slack": "Slack",
    "other": "其它",
}
_WH_PLATFORM_KEY = {v: k for k, v in _WH_PLATFORM_LABEL.items()}
_WH_PLATFORM_CHOICES = tuple(_WH_PLATFORM_LABEL.values())

_LLM_PROVIDER_LABEL = {
    "openai": "OpenAI 兼容",
    "xai": "xAI",
    "custom": "Custom",
    "cli": "CLI",
}
_LLM_PROVIDER_KEY = {v: k for k, v in _LLM_PROVIDER_LABEL.items()}
_LLM_PROVIDER_CHOICES = tuple(_LLM_PROVIDER_LABEL.values())

_NEW_WH = "新建通道"
_NEW_LLM = "新建模型"


def _round_pts(x1: int, y1: int, x2: int, y2: int, r: int) -> list[int]:
    r = max(1, int(r))
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


def _make_round_panel(tk: Any, master: Any, *, fill: str, radius: int = 18, pad: int = 14) -> Any:
    parent_bg = BG
    try:
        parent_bg = master.cget("bg") or BG
    except Exception:
        pass
    wrap = tk.Frame(master, bg=parent_bg, highlightthickness=0, bd=0)
    cv = tk.Canvas(wrap, bg=parent_bg, highlightthickness=0, bd=0)
    cv.place(x=0, y=0, relwidth=1, relheight=1)
    body = tk.Frame(wrap, bg=fill, highlightthickness=0, bd=0)
    body.pack(fill="both", expand=True, padx=pad, pady=pad)

    def _paint(_e=None) -> None:
        cv.delete("r")
        w, h = wrap.winfo_width(), wrap.winfo_height()
        if w < 8 or h < 8:
            return
        rad = min(radius, w // 2, h // 2)
        cv.create_polygon(
            _round_pts(1, 1, w - 1, h - 1, rad),
            smooth=True,
            splinesteps=12,
            fill=fill,
            outline="",
            tags="r",
        )

    wrap.bind("<Configure>", _paint)
    wrap.body = body  # type: ignore[attr-defined]
    return wrap


class _RoundButton:
    def __init__(
        self,
        tk: Any,
        master: Any,
        *,
        text: str,
        command: Callable[[], None],
        bg: str,
        fg: str,
        radius: int = 14,
        height: int = 36,
        width: int = 96,
    ) -> None:
        self._tk = tk
        self._cmd = command
        self._text = text
        self._bg = bg
        self._fg = fg
        self._radius = radius
        self._disabled = False
        self._hover = False
        self.widget = tk.Canvas(
            master,
            height=height,
            width=width,
            bg=master.cget("bg") if str(master.cget("bg")) else BG,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.widget.bind("<Configure>", lambda _e: self._draw())
        self.widget.bind("<Button-1>", self._click)
        self.widget.bind("<Enter>", lambda _e: self._set_hover(True))
        self.widget.bind("<Leave>", lambda _e: self._set_hover(False))
        self._draw()

    def grid(self, **kw: Any) -> None:
        self.widget.grid(**kw)

    def pack(self, **kw: Any) -> None:
        self.widget.pack(**kw)

    def configure(self, **kw: Any) -> None:
        if "state" in kw:
            self._disabled = str(kw["state"]).lower() == "disabled"
            self.widget.configure(cursor="" if self._disabled else "hand2")
            self._draw()
        if "text" in kw:
            self._text = str(kw["text"])
            self._draw()

    def _set_hover(self, on: bool) -> None:
        self._hover = on and not self._disabled
        self._draw()

    def _click(self, _e: Any) -> None:
        if self._disabled:
            return
        self._cmd()

    def _draw(self) -> None:
        cv = self.widget
        cv.delete("all")
        w = max(cv.winfo_width(), 40)
        h = max(cv.winfo_height(), 28)
        fill = self._bg
        if self._disabled:
            fill = "#3f3f46"
            fg = "#a1a1aa"
        else:
            fg = self._fg
            if self._hover:
                fill = _tint(self._bg, 18)
        rad = min(self._radius, h // 2)
        cv.create_polygon(
            _round_pts(1, 1, w - 1, h - 1, rad),
            smooth=True,
            splinesteps=10,
            fill=fill,
            outline="",
            tags="bg",
        )
        cv.create_text(w / 2, h / 2, text=self._text, fill=fg, font=FONT_UI)


def _tint(hex_color: str, delta: int) -> str:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    rgb = [min(255, max(0, int(h[i : i + 2], 16) + delta)) for i in (0, 2, 4)]
    return "#{:02x}{:02x}{:02x}".format(*rgb)


class _QueueWriter:
    def __init__(self, q: queue.Queue[str], fallback: TextIO | None = None) -> None:
        self._q = q
        self._fallback = fallback
        self._buf = ""

    def write(self, data: str) -> int:
        if not data:
            return 0
        text = data if isinstance(data, str) else str(data)
        self._buf += text.replace("\r\n", "\n").replace("\r", "\n")
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._q.put(line + "\n")
        if self._fallback is not None:
            try:
                self._fallback.write(data)
            except Exception:
                pass
        return len(text)

    def flush(self) -> None:
        if self._buf:
            self._q.put(self._buf)
            self._buf = ""
        if self._fallback is not None:
            try:
                self._fallback.flush()
            except Exception:
                pass

    def isatty(self) -> bool:
        return False


class _QueueLogHandler(logging.Handler):
    def __init__(self, q: queue.Queue[str]) -> None:
        super().__init__()
        self._q = q
        self.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._q.put(self.format(record) + "\n")
        except Exception:
            pass


class EvaLauncher:
    def __init__(
        self,
        *,
        port: int,
        host: str,
        open_browser: bool = False,
        debug: bool = False,
        auto_start: bool | None = None,
    ) -> None:
        import tkinter as tk
        from tkinter import ttk

        self._tk = tk
        env = parse_env()
        self.port = int(port)
        self.host = self._normalize_host(host or env.get("HOST") or _HOST_LAN)
        self.debug = bool(debug) if debug else _truthy(env.get("DEBUG", "false"))
        if auto_start is None:
            try:
                auto_start = bool(load_launch_prefs().get("start_on_boot"))
            except Exception:
                auto_start = False
        self.auto_start = bool(auto_start)
        self._open_browser_pref = bool(open_browser)
        self._log_q: queue.Queue[str] = queue.Queue()
        self._server = EvaServer(log=self._emit)
        self._busy = False
        self._login_busy = False
        self._state = "idle"
        self._old_stdout = sys.stdout
        self._old_stderr = sys.stderr
        self._log_handler: logging.Handler | None = None
        self._log_lines = 0
        self._lock_widgets: list[Any] = []
        self._card_shown = False
        self._tray = None

        self.root = tk.Tk()
        self.root.title(f"Eva 启动器  :{self.port}")
        self.root.configure(bg=BG)
        self.root.minsize(1000, 640)
        self.root.geometry("1200x720")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._set_window_icon()

        self._style(ttk)
        self._build(tk, ttk, env)
        self._install_log_capture()
        self._set_state("idle")
        self._drain_logs()
        self._emit(f"Eva {__version__}  目录 {os.getcwd()}")
        if self.auto_start:
            self._emit("已勾选开机启动，即将自动运行服务。默认不打开浏览器。")
        else:
            self._emit("点「启动」运行服务。默认不打开浏览器。")
        self._refresh_auth_hint()
        self.root.after(0, self._raise_window)
        self.root.after(80, self._apply_win_round)
        self.root.after(200, self._setup_tray)
        self.root.bind("<Unmap>", self._on_unmap)
        if self.auto_start:
            self.root.after(280, self._on_start)
        self.root.after(1200, self._kick_update_check)

    @staticmethod
    def _normalize_host(raw: str) -> str:
        h = (raw or "").strip() or _HOST_LAN
        if h in ("localhost", "::1"):
            return _HOST_LOCAL
        if h in ("*", "::"):
            return _HOST_LAN
        return h

    def _apply_win_round(self) -> None:
        if sys.platform != "win32":
            return
        try:
            import ctypes

            hwnd = ctypes.windll.user32.GetAncestor(self.root.winfo_id(), 2)
            pref = ctypes.c_int(2)  # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref)
            )
        except Exception:
            pass

    def _set_window_icon(self) -> None:
        ico = logo_ico()
        try:
            if sys.platform == "win32" and ico.is_file():
                self.root.iconbitmap(str(ico))
        except Exception:
            pass
        photo = self._logo_photo(32)
        if photo is not None:
            try:
                self.root.iconphoto(True, photo)
            except Exception:
                pass
        self._win_icon = photo

    def _logo_photo(self, size: int) -> Any:
        path = logo_png()
        if not path.is_file():
            return None
        try:
            from PIL import Image, ImageTk

            im = Image.open(path).convert("RGBA").resize(
                (size, size), Image.Resampling.LANCZOS
            )
            return ImageTk.PhotoImage(im, master=self.root)
        except Exception:
            try:
                return self._tk.PhotoImage(file=str(path))
            except Exception:
                return None

    def _raise_window(self) -> None:
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            if sys.platform == "win32":
                self.root.attributes("-topmost", True)
                self.root.after(400, lambda: self.root.attributes("-topmost", False))
        except Exception:
            pass

    def _style(self, ttk: Any) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG2, foreground=FG, font=FONT_UI)
        style.configure("Muted.TLabel", background=BG2, foreground=MUTED, font=FONT_UI_SM)
        style.configure("Title.TLabel", background=BG, foreground=FG, font=FONT_TITLE)
        style.configure("TFrame", background=BG)
        style.configure("Head.TLabel", background=BG, foreground=FG, font=FONT_UI)
        style.configure("Sec.TLabel", background=BG2, foreground=MUTED, font=FONT_SEC)
        style.configure("Url.TLabel", background=BG2, foreground=SUCCESS, font=FONT_MONO)
        style.configure(
            "TCheckbutton",
            background=BG2,
            foreground=FG,
            font=FONT_UI_SM,
            focuscolor=BG2,
        )
        style.map("TCheckbutton", background=[("active", BG2)])
        style.configure(
            "TCombobox",
            fieldbackground=BG3,
            background=BG3,
            foreground=FG,
            arrowcolor=FG,
            bordercolor=BG3,
            lightcolor=BG3,
            darkcolor=BG3,
            padding=6,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", BG3)],
            foreground=[("readonly", FG)],
        )

    def _line(self, parent: Any) -> None:
        self._tk.Frame(parent, bg="#2f2f2f", height=1).pack(fill="x")

    def _slot(self, parent: Any, title: str) -> Any:
        wrap = self._tk.Frame(parent, bg=BG2)
        wrap.pack(fill="x")
        row = self._tk.Frame(wrap, bg=BG2)
        row.pack(fill="x")
        self._tk.Label(
            row, text=title, bg=BG2, fg="#e5e5e5", font=FONT_UI, anchor="w"
        ).pack(side="left", padx=(4, 8), pady=8)
        slot = self._tk.Frame(row, bg=BG2)
        slot.pack(side="left", fill="x", expand=True, padx=(0, 2), pady=6)
        self._line(wrap)
        slot.wrap = wrap  # type: ignore[attr-defined]
        return slot

    def _sec(self, parent: Any, title: str) -> None:
        self._tk.Label(
            parent,
            text=title,
            bg=BG2,
            fg=MUTED,
            font=FONT_SEC,
            anchor="w",
        ).pack(fill="x", padx=4, pady=(12, 2))

    def _mk_entry(self, parent: Any, var: Any, *, show: str = "") -> Any:
        e = self._tk.Entry(
            parent,
            textvariable=var,
            bg=BG3,
            fg=FG,
            insertbackground=FG,
            relief="flat",
            bd=4,
            highlightthickness=0,
            font=FONT_MONO,
            show=show,
        )
        e.pack(fill="x")
        return e

    def _mk_combo(self, parent: Any, var: Any, values: list[str] | tuple[str, ...]) -> Any:
        box = self._ttk.Combobox(
            parent,
            textvariable=var,
            values=list(values),
            state="readonly",
            font=FONT_MONO,
        )
        box.pack(fill="x")
        return box

    def _scroll_box(self, parent: Any) -> Any:
        tk = self._tk
        wrap = tk.Frame(parent, bg=BG2)
        canvas = tk.Canvas(wrap, bg=BG2, highlightthickness=0, bd=0)
        vsb = self._ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=BG2)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)

        def _inner_cfg(_e: Any = None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all") or (0, 0, 0, 0))

        def _sync_width(_e: Any = None) -> None:
            w = max(int(canvas.winfo_width()), 1)
            canvas.itemconfigure(win, width=w)
            canvas.configure(scrollregion=canvas.bbox("all") or (0, 0, 0, 0))

        inner.bind("<Configure>", _inner_cfg)
        canvas.bind("<Configure>", _sync_width)
        canvas.bind("<Map>", _sync_width)

        def _wheel(e: Any) -> str:
            if getattr(self, "_more_open", False):
                canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
            return "break"

        def _enter(_e: Any = None) -> None:
            canvas.bind_all("<MouseWheel>", _wheel)

        def _leave(_e: Any = None) -> None:
            canvas.unbind_all("<MouseWheel>")

        wrap.bind("<Enter>", _enter)
        wrap.bind("<Leave>", _leave)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        wrap.inner = inner  # type: ignore[attr-defined]
        wrap.canvas = canvas  # type: ignore[attr-defined]
        wrap.win = win  # type: ignore[attr-defined]
        wrap.sync_width = _sync_width  # type: ignore[attr-defined]
        return wrap

    def _browse_btn(self, parent: Any, command: Callable[[], None]) -> Any:
        btn = self._tk.Button(
            parent,
            text="浏览",
            command=command,
            bg=BG2,
            fg=MUTED,
            bd=0,
            relief="flat",
            font=FONT_UI_SM,
            cursor="hand2",
            padx=8,
        )
        btn.pack(side="right")
        return btn

    def _build(self, tk: Any, ttk: Any, env: dict[str, str]) -> None:
        self._ttk = ttk
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=20, pady=(14, 8))
        self._header_logo = self._logo_photo(36)
        if self._header_logo is not None:
            tk.Label(header, image=self._header_logo, bg=BG, bd=0).pack(side="left")
        ttk.Label(header, text="Eva", style="Title.TLabel").pack(side="left", padx=(10, 12))
        self._status_var = tk.StringVar(value="未启动")
        self._status_lbl = tk.Label(
            header,
            textvariable=self._status_var,
            bg=BG,
            fg=MUTED,
            font=FONT_UI_SM,
        )
        self._status_lbl.pack(side="left")

        actions = tk.Frame(header, bg=BG)
        actions.pack(side="right")
        self._start_btn = _RoundButton(
            tk, actions, text="启动", command=self._on_start, bg=ACCENT, fg=ACCENT_FG, width=88
        )
        self._start_btn.pack(side="left", padx=(0, 8))
        self._stop_btn = _RoundButton(
            tk, actions, text="停止", command=self._on_stop, bg=DANGER_BG, fg=FG, width=88
        )
        self._stop_btn.pack(side="left", padx=(0, 8))
        self._open_btn = _RoundButton(
            tk, actions, text="打开页面", command=self._open_page, bg=BG3, fg=FG, width=100
        )
        self._open_btn.pack(side="left")

        main = tk.Frame(self.root, bg=BG)
        main.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        prefs = load_launch_prefs()
        side = tk.Frame(main, bg=BG2, width=380)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        form = tk.Frame(side, bg=BG2)
        form.pack(fill="both", expand=True, padx=14, pady=12)

        self._port_var = tk.StringVar(value=str(self.port))
        self._port_entry = self._mk_entry(self._slot(form, "端口"), self._port_var)
        self._port_entry.bind("<Return>", lambda _e: self._on_start())

        host0 = str(prefs.get("host") or self.host)
        self._host_var = tk.StringVar(
            value=host0 if host0 in _HOST_CHOICES else _HOST_LAN
        )
        self._host_combo = ttk.Combobox(
            self._slot(form, "监听"),
            textvariable=self._host_var,
            values=list(_HOST_CHOICES),
            state="readonly",
            font=FONT_MONO,
        )
        self._host_combo.pack(fill="x")

        self._gw_var = tk.StringVar(
            value=env.get("AUTH_CONTROL_URL") or env.get("AUTH_CONTROL_URLS") or ""
        )
        self._gw_entry = self._mk_entry(self._slot(form, "网关"), self._gw_var)

        self._key_var = tk.StringVar(value=env.get("AUTH_CONTROL_KEY") or "")
        self._card_var = tk.StringVar(value=str(prefs.get("card") or ""))
        card_slot = self._slot(form, "卡密")
        self._card_entry = self._mk_entry(card_slot, self._card_var, show="•")
        self._card_entry.pack_forget()
        self._card_entry.pack(side="left", fill="x", expand=True)
        self._card_toggle = tk.Button(
            card_slot,
            text="显示",
            command=self._toggle_card,
            bg=BG2,
            fg=MUTED,
            bd=0,
            relief="flat",
            font=FONT_UI_SM,
            cursor="hand2",
            padx=8,
        )
        self._card_toggle.pack(side="right")

        self._browser_var = tk.BooleanVar(value=bool(prefs.get("open_browser")))
        self._debug_var = tk.BooleanVar(
            value=bool(prefs.get("debug")) if "debug" in prefs else self.debug
        )
        self._boot_var = tk.BooleanVar(value=False)
        opt_slot = self._slot(form, "选项")
        self._browser_chk = ttk.Checkbutton(
            opt_slot, text="打开浏览器", variable=self._browser_var
        )
        self._debug_chk = ttk.Checkbutton(opt_slot, text="DEBUG", variable=self._debug_var)
        self._boot_chk = ttk.Checkbutton(
            opt_slot,
            text="开机启动",
            variable=self._boot_var,
        )
        self._browser_chk.pack(side="left")
        self._debug_chk.pack(side="left", padx=(12, 0))
        self._boot_chk.pack(side="left", padx=(12, 0))
        self._sync_boot_checkbox(prefs)
        self._boot_chk.configure(command=self._on_boot_toggle)

        upd_slot = self._slot(form, "更新")
        self._upd_apply_btn = self._browse_btn(upd_slot, self._on_update_apply)
        self._upd_apply_btn.configure(text="更新")
        self._upd_check_btn = self._browse_btn(upd_slot, self._on_update_check)
        self._upd_check_btn.configure(text="检查")
        self._upd_var = tk.StringVar(value=f"v{__version__}")
        self._upd_entry = self._mk_entry(upd_slot, self._upd_var)
        self._upd_entry.pack_forget()
        self._upd_entry.pack(side="left", fill="x", expand=True)
        self._upd_entry.configure(state="readonly")
        self._upd_hint = tk.Label(
            form,
            text="检查 GitHub 是否有新版本。更新只换程序，不改 data / 工作区 / .env。",
            bg=BG2,
            fg=MUTED,
            font=FONT_UI_SM,
            wraplength=330,
            justify="left",
            anchor="w",
        )
        self._upd_hint.pack(fill="x", pady=(0, 4))

        self._auth_hint = tk.Label(
            form,
            text="",
            bg=BG2,
            fg=MUTED,
            font=FONT_UI_SM,
            wraplength=330,
            justify="left",
            anchor="w",
        )
        self._auth_hint.pack(fill="x", pady=(8, 4))

        self._more_open = False
        self._more_dirty = False
        self._more_ready = False
        self._more_btn = tk.Button(
            form,
            text="更多设定  ▸",
            command=self._toggle_more,
            bg=BG2,
            fg=MUTED,
            bd=0,
            relief="flat",
            font=FONT_UI_SM,
            cursor="hand2",
            anchor="w",
        )
        self._more_btn.pack(fill="x", pady=(4, 0))
        self._more_wrap = self._scroll_box(form)
        self._more = self._more_wrap.inner
        self._build_more(tk, ttk)

        self._save_btn = _RoundButton(
            tk, form, text="保存配置", command=self._on_save, bg=BG3, fg=FG, width=200, height=36
        )
        self._save_btn.pack(fill="x", pady=(14, 0))

        self._lock_widgets = [
            self._port_entry,
            self._host_combo,
            self._debug_chk,
            self._office_hub_entry,
            self._office_mode_combo,
            self._upd_repo_entry,
            self._upd_token_entry,
            self._ws_path_entry,
            self._ws_browse_btn,
            self._db_backend_combo,
            self._db_sqlite_entry,
            self._db_host_entry,
            self._db_port_entry,
            self._db_name_entry,
            self._db_user_entry,
            self._db_password_entry,
            self._db_ssl_chk,
            self._wh_pick_combo,
            self._wh_name_entry,
            self._wh_slug_entry,
            self._wh_token_entry,
            self._wh_platform_combo,
            self._llm_pick_combo,
            self._llm_name_entry,
            self._llm_provider_combo,
            self._llm_base_entry,
            self._llm_key_entry,
            self._llm_model_entry,
            self._llm_default_chk,
        ]

        right = tk.Frame(main, bg=LOG_BG)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        url_bar = tk.Frame(right, bg=LOG_BG)
        url_bar.pack(fill="x", padx=14, pady=(12, 0))
        tk.Label(url_bar, text="访问", bg=LOG_BG, fg=MUTED, font=FONT_UI_SM).pack(
            side="left"
        )
        self._urls_var = tk.StringVar(value="启动后显示地址")
        tk.Label(
            url_bar,
            textvariable=self._urls_var,
            bg=LOG_BG,
            fg=SUCCESS,
            font=FONT_MONO,
            anchor="w",
            justify="left",
        ).pack(side="left", fill="x", expand=True, padx=(8, 0))
        log_hold = tk.Frame(right, bg=LOG_BG)
        log_hold.pack(fill="both", expand=True, padx=8, pady=8)
        scroll = ttk.Scrollbar(log_hold)
        scroll.pack(side="right", fill="y")
        self._log = tk.Text(
            log_hold,
            bg=LOG_BG,
            fg="#d4d4d4",
            insertbackground=FG,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            font=FONT_LOG,
            wrap="word",
            state="disabled",
            yscrollcommand=scroll.set,
        )
        self._log.pack(side="left", fill="both", expand=True)
        scroll.config(command=self._log.yview)

    def _build_more(self, tk: Any, ttk: Any) -> None:
        more = self._more
        office, storage, webhooks, llms = self._load_more_state()

        self._sec(more, "接入办公室")
        self._office_hub_var = tk.StringVar(value=str(office.get("hub_url") or ""))
        self._office_hub_entry = self._mk_entry(
            self._slot(more, "Hub 地址"), self._office_hub_var
        )
        mode_key = str(office.get("mode") or "local")
        self._office_mode_var = tk.StringVar(
            value=_OFFICE_MODE_LABEL.get(mode_key, _OFFICE_MODE_LABEL["local"])
        )
        self._office_mode_combo = self._mk_combo(
            self._slot(more, "接入方式"), self._office_mode_var, _OFFICE_MODE_CHOICES
        )
        pair_slot = self._slot(more, "连接码")
        self._pair_copy_btn = self._browse_btn(pair_slot, self._copy_pairing)
        self._pair_copy_btn.configure(text="复制")
        self._pair_refresh_btn = self._browse_btn(pair_slot, self._refresh_pairing_code)
        self._pair_refresh_btn.configure(text="刷新")
        self._pair_var = tk.StringVar(value="")
        self._pair_entry = self._mk_entry(pair_slot, self._pair_var)
        self._pair_entry.pack_forget()
        self._pair_entry.pack(side="left", fill="x", expand=True)
        self._pair_entry.configure(state="readonly")
        self._pair_hint = tk.Label(
            more,
            text="启动并登录后，把连接码给 Hub 添加本机。",
            bg=BG2,
            fg=MUTED,
            font=FONT_UI_SM,
            wraplength=300,
            justify="left",
            anchor="w",
        )
        self._pair_hint.pack(fill="x", padx=4, pady=(0, 4))

        self._sec(more, "程序更新")
        try:
            from app.services.online_update import configured_repo, load_channel

            ch = load_channel()
            repo_now = str(ch.get("repo") or "").strip() or configured_repo()
        except Exception:
            repo_now = "jevonsu/EVA"
        self._upd_repo_var = tk.StringVar(value=repo_now)
        self._upd_repo_entry = self._mk_entry(self._slot(more, "仓库"), self._upd_repo_var)
        self._upd_token_var = tk.StringVar(value="")
        self._upd_token_entry = self._mk_entry(
            self._slot(more, "Token"), self._upd_token_var, show="•"
        )
        tk.Label(
            more,
            text="私有仓库检查更新用。已保存则 Token 留空。点「保存配置」写入。",
            bg=BG2,
            fg=MUTED,
            font=FONT_UI_SM,
            wraplength=300,
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=4, pady=(0, 4))

        self._sec(more, "工作区路径")
        self._ws_path_var = tk.StringVar(value=str(office.get("root") or ""))
        ws_slot = self._slot(more, "路径")
        self._ws_browse_btn = self._browse_btn(ws_slot, self._browse_workspace)
        self._ws_path_entry = self._mk_entry(ws_slot, self._ws_path_var)
        self._ws_path_entry.pack_forget()
        self._ws_path_entry.pack(side="left", fill="x", expand=True)

        self._sec(more, "数据库")
        db_box = tk.Frame(more, bg=BG2)
        db_box.pack(fill="x")
        backend = str(storage.get("backend") or "sqlite")
        self._db_backend_var = tk.StringVar(
            value=_DB_LABEL.get(backend, _DB_LABEL["sqlite"])
        )
        self._db_backend_combo = self._mk_combo(
            self._slot(db_box, "存储方式"), self._db_backend_var, _DB_CHOICES
        )
        self._db_backend_combo.bind("<<ComboboxSelected>>", self._db_sync_fields)
        self._db_sqlite_var = tk.StringVar(
            value=str(storage.get("sqlite_path") or "eva.db")
        )
        db_sqlite_slot = self._slot(db_box, "SQLite 文件")
        self._db_sqlite_entry = self._mk_entry(db_sqlite_slot, self._db_sqlite_var)
        self._db_sqlite_wrap = db_sqlite_slot.wrap
        self._db_host_var = tk.StringVar(value=str(storage.get("host") or "127.0.0.1"))
        db_host_slot = self._slot(db_box, "主机")
        self._db_host_entry = self._mk_entry(db_host_slot, self._db_host_var)
        self._db_port_var = tk.StringVar(
            value="" if not int(storage.get("port") or 0) else str(storage.get("port"))
        )
        db_port_slot = self._slot(db_box, "端口")
        self._db_port_entry = self._mk_entry(db_port_slot, self._db_port_var)
        self._db_name_var = tk.StringVar(value=str(storage.get("database") or "eva"))
        db_name_slot = self._slot(db_box, "库名")
        self._db_name_entry = self._mk_entry(db_name_slot, self._db_name_var)
        self._db_user_var = tk.StringVar(value=str(storage.get("username") or ""))
        db_user_slot = self._slot(db_box, "用户名")
        self._db_user_entry = self._mk_entry(db_user_slot, self._db_user_var)
        self._db_password_var = tk.StringVar(value="")
        db_pwd_slot = self._slot(db_box, "密码")
        self._db_password_entry = self._mk_entry(
            db_pwd_slot, self._db_password_var, show="•"
        )
        db_ssl_slot = self._slot(db_box, "选项")
        self._db_ssl_var = tk.BooleanVar(value=bool(storage.get("ssl")))
        self._db_ssl_chk = ttk.Checkbutton(
            db_ssl_slot, text="SSL", variable=self._db_ssl_var
        )
        self._db_ssl_chk.pack(side="left")
        self._db_remote_wraps = [
            db_host_slot.wrap,
            db_port_slot.wrap,
            db_name_slot.wrap,
            db_user_slot.wrap,
            db_pwd_slot.wrap,
            db_ssl_slot.wrap,
        ]

        self._sec(more, "Webhook")
        self._wh_rows = list(webhooks)
        self._wh_id_var = tk.StringVar(value="")
        self._wh_pick_var = tk.StringVar(value=_NEW_WH)
        self._wh_pick_combo = self._mk_combo(
            self._slot(more, "通道"), self._wh_pick_var, [_NEW_WH]
        )
        self._wh_pick_combo.bind("<<ComboboxSelected>>", self._on_wh_pick)
        self._wh_name_var = tk.StringVar(value="")
        self._wh_name_entry = self._mk_entry(self._slot(more, "名称"), self._wh_name_var)
        self._wh_slug_var = tk.StringVar(value="")
        self._wh_slug_entry = self._mk_entry(self._slot(more, "Slug"), self._wh_slug_var)
        self._wh_token_var = tk.StringVar(value="")
        self._wh_token_entry = self._mk_entry(
            self._slot(more, "Token"), self._wh_token_var, show="•"
        )
        self._wh_platform_var = tk.StringVar(value=_WH_PLATFORM_LABEL["custom"])
        self._wh_platform_combo = self._mk_combo(
            self._slot(more, "平台"), self._wh_platform_var, _WH_PLATFORM_CHOICES
        )

        self._sec(more, "模型")
        self._llm_rows = list(llms)
        self._llm_id_var = tk.StringVar(value="")
        self._llm_pick_var = tk.StringVar(value=_NEW_LLM)
        self._llm_pick_combo = self._mk_combo(
            self._slot(more, "选择"), self._llm_pick_var, [_NEW_LLM]
        )
        self._llm_pick_combo.bind("<<ComboboxSelected>>", self._on_llm_pick)
        self._llm_name_var = tk.StringVar(value="")
        self._llm_name_entry = self._mk_entry(
            self._slot(more, "显示名"), self._llm_name_var
        )
        self._llm_provider_var = tk.StringVar(value=_LLM_PROVIDER_LABEL["xai"])
        self._llm_provider_combo = self._mk_combo(
            self._slot(more, "Provider"), self._llm_provider_var, _LLM_PROVIDER_CHOICES
        )
        self._llm_base_var = tk.StringVar(value="https://api.x.ai/v1")
        self._llm_base_entry = self._mk_entry(
            self._slot(more, "Base URL"), self._llm_base_var
        )
        self._llm_key_var = tk.StringVar(value="")
        self._llm_key_entry = self._mk_entry(
            self._slot(more, "API Key"), self._llm_key_var, show="•"
        )
        self._llm_model_var = tk.StringVar(value="")
        self._llm_model_entry = self._mk_entry(
            self._slot(more, "Model ID"), self._llm_model_var
        )
        def_slot = self._slot(more, "选项")
        self._llm_default_var = tk.BooleanVar(value=False)
        self._llm_default_chk = ttk.Checkbutton(
            def_slot, text="设为默认", variable=self._llm_default_var
        )
        self._llm_default_chk.pack(side="left")

        self._refresh_wh_combo(select_id="")
        self._refresh_llm_combo(select_id="")
        self._db_sync_fields()
        self._refresh_pairing()
        self._wire_more_dirty()
        self._more_dirty = False
        self._more_ready = True

    def _load_more_state(self) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        office: dict[str, Any] = {"mode": "local", "root": "", "hub_url": ""}
        storage: dict[str, Any] = {}
        webhooks: list[dict[str, Any]] = []
        llms: list[dict[str, Any]] = []
        try:
            from app.config_store import get_config_store
            from app.services.workspace_bind import local_default_root

            raw = get_config_store().get_raw().get("workspace")
            if isinstance(raw, dict):
                office = {
                    "mode": str(raw.get("mode") or "local"),
                    "root": str(raw.get("root") or ""),
                    "hub_url": str(raw.get("hub_url") or ""),
                }
            if not str(office.get("root") or "").strip():
                office["root"] = str(local_default_root())
        except Exception as extra:
            self._emit(f"读取办公室/工作区失败：{extra}")
        try:
            from app.storage.settings import get_storage_settings

            storage = get_storage_settings(force=True).__dict__.copy()
        except Exception as extra:
            self._emit(f"读取数据库设定失败：{extra}")
        try:
            from app.webhook.store import get_webhook_store

            webhooks = get_webhook_store().list_raw()
        except Exception as extra:
            self._emit(f"读取 Webhook 失败：{extra}")
        try:
            from app.config_store import get_config_store

            llms = get_config_store().list_llms()
        except Exception as extra:
            self._emit(f"读取模型失败：{extra}")
        return office, storage, webhooks, llms

    def _toggle_more(self) -> None:
        self._more_open = not self._more_open
        if self._more_open:
            self._more_wrap.pack(
                fill="both", expand=True, pady=(8, 0), before=self._save_btn.widget
            )
            self._more_btn.configure(text="更多设定  ▾")
            try:
                self._more_wrap.canvas.yview_moveto(0)
            except Exception:
                pass
            self.root.after(16, self._sync_more_width)
        else:
            self._more_wrap.pack_forget()
            try:
                self._more_wrap.canvas.unbind_all("<MouseWheel>")
            except Exception:
                pass
            self._more_btn.configure(text="更多设定  ▸")

    def _sync_more_width(self) -> None:
        wrap = getattr(self, "_more_wrap", None)
        if wrap is None:
            return
        try:
            wrap.canvas.update_idletasks()
            wrap.sync_width()
        except Exception:
            pass

    def _mark_more_dirty(self, *_a: Any) -> None:
        if getattr(self, "_more_ready", False):
            self._more_dirty = True

    def _wire_more_dirty(self) -> None:
        vars_ = [
            self._office_hub_var,
            self._office_mode_var,
            self._ws_path_var,
            self._db_backend_var,
            self._db_sqlite_var,
            self._db_host_var,
            self._db_port_var,
            self._db_name_var,
            self._db_user_var,
            self._db_password_var,
            self._wh_pick_var,
            self._wh_name_var,
            self._wh_slug_var,
            self._wh_token_var,
            self._wh_platform_var,
            self._llm_pick_var,
            self._llm_name_var,
            self._llm_provider_var,
            self._llm_base_var,
            self._llm_key_var,
            self._llm_model_var,
        ]
        for v in vars_:
            try:
                v.trace_add("write", self._mark_more_dirty)
            except Exception:
                pass
        try:
            self._db_ssl_var.trace_add("write", self._mark_more_dirty)
            self._llm_default_var.trace_add("write", self._mark_more_dirty)
        except Exception:
            pass

    def _refresh_pairing(self) -> None:
        hint = "启动并登录后，把连接码给 Hub 添加本机。"
        code = ""
        try:
            from app.auth.desktop_login import session_ok
            from app.auth.hub_grant import current_pairing, ensure_pairing

            if session_ok():
                row = current_pairing()
                if not row.get("active") or not row.get("pairing_code"):
                    try:
                        row = ensure_pairing()
                    except ValueError:
                        row = {}
                code = str((row or {}).get("pairing_code") or "")
                rem = int((row or {}).get("remaining_sec") or 0)
                if code:
                    hint = f"Hub 添加本机时填此连接码（约 {rem} 秒内有效，一次性）。"
                else:
                    hint = "已登录。点刷新生成连接码。"
        except Exception as extra:
            hint = f"连接码暂不可用：{extra}"
        self._pair_var.set(code)
        try:
            self._pair_hint.configure(text=hint)
        except Exception:
            pass

    def _copy_pairing(self) -> None:
        code = (self._pair_var.get() or "").strip()
        if not code:
            self._refresh_pairing()
            code = (self._pair_var.get() or "").strip()
        if not code:
            self._emit("还没有连接码。请先启动并登录，再点刷新。")
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(code)
            self._emit(f"连接码已复制：{code}")
        except Exception as extra:
            self._emit(f"复制失败：{extra}")

    def _refresh_pairing_code(self) -> None:
        try:
            from app.auth.desktop_login import session_ok
            from app.auth.hub_grant import refresh_pairing

            if not session_ok():
                self._emit("请先启动并登录，再刷新连接码。")
                self._refresh_pairing()
                return
            row = refresh_pairing()
            code = str((row or {}).get("pairing_code") or "")
            self._pair_var.set(code)
            rem = int((row or {}).get("remaining_sec") or 0)
            self._pair_hint.configure(
                text=f"已刷新。Hub 添加本机时填此连接码（约 {rem} 秒内有效）。"
            )
            if code:
                self._emit(f"连接码已刷新：{code}")
        except ValueError as extra:
            self._emit(f"[X] {extra}")
        except Exception as extra:
            self._emit(f"刷新连接码失败：{extra}")

    def _browse_workspace(self) -> None:
        from tkinter import filedialog

        current = (self._ws_path_var.get() or "").strip()
        picked = filedialog.askdirectory(
            parent=self.root,
            title="选择工作区文件夹",
            initialdir=current or None,
        )
        if picked:
            self._ws_path_var.set(picked)

    def _db_backend_key(self) -> str:
        return _DB_KEY.get((self._db_backend_var.get() or "").strip(), "sqlite")

    def _db_sync_fields(self, _e: Any = None) -> None:
        sqlite = self._db_backend_key() == "sqlite"
        try:
            if sqlite:
                self._db_sqlite_wrap.pack(fill="x")
                for w in self._db_remote_wraps:
                    w.pack_forget()
            else:
                self._db_sqlite_wrap.pack_forget()
                for w in self._db_remote_wraps:
                    w.pack(fill="x")
        except Exception:
            pass

    def _wh_label(self, row: dict[str, Any]) -> str:
        name = str(row.get("name") or "未命名")
        slug = str(row.get("slug") or row.get("id") or "")
        return f"{name}  ·  {slug}" if slug else name

    def _llm_label(self, row: dict[str, Any]) -> str:
        name = str(row.get("name") or row.get("model") or "LLM")
        if row.get("is_default"):
            return f"{name}  （默认）"
        return name

    def _refresh_wh_combo(self, select_id: str = "") -> None:
        labels = [_NEW_WH] + [self._wh_label(r) for r in self._wh_rows]
        self._wh_pick_combo.configure(values=labels)
        if select_id:
            for row in self._wh_rows:
                if str(row.get("id") or "") == str(select_id):
                    self._wh_pick_var.set(self._wh_label(row))
                    self._fill_webhook(row)
                    return
        self._wh_pick_var.set(_NEW_WH)
        self._fill_webhook(None)

    def _refresh_llm_combo(self, select_id: str = "") -> None:
        labels = [_NEW_LLM] + [self._llm_label(r) for r in self._llm_rows]
        self._llm_pick_combo.configure(values=labels)
        if select_id:
            for row in self._llm_rows:
                if str(row.get("id") or "") == str(select_id):
                    self._llm_pick_var.set(self._llm_label(row))
                    self._fill_llm(row)
                    return
        self._llm_pick_var.set(_NEW_LLM)
        self._fill_llm(None)

    def _on_wh_pick(self, _e: Any = None) -> None:
        label = (self._wh_pick_var.get() or "").strip()
        if label == _NEW_WH:
            self._fill_webhook(None)
            return
        for row in self._wh_rows:
            if self._wh_label(row) == label:
                self._fill_webhook(row)
                return
        self._fill_webhook(None)

    def _on_llm_pick(self, _e: Any = None) -> None:
        label = (self._llm_pick_var.get() or "").strip()
        if label == _NEW_LLM:
            self._fill_llm(None)
            return
        for row in self._llm_rows:
            if self._llm_label(row) == label:
                self._fill_llm(row)
                return
        self._fill_llm(None)

    def _fill_webhook(self, row: dict[str, Any] | None) -> None:
        try:
            self._wh_token_entry.configure(show="•")
        except Exception:
            pass
        if not row:
            self._wh_id_var.set("")
            self._wh_name_var.set("")
            self._wh_slug_var.set("")
            self._wh_token_var.set("")
            self._wh_platform_var.set(_WH_PLATFORM_LABEL["custom"])
            return
        self._wh_id_var.set(str(row.get("id") or ""))
        self._wh_name_var.set(str(row.get("name") or ""))
        self._wh_slug_var.set(str(row.get("slug") or ""))
        self._wh_token_var.set("")
        plat = str(row.get("platform") or "custom")
        self._wh_platform_var.set(
            _WH_PLATFORM_LABEL.get(plat, _WH_PLATFORM_LABEL["custom"])
        )

    def _fill_llm(self, row: dict[str, Any] | None) -> None:
        if not row:
            self._llm_id_var.set("")
            self._llm_name_var.set("")
            self._llm_provider_var.set(_LLM_PROVIDER_LABEL["xai"])
            self._llm_base_var.set("https://api.x.ai/v1")
            self._llm_key_var.set("")
            self._llm_model_var.set("")
            self._llm_default_var.set(False)
            return
        self._llm_id_var.set(str(row.get("id") or ""))
        self._llm_name_var.set(str(row.get("name") or ""))
        prov = str(row.get("provider") or "xai")
        self._llm_provider_var.set(
            _LLM_PROVIDER_LABEL.get(prov, _LLM_PROVIDER_LABEL["custom"])
        )
        self._llm_base_var.set(str(row.get("base_url") or ""))
        self._llm_key_var.set("")
        self._llm_model_var.set(str(row.get("model") or ""))
        self._llm_default_var.set(bool(row.get("is_default")))

    def _persist_form(self, port: int) -> None:
        want_boot = bool(self._boot_var.get())
        save_launch_prefs(
            port=port,
            host=self._normalize_host(self._host_var.get()),
            card=(self._card_var.get() or "").strip(),
            open_browser=bool(self._browser_var.get()),
            debug=bool(self._debug_var.get()),
            start_on_boot=want_boot,
        )
        if sys.platform == "win32":
            try:
                from app.win_startup import disable as disable_startup
                from app.win_startup import enable as enable_startup
                from app.win_startup import is_enabled

                if want_boot and not is_enabled():
                    enable_startup()
                elif (not want_boot) and is_enabled():
                    disable_startup()
            except Exception as extra:
                self._emit(f"[X] 开机启动同步失败：{extra}")
        try:
            from app.services.online_update import save_channel

            tok = (self._upd_token_var.get() or "").strip()
            save_channel(
                repo=(self._upd_repo_var.get() or "").strip() or None,
                token=tok or None,
            )
            if tok:
                self._upd_token_var.set("")
        except Exception as extra:
            self._emit(f"[X] 更新仓库保存失败：{extra}")

    def _on_save(self) -> None:
        try:
            port = self._read_port()
            self._apply_env(port)
            self._persist_form(port)
            self._apply_more(persist_all=True)
            self._more_dirty = False
            self._emit("配置已保存（含卡密）。下次打开启动器会自动填入。")
        except ValueError as extra:
            self._emit(f"[X] {extra}")

    def _sync_boot_checkbox(self, prefs: dict[str, Any] | None = None) -> None:
        if sys.platform != "win32":
            try:
                self._boot_chk.configure(state="disabled")
            except Exception:
                pass
            self._boot_var.set(False)
            return
        from app.win_startup import enable as enable_startup
        from app.win_startup import is_enabled

        on = is_enabled()
        pref = bool((prefs or {}).get("start_on_boot"))
        if pref and not on:
            try:
                enable_startup()
                on = True
            except Exception as exc:
                self._emit(f"[X] 开机启动快捷方式丢失，未能重建：{exc}")
        self._boot_var.set(on)

    def _kick_update_check(self) -> None:
        if getattr(self, "_upd_busy", False):
            return
        threading.Thread(target=self._update_check_worker, args=(True,), daemon=True).start()

    def _on_update_check(self) -> None:
        if getattr(self, "_upd_busy", False):
            return
        self._upd_busy = True
        self._emit("正在检查 GitHub 更新…")
        threading.Thread(target=self._update_check_worker, args=(False,), daemon=True).start()

    def _update_check_worker(self, quiet: bool) -> None:
        try:
            from app.services.online_update import check, pending_zip

            status = check(force=not quiet, interactive=not quiet)
            local = status.get("local") or {}
            remote = status.get("remote") or {}
            ver = str(local.get("version") or __version__)
            label = f"v{ver.lstrip('vV')}"
            if status.get("newer"):
                tag = str(remote.get("tag") or remote.get("version") or "")
                label = f"{label} → {tag}" if tag else label
                msg = f"发现新版本 {tag or ''}。点「更新」下载并替换程序，data / 工作区 / .env 不动。"
            elif pending_zip().is_file():
                msg = "已下载更新包。请先停止服务，再点「更新」。"
            else:
                msg = "已是最新版本。"
            def _done() -> None:
                self._upd_busy = False
                try:
                    self._upd_var.set(label.strip())
                except Exception:
                    pass
                if (not quiet) or status.get("newer") or pending_zip().is_file():
                    self._emit(msg)
            self._ui(_done)
        except Exception as extra:
            def _fail() -> None:
                self._upd_busy = False
                if not quiet:
                    self._emit(f"[X] 检查更新失败：{extra}")
            self._ui(_fail)

    def _on_update_apply(self) -> None:
        if getattr(self, "_upd_busy", False) or self._busy:
            return
        if self._server.running or self._state in ("starting", "running"):
            self._emit("请先点「停止」，再更新。")
            return
        self._upd_busy = True
        self._busy = True
        self._emit("正在下载并应用更新…")
        threading.Thread(target=self._update_apply_worker, daemon=True).start()

    def _update_apply_worker(self) -> None:
        try:
            from app.services.online_update import apply_now, apply_pending_zip, check, pending_zip

            if pending_zip().is_file():
                result = apply_pending_zip()
            else:
                status = check(force=True)
                if not status.get("newer"):
                    def _latest() -> None:
                        self._upd_busy = False
                        self._busy = False
                        self._emit("已是最新版本。")
                    self._ui(_latest)
                    return
                result = apply_now(force=True)
            tag = str(result.get("applied_tag") or "")
            if not result.get("ok"):
                msg = str(result.get("message") or result.get("error") or "没有可应用的更新")
            else:
                pip = str(result.get("pip") or "")
                msg = f"已应用 {tag or '更新'}。请重新点「启动」。data / 工作区 / .env 未改动。"
                if pip:
                    msg += " " + pip
            def _done() -> None:
                self._upd_busy = False
                self._busy = False
                self._emit(msg)
                try:
                    from app.services.online_update import local_info

                    ver = str((local_info().get("version") or __version__))
                    self._upd_var.set(f"v{ver.lstrip('vV')}")
                except Exception:
                    pass
            self._ui(_done)
        except Exception as extra:
            def _fail() -> None:
                self._upd_busy = False
                self._busy = False
                self._emit(f"[X] 更新失败：{extra}")
            self._ui(_fail)

    def _on_boot_toggle(self) -> None:
        want = bool(self._boot_var.get())
        if sys.platform != "win32":
            self._boot_var.set(False)
            self._emit("开机启动仅支持 Windows。")
            return
        from app.win_startup import disable as disable_startup
        from app.win_startup import enable as enable_startup

        try:
            if want:
                enable_startup()
                self._emit(
                    "已勾选开机启动：登录 Windows 后会自动打开并运行 Eva；"
                    "手动打开启动器也会自动运行。"
                )
            else:
                disable_startup()
                self._emit("已取消开机启动。下次打开启动器需点「启动」。")
            save_launch_prefs(start_on_boot=want)
        except Exception as extra:
            self._boot_var.set(not want)
            self._emit(f"[X] 开机启动设置失败：{extra}")

    def _toggle_card(self) -> None:
        self._card_shown = not self._card_shown
        self._card_entry.configure(show="" if self._card_shown else "•")
        self._card_toggle.configure(text="隐藏" if self._card_shown else "显示")

    def _refresh_auth_hint(self) -> None:
        try:
            from app.auth.desktop_login import session_ok

            logged = session_ok()
        except Exception:
            logged = False
        if logged:
            self._auth_hint.configure(
                text="本机已有登录会话，打开页面无需再填卡密。"
            )
        else:
            self._auth_hint.configure(
                text="卡密仅用于换会话，不落盘。控制密钥不在界面显示。"
            )

    def _install_log_capture(self) -> None:
        writer = _QueueWriter(self._log_q)
        sys.stdout = writer  # type: ignore[assignment]
        sys.stderr = writer  # type: ignore[assignment]
        handler = _QueueLogHandler(self._log_q)
        handler.setLevel(logging.DEBUG if self.debug else logging.INFO)
        root = logging.getLogger()
        root.addHandler(handler)
        if not root.handlers or root.level == logging.NOTSET:
            root.setLevel(logging.DEBUG if self.debug else logging.INFO)
        self._log_handler = handler

    def _emit(self, msg: str) -> None:
        if not msg:
            return
        if not msg.endswith("\n"):
            msg += "\n"
        self._log_q.put(msg)

    def _drain_logs(self) -> None:
        chunk = []
        try:
            while True:
                chunk.append(self._log_q.get_nowait())
        except queue.Empty:
            pass
        if chunk:
            text = "".join(chunk)
            widget = self._log
            widget.configure(state="normal")
            widget.insert("end", text)
            self._log_lines += text.count("\n")
            if self._log_lines > 4000:
                widget.delete("1.0", "2000.0")
                self._log_lines = int(widget.index("end-1c").split(".")[0] or 0)
            widget.see("end")
            widget.configure(state="disabled")
        self.root.after(80, self._drain_logs)

    def _set_lock(self, locked: bool) -> None:
        for w in self._lock_widgets:
            try:
                cls = str(w.winfo_class())
                if cls == "TCombobox":
                    w.configure(state="disabled" if locked else "readonly")
                else:
                    w.configure(state="disabled" if locked else "normal")
            except Exception:
                pass

    def _set_state(self, state: str, detail: str = "") -> None:
        self._state = state
        label, color = _STATUS.get(state, ("未知", MUTED))
        if detail:
            label = f"{label}  {detail}"
        self._status_var.set(label)
        try:
            self._status_lbl.configure(fg=color)
        except Exception:
            pass
        try:
            self.root.title(f"Eva 启动器  :{self.port}")
        except Exception:
            pass
        running = state == "running"
        starting = state in ("starting", "stopping")
        self._start_btn.configure(state="disabled" if running or starting else "normal")
        self._stop_btn.configure(state="normal" if running else "disabled")
        self._open_btn.configure(state="normal" if running else "disabled")
        self._set_lock(running or starting)
        if running:
            local = local_url(self._server.port)
            bits = [f"本机 {local.rstrip('/')}"]
            for u in public_urls(self._server.host, self._server.port):
                bits.append(f"局域网 {u.rstrip('/')}")
            self._urls_var.set("   ·   ".join(bits))
        elif state == "idle":
            self._urls_var.set("启动后显示地址")

    def _ui(self, fn: Any) -> None:
        self.root.after(0, fn)

    def _read_port(self) -> int:
        raw = (self._port_var.get() or "").strip()
        if not raw.isdigit():
            raise ValueError("端口须为 1–65535 的数字")
        port = int(raw)
        if not (1 <= port <= 65535):
            raise ValueError("端口须为 1–65535 的数字")
        return port

    def _apply_env(self, port: int) -> None:
        host = self._normalize_host(self._host_var.get())
        debug = bool(self._debug_var.get())
        gw = (self._gw_var.get() or "").strip()
        key = (self._key_var.get() or "").strip()
        os.environ["PORT"] = str(port)
        os.environ["HOST"] = host
        os.environ["DEBUG"] = "true" if debug else "false"
        os.environ["AUTH_CONTROL_URL"] = gw
        if key:
            os.environ["AUTH_CONTROL_KEY"] = key
        env_keys = {
            "HOST": host,
            "DEBUG": "true" if debug else "false",
            "AUTH_CONTROL_URL": gw,
        }
        if key:
            env_keys["AUTH_CONTROL_KEY"] = key
        written = upsert_env(env_keys)
        try:
            from app.config import get_settings

            get_settings.cache_clear()
        except Exception:
            pass
        self.host = host
        self.debug = debug
        if self._log_handler is not None:
            self._log_handler.setLevel(logging.DEBUG if debug else logging.INFO)
        self._emit("已写入 .env：" + ", ".join(written) + f"；端口 {port}")

    def _apply_more(self, *, persist_all: bool = True) -> None:
        try:
            if not persist_all and not self._more_dirty:
                return
            notes: list[str] = [
                self._save_office_workspace(),
                self._save_database(),
                self._save_webhook(),
                self._save_llm(),
            ]
            text = "；".join(n for n in notes if n)
            if text:
                self._emit("更多设定已保存：" + text)
            self._more_dirty = False
        except ValueError:
            raise
        except Exception as extra:
            raise ValueError(str(extra)) from extra

    def _save_office_workspace(self) -> str:
        from pathlib import Path

        from app.services.workspace_bind import apply_binding, local_default_root

        mode = _OFFICE_MODE_KEY.get(
            (self._office_mode_var.get() or "").strip(), "local"
        )
        hub = (self._office_hub_var.get() or "").strip()
        if hub and not hub.startswith(("http://", "https://")):
            hub = "http://" + hub
        root = (self._ws_path_var.get() or "").strip()
        default_root = str(local_default_root())
        extra = ""
        if mode == "local":
            root = ""
            hub = ""
        elif mode == "shared_path":
            if not root:
                raise ValueError("共享文件夹需要填写工作区路径")
            p = Path(root).expanduser()
            try:
                p = p.resolve()
            except OSError as exc:
                raise ValueError(f"工作区路径无效：{exc}") from exc
            if not p.is_dir():
                raise ValueError(f"工作区路径不存在：{p}")
            root = str(p)
        pub = apply_binding(mode=mode, root=root, hub_url=hub)
        used = str(pub.get("root") or default_root)
        label = _OFFICE_MODE_LABEL.get(mode, mode)
        bit = f"办公室 {label}，工作区 {used}"
        if hub:
            bit += f"，Hub {hub}"
        return bit + extra

    def _save_database(self) -> str:
        from app.storage.settings import update_storage_settings

        backend = self._db_backend_key()
        port_raw = (self._db_port_var.get() or "").strip()
        port = int(port_raw) if port_raw.isdigit() else 0
        patch: dict[str, Any] = {
            "backend": backend,
            "sqlite_path": (self._db_sqlite_var.get() or "").strip() or "eva.db",
            "host": (self._db_host_var.get() or "").strip() or "127.0.0.1",
            "port": port,
            "database": (self._db_name_var.get() or "").strip() or "eva",
            "username": (self._db_user_var.get() or "").strip(),
            "password": (self._db_password_var.get() or "").strip() or "********",
            "ssl": bool(self._db_ssl_var.get()),
        }
        cfg = update_storage_settings(patch)
        msg = f"数据库 {_DB_LABEL.get(cfg.backend, cfg.backend)}"
        if self._state == "running":
            msg += "（已写入，重启服务后生效）"
        return msg

    def _save_webhook(self) -> str:
        name = (self._wh_name_var.get() or "").strip()
        slug = (self._wh_slug_var.get() or "").strip()
        token = (self._wh_token_var.get() or "").strip()
        wh_id = (self._wh_id_var.get() or "").strip()
        if not name and not slug and not wh_id:
            return ""
        from app.webhook.store import get_webhook_store

        store = get_webhook_store()
        creating = not bool(wh_id)
        platform = _WH_PLATFORM_KEY.get(
            (self._wh_platform_var.get() or "").strip(), "custom"
        )
        fields: dict[str, Any] = {
            "name": name or "未命名通道",
            "slug": slug,
            "platform": platform,
        }
        if creating:
            fields["enabled"] = True
        if token:
            fields["token"] = token
        if wh_id:
            row = store.update(wh_id, fields)
            if row is None:
                row = store.create(fields)
                creating = True
        else:
            row = store.create(fields)
        try:
            self._wh_rows = store.list_raw()
        except Exception:
            pass
        rid = str((row or {}).get("id") or "")
        self._refresh_wh_combo(select_id=rid)
        path = str((row or {}).get("url_path") or "")
        token_note = ""
        if creating and rid:
            revealed = store.reveal_token(rid)
            if revealed:
                self._wh_token_var.set(revealed)
                try:
                    self._wh_token_entry.configure(show="")
                except Exception:
                    pass
                token_note = "，Token 已填入（请自行保存）"
        return (
            f"Webhook {(row or {}).get('name') or name}  {path}{token_note}".strip()
        )

    def _save_llm(self) -> str:
        llm_id = (self._llm_id_var.get() or "").strip()
        name = (self._llm_name_var.get() or "").strip()
        base_url = (self._llm_base_var.get() or "").strip()
        model = (self._llm_model_var.get() or "").strip()
        key = (self._llm_key_var.get() or "").strip()
        if not llm_id and not name and not model and not key:
            return ""
        from app.config_store import get_config_store

        store = get_config_store()
        provider = _LLM_PROVIDER_KEY.get(
            (self._llm_provider_var.get() or "").strip(), "xai"
        )
        payload: dict[str, Any] = {
            "name": name or model or "LLM",
            "provider": provider,
            "base_url": base_url,
            "model": model,
            "is_default": bool(self._llm_default_var.get()),
        }
        if not llm_id:
            payload["enabled"] = True
        if llm_id:
            payload["id"] = llm_id
        if key:
            payload["api_key"] = key
        row = store.upsert_llm(payload)
        try:
            self._llm_rows = store.list_llms()
        except Exception:
            pass
        rid = str((row or {}).get("id") or "")
        self._refresh_llm_combo(select_id=rid)
        shown = str((row or {}).get("name") or payload["name"])
        return f"模型 {shown}"

    def _do_login(self, port: int) -> None:
        from app.auth.desktop_login import launcher_login, session_ok

        card = (self._card_var.get() or "").strip()
        if not card:
            if session_ok():
                self._emit("本机已有登录会话，打开页面无需再填卡密。")
            else:
                self._emit("未填卡密：启动后打开页面仍会进入登录页。")
            self._ui(self._refresh_auth_hint)
            self._ui(self._refresh_pairing)
            return
        ok, msg = launcher_login(
            card_code=card,
            control_url=(self._gw_var.get() or "").strip(),
            control_key=(self._key_var.get() or "").strip(),
            port=port,
        )
        if ok:
            self._emit(msg)
        else:
            self._emit(f"[鉴权] {msg}")
        self._ui(self._refresh_auth_hint)
        self._ui(self._refresh_pairing)

    def _on_start(self) -> None:
        if self._busy or self._server.running or self._state in ("starting", "running"):
            return
        try:
            port = self._read_port()
            self._apply_env(port)
            self._apply_more(persist_all=False)
        except ValueError as exc:
            self._emit(f"[X] {exc}")
            self._set_state("failed", str(exc))
            return
        if port_busy(port) and not self._server.running:
            alt = next_free_port(port + 1)
            self._emit(f"端口 {port} 已被占用，改用 {alt}")
            port = alt
            self._port_var.set(str(port))
            os.environ["PORT"] = str(port)
        self.port = port
        save_launch_port(port)
        self._persist_form(port)
        self._busy = True
        self._set_state("starting", str(port))
        threading.Thread(target=self._start_worker, args=(port,), daemon=True).start()

    def _start_worker(self, port: int) -> None:
        try:
            self._do_login(port)
            self._server.start(
                host=self.host,
                port=port,
                debug=self.debug,
                log_to_console=False,
            )
            if not self._server.wait_ready(timeout=45.0):
                self._server.stop()
                raise RuntimeError(f"启动超时（{health_url(port)} 无响应）")
        except Exception as exc:
            msg = str(exc)
            self._emit(f"[X] {msg}")
            self._ui(lambda m=msg: self._finish_failed(m))
            return
        for line in self._server.banner_lines():
            if line.strip():
                self._emit(line)
        self._emit("服务已启动。关闭窗口或点「停止」会关掉服务。")
        if self._browser_var.get():
            try:
                webbrowser.open(local_url(port))
            except Exception as exc:
                self._emit(f"打开浏览器失败：{exc}")
        self._ui(self._finish_running)

    def _finish_running(self) -> None:
        self._busy = False
        self._set_state("running", str(self._server.port))
        self._refresh_pairing()

    def _finish_failed(self, detail: str) -> None:
        self._busy = False
        self._set_state("failed", detail[:80])

    def _on_stop(self) -> None:
        if self._busy or not self._server.running:
            return
        self._busy = True
        self._set_state("stopping")
        threading.Thread(target=self._stop_worker, daemon=True).start()

    def _stop_worker(self) -> None:
        self._emit("正在停止…")
        self._server.stop()
        self._emit("已停止。")
        self._ui(self._finish_stopped)

    def _finish_stopped(self) -> None:
        self._busy = False
        self._set_state("idle")

    def _open_page(self) -> None:
        if not self._server.running:
            return
        try:
            webbrowser.open(local_url(self._server.port))
        except Exception as extra:
            self._emit(f"打开浏览器失败：{extra}")

    def _setup_tray(self) -> None:
        if sys.platform != "win32":
            return
        try:
            import pystray
            from PIL import Image

            path = logo_png()
            image = Image.open(path).convert("RGBA") if path.is_file() else Image.new("RGBA", (32, 32), (23, 23, 23, 255))

            def hop(fn: Any):
                def _run(icon=None, item=None) -> None:
                    self.root.after(0, fn)

                return _run

            menu = pystray.Menu(
                pystray.MenuItem("启动", hop(self._on_start)),
                pystray.MenuItem("停止", hop(self._on_stop)),
                pystray.MenuItem("打开页面", hop(self._open_page)),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("显示窗口", hop(self._show_window), default=True),
                pystray.MenuItem("退出", hop(self._quit_from_tray)),
            )
            icon = pystray.Icon("Eva", image, "Eva", menu)
            self._tray = icon
            threading.Thread(target=icon.run, name="eva-tray", daemon=True).start()
            self._emit("已放到系统托盘。最小化会藏到右下角；右键可启动 / 停止 / 打开页面。")
        except Exception as extra:
            self._emit(f"系统托盘不可用：{extra}")

    def _on_unmap(self, event: Any) -> None:
        if event.widget is not self.root:
            return
        try:
            if self.root.state() == "iconic":
                self._hide_to_tray()
        except Exception:
            pass

    def _hide_to_tray(self) -> None:
        try:
            self.root.withdraw()
        except Exception:
            pass

    def _show_window(self) -> None:
        try:
            self.root.deiconify()
            self.root.state("normal")
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    def _quit_from_tray(self) -> None:
        self._on_close()

    def _teardown_tray(self) -> None:
        tray = self._tray
        self._tray = None
        if tray is not None:
            try:
                tray.stop()
            except Exception:
                pass

    def _on_close(self) -> None:
        if self._server.running or self._state in ("starting", "stopping"):
            from tkinter import messagebox

            self._show_window()
            if not messagebox.askokcancel("Eva 启动器", "关闭窗口会停止服务，确定退出？"):
                return
        self._teardown_tray()
        wrap = getattr(self, "_more_wrap", None)
        if wrap is not None:
            try:
                wrap.canvas.unbind_all("<MouseWheel>")
            except Exception:
                pass
        try:
            self._server.stop(timeout=4.0)
        except Exception:
            pass
        self._restore_stdio()
        self.root.destroy()

    def _restore_stdio(self) -> None:
        try:
            sys.stdout = self._old_stdout
            sys.stderr = self._old_stderr
        except Exception:
            pass
        if self._log_handler is not None:
            try:
                logging.getLogger().removeHandler(self._log_handler)
            except Exception:
                pass
            self._log_handler = None

    def run(self) -> None:
        self.root.mainloop()


def _truthy(raw: str) -> bool:
    return (raw or "").strip().lower() in ("1", "true", "yes", "on")


def run_launcher(
    *,
    port: int,
    host: str = "0.0.0.0",
    open_browser: bool = False,
    debug: bool = False,
    auto_start: bool | None = None,
) -> None:
    EvaLauncher(
        port=port,
        host=host,
        open_browser=open_browser,
        debug=debug,
        auto_start=auto_start,
    ).run()
