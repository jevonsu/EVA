/* 设定 → 模型路由 → 主备自动切换（Kaggle 主模型 / DeepSeek 备用）+ 顶栏状态小标签 */
(function () {
  "use strict";
  let st = null; // {config, llms, status}
  let pollTimer = null;

  async function j(path, opt) {
    const r = await fetch(path, Object.assign({ credentials: "same-origin", headers: { "Content-Type": "application/json" } }, opt || {}));
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      const e = new Error(d.detail || "HTTP " + r.status);
      e.status = r.status;
      throw e;
    }
    return d;
  }
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const ic = (n, c) => (window.IconParkUI ? window.IconParkUI.icon(n, c || "ipk-xs") : "");

  function css() {
    if (document.getElementById("llmFoStyle")) return;
    const s = document.createElement("style");
    s.id = "llmFoStyle";
    s.textContent = `
#llmFailoverBox{margin-top:16px;min-width:0;max-width:100%}
#llmFailoverBox .fo-card{gap:0}
#llmFailoverBox .fo-fold>summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:10px;flex-wrap:wrap;user-select:none;min-width:0}
#llmFailoverBox .fo-fold>summary::-webkit-details-marker{display:none}
#llmFailoverBox .fo-fold>summary .mr-section-title{order:0}
#llmFailoverBox .fo-fold>summary .mr-status{order:1;margin-left:auto}
#llmFailoverBox .fo-fold>summary::after{order:2;content:"\\25B8";color:var(--text-muted,#8b949e);font-size:12px;width:12px;text-align:center}
#llmFailoverBox .fo-fold>summary .fo-sum-line{order:3}
#llmFailoverBox #foAddBk{margin-top:6px}
#llmFailoverBox .fo-fold[open]>summary::after{content:"\\25BE"}
#llmFailoverBox .fo-sum-line{flex-basis:100%;font-size:12px;line-height:1.55;color:var(--text-muted,#8b949e);min-width:0;overflow-wrap:anywhere}
#llmFailoverBox .fo-sum-line .fo-dot{margin-right:4px}
#llmFailoverBox .fo-body{display:flex;flex-direction:column;gap:14px;margin-top:14px;min-width:0}
#llmFailoverBox .fo-body .mr-section-desc{margin:0}
#llmFailoverBox .fo-enable{display:inline-flex;align-items:center;gap:8px;font-size:13px;color:var(--text,#e6edf3);cursor:pointer;width:max-content;max-width:100%}
#llmFailoverBox .fo-enable input{width:16px;height:16px;margin:0;flex:none}
#llmFailoverBox .fo-pair{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:10px 14px;align-items:start}
#llmFailoverBox .fo-pair .agent-field,#llmFailoverBox .agent-row .agent-field{min-width:0;margin:0}
#llmFailoverBox .agent-field select,#llmFailoverBox .agent-field input{width:100%;max-width:100%;min-width:0;box-sizing:border-box}
#llmFailoverBox .fo-backups{display:flex;flex-direction:column;gap:6px}
#llmFailoverBox .fo-bk{display:flex;align-items:center;gap:6px;min-width:0}
#llmFailoverBox .fo-bk .mr-tag{flex:1;min-width:0;max-width:none;font-size:12px;padding:5px 10px}
#llmFailoverBox .fo-bk .btn.icon-btn{flex:none}
#llmFailoverBox .fo-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap;min-width:0}
#llmFailoverBox .fo-actions .form-msg{flex-basis:100%;margin:0}
#llmFailoverBox .fo-status{display:flex;flex-direction:column;gap:2px;padding:10px 12px;border-radius:var(--radius,10px);background:rgba(255,255,255,.03);border:1px solid var(--glass-border,rgba(255,255,255,.1));font-size:12.5px;line-height:1.6;color:var(--text,#e6edf3);min-width:0;overflow-wrap:anywhere}
#llmFailoverBox .fo-status .fo-muted{color:var(--text-muted,#8b949e)}
#llmFailoverBox .fo-status details summary{cursor:pointer;color:var(--text-muted,#8b949e)}
#llmFailoverBox .fo-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:middle;background:#8b949e}
#llmFailoverBox .fo-dot.up{background:#3fb950}#llmFailoverBox .fo-dot.down{background:#f85149}#llmFailoverBox .fo-dot.retrying{background:#d29922}
#llmFailoverBox .fo-events{margin:4px 0 0;padding-left:18px;max-height:140px;overflow:auto}
#llmFailoverBox .agent-fold-details .agent-row{margin-top:10px}
#llmFailoverBox .agent-fold-details .hint{margin:8px 0 0}
#llmFailoverBox .fo-token,#llmFailoverBox .fo-code{font-family:ui-monospace,Consolas,monospace;font-size:12px;word-break:break-all;white-space:pre-wrap;padding:8px 10px;border-radius:8px;background:rgba(0,0,0,.25);border:1px solid rgba(255,255,255,.08);margin-top:6px;max-width:100%;box-sizing:border-box}
#llmFailoverBox .fo-token{user-select:all}
#llmFailoverBox .fo-tools{display:flex;flex-direction:column;gap:2px}
#llmFailoverBox .fo-tools .hint{margin:0 0 0 24px}
@media (max-width:720px){#llmFailoverBox .fo-pair{grid-template-columns:1fr}#llmFailoverBox .fo-meta{display:none}}
.top-actions #llmFoChip{cursor:pointer;font:inherit;font-size:11px;appearance:none;-webkit-appearance:none;flex:none}
@media (max-width:720px){.top-actions #llmFoChip{font-size:10px}}
#llmFoChip.fo-backup{color:#d29922 !important;border-color:rgba(210,153,34,.35) !important}
@media (max-width:720px){#llmFoChip.fo-up{display:none !important}}
`;
    document.head.appendChild(s);
  }

  function llmLabel(l) {
    let s = l.name || l.id;
    if (l.model && l.model !== l.name) s += " · " + l.model;
    if (l.is_default) s += "（默认）";
    if (!l.enabled) s += "（已停用）";
    return s;
  }
  function nameOf(id) {
    const l = (st.llms || []).find((x) => x.id === id);
    return l ? llmLabel(l) : "（已删除的模型）";
  }
  function fmtAgo(ts, now) {
    if (!ts) return "—";
    const d = Math.max(0, Math.round((now || Date.now() / 1000) - ts));
    if (d < 60) return d + " 秒前";
    if (d < 3600) return Math.round(d / 60) + " 分钟前";
    return Math.round(d / 3600) + " 小时前";
  }
  const STATE_ZH = { up: "在线", down: "离线（熔断中）", retrying: "冷却结束，下次请求重试", unknown: "未知（尚未使用）" };

  function msg(t, kind) {
    const m = document.getElementById("msgLlmFo");
    if (m) { m.textContent = t || ""; m.className = "form-msg" + (kind ? " " + kind : ""); }
  }

  let foldOpen = false; // 默认折叠，记住用户展开状态

  function statusHtml(s) {
    if (!s) return "";
    const p = s.primary;
    let h = "";
    if (!s.enabled) h += `<div class="fo-muted">主备切换未开启。</div>`;
    if (p) {
      h += `<div><span class="fo-dot ${esc(p.state)}"></span>主模型 <b>${esc(p.name)}</b>（${esc(p.host || "—")}）：${esc(STATE_ZH[p.state] || p.state)}`;
      if (p.state === "down" && p.down_for_s) h += `，约 ${p.down_for_s} 秒后再试`;
      if (p.probing) h += "，后台探测中";
      h += `</div>`;
      if (p.last_error) h += `<div class="fo-muted">最近错误：${esc(p.last_error)}（${fmtAgo(p.last_error_at, s.now)}）</div>`;
      if (p.last_ok_at) h += `<div class="fo-muted">最近成功：${fmtAgo(p.last_ok_at, s.now)}</div>`;
    }
    (s.backups || []).forEach((b, i) => {
      h += `<div><span class="fo-dot ${esc(b.state)}"></span>备用 ${i + 1}：<b>${esc(b.name)}</b> ${esc(STATE_ZH[b.state] || b.state)}${b.last_error ? "；最近错误：" + esc(b.last_error) : ""}</div>`;
    });
    if (s.active) h += `<div>当前使用：<b>${esc(s.active.name)}</b></div>`;
    if (s.last_switch) h += `<div class="fo-muted">最近切换：${esc(s.last_switch.from_name || "—")} → ${esc(s.last_switch.to_name || "—")}，原因：${esc(s.last_switch.reason || "—")}（${fmtAgo(s.last_switch.at, s.now)}）</div>`;
    if ((s.events || []).length) {
      h += `<details><summary>最近事件（${s.events.length}）</summary><ul class="fo-events">`;
      for (const e of s.events) h += `<li>${fmtAgo(e.at, s.now)}：${esc(e.msg)}</li>`;
      h += `</ul></details>`;
    }
    return h;
  }

  /* 折叠时的一行摘要 */
  function summaryHtml(c, s) {
    if (!c.enabled) return "未开启：主模型出错时不会自动改用备用模型。";
    const p = s && s.primary;
    if (!p) return "已开启";
    const act = s.active ? s.active.name : p.name;
    let t = `<span class="fo-dot ${esc(p.state)}"></span>主模型 ${esc(p.name)} ${esc(STATE_ZH[p.state] || p.state)} · 当前使用 ${esc(act)}`;
    if (s.last_switch && s.last_switch.to !== p.id) t += ` · 切换原因：${esc(s.last_switch.reason || "—")}`;
    return t;
  }
  function refreshSummary() {
    const el = document.getElementById("foSumLine");
    if (el && st) el.innerHTML = summaryHtml(st.config, st.status);
    const b = document.getElementById("foSumBadge");
    if (b && st) { b.textContent = st.config.enabled ? "已开启" : "未开启"; b.className = "mr-status" + (st.config.enabled ? " is-on" : ""); }
  }

  function render() {
    const box = document.getElementById("llmFailoverBox");
    if (!box || !st) return;
    const c = st.config;
    const llms = st.llms || [];
    const primaryOpts = `<option value=""${c.primary_llm_id ? "" : " selected"}>跟随默认模型（推荐：把 Kaggle 设为默认）</option>` +
      llms.map((l) => `<option value="${esc(l.id)}"${l.id === c.primary_llm_id ? " selected" : ""}>${esc(llmLabel(l))}</option>`).join("");
    const pid = c.primary_llm_id || ((llms.find((l) => l.is_default) || {}).id || "");
    const bk = (c.backup_llm_ids || []);
    const addable = llms.filter((l) => l.id !== pid && !bk.includes(l.id) && !l.is_cli);
    let bkHtml = bk.map((id, i) => `<div class="fo-bk" data-id="${esc(id)}"><span class="mr-tag fo-bk-n" title="${esc(nameOf(id))}">${i + 1}. ${esc(nameOf(id))}</span>
        <button type="button" class="btn icon-btn" data-fo="bk-up" ${i ? "" : "disabled"} title="上移">${ic("to-top", "ipk-sm")}</button>
        <button type="button" class="btn icon-btn" data-fo="bk-del" title="移除">${ic("delete", "ipk-sm")}</button></div>`).join("");
    if (!bk.length) bkHtml = `<span class="mr-tag is-empty">还没有备用模型，至少加一个（如 DeepSeek）</span>`;
    const num = (k, label) => `<label class="agent-field agent-field-sm">${label}<input type="number" min="1" step="1" data-num="${k}" value="${esc(c[k])}"></label>`;
    const pushUrl = location.origin + "/api/llm-push/primary";
    const prevDet = document.getElementById("foPushDet");
    const detOpen = prevDet ? prevDet.open : false;
    const prevAdv = document.getElementById("foAdvDet");
    const advOpen = prevAdv ? prevAdv.open : false;
    box.innerHTML = `<section class="mr-section fo-card" id="llmFailoverSection">
      <details class="fo-fold" id="foFold"${foldOpen ? " open" : ""}>
        <summary>
          <span class="mr-section-title">${ic("connection")} 主备自动切换</span>
          <span class="mr-status${c.enabled ? " is-on" : ""}" id="foSumBadge">${c.enabled ? "已开启" : "未开启"}</span>
          <span class="fo-sum-line" id="foSumLine">${summaryHtml(c, st.status)}</span>
        </summary>
        <div class="fo-body">
          <p class="mr-section-desc">主模型（如 Kaggle 隧道）连不上、超时、报错或返回 Cloudflare 错误页时，自动改用备用模型（如 DeepSeek）；主模型恢复后自动切回。只作用于主模型本身的调用（默认对话、流式、路由到主模型的功能）。</p>
          <label class="fo-enable"><input type="checkbox" id="foEnabled"${c.enabled ? " checked" : ""}><span>启用主备自动切换</span></label>
          <div class="fo-pair">
            <label class="agent-field">主模型<select id="foPrimary">${primaryOpts}</select></label>
            <div class="agent-field">备用模型（按顺序尝试）
              <div class="fo-backups">${bkHtml}</div>
              ${addable.length ? `<select id="foAddBk"><option value="">＋ 添加备用模型…</option>${addable.map((l) => `<option value="${esc(l.id)}">${esc(llmLabel(l))}</option>`).join("")}</select>` : ""}
            </div>
          </div>
          <div class="fo-tools">
            <label class="fo-enable"><input type="checkbox" id="foToolsBk"${c.tools_use_backup ? " checked" : ""}><span>工具调用/复杂任务始终用备用模型</span></label>
            <p class="hint">开启后带工具的请求先走备用，普通聊天仍走主模型。</p>
          </div>
          <details class="agent-fold-details" id="foAdvDet"${advOpen ? " open" : ""}>
            <summary>超时与熔断<span class="fo-meta">（连接 ${esc(c.connect_timeout)}s · 首字 ${esc(c.first_token_timeout)}s · 冷却 ${esc(c.cooldown_s)}–${esc(c.cooldown_max_s)}s）</span></summary>
            <div class="agent-row agent-row-defaults">
              ${num("connect_timeout", "连接超时（秒）")}
              ${num("first_token_timeout", "首字超时（秒）")}
              ${num("stream_idle_timeout", "中途停顿超时（秒）")}
              ${num("response_timeout", "整体超时（秒）")}
              ${num("cooldown_s", "熔断冷却起始（秒）")}
              ${num("cooldown_max_s", "熔断冷却上限（秒）")}
            </div>
            <p class="hint">连接超时：连不上主模型多久后切换；首字超时：流式多久没出第一个字就切换；中途停顿：流式中途卡住多久算断开；整体超时：非流式（工具调用）整条回复上限；熔断：失败后这段时间内不再试主模型，连续失败翻倍到上限。</p>
          </details>
          <div class="fo-actions">
            <button type="button" class="cfg-tool is-primary" data-fo="save">${ic("save")}<span>保存</span></button>
            <button type="button" class="cfg-tool" data-fo="test">${ic("lightning")}<span>测试主模型</span></button>
            <button type="button" class="cfg-tool" data-fo="reset" title="清除熔断，下一条消息立即重试主模型">${ic("refresh")}<span>立即重试主模型</span></button>
            <span class="form-msg" id="msgLlmFo"></span>
          </div>
          <div class="fo-status" id="foStatus">${statusHtml(st.status)}</div>
          <details class="agent-fold-details" id="foPushDet"${detOpen ? " open" : ""}>
            <summary>推送新地址<span class="fo-meta">（Kaggle 重启后自动更新主模型地址）</span><span class="agent-fold-badge${c.push_token_set ? " is-on" : ""}">${c.push_token_set ? "令牌已设置" : "未设置"}</span></summary>
            <p class="hint">推送令牌：${c.push_token_set ? "已设置（为安全只在生成时显示一次）" : "未设置（推送接口停用）"}</p>
            <div class="fo-actions" style="margin-top:8px">
              <button type="button" class="cfg-tool" data-fo="gen-token">${ic("shield")}<span>${c.push_token_set ? "重新生成令牌" : "生成推送令牌"}</span></button>
              ${c.push_token_set ? `<button type="button" class="cfg-tool" data-fo="clear-token">${ic("forbid")}<span>停用推送</span></button>` : ""}
            </div>
            <div id="foTokenOut"></div>
            <p class="hint">笔记本里隧道起来后调用（EVA 需能从公网访问，例如通过你自己的隧道/端口映射）：</p>
            <div class="fo-code">curl -X POST ${esc(pushUrl)} \\
  -H "Authorization: Bearer &lt;推送令牌&gt;" -H "Content-Type: application/json" \\
  -d '{"base_url":"https://xxxx.trycloudflare.com/v1","api_key":"&lt;Kaggle 的 Key&gt;","model":"eva-uncensored"}'</div>
          </details>
        </div>
      </details>
    </section>`;
    const fold = document.getElementById("foFold");
    if (fold) fold.addEventListener("toggle", () => { foldOpen = fold.open; });
  }

  function readForm() {
    const c = Object.assign({}, st.config);
    c.enabled = document.getElementById("foEnabled").checked;
    c.primary_llm_id = document.getElementById("foPrimary").value;
    c.tools_use_backup = document.getElementById("foToolsBk").checked;
    document.querySelectorAll("#llmFailoverBox [data-num]").forEach((el) => {
      const v = parseFloat(el.value);
      if (!isNaN(v)) c[el.dataset.num] = v;
    });
    delete c.push_token_set;
    return c;
  }

  async function save() {
    try {
      const d = await j("/api/llm/failover", { method: "PUT", body: JSON.stringify({ config: readForm() }) });
      st.config = d.config; st.status = d.status;
      render(); msg("已保存，立即生效", "ok"); chip(st.status);
    } catch (e) { msg(e.message, "error"); }
  }

  async function onClick(e) {
    const b = e.target.closest("[data-fo]");
    if (!b || b.disabled) return;
    const act = b.dataset.fo;
    if (act === "save") return save();
    if (act === "bk-up" || act === "bk-del") {
      const id = b.closest(".fo-bk").dataset.id;
      const list = (st.config.backup_llm_ids || []).slice();
      const i = list.indexOf(id);
      if (act === "bk-del") list.splice(i, 1);
      else if (i > 0) [list[i - 1], list[i]] = [list[i], list[i - 1]];
      st.config = Object.assign(readForm(), { backup_llm_ids: list, push_token_set: st.config.push_token_set });
      render(); msg("备用顺序已改，记得保存", "");
      return;
    }
    if (act === "test") {
      msg("测试中…");
      b.disabled = true;
      try {
        const d = await j("/api/llm/failover/test", { method: "POST", body: "{}" });
        st.status = d.status;
        render();
        const p = d.probe || {}, c = d.chat || {};
        const t = `探测 ${p.ok ? "成功" + (p.ms != null ? "（" + p.ms + "ms）" : "") : "失败：" + (p.error || "")}；对话 ${c.ok ? "成功（" + c.ms + "ms）：" + (c.reply || "") : "失败：" + (c.error || "")}`;
        msg(t, d.ok ? "ok" : "error");
        chip(d.status);
      } catch (e2) { msg(e2.message, "error"); }
      return;
    }
    if (act === "reset") {
      try { const d = await j("/api/llm/failover/reset", { method: "POST", body: "{}" }); st.status = d.status; render(); msg("已清除熔断，下一条消息会先试主模型", "ok"); chip(d.status); }
      catch (e2) { msg(e2.message, "error"); }
      return;
    }
    if (act === "gen-token") {
      if (st.config.push_token_set && !confirm("重新生成后旧令牌立即失效，继续？")) return;
      try {
        const d = await j("/api/llm/failover/push_token", { method: "POST", body: "{}" });
        st.config.push_token_set = true;
        render();
        document.getElementById("foTokenOut").innerHTML = `<p class="hint">新令牌（只显示这一次，请复制保存到 Kaggle 笔记本的 Secrets）：</p><div class="fo-token">${esc(d.push_token)}</div>`;
        msg("已生成推送令牌", "ok");
      } catch (e2) { msg(e2.message, "error"); }
      return;
    }
    if (act === "clear-token") {
      if (!confirm("停用推送接口？")) return;
      try { await j("/api/llm/failover/push_token", { method: "DELETE" }); st.config.push_token_set = false; render(); msg("推送接口已停用", "ok"); }
      catch (e2) { msg(e2.message, "error"); }
    }
  }

  function onChange(e) {
    if (e.target.id === "foAddBk" && e.target.value) {
      const list = (st.config.backup_llm_ids || []).slice();
      list.push(e.target.value);
      st.config = Object.assign(readForm(), { backup_llm_ids: list, push_token_set: st.config.push_token_set });
      render(); msg("已加入备用，记得保存", "");
    }
    if (e.target.id === "foPrimary") {
      const pid = e.target.value || ((st.llms.find((l) => l.is_default) || {}).id || "");
      st.config = Object.assign(readForm(), { push_token_set: st.config.push_token_set });
      st.config.backup_llm_ids = (st.config.backup_llm_ids || []).filter((x) => x !== pid);
      render();
    }
  }

  async function load() {
    css();
    const host = document.getElementById("modelRoutingBox");
    if (!host) return;
    let box = document.getElementById("llmFailoverBox");
    if (!box) {
      box = document.createElement("div");
      box.id = "llmFailoverBox";
      host.parentNode.insertBefore(box, host.nextSibling); // 放在原生路由内容之后，不挤动原有布局
      box.addEventListener("click", onClick);
      box.addEventListener("change", onChange);
    }
    try {
      st = await j("/api/llm/failover");
      render();
      chip(st.status);
    } catch (e) {
      box.innerHTML = `<section class="mr-section fo-card" id="llmFailoverSection"><div class="mr-section-titles"><div class="mr-section-title">${ic("connection")} 主备自动切换</div>
        <p class="mr-section-desc">${e.status === 404 ? "功能已安装，需重启 EVA 后可用。" : "载入失败：" + esc(e.message)}</p></div></section>`;
    }
  }

  /* ---- 顶栏小标签：仅在开启时显示 ---- */
  function chip(s) {
    let el = document.getElementById("llmFoChip");
    if (!s || !s.enabled || !s.primary) { if (el) el.hidden = true; return; }
    if (!el) {
      const anchor = document.getElementById("modeHint");
      if (!anchor || !anchor.parentNode) return;
      el = document.createElement("button");
      el.type = "button";
      el.id = "llmFoChip";
      el.className = "hint-chip top-hint-chip";
      el.addEventListener("click", () => {
        try { if (window.L && typeof window.L.openConfig === "function") window.L.openConfig("routing"); } catch (_) {}
      });
      anchor.parentNode.insertBefore(el, anchor);
    }
    const onPrimary = s.active && s.active.id === s.primary.id && s.primary.state !== "down";
    el.hidden = false;
    el.textContent = onPrimary ? "主模型" : (s.primary.state === "down" ? "备用中" : "主模型");
    el.className = "hint-chip top-hint-chip " + (onPrimary || s.primary.state !== "down" ? "fo-up" : "fo-backup");
    let tip = `主模型 ${s.primary.name}：${STATE_ZH[s.primary.state] || s.primary.state}`;
    if (s.active) tip += `\n当前使用：${s.active.name}`;
    if (s.last_switch) tip += `\n最近切换原因：${s.last_switch.reason || "—"}`;
    el.title = tip + "\n（点一下打开设定 → 模型路由）";
    const sb = document.getElementById("foStatus");
    if (sb && st) { st.status = s; sb.innerHTML = statusHtml(s); }
    if (st) { st.status = s; refreshSummary(); }
  }
  async function poll() {
    try { chip(await j("/api/llm/failover/status")); }
    catch (e) { if (e.status === 404) { clearInterval(pollTimer); pollTimer = null; } }
  }
  function startPoll() {
    if (pollTimer) return;
    css(); // 顶栏标签样式需在设定页打开前就生效
    poll();
    pollTimer = setInterval(() => { if (!document.hidden) poll(); }, 30000);
  }

  const orig = window.loadModelRouting;
  window.loadModelRouting = async function () {
    const r = orig ? orig.apply(this, arguments) : undefined;
    load();
    return r;
  };
  window.loadLlmFailover = load;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", startPoll);
  else startPoll();
})();
