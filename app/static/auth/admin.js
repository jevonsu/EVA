(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const loginPanel = $("loginPanel");
  const dashPanel = $("dashPanel");

  function setMsg(el, text, kind) {
    if (!el) return;
    el.textContent = text || "";
    el.className = "msg" + (kind ? " " + kind : "");
  }

  function fmtTs(ts) {
    if (!ts) return "—";
    try {
      return new Date(ts * 1000).toLocaleString();
    } catch {
      return "—";
    }
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const d = data.detail || data.message || res.statusText;
      throw new Error(typeof d === "string" ? d : JSON.stringify(d));
    }
    return data;
  }

  async function ensureAdmin() {
    try {
      await api("/api/auth/admin/me");
      showDash();
      await refreshAll();
    } catch {
      showLogin();
    }
  }

  function showLogin() {
    loginPanel.hidden = false;
    dashPanel.hidden = true;
  }
  function showDash() {
    loginPanel.hidden = true;
    dashPanel.hidden = false;
  }

  $("adminLoginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("btnAdminLogin");
    btn.disabled = true;
    setMsg($("loginMsg"), "登录中…");
    try {
      await api("/api/auth/admin/login", {
        method: "POST",
        body: JSON.stringify({
          username: $("user").value.trim(),
          password: $("pass").value,
          website: ($("website") && $("website").value) || "",
        }),
      });
      setMsg($("loginMsg"), "成功", "ok");
      showDash();
      await refreshAll();
    } catch (err) {
      setMsg($("loginMsg"), err.message || "登录失败", "err");
    } finally {
      btn.disabled = false;
    }
  });

  $("btnLogout").addEventListener("click", async () => {
    try {
      await api("/api/auth/admin/logout", { method: "POST", body: "{}" });
    } catch (_) {}
    showLogin();
  });

  $("btnRefresh").addEventListener("click", () => refreshAll());
  $("btnFilter").addEventListener("click", () => loadCards());

  async function refreshAll() {
    await Promise.all([loadStats(), loadCards()]);
  }

  async function loadStats() {
    try {
      const d = await api("/api/auth/admin/stats");
      const s = d.stats || {};
      $("stats").innerHTML = [
        ["总数", s.total || 0],
        ["未使用", s.unused || 0],
        ["已激活", s.active || 0],
        ["已吊销", s.revoked || 0],
        ["在线会话", s.active_sessions || 0],
      ]
        .map(
          ([k, v]) =>
            `<div class="stat"><b>${v}</b><span>${k}</span></div>`
        )
        .join("");
      const audit = d.audit || [];
      $("audit").innerHTML = audit.length
        ? audit
            .map((a) => {
              const t = fmtTs(a.ts);
              return `<div><strong>${escapeHtml(a.event)}</strong> · ${escapeHtml(
                a.ip || ""
              )} · ${escapeHtml(t)}<br/><span>${escapeHtml(a.detail || "")}</span></div>`;
            })
            .join("")
        : "<div>暂无审计记录</div>";
    } catch (err) {
      setMsg($("listMsg"), err.message, "err");
    }
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function loadCards() {
    const status = $("filterStatus").value || "";
    const q = status ? `?status=${encodeURIComponent(status)}&limit=100` : "?limit=100";
    try {
      const d = await api("/api/auth/admin/cards" + q);
      const items = d.items || [];
      const body = $("cardBody");
      body.innerHTML = "";
      if (!items.length) {
        body.innerHTML = `<tr><td colspan="9" style="color:#8b949e">暂无卡片</td></tr>`;
        return;
      }
      for (const c of items) {
        const tr = document.createElement("tr");
        const st = c.status || "";
        tr.innerHTML = `
          <td>${c.id}</td>
          <td><code>${escapeHtml(c.code_hint || "")}</code></td>
          <td><span class="badge ${escapeHtml(st)}">${escapeHtml(st)}</span></td>
          <td>${escapeHtml((c.batch_id || "").slice(0, 10))}</td>
          <td>${c.max_sessions ?? ""}</td>
          <td>${c.login_count ?? 0}</td>
          <td>${fmtTs(c.expires_at)}</td>
          <td>${escapeHtml(c.note || "")}</td>
          <td></td>`;
        const td = tr.lastElementChild;
        if (st !== "revoked") {
          const b = document.createElement("button");
          b.type = "button";
          b.className = "btn danger";
          b.textContent = "吊销";
          b.addEventListener("click", async () => {
            if (!confirm(`确认吊销卡片 #${c.id}？已登录会话将立即失效。`)) return;
            try {
              await api(`/api/auth/admin/cards/${c.id}/revoke`, {
                method: "POST",
                body: "{}",
              });
              await refreshAll();
            } catch (err) {
              alert(err.message);
            }
          });
          td.appendChild(b);
        }
        body.appendChild(tr);
      }
      setMsg($("listMsg"), `共 ${items.length} 条（本页）`);
    } catch (err) {
      setMsg($("listMsg"), err.message, "err");
    }
  }

  $("btnIssue").addEventListener("click", async () => {
    const btn = $("btnIssue");
    btn.disabled = true;
    setMsg($("issueMsg"), "生成中…");
    $("codesBox").hidden = true;
    $("btnCopy").hidden = true;
    try {
      const d = await api("/api/auth/admin/cards/issue", {
        method: "POST",
        body: JSON.stringify({
          count: parseInt($("count").value, 10) || 1,
          valid_days: parseInt($("days").value, 10) || 0,
          max_sessions: parseInt($("maxSess").value, 10) || 3,
          note: ($("note").value || "").trim(),
        }),
      });
      const cards = d.cards || [];
      $("codesBox").hidden = false;
      $("codesBox").textContent = cards.join("\n");
      $("btnCopy").hidden = false;
      setMsg(
        $("issueMsg"),
        `已生成 ${cards.length} 张。明文卡密仅显示一次，请立即复制保存。`,
        "ok"
      );
      await refreshAll();
    } catch (err) {
      setMsg($("issueMsg"), err.message, "err");
    } finally {
      btn.disabled = false;
    }
  });

  $("btnCopy").addEventListener("click", async () => {
    const t = $("codesBox").textContent || "";
    try {
      await navigator.clipboard.writeText(t);
      setMsg($("issueMsg"), "已复制到剪贴板", "ok");
    } catch {
      setMsg($("issueMsg"), "复制失败，请手动选择文本", "err");
    }
  });

  ensureAdmin();
})();
