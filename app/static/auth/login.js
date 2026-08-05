(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const form = $("loginForm");
  const msg = $("msg");
  const btn = $("btnLogin");
  const card = $("card");

  function setMsg(text, kind) {
    msg.textContent = text || "";
    msg.className = "msg" + (kind ? " " + kind : "");
  }

  // already logged in?
  fetch("/api/auth/me", { credentials: "same-origin" })
    .then((r) => r.json())
    .then((d) => {
      if (d && d.authenticated) {
        const n = new URLSearchParams(location.search).get("next") || "/";
        location.replace(n.startsWith("/") ? n : "/");
      }
    })
    .catch(() => {});

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const code = (card.value || "").trim();
    if (!code) {
      setMsg("请输入卡密", "err");
      return;
    }
    btn.disabled = true;
    setMsg("验证中…");
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          card_code: code,
          website: ($("website") && $("website").value) || "",
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = data.detail || data.message || "登录失败";
        setMsg(typeof detail === "string" ? detail : JSON.stringify(detail), "err");
        btn.disabled = false;
        return;
      }
      setMsg("登录成功，正在进入…", "ok");
      const n = new URLSearchParams(location.search).get("next") || data.redirect || "/";
      location.replace(n.startsWith("/") ? n : "/");
    } catch (err) {
      setMsg("网络错误，请稍后重试", "err");
      btn.disabled = false;
    }
  });
})();
