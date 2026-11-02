/* 设定 → 模型路由：默认模型 + 自定义规则（弹窗编辑） */
(function () {
  "use strict";
  let state = null;
  let editingId = null; // null | "new" | rule id

  const CHAT_FEATURES_NO_CLI = new Set([
    "chat.web", "chat.stream", "chat.roleplay", "chat.webhook",
    "chat.scheduler", "chat.workflow", "vision", "skill", "tool_final",
  ]);
  function isCliLlm(id) {
    const l = (state.llms || []).find((x) => x.id === id);
    return !!(l && l.is_cli);
  }
  function hasChatFeature(features) {
    return (features || []).some((f) => CHAT_FEATURES_NO_CLI.has(f) || String(f).startsWith("skill:"));
  }

  async function j(path, opt) {
    const r = await fetch(path, Object.assign({ credentials: "same-origin", headers: { "Content-Type": "application/json" } }, opt || {}));
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || "HTTP " + r.status);
    return d;
  }
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const ic = (n, c) => (window.IconParkUI ? window.IconParkUI.icon(n, c || "ipk-xs") : "");

  function msg(t, kind) {
    const m = document.getElementById("msgModelRouting");
    if (m) { m.textContent = t || ""; m.className = "form-msg" + (kind ? " " + kind : ""); }
  }

  function llmLabel(l) {
    let s = l.name || l.id;
    if (l.model && l.model !== l.name) s += " · " + l.model;
    if (l.is_cli) s += " · CLI";
    if (l.is_default) s += "（默认）";
    if (!l.enabled) s += "（已停用）";
    return s;
  }
  function llmOptions(sel, emptyLabel) {
    let h = emptyLabel != null
      ? `<option value="">${esc(emptyLabel)}</option>`
      : '<option value="" disabled' + (sel ? "" : " selected") + ">选择模型…</option>";
    for (const l of state.llms) {
      h += `<option value="${esc(l.id)}"${l.id === sel ? " selected" : ""}>${esc(llmLabel(l))}</option>`;
    }
    if (sel && !state.llms.some((l) => l.id === sel)) {
      h += `<option value="${esc(sel)}" selected>（已删除的模型，将回退默认）</option>`;
    }
    return h;
  }
  function featLabel(id) {
    if (id.startsWith("skill:")) {
      const sid = id.slice(6);
      const s = state.skills.find((x) => x.id === sid);
      return "技能 · " + (s ? s.label : sid);
    }
    const f = state.features.find((x) => x.id === id);
    return f ? f.label : id;
  }
  function llmName(id) {
    const l = state.llms.find((x) => x.id === id);
    return l ? llmLabel(l) : "（已删除的模型）";
  }

  function featureGroupsHtml(selected) {
    const sel = new Set(selected || []);
    const groups = {};
    for (const f of state.features) (groups[f.group] = groups[f.group] || []).push(f);
    let feats = "";
    for (const [g, list] of Object.entries(groups)) {
      feats += `<div class="mr-fgroup"><div class="mr-fgroup-title">${esc(g)}</div><div class="mr-chips">`;
      for (const f of list) {
        feats += `<label class="mr-chip" title="${esc(f.hint || "")}"><input type="checkbox" value="${esc(f.id)}"${sel.has(f.id) ? " checked" : ""}><span>${esc(f.label)}</span></label>`;
      }
      feats += "</div></div>";
    }
    if (state.skills.length) {
      feats += `<div class="mr-fgroup"><div class="mr-fgroup-title">指定技能</div><div class="mr-chips mr-skill-chips">`;
      for (const s of state.skills) {
        const id = "skill:" + s.id;
        feats += `<label class="mr-chip" title="${esc(s.id)}"><input type="checkbox" value="${esc(id)}"${sel.has(id) ? " checked" : ""}><span>${esc(s.label)}</span></label>`;
      }
      feats += "</div></div>";
    }
    return feats;
  }

  function fillEditor(rule) {
    const r = rule || { name: "", features: [], llm_id: "", enabled: true };
    const nameEl = document.getElementById("mrEdName");
    const llmEl = document.getElementById("mrEdLlm");
    const enEl = document.getElementById("mrEdEnabled");
    const featsEl = document.getElementById("mrEdFeatures");
    const titleEl = document.getElementById("mrEditorTitle");
    if (!nameEl || !llmEl || !enEl || !featsEl) return;
    if (titleEl) {
      const label = editingId === "new" ? "新增路由规则" : "编辑路由规则";
      const icon = titleEl.querySelector("[data-ipk], .ipk, svg");
      titleEl.textContent = "";
      if (icon) titleEl.appendChild(icon);
      else if (window.IconParkUI) titleEl.insertAdjacentHTML("afterbegin", window.IconParkUI.icon("category-management", "ipk-sm") + " ");
      titleEl.appendChild(document.createTextNode(" " + label));
    }
    nameEl.value = r.name || "";
    llmEl.innerHTML = llmOptions(r.llm_id);
    enEl.checked = r.enabled !== false;
    featsEl.innerHTML = featureGroupsHtml(r.features);
    const hint = document.getElementById("mrEdMsg");
    if (hint) { hint.textContent = ""; hint.className = "form-msg"; }
  }

  function openEditor(rule) {
    fillEditor(rule);
    const modal = document.getElementById("modelRoutingEditorModal");
    if (modal) modal.classList.remove("hidden");
    setTimeout(() => {
      const n = document.getElementById("mrEdName");
      if (n) n.focus();
    }, 30);
  }

  function closeEditor() {
    editingId = null;
    const modal = document.getElementById("modelRoutingEditorModal");
    if (modal) modal.classList.add("hidden");
  }

  function ruleCard(r, idx) {
    const pills = (r.features || []).map((f) => `<span class="mr-tag">${esc(featLabel(f))}</span>`).join("");
    const on = !!r.enabled;
    return `<article class="mr-rule${on ? "" : " is-off"}" data-id="${esc(r.id)}">
      <div class="mr-rule-main">
        <div class="mr-rule-top">
          <span class="mr-ord" title="匹配优先级">#${idx + 1}</span>
          <h4 class="mr-rule-name">${esc(r.name || "未命名规则")}</h4>
          <span class="mr-status ${on ? "is-on" : ""}">${on ? "启用" : "停用"}</span>
        </div>
        <div class="mr-rule-tags">${pills || '<span class="mr-tag is-empty">未选功能</span>'}</div>
        <div class="mr-rule-target">${ic("right")} <span>${esc(llmName(r.llm_id))}</span></div>
      </div>
      <div class="mr-rule-actions">
        <button type="button" class="btn icon-btn" data-act="up" title="上移（越靠前越优先）" ${idx === 0 ? "disabled" : ""}>${ic("to-top", "ipk-sm")}</button>
        <button type="button" class="btn icon-btn" data-act="toggle" title="${on ? "停用" : "启用"}">${ic(on ? "forbid" : "check-one", "ipk-sm")}</button>
        <button type="button" class="btn icon-btn" data-act="edit" title="编辑">${ic("edit", "ipk-sm")}</button>
        <button type="button" class="btn icon-btn" data-act="del" title="删除">${ic("delete", "ipk-sm")}</button>
      </div>
    </article>`;
  }

  function render() {
    const box = document.getElementById("modelRoutingBox");
    if (!box || !state) return;
    const r = state.routing;
    const n = (r.rules || []).length;
    let h = "";
    h += `<section class="mr-section mr-section-default">
      <header class="mr-section-head">
        <div class="mr-section-titles">
          <div class="mr-section-title">${ic("config")} 默认设置</div>
          <p class="mr-section-desc">没有规则命中时使用的兜底模型。可留空，跟随「模型」页的默认。</p>
        </div>
      </header>
      <div class="mr-default-row">
        <label class="agent-field mr-default-field">
          <span>默认模型</span>
          <select id="mrDefault">${llmOptions(r.default_llm, "跟随「模型」页的默认模型")}</select>
        </label>
      </div>
    </section>`;

    h += `<section class="mr-section mr-section-rules">
      <header class="mr-section-head">
        <div class="mr-section-titles">
          <div class="mr-section-title">${ic("list")} 自定义规则 <em class="mr-count">${n}</em></div>
          <p class="mr-section-desc">按功能点多选指定模型；列表自上而下匹配，取第一条已启用规则。</p>
        </div>
        <div class="cfg-tool-cluster">
          <button type="button" class="cfg-tool is-primary" data-act="add">${ic("plus")}<span>新增规则</span></button>
        </div>
      </header>`;

    if (!n) {
      h += `<div class="mr-empty">
        <div class="mr-empty-icon">${ic("category-management", "ipk-lg")}</div>
        <div class="mr-empty-title">还没有自定义规则</div>
        <p class="mr-empty-text">所有功能都会走上方的默认模型。需要按识图、技能、定时任务等分流时，点右上角新增。</p>
        <button type="button" class="cfg-tool is-primary" data-act="add">${ic("plus")}<span>新增第一条规则</span></button>
      </div>`;
    } else {
      h += `<div class="mr-rule-list">`;
      r.rules.forEach((rule, i) => { h += ruleCard(rule, i); });
      h += `</div>`;
    }
    h += `</section>`;
    box.innerHTML = h;
  }

  async function persist(next, okText) {
    try {
      const d = await j("/api/config/model_routing", { method: "PUT", body: JSON.stringify({ routing: next }) });
      state.routing = d.routing;
      render();
      msg(okText || "已保存，立即生效", "ok");
      return true;
    } catch (e) {
      msg(e.message, "error");
      return false;
    }
  }

  function readEditor() {
    const name = (document.getElementById("mrEdName").value || "").trim();
    const llm_id = document.getElementById("mrEdLlm").value;
    const enabled = document.getElementById("mrEdEnabled").checked;
    const features = [...document.querySelectorAll("#mrEdFeatures input:checked")].map((x) => x.value);
    if (!features.length) throw new Error("请至少选择一个功能");
    if (!llm_id) throw new Error("请选择目标模型");
    if (isCliLlm(llm_id) && hasChatFeature(features)) {
      throw new Error("对话类功能不能选 CLI 模型（工具循环会静默退回默认）。请改用 API 模型，或只把 CLI 绑到非对话功能。");
    }
    return { name: name || "未命名规则", llm_id, enabled, features };
  }

  function edMsg(t, kind) {
    const m = document.getElementById("mrEdMsg");
    if (m) { m.textContent = t || ""; m.className = "form-msg" + (kind ? " " + kind : ""); }
  }

  async function saveEditor() {
    let v;
    try { v = readEditor(); }
    catch (err) { edMsg(err.message, "error"); return; }
    const rules = state.routing.rules.map((x) => Object.assign({}, x));
    const base = { default_llm: state.routing.default_llm };
    if (editingId === "new") rules.push(Object.assign({ id: "" }, v));
    else {
      const i = rules.findIndex((x) => x.id === editingId);
      if (i >= 0) rules[i] = Object.assign(rules[i], v);
    }
    const ok = await persist(Object.assign(base, { rules }), editingId === "new" ? "规则已添加" : "规则已更新");
    if (ok) closeEditor();
  }

  function onBoxClick(e) {
    const b = e.target.closest("[data-act]");
    if (!b || b.disabled) return;
    const act = b.dataset.act;
    const card = b.closest(".mr-rule");
    const id = card && card.dataset.id;
    const rules = state.routing.rules.map((x) => Object.assign({}, x));
    const base = { default_llm: state.routing.default_llm };

    if (act === "add") {
      editingId = "new";
      openEditor(null);
      return;
    }
    if (!id) return;
    const i = rules.findIndex((x) => x.id === id);
    if (i < 0) return;

    if (act === "edit") {
      editingId = id;
      openEditor(rules[i]);
      return;
    }
    if (act === "del") {
      if (!confirm("删除规则「" + (rules[i].name || "未命名规则") + "」？")) return;
      rules.splice(i, 1);
      persist(Object.assign(base, { rules }), "已删除");
    } else if (act === "toggle") {
      rules[i].enabled = !rules[i].enabled;
      persist(Object.assign(base, { rules }));
    } else if (act === "up" && i > 0) {
      [rules[i - 1], rules[i]] = [rules[i], rules[i - 1]];
      persist(Object.assign(base, { rules }));
    }
  }

  function onBoxChange(e) {
    if (e.target.id === "mrDefault") {
      persist({ default_llm: e.target.value, rules: state.routing.rules });
    }
  }

  function refreshCliHint() {
    const hint = document.getElementById("mrEdMsg");
    if (!hint) return;
    try {
      const llm_id = document.getElementById("mrEdLlm").value;
      const features = [...document.querySelectorAll("#mrEdFeatures input:checked")].map((x) => x.value);
      if (isCliLlm(llm_id) && hasChatFeature(features)) {
        hint.textContent = "警告：对话类功能选 CLI 会在工具循环静默退回默认模型，无法保存。";
        hint.className = "form-msg error";
      } else if (hint.className.indexOf("error") >= 0 && hint.textContent.indexOf("CLI") >= 0) {
        hint.textContent = "";
        hint.className = "form-msg";
      }
    } catch (_) {}
  }

  function bindEditorModal() {
    const modal = document.getElementById("modelRoutingEditorModal");
    if (!modal || modal.dataset.bound) return;
    modal.dataset.bound = "1";
    modal.addEventListener("change", (e) => {
      if (e.target && (e.target.id === "mrEdLlm" || e.target.closest("#mrEdFeatures"))) refreshCliHint();
    });
    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeEditor();
      const b = e.target.closest("[data-act]");
      if (!b) return;
      if (b.dataset.act === "cancel-ed") closeEditor();
      if (b.dataset.act === "save-ed") saveEditor();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && modal && !modal.classList.contains("hidden")) closeEditor();
    });
  }

  async function load() {
    const box = document.getElementById("modelRoutingBox");
    if (!box) return;
    if (!box.dataset.bound) {
      box.addEventListener("click", onBoxClick);
      box.addEventListener("change", onBoxChange);
      box.dataset.bound = "1";
    }
    bindEditorModal();
    try {
      state = await j("/api/config/model_routing");
      editingId = null;
      closeEditor();
      render();
      msg("");
    } catch (e) {
      msg("载入路由失败：" + e.message, "error");
    }
  }
  window.loadModelRouting = load;
})();
