(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const form = $("loginForm");
  const msg = $("msg");
  const btn = $("btnLogin");
  const card = $("card");
  const controlUrl = $("controlUrl");
  const controlKey = $("controlKey");
  const btnToggleCard = $("btnToggleCard");
  const setupBanner = $("setupBanner");
  const presetRow = $("presetRow");
  const presetChips = $("presetChips");

  const DEVICE_KEY = "eva_device_id";
  const CONTROL_URL_LS = "eva_control_url";
  const HAS_SAVED_LS = "eva_login_has_saved";
  try {
    localStorage.removeItem("eva_card_code");
    localStorage.removeItem("eva_control_key");
  } catch (_) {}

  let sharedDeviceId = "";
  let envHasDefault = false;
  let vendorReady = false;
  let hasSavedCard = false;

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

  function normalizeUrl(u) {
    let s = (u || "").trim().replace(/\/+$/, "");
    if (!s) return "";
    if (!/^https?:\/\//i.test(s)) s = "http://" + s;
    return s.replace(/\/+$/, "");
  }

  function applyPrefs(prefs) {
    if (!prefs) return;
    if (prefs.device_id && String(prefs.device_id).length >= 8) {
      sharedDeviceId = String(prefs.device_id);
      lsSet(DEVICE_KEY, sharedDeviceId);
    }
    if (!prefs.has_saved) {
      if (card) card.value = "";
      return;
    }
    hasSavedCard = !!(prefs.card_saved || prefs.card_code);
    if (card) {
      if (prefs.card_code) card.value = prefs.card_code;
      else if (hasSavedCard) {
        card.value = "";
        card.placeholder = prefs.card_hint
          ? "已保存 " + prefs.card_hint + " · 留空沿用"
          : "已保存卡密 · 留空沿用";
      }
    }
    lsSet(HAS_SAVED_LS, "1");
    if (prefs.control_url) lsSet(CONTROL_URL_LS, prefs.control_url);
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

  function renderPresets(presets, selected) {
    if (!presetRow || !presetChips) return;
    const list = Array.isArray(presets) ? presets : [];
    if (list.length < 2) {
      presetRow.classList.add("hidden");
      return;
    }
    presetRow.classList.remove("hidden");
    const cur = normalizeUrl(selected || (controlUrl && controlUrl.value) || "");
    presetChips.innerHTML = "";
    list.forEach((p) => {
      const url = normalizeUrl(p.url || "");
      if (!url) return;
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = p.label || url;
      if (url === cur) b.classList.add("is-on");
      b.addEventListener("click", () => {
        if (controlUrl) controlUrl.value = url;
        renderPresets(list, url);
      });
      presetChips.appendChild(b);
    });
  }

  const params = new URLSearchParams(location.search);

  fetch("/api/auth/me", { credentials: "same-origin" })
    .then((r) => r.json())
    .then((d) => {
      if (d && d.authenticated) {
        const n = params.get("next") || "/";
        location.replace(n.startsWith("/") ? n : "/");
      }
    })
    .catch(() => {});

  fetch("/api/auth/bootstrap?probe=false", { credentials: "same-origin" })
    .then((r) => r.json())
    .then((d) => {
      if (!d || !d.ok) return;
      if (d.login_prefs) applyPrefs(d.login_prefs);
      else if (lsGet(HAS_SAVED_LS) === "1") {
        applyPrefs({
          has_saved: true,
          control_url: lsGet(CONTROL_URL_LS),
          device_id: lsGet(DEVICE_KEY),
        });
      } else applyPrefs({ has_saved: false });

      envHasDefault = !!d.env_has_default;
      const keySet = !!d.env_control_key_set;
      vendorReady = envHasDefault && keySet;
      const url = normalizeUrl(d.default_control_url || d.suggested_control_url || "");
      if (controlUrl) controlUrl.value = url;
      if (setupBanner) {
        if (vendorReady) {
          setupBanner.classList.add("hidden");
          setupBanner.textContent = "";
        } else {
          setupBanner.classList.remove("hidden");
          setupBanner.textContent =
            "发卡服务未配置。请发卡方在本机 .env 预填 AUTH_CONTROL_URL 与 AUTH_CONTROL_KEY 后再发给客户。";
        }
      }
      renderPresets(d.presets || [], url);
    })
    .catch(() => {
      if (setupBanner) {
        setupBanner.classList.remove("hidden");
        setupBanner.textContent = "无法读取本机登录配置";
      }
    });

  setTimeout(() => {
    if (card && !(card.value || "").trim()) card.focus();
    else if (btn) btn.focus();
  }, 80);

  if (btnToggleCard && card) {
    btnToggleCard.addEventListener("click", () => {
      const show = card.type === "password";
      card.type = show ? "text" : "password";
      btnToggleCard.textContent = show ? "隐藏" : "显示";
      btnToggleCard.setAttribute("aria-pressed", show ? "true" : "false");
      try {
        card.focus();
      } catch (_) {}
    });
  }

  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const code = (card && card.value ? card.value : "").trim();
      const url = normalizeUrl(controlUrl && controlUrl.value);
      if ((!code || code.length < 8) && !hasSavedCard) {
        setMsg("请输入有效卡密", "err");
        card && card.focus();
        return;
      }
      if (!url && !envHasDefault) {
        setMsg("发卡服务未配置，请联系供应商", "err");
        return;
      }

      const deviceId = getDeviceId();
      if (btn) btn.disabled = true;
      setMsg("正在登录…");

      try {
        const res = await fetch("/api/auth/login", {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
          },
          body: JSON.stringify({
            card_code: code,
            control_url: url,
            control_key: "",
            auto_failover: true,
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

        const usedUrl = normalizeUrl(data.control_url || url) || url;
        lsSet(HAS_SAVED_LS, "1");
        lsSet(CONTROL_URL_LS, usedUrl);
        lsSet(DEVICE_KEY, deviceId);
        try {
          await fetch("/api/auth/login-prefs", {
            method: "PUT",
            credentials: "same-origin",
            headers: {
              "Content-Type": "application/json",
              Accept: "application/json",
            },
            body: JSON.stringify({
              control_url: usedUrl,
              device_id: deviceId,
            }),
          });
        } catch (_) {}

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
