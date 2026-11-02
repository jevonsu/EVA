(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const form = $("loginForm");
  const msg = $("msg");
  const btn = $("btnLogin");
  const username = $("username");
  const password = $("password");
  const btnTogglePwd = $("btnTogglePwd");
  const setupBanner = $("setupBanner");
  const brandSub = $("brandSub");
  const loginHint = $("loginHint");
  const btnLoginLabel = $("btnLoginLabel");

  const DEVICE_KEY = "eva_device_id";
  try {
    localStorage.removeItem("eva_card_code");
    localStorage.removeItem("eva_control_key");
  } catch (_) {}

  let sharedDeviceId = "";
  let needsSetup = false;

  function setMsg(text, kind) {
    if (!msg) return;
    msg.textContent = text || "";
    msg.className = "msg" + (kind ? " " + kind : "");
  }

  function lsGet(k) {
    try {
      return localStorage.getItem(k) || "";
    } catch (_) {
      return "";
    }
  }

  function lsSet(k, v) {
    try {
      if (v == null || v === "") localStorage.removeItem(k);
      else localStorage.setItem(k, v);
    } catch (_) {}
  }

  function getDeviceId() {
    if (sharedDeviceId && sharedDeviceId.length >= 8) return sharedDeviceId;
    try {
      let id = localStorage.getItem(DEVICE_KEY) || "";
      if (id && id.length >= 8) {
        sharedDeviceId = id;
        return id;
      }
    } catch (_) {}
    const rand =
      (crypto && crypto.randomUUID && crypto.randomUUID()) ||
      "d" + Math.random().toString(36).slice(2) + Date.now().toString(36);
    const id = String(rand).replace(/[^A-Za-z0-9._:-]/g, "").slice(0, 64);
    sharedDeviceId = id.length >= 8 ? id : "eva-fallback-" + Date.now();
    lsSet(DEVICE_KEY, sharedDeviceId);
    return sharedDeviceId;
  }

  function deviceLabel() {
    try {
      const parts = [
        "Web",
        navigator.platform || "",
        (navigator.language || "").slice(0, 8),
        screen && screen.width ? screen.width + "x" + screen.height : "",
      ].filter(Boolean);
      return parts.join(" · ").slice(0, 120);
    } catch (_) {
      return "Eva Web";
    }
  }

  function applySetupMode(setup) {
    needsSetup = !!setup;
    if (brandSub) brandSub.textContent = setup ? "创建管理员" : "账号密码登录";
    if (btnLoginLabel) btnLoginLabel.textContent = setup ? "创建并登录" : "登录";
    if (loginHint) {
      loginHint.textContent = setup
        ? "首次使用：设置管理员用户名与密码（至少 8 位）。也可在 .env 写 EVA_ADMIN_USER / EVA_ADMIN_PASSWORD。"
        : "使用本机账号与密码登录。会话保存在本机 data/auth，同一目录重启无需重登。";
    }
    if (setupBanner) {
      if (setup) {
        setupBanner.classList.remove("hidden");
        setupBanner.textContent = "尚未创建用户。请设置管理员账号与密码。";
      } else {
        setupBanner.classList.add("hidden");
        setupBanner.textContent = "";
      }
    }
    if (password) {
      password.autocomplete = setup ? "new-password" : "current-password";
    }
  }

  const params = new URLSearchParams(location.search);

  fetch("/api/auth/me", { credentials: "same-origin" })
    .then((r) => r.json())
    .then((d) => {
      if (d && d.authenticated) {
        const n = params.get("next") || "/";
        location.replace(n.startsWith("/") ? n : "/");
      } else if (d && d.needs_setup) {
        applySetupMode(true);
      }
    })
    .catch(() => {});

  fetch("/api/auth/bootstrap?probe=false", { credentials: "same-origin" })
    .then((r) => r.json())
    .then((d) => {
      if (!d || !d.ok) return;
      if (d.login_prefs && d.login_prefs.device_id) {
        sharedDeviceId = String(d.login_prefs.device_id);
        lsSet(DEVICE_KEY, sharedDeviceId);
      }
      applySetupMode(!!d.needs_setup);
    })
    .catch(() => {
      if (setupBanner) {
        setupBanner.classList.remove("hidden");
        setupBanner.textContent = "无法读取本机登录配置";
      }
    });

  setTimeout(() => {
    if (username && !(username.value || "").trim()) username.focus();
    else if (btn) btn.focus();
  }, 80);

  if (btnTogglePwd && password) {
    btnTogglePwd.addEventListener("click", () => {
      const show = password.type === "password";
      password.type = show ? "text" : "password";
      btnTogglePwd.textContent = show ? "隐藏" : "显示";
      btnTogglePwd.setAttribute("aria-pressed", show ? "true" : "false");
      try {
        password.focus();
      } catch (_) {}
    });
  }

  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const user = (username && username.value ? username.value : "").trim();
      const pwd = password && password.value ? password.value : "";
      if (!user || user.length < 3) {
        setMsg("请输入有效用户名（至少 3 位）", "err");
        username && username.focus();
        return;
      }
      if (!pwd || pwd.length < 8) {
        setMsg("密码至少 8 位", "err");
        password && password.focus();
        return;
      }

      const deviceId = getDeviceId();
      if (btn) btn.disabled = true;
      setMsg(needsSetup ? "正在创建账号…" : "正在登录…");

      const endpoint = needsSetup ? "/api/auth/setup" : "/api/auth/login";
      try {
        const res = await fetch(endpoint, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
          },
          body: JSON.stringify({
            username: user,
            password: pwd,
            website: ($("website") && $("website").value) || "",
            device_id: deviceId,
            device_label: deviceLabel(),
          }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          const detail = data.detail || data.message || "登录失败";
          const text =
            typeof detail === "string" ? detail : JSON.stringify(detail);
          setMsg(text, "err");
          if (btn) btn.disabled = false;
          return;
        }

        lsSet(DEVICE_KEY, deviceId);

        const next =
          new URLSearchParams(location.search).get("next") ||
          data.redirect ||
          "/";
        const go = () => location.replace(next.startsWith("/") ? next : "/");
        const pair = (data.pairing_code || "").trim();
        if (pair && $("pairPanel") && $("pairCode")) {
          if (form) form.classList.add("hidden");
          $("pairPanel").classList.remove("hidden");
          $("pairCode").textContent = pair;
          setMsg("登录成功", "ok");
          $("btnCopyPair")?.addEventListener("click", async () => {
            try {
              await navigator.clipboard.writeText(pair);
              setMsg("连接码已复制", "ok");
            } catch (_) {
              setMsg("请手动复制连接码", "err");
            }
          });
          $("btnEnterEva")?.addEventListener("click", go);
          return;
        }
        setMsg("登录成功，正在进入…", "ok");
        go();
      } catch (_) {
        setMsg("网络错误，请稍后重试", "err");
        if (btn) btn.disabled = false;
      }
    });
  }
})();
