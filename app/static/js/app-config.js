/**
 * Lily - Config Panel
 */
((L) => {
 "use strict";
 const { $, els, state, showToast, renderSkeleton, escapeHtml, setMsg } = L;
 const _ipk = (n, c) => (typeof L.ipk === "function" ? L.ipk(n, c) : "");
 const _ipkLabel = (n, t, c) =>
   typeof L.ipkLabel === "function" ? L.ipkLabel(n, t, c) : t || "";

 const api = (...a) => L.api(...a);
 const loadHealth = (...a) => L.loadHealth(...a);
 const loadTasks = (...a) => L.loadTasks(...a);
 const loadMemory = (...a) => L.loadMemory(...a);
 const closeMobileSidebar = (...a) => L.closeMobileSidebar(...a);

 function getConfigModal() {
 return document.getElementById("configModal") || els.configModal;
 }

 /** Nested editor modals stacked above settings (LLM / Tools / MCP / …) */
 const CFG_NESTED_MODALS = [
 "llmEditorModal",
 "customToolEditorModal",
 "mcpEditorModal",
 "integrationEditorModal",
 "memoryAddModal",
 "webhookEditorModal",
 "wsFileModal",
 "promptEditorModal",
 ];

 function openNestedEditor(modalId) {
 const m = $(modalId);
 if (!m) return null;
 m.classList.remove("hidden");
 document.body.classList.add("cfg-nested-open");
 if (typeof L.hydrateIconPark === "function") L.hydrateIconPark(m);
 return m;
 }

 function closeNestedEditor(modalId) {
 if (modalId) $(modalId)?.classList.add("hidden");
 const anyOpen = CFG_NESTED_MODALS.some((id) => {
 const el = $(id);
 return el && !el.classList.contains("hidden");
 });
 // also kb/task/wf nested
 const other =
 document.querySelector(
 "#kbPageModal:not(.hidden), #taskPageModal:not(.hidden), #wfPageModal:not(.hidden), #wfRunModal:not(.hidden), #wfRunDetailModal:not(.hidden)"
 );
 if (!anyOpen && !other) {
 document.body.classList.remove("cfg-nested-open");
 document.body.classList.remove("ws-file-modal-open");
 }
 }

 function bindNestedBackdropClose(modalId, closeFn) {
 const m = $(modalId);
 if (!m || m.dataset.backdropBound === "1") return;
 m.dataset.backdropBound = "1";
 m.addEventListener("click", (e) => {
 if (e.target === m) closeFn();
 });
 }

 // ==================== Config 面板 ====================
 function ensureNestedBackdropBinds() {
  // 嵌套编辑器在 modal HTML 注入后才存在；可重复调用，内部有 once 标记
  try {
   bindNestedBackdropClose("llmEditorModal", closeLlmEditor);
   bindNestedBackdropClose("customToolEditorModal", closeCustomToolEditor);
   bindNestedBackdropClose("mcpEditorModal", closeMcpEditor);
   bindNestedBackdropClose("integrationEditorModal", closeIntegrationEditor);
   bindNestedBackdropClose("promptEditorModal", closePromptEditor);
  } catch (_) {}
 }

 async function ensureConfigModal() {
 // index.html starts async fetch; wait if still in flight
 if (typeof window.__configModalReady !== "undefined") {
  try {
   await window.__configModalReady;
  } catch (_) {}
 }
 let modal = getConfigModal();
 if (modal) {
  ensureNestedBackdropBinds();
  return modal;
 }
 // retry once if first paint raced the inject
 try {
  const r = await fetch("/static/html/config-modal.html", {
   credentials: "same-origin",
  });
  if (r.ok) {
   const html = await r.text();
   const c = document.getElementById("configModalContainer");
   if (c && !getConfigModal()) c.innerHTML = html;
  }
 } catch (_) {}
 modal = getConfigModal();
 if (modal) ensureNestedBackdropBinds();
 return modal;
 }

 async function openConfig(tab) {
 closeMobileSidebar();
 const modal = await ensureConfigModal();
 if (!modal) {
 showToast("设定面板加载失败，请刷新页面", "error");
 return;
 }
 els.configModal = modal;
 modal.classList.remove("hidden");
 document.body.classList.add("modal-open");
 if (typeof L.hydrateIconPark === "function") L.hydrateIconPark(modal);

 const target =
  tab ||
  document.querySelector("#configTabs .tab.active")?.dataset.tab ||
  "agent";

 // 有缓存：立刻画界面并切到目标页，避免对话生成中还卡在「载入中…」
 const hasCache = !!(state.config && typeof state.config === "object");
 if (hasCache) {
  try {
   renderAgentForm(state.config);
  } catch (_) {}
  switchTab(target, { soft: true });
  // 后台静默刷新人设（面板由 switchTab 按需加载）
  loadConfig({ soft: true, panels: false }).catch(() => {});
  return;
 }

 // 首次打开：载入人设后切 tab（switchTab 再拉对应面板）
 loadConfig({ soft: false, panels: false })
  .then(() => switchTab(target, { soft: false }))
  .catch(() => switchTab(target, { soft: false }));
 }

 function closeConfig() {
 // close nested editors first
 CFG_NESTED_MODALS.forEach((id) => $(id)?.classList.add("hidden"));
 document.body.classList.remove("cfg-nested-open");
 document.body.classList.remove("ws-file-modal-open");
 const modal = getConfigModal();
 if (modal) modal.classList.add("hidden");
 document.body.classList.remove("modal-open");
 loadHealth();
 }

 const CFG_TAB_GROUP = {
  agent: "daily",
  llm: "daily",
  integrations: "daily",
  skills: "capability",
  tools: "system",
  tasks: "capability",
  memory: "capability",
  kb: "capability",
  workspace: "capability",
  workflows: "capability",
  mcp: "system",
  webhooks: "system",
  storage: "system",
  office: "system",
  update: "system",
 };
 const _cfgGroupTab = {
  daily: "agent",
  capability: "skills",
  system: "mcp",
 };

 function groupForTab(name) {
  return CFG_TAB_GROUP[name] || "daily";
 }

 function applyConfigGroup(group, root) {
  const el = root || getConfigModal() || document;
  el.querySelectorAll("#configGroups .cfg-group").forEach((b) => {
   const on = b.dataset.group === group;
   b.classList.toggle("active", on);
   b.setAttribute("aria-selected", on ? "true" : "false");
  });
  el.querySelectorAll("#configTabs .tab").forEach((t) => {
   t.hidden = false;
   t.removeAttribute("hidden");
   t.setAttribute("aria-hidden", "false");
  });
  el.querySelectorAll(".cfg-side-block").forEach((b) => {
   b.classList.toggle("is-active", b.dataset.sideGroup === group);
  });
 }

 function switchConfigGroup(group) {
  const g = group || "daily";
  const root = getConfigModal() || document;
  const current = root.querySelector("#configTabs .tab.active")?.dataset.tab;
  if (current && groupForTab(current) === g) {
   applyConfigGroup(g, root);
   return;
  }
  switchTab(_cfgGroupTab[g] || "agent");
 }

 function switchTab(name, opts = {}) {
 const soft = !!opts.soft;
 const tab = name || "agent";
 const group = groupForTab(tab);
 _cfgGroupTab[group] = tab;
 // 只操作设定窗内的 tab，避免和页面其它 .tab 冲突
 const root = getConfigModal() || document;
 applyConfigGroup(group, root);
 root.querySelectorAll("#configTabs .tab").forEach((t) =>
  t.classList.toggle("active", t.dataset.tab === tab)
 );
 root.querySelectorAll(".tab-panel").forEach((p) =>
  p.classList.toggle("active", p.dataset.panel === tab)
 );
 // soft：有内容时不先清空再 skeleton，对话生成中也能立刻看到上次数据
 if (tab === "tasks") loadTasks({ soft });
 if (tab === "memory") loadMemory($("memSearch")?.value || "", { soft });
 if (tab === "kb") typeof L.loadKb === "function" && L.loadKb($("kbSearch")?.value || "", { soft });
 if (tab === "workflows")
  typeof L.loadWorkflows === "function" && L.loadWorkflows({ soft });
 if (tab === "workspace")
  typeof L.loadWorkspace === "function" && L.loadWorkspace(undefined, { soft });
 if (tab === "webhooks")
  typeof L.loadWebhooks === "function" && L.loadWebhooks({ soft });
 if (tab === "storage") {
  try {
   loadStorage({ soft });
  } catch (e) {
   console.warn("loadStorage", e);
  }
 }
 if (tab === "llm") loadLlms({ soft });
 if (tab === "tools") loadToolsPanel({ soft });
 if (tab === "skills") loadSkills({ soft });
 if (tab === "mcp") loadMcp({ soft });
 if (tab === "integrations") loadIntegrations({ soft });
 if (tab === "office") loadOfficePairing({ soft });
 if (tab === "update") loadAppUpdate({ soft });
 const activeTab = root.querySelector(
  `#configTabs .tab[data-tab="${tab}"]`
 );
 if (activeTab)
  activeTab.scrollIntoView({
   behavior: "smooth",
   block: "nearest",
   inline: "nearest",
  });
 const body = root.querySelector(".modal-body");
 if (body) body.scrollTop = 0;
 }

 function _panelHasContent(el) {
  if (!el) return false;
  if (el.querySelector(".card, .session-item, .wf-def-card, .llm-card, tr, .ws-item"))
   return true;
  // 非空且不是纯 skeleton
  const kids = el.children;
  if (!kids || !kids.length) return false;
  return !el.querySelector(".skeleton");
 }

 async function loadConfig(opts = {}) {
 const soft = !!opts.soft;
 // panels: true=加载当前 tab 面板；false=只拉人设/基础配置（启动预热用）
 const loadPanels = opts.panels !== false;
 try {
 // 有缓存时不先挡界面；后台拉最新
 if (!soft || !state.config) {
  setMsg("msgAgent", soft ? "" : "载入中…");
 }
 const cfg = await api("/api/config");
 state.config = cfg;
 state.configLoadedAt = Date.now();
 renderAgentForm(cfg);
 setMsg("msgAgent", "", "");
 if (!loadPanels) return;
 // 只刷新当前可见 tab，避免启动/打开设定时并行打 5 个重接口
 const active =
  document.querySelector("#configTabs .tab.active")?.dataset.tab || "agent";
 const softOpt = { soft };
 if (active === "llm") await loadLlms(softOpt);
 else if (active === "tools") await loadToolsPanel(softOpt);
 else if (active === "skills") await loadSkills(softOpt);
 else if (active === "mcp") await loadMcp(softOpt);
 else if (active === "integrations") await loadIntegrations(softOpt);
 else if (active === "tasks" && typeof L.loadTasks === "function")
  await L.loadTasks({ soft: true });
 else if (active === "memory" && typeof L.loadMemory === "function")
  await L.loadMemory($("memSearch")?.value || "", { soft: true });
 else if (active === "storage") await loadStorage(softOpt);
 } catch (e) {
 setMsg("msgAgent", "读取配置失败: " + e.message, "error");
 // 有旧缓存时不弹致命 toast 打扰生成中的操作
 if (!soft || !state.config) showToast("读取配置失败", "error");
 }
 }

 function _asArr(v) {
  if (Array.isArray(v)) return v.map((x) => String(x || "").trim()).filter(Boolean);
  const s = String(v || "").trim();
  if (!s) return [];
  return s
   .split(/[,，、]/)
   .map((x) => x.trim())
   .filter(Boolean);
 }

 function _uniq(list) {
  const out = [];
  const seen = new Set();
  for (const x of list || []) {
   const t = String(x || "").trim();
   if (!t) continue;
   const k = t.toLowerCase();
   if (seen.has(k)) continue;
   seen.add(k);
   out.push(t);
  }
  return out;
 }

 function _filterHidden(list, hidden) {
  const ban = new Set(_asArr(hidden).map((x) => x.toLowerCase()));
  return _asArr(list).filter((x) => !ban.has(x.toLowerCase()));
 }

 // Agent 身份已改为纯文本「角色背景」；多选仅保留给其它面板复用结构
 const MS_KEYS = [];
 const MS_CONTAINERS = {};
 const MS_VALUE_FIELDS = {};

 /** 角色背景：优先 background；旧版 role 多选标签作一次性回填 */
 function roleBackgroundFromAgent(a) {
  const bg = String((a && a.background) || "").trim();
  if (bg) return bg;
  const roles = Array.isArray(a && a.role)
   ? a.role.map((x) => String(x || "").trim()).filter(Boolean)
   : [];
  if (roles.length) return roles.join("、");
  return "";
 }

 function _emptyMsMap() {
  const o = {};
  MS_KEYS.forEach((k) => {
   o[k] = [];
  });
  return o;
 }

 function _isPreset(kind, value) {
  const agent = (state.config && state.config.agent) || {};
  const presets = agent.persona_presets || {};
  const v = String(value || "").trim().toLowerCase();
  return _asArr(presets[kind]).some((p) => p.toLowerCase() === v);
 }

 function getMsSelection(kindOrRoot) {
  const root =
   typeof kindOrRoot === "string"
    ? $(MS_CONTAINERS[kindOrRoot])
    : kindOrRoot;
  if (!root) return [];
  return Array.from(root.querySelectorAll(".agent-ms-item.is-on"))
   .map((b) => (b.getAttribute("data-value") || b.dataset.value || "").trim())
   .filter(Boolean);
 }

 function getVisibleOptions(kind) {
  const agent = (state.config && state.config.agent) || {};
  const presets = agent.persona_presets || {};
  return _filterHidden(
   _uniq([...(presets[kind] || []), ...(_personaCustomOpts[kind] || [])]),
   _personaHiddenOpts[kind]
  );
 }

 function _updateMsTrigger(root) {
  if (!root) return;
  const textEl = root.querySelector(".agent-ms-trigger-text");
  if (!textEl) return;
  const selected = getMsSelection(root);
  const ph = root.dataset.placeholder || "请选择";
  if (!selected.length) {
   textEl.textContent = ph;
   textEl.classList.add("is-placeholder");
   textEl.removeAttribute("title");
   root.dataset.selected = "";
   return;
  }
  textEl.classList.remove("is-placeholder");
  const summary =
   selected.length <= 2
    ? selected.join("、")
    : `已选 ${selected.length} 项：${selected.slice(0, 2).join("、")}…`;
  textEl.textContent = summary;
  textEl.title = selected.join("、");
  root.dataset.selected = selected.join("\n");
 }

 function closeAllMs(except) {
  document.querySelectorAll(".agent-ms.is-open").forEach((el) => {
   if (except && el === except) return;
   el.classList.remove("is-open");
   const t = el.querySelector(".agent-ms-trigger");
   if (t) t.setAttribute("aria-expanded", "false");
  });
 }

 function renderMultiSelect(containerId, options, selected, kind) {
  const root = $(containerId);
  if (!root) return;
  const opts = _uniq(options);
  const sel = new Set(_asArr(selected).map((x) => x.toLowerCase()));
  if (!root.dataset.placeholder) {
   root.dataset.placeholder = root.getAttribute("data-placeholder") || "请选择";
  }
  const wasOpen = root.classList.contains("is-open");
  root.dataset.kind = kind;
  root.innerHTML = "";
  if (wasOpen) root.classList.add("is-open");

  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "agent-ms-trigger";
  trigger.setAttribute("aria-haspopup", "listbox");
  trigger.setAttribute("aria-expanded", wasOpen ? "true" : "false");
  const text = document.createElement("span");
  text.className = "agent-ms-trigger-text is-placeholder";
  text.textContent = root.dataset.placeholder || "请选择";
  trigger.appendChild(text);
  const caret = document.createElement("span");
  caret.className = "agent-ms-caret";
  caret.setAttribute("aria-hidden", "true");
  caret.textContent = "▼";
  trigger.appendChild(caret);
  trigger.addEventListener("click", (e) => {
   e.preventDefault();
   e.stopPropagation();
   const open = !root.classList.contains("is-open");
   closeAllMs(root);
   root.classList.toggle("is-open", open);
   trigger.setAttribute("aria-expanded", open ? "true" : "false");
  });
  root.appendChild(trigger);

  const panel = document.createElement("div");
  panel.className = "agent-ms-panel";
  panel.addEventListener("click", (e) => e.stopPropagation());

  const list = document.createElement("div");
  list.className = "agent-ms-list";
  list.setAttribute("role", "listbox");
  list.setAttribute("aria-multiselectable", "true");

  for (const opt of opts) {
   const on = sel.has(opt.toLowerCase());
   // div (not button) to avoid nested-button / full-width input issues
   const item = document.createElement("div");
   item.className = "agent-ms-item" + (on ? " is-on" : "");
   item.setAttribute("data-value", opt);
   item.setAttribute("role", "option");
   item.setAttribute("aria-selected", on ? "true" : "false");
   item.tabIndex = 0;

   const check = document.createElement("span");
   check.className = "agent-ms-check";
   check.setAttribute("aria-hidden", "true");
   check.textContent = "✓";

   const lab = document.createElement("span");
   lab.className = "agent-ms-item-label";
   lab.textContent = opt;
   lab.title = opt;

   const del = document.createElement("button");
   del.type = "button";
   del.className = "agent-ms-item-del";
   del.title = "删除选项";
   del.setAttribute("aria-label", "删除 " + opt);
   del.textContent = "×";
   del.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    removePersonaOption(kind, opt);
   });

   item.appendChild(check);
   item.appendChild(lab);
   item.appendChild(del);

   const toggle = (e) => {
    if (e.target.closest(".agent-ms-item-del")) return;
    e.preventDefault();
    e.stopPropagation();
    item.classList.toggle("is-on");
    const nowOn = item.classList.contains("is-on");
    item.setAttribute("aria-selected", nowOn ? "true" : "false");
    _updateMsTrigger(root);
   };
   item.addEventListener("click", toggle);
   item.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") toggle(e);
   });
   list.appendChild(item);
  }
  panel.appendChild(list);

  const addRow = document.createElement("div");
  addRow.className = "agent-ms-add";
  const addInput = document.createElement("input");
  addInput.type = "text";
  addInput.placeholder = "自定义选项，回车添加";
  addInput.addEventListener("click", (e) => e.stopPropagation());
  addInput.addEventListener("keydown", (e) => {
   if (e.key !== "Enter") return;
   e.preventDefault();
   e.stopPropagation();
   addPersonaOption(kind, addInput);
  });
  const addBtn = document.createElement("button");
  addBtn.type = "button";
  addBtn.className = "btn";
  addBtn.textContent = "添加";
  addBtn.addEventListener("click", (e) => {
   e.preventDefault();
   e.stopPropagation();
   addPersonaOption(kind, addInput);
  });
  addRow.appendChild(addInput);
  addRow.appendChild(addBtn);
  panel.appendChild(addRow);

  root.appendChild(panel);
  _updateMsTrigger(root);
 }

 function fillSelect(selectId, options, selected, fallback) {
  const sel = $(selectId);
  if (!sel) return;
  const opts = _uniq(options || []);
  // empty string is intentional (cleared / fresh config) — do not force fallback
  const raw =
   selected == null || selected === undefined
    ? ""
    : String(selected).trim();
  const cur =
   raw !== ""
    ? raw
    : fallback != null && String(fallback).trim() !== ""
      ? String(fallback).trim()
      : "";
  if (cur && !opts.some((o) => o.toLowerCase() === cur.toLowerCase())) {
   opts.unshift(cur);
  }
  sel.innerHTML = "";
  if (!cur) {
   const empty = document.createElement("option");
   empty.value = "";
   empty.textContent = "（未设置）";
   sel.appendChild(empty);
  }
  for (const opt of opts) {
   const o = document.createElement("option");
   o.value = opt;
   o.textContent = opt;
   if (cur && opt.toLowerCase() === cur.toLowerCase()) o.selected = true;
   sel.appendChild(o);
  }
  if (cur) sel.value = cur;
  else sel.value = "";
 }

 function syncPersonaStateFromCfg(cfg) {
  const a = (cfg && cfg.agent) || {};
  const custom = a.persona_options || {};
  _personaCustomOpts = _emptyMsMap();
  _personaHiddenOpts = _emptyMsMap();
  MS_KEYS.forEach((k) => {
   _personaCustomOpts[k] = _asArr(custom[k]);
   _personaHiddenOpts[k] = _asArr(
    custom[k + "_hidden"] || custom["hidden_" + k]
   );
  });
 }

 let _personaCustomOpts = _emptyMsMap();
 let _personaHiddenOpts = _emptyMsMap();
 let _msDocBound = false;

 function ensureMsDocClose() {
  if (_msDocBound) return;
  _msDocBound = true;
  document.addEventListener("click", () => closeAllMs());
  document.addEventListener("keydown", (e) => {
   if (e.key === "Escape") closeAllMs();
  });
 }

 function refreshMsSection(kind) {
  const containerId = MS_CONTAINERS[kind];
  if (!containerId) return;
  const sel = getMsSelection(kind);
  const opts = getVisibleOptions(kind);
  const keep = sel.filter((s) =>
   opts.some((o) => o.toLowerCase() === s.toLowerCase())
  );
  renderMultiSelect(containerId, opts, keep, kind);
 }

 function _setText(id, value) {
  const el = $(id);
  if (el) el.value = value == null ? "" : String(value);
 }

 function syncRoleplayFieldsUi(opts) {
  const openDetails = !!(opts && opts.openDetails);
  const on = !!$("cfgRoleplayEnabled")?.checked;
  const box = $("roleplayFields");
  if (box) {
   box.classList.toggle("is-off", !on);
   box.setAttribute("aria-hidden", on ? "false" : "true");
   box.querySelectorAll("textarea, select, input").forEach((el) => {
    if (el instanceof HTMLElement) el.tabIndex = on ? 0 : -1;
   });
  }
  const badge = $("roleplaySummaryBadge");
  if (badge) {
   badge.textContent = on ? "已启用" : "未启用";
   badge.classList.toggle("is-on", on);
  }
  const details = $("roleplayDetails");
  // 勾选启用 / 载入时已启用 → 自动展开，方便填人设
  if (details && openDetails && on) {
   details.open = true;
  }
  const baseHint = $("agentBaseHint");
  if (baseHint) {
   baseHint.textContent = on
    ? "名称 · 语言 · 角色背景 + 扮演人设"
    : "名称 · 语言 · 角色背景";
  }
  const rbHint = $("agentRoleBgHint");
  if (rbHint) {
   rbHint.textContent = on
    ? "始终注入 · 与扮演互补"
    : "是谁 · 经历立场 · 世界观";
  }
 }

 function bindAgentFormExtras() {
  if (bindAgentFormExtras._done) return;
  // 按钮由 bindConfigDelegatedUi 事件委托处理；这里只绑表单 change
  if (!$("cfgRoleplayEnabled") && !$("cfgAgentName")) return;
  bindAgentFormExtras._done = true;
  $("cfgRoleplayEnabled")?.addEventListener("change", () => {
   syncRoleplayFieldsUi({ openDetails: true });
  });
 }

 function renderAgentForm(cfg) {
  try {
   if (cfg && state) {
    // cfg may be full /api/config or { agent }
    if (cfg.agent) state.config = { ...(state.config || {}), ...cfg };
    else state.config = { ...(state.config || {}), agent: cfg };
   }
  } catch (_) {}
  queueMicrotask(() => {
   if (typeof L.refreshVoiceLangFromPersona === "function") {
    L.refreshVoiceLangFromPersona();
   }
  });
  if (!$("cfgAgentName")) return;
  ensureMsDocClose();
  bindAgentFormExtras();
  const a = cfg.agent || {};
  const presets = a.persona_presets || {};
  const merged = a.persona_options_merged || {};
  syncPersonaStateFromCfg(cfg);

  $("cfgAgentName").value = a.name || "";
  // no default language — empty stays empty after wipe
  fillSelect("cfgLanguage", presets.language || merged.language, a.language, "");

  MS_KEYS.forEach((kind) => {
   const id = MS_CONTAINERS[kind];
   const field = MS_VALUE_FIELDS[kind];
   if (!id) return;
   const opts = _filterHidden(
    merged[kind] || getVisibleOptions(kind),
    _personaHiddenOpts[kind]
   );
   renderMultiSelect(id, opts, a[field], kind);
  });

  _setText("cfgRoleBackground", roleBackgroundFromAgent(a));
  if ($("cfgRoleplayEnabled")) {
   $("cfgRoleplayEnabled").checked = !!(
    a.roleplay_enabled === true ||
    a.roleplay_enabled === 1 ||
    a.roleplay_enabled === "1" ||
    a.roleplay_enabled === "true"
   );
  }
  if ($("cfgRoleplayIntensity")) {
   const inten = String(a.roleplay_intensity || "medium").toLowerCase();
   $("cfgRoleplayIntensity").value = ["light", "medium", "deep"].includes(
    inten
   )
    ? inten
    : "medium";
  }
  _setText("cfgRelationship", a.relationship || "");
  _setText("cfgPersonality", a.personality || "");
  _setText("cfgSpeechPatterns", a.speech_patterns || "");
  _setText("cfgExampleDialogue", a.example_dialogue || "");
  _setText("cfgOocRules", a.ooc_rules || "");
  loadEvolutionPanel();
  // 已启用扮演时展开折叠，便于查看/改人设
  const rpOn = !!$("cfgRoleplayEnabled")?.checked;
  syncRoleplayFieldsUi({ openDetails: rpOn });
  if (rpOn) {
   const d = $("roleplayDetails");
   if (d) d.open = true;
  }
  $("cfgMaxRounds").value = a.max_tool_rounds ?? 8;
  $("cfgMaxHistory").value =
   a.max_history_messages ?? a.max_history ?? 40;
  if ($("cfgEvoEnabled")) {
   const on = a.evolution_enabled !== false && a.evolution_enabled !== 0;
   $("cfgEvoEnabled").value = on ? "1" : "0";
  }
  if ($("cfgEvoTrigger"))
   $("cfgEvoTrigger").value = a.evolution_trigger_messages ?? 24;
  if ($("cfgEvoKeep")) $("cfgEvoKeep").value = a.evolution_keep_messages ?? 16;
  if ($("cfgEvoMaxEntries"))
   $("cfgEvoMaxEntries").value = a.evolution_max_entries ?? 12;
  const fixed = $("cfgSystemFixedRules");
  if (fixed) {
   fixed.textContent =
    a.system_fixed_rules_summary ||
    "系统固定规则由项目代码注入（工具路由、记忆、媒体、安全等），逻辑不变，不可在此人设中修改。";
  }
 }

 function addPersonaOption(kind, inputElOrId) {
  const key = kind;
  if (!MS_KEYS.includes(key)) return;
  const input =
   typeof inputElOrId === "string" ? $(inputElOrId) : inputElOrId;
  const raw = (input?.value || "").trim();
  if (!raw) {
   setMsg("msgAgent", "请先输入自定义选项", "error");
   return;
  }
  _personaHiddenOpts[key] = _asArr(_personaHiddenOpts[key]).filter(
   (x) => x.toLowerCase() !== raw.toLowerCase()
  );
  const visible = getVisibleOptions(key);
  if (visible.some((x) => x.toLowerCase() === raw.toLowerCase())) {
   setMsg("msgAgent", "该选项已存在", "error");
   return;
  }
  if (!_isPreset(key, raw)) {
   const list = _asArr(_personaCustomOpts[key]);
   if (!list.some((x) => x.toLowerCase() === raw.toLowerCase())) {
    list.push(raw);
    _personaCustomOpts[key] = list;
   }
  }
  if (input) input.value = "";
  const sel = getMsSelection(key);
  if (!sel.some((x) => x.toLowerCase() === raw.toLowerCase())) sel.push(raw);
  renderMultiSelect(MS_CONTAINERS[key], getVisibleOptions(key), sel, key);
  // keep open after add for continued selection
  const root = $(MS_CONTAINERS[key]);
  if (root) root.classList.add("is-open");
  setMsg("msgAgent", "已添加（保存人设后持久化）", "ok");
 }

 function removePersonaOption(kind, value) {
  const key = kind;
  if (!MS_KEYS.includes(key)) return;
  const val = String(value || "").trim();
  if (!val) return;
  const opts = getVisibleOptions(key);
  if (opts.length <= 1) {
   setMsg("msgAgent", "至少保留一个选项", "error");
   return;
  }
  _personaCustomOpts[key] = _asArr(_personaCustomOpts[key]).filter(
   (x) => x.toLowerCase() !== val.toLowerCase()
  );
  if (_isPreset(key, val)) {
   const hid = _asArr(_personaHiddenOpts[key]);
   if (!hid.some((x) => x.toLowerCase() === val.toLowerCase())) {
    hid.push(val);
    _personaHiddenOpts[key] = hid;
   }
  }
  refreshMsSection(key);
  const root = $(MS_CONTAINERS[key]);
  if (root) root.classList.add("is-open");
  setMsg("msgAgent", "已删除选项（保存人设后持久化）", "ok");
 }

 function _fmtEvoTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
 }

 function renderEvolutionPanel(data) {
  const body = $("evoPersonaBody");
  const meta = $("evoPersonaMeta");
  if (!body) return;
  const empty = !data || data.empty;
  const entries = (data && data.entries) || [];
  const bits = [];
  if (data && data.session_title) bits.push(data.session_title);
  else if (data && data.session_id)
   bits.push("会话 " + String(data.session_id).slice(0, 8));
  if (data && data.version) bits.push("第 " + data.version + " 次演化");
  if (data && data.updated_at) bits.push(_fmtEvoTime(data.updated_at));
  if (meta) meta.textContent = bits.join(" · ");
  if (empty) {
   body.innerHTML =
    '<p class="evo-persona-empty">当前会话还没演化。对话达到「演化触发条数」后，压缩出的人格与要点会出现在这里。</p>';
   return;
  }
  const rows = entries
   .map((e) => {
    const kind = escapeHtml(e.kind_label || e.kind || "要点");
    const isPersona = e.kind === "preference";
    return (
     `<div class="evo-persona-item${isPersona ? " is-persona" : ""}">` +
     `<span class="evo-kind">${kind}</span>` +
     `<p>${escapeHtml(e.content || "")}</p>` +
     `</div>`
    );
   })
   .join("");
  const prose =
   !entries.length && data.text
    ? `<p class="evo-persona-text">${escapeHtml(data.text)}</p>`
    : "";
  body.innerHTML = rows + prose ||
   '<p class="evo-persona-empty">演化结果为空。</p>';
 }

 async function loadEvolutionPanel() {
  const body = $("evoPersonaBody");
  const meta = $("evoPersonaMeta");
  if (!body) return;
  const sid = (state && state.sessionId) || "";
  if (!sid) {
   if (meta) meta.textContent = "";
   body.innerHTML =
    '<p class="evo-persona-empty">新对话还没有演化。聊到触发条数后，这里会显示压缩后的人格要点。</p>';
   return;
  }
  try {
   const data = await api(
    "/api/sessions/" + encodeURIComponent(sid) + "/evolution"
   );
   renderEvolutionPanel(data);
  } catch (e) {
   if (meta) meta.textContent = "";
   body.innerHTML =
    '<p class="evo-persona-empty">无法读取演化结果：' +
    escapeHtml(e.message || e) +
    "</p>";
  }
 }

 function collectAgentFormPayload() {
  const persona_options = {};
  MS_KEYS.forEach((k) => {
   persona_options[k] = _asArr(_personaCustomOpts[k]);
   persona_options[k + "_hidden"] = _asArr(_personaHiddenOpts[k]);
  });
  return {
   name: $("cfgAgentName")?.value || "",
   // 旧版「角色 / 语言风格」多选已废弃；统一写入 background 为「角色背景」
   role: [],
   language: $("cfgLanguage")?.value || "跟随用户",
   language_style: [],
   background: ($("cfgRoleBackground")?.value || "").trim(),
   roleplay_enabled: !!$("cfgRoleplayEnabled")?.checked,
   roleplay_intensity: $("cfgRoleplayIntensity")?.value || "medium",
   relationship: $("cfgRelationship")?.value || "",
   personality: $("cfgPersonality")?.value || "",
   speech_patterns: $("cfgSpeechPatterns")?.value || "",
   example_dialogue: $("cfgExampleDialogue")?.value || "",
   ooc_rules: $("cfgOocRules")?.value || "",
   persona_options,
   max_tool_rounds: parseInt($("cfgMaxRounds")?.value, 10) || 8,
   max_history_messages: parseInt($("cfgMaxHistory")?.value, 10) || 40,
   evolution_enabled: ($("cfgEvoEnabled")?.value || "1") !== "0",
   evolution_trigger_messages: parseInt($("cfgEvoTrigger")?.value, 10) || 24,
   evolution_keep_messages: parseInt($("cfgEvoKeep")?.value, 10) || 16,
   evolution_max_entries: parseInt($("cfgEvoMaxEntries")?.value, 10) || 12,
  };
 }

 // --- LLM ---
 async function loadLlms(opts = {}) {
 const soft = !!opts.soft;
 const list = $("llmList");
 if (!list) return;
 const keepUi = soft && _panelHasContent(list);
 if (!keepUi) {
  list.innerHTML = "";
  renderSkeleton(list, 3);
  setMsg("msgLlm", "载入中…");
 }
 try {
 let llms = await api("/api/config/llms");
 if (!Array.isArray(llms)) llms = llms.items || [];
 // 默认模型置顶，更醒目
 llms = llms.slice().sort((a, b) => {
 const rank = (x) =>
  x && (x.is_default || x.default) ? 0 : x && x.is_deputy ? 1 : 2;
 return rank(a) - rank(b);
 });
 list.innerHTML = "";
 if (!llms.length) {
 list.innerHTML =
 '<div class="card"><div class="card-body"><div class="card-sub">未配置 LLM，点「添加」</div></div></div>';
 setMsg("msgLlm", "0 个", "ok");
 return;
 }
 for (const llm of llms) {
 const card = document.createElement("div");
 const isDefault = !!(llm.is_default || llm.default);
 const isDeputy = !!llm.is_deputy && !isDefault;
 const enabled = llm.enabled !== false;
 card.className =
 "card llm-card" +
 (isDefault ? " is-default" : "") +
 (isDeputy ? " is-deputy" : "") +
 (enabled ? "" : " is-disabled");
 const mod = llm.modality || "";
 const modLabel = llm.modality_label || modalityLabelLocal(llm.model, llm.name);
 const modClass =
 mod === "multimodal" || modLabel === "全模态"
 ? "llm-mod-multi"
 : mod === "image" || mod === "video"
 ? "llm-mod-media"
 : "llm-mod-text";
 const modHint = llm.modality_hint || "";
 const lid = llm.id || "";
 card.dataset.llmId = lid;
 card.innerHTML = `
 <div class="card-body">
 <div class="card-title">
 <span class="llm-card-name">${escapeHtml(llm.name || llm.model || "未命名")}</span>
 ${
 isDefault
 ? `<span class="pill llm-default-badge" title="当前默认对话模型">${_ipk(
 "star",
 "ipk-xs"
 )} 默认</span>`
 : ""
 }
 ${
 isDeputy
 ? `<span class="pill llm-deputy-badge" title="这一轮要调技能时自动用，日常聊天仍走默认">副模型</span>`
 : ""
 }
 <span class="pill ${modClass}" title="${escapeHtml(
 modHint || modLabel
 )}">${escapeHtml(modLabel)}</span>
 ${
 llm.use_proxy
 ? `<span class="pill llm-proxy-badge" title="该模型走代理">代理</span>`
 : ""
 }
 </div>
 <div class="card-sub">${escapeHtml(
 isLlmCli(llm) ? "CLI" : llm.provider || "—"
 )} · <code>${escapeHtml(
 llm.model || (isLlmCli(llm) ? llm.cli_command || "cli" : "—")
 )}</code>${enabled ? "" : " · " + _ipkLabel("forbid", "停用", "ipk-xs")}</div>
 <div class="card-sub muted-line">${escapeHtml(
 isLlmCli(llm)
 ? [llm.cli_command, llm.cli_args].filter(Boolean).join(" ")
 : llm.base_url || ""
 )}</div>
 <div class="card-sub llm-balance-line" data-llm-balance="${escapeHtml(lid)}">
 <span class="llm-balance-label">余额</span>
 <span class="llm-balance-value">${isLlmCli(llm) ? "CLI" : "未查询"}</span>
 </div>
 </div>
 <div class="card-actions">
 ${
 !isDefault
 ? `<button type="button" class="btn btn-set-default icon-btn" title="设为默认">${_ipk(
 "star",
 "ipk-sm"
 )}</button>`
 : ""
 }
 ${
 !isDeputy && llms.length > 1
 ? `<button type="button" class="btn btn-set-deputy icon-btn" title="设为副模型（调技能时自动用这一轮）">${_ipk(
 "lightning",
 "ipk-sm"
 )}</button>`
 : ""
 }
 ${
 isLlmCli(llm)
 ? ""
 : `<button type="button" class="btn llm-balance-refresh icon-btn" title="刷新余额" data-llm-id="${escapeHtml(
 lid
 )}">${_ipk("refresh", "ipk-sm")}</button>`
 }
 <button type="button" class="btn edit-llm icon-btn" title="编辑">${_ipk("edit", "ipk-sm")}</button>
 <button type="button" class="btn danger delete-llm icon-btn" title="删除">${_ipk("delete", "ipk-sm")}</button>
 </div>`;
 card.querySelector(".edit-llm").addEventListener("click", () => openLlmEditor(llm));
 card.querySelector(".delete-llm").addEventListener("click", () => deleteLlm(llm.id));
 card
 .querySelector(".llm-balance-refresh")
 ?.addEventListener("click", (ev) => {
 ev.stopPropagation();
 refreshLlmBalance(lid, true);
 });
 const defBtn = card.querySelector(".btn-set-default");
 if (defBtn) {
 defBtn.addEventListener("click", async () => {
 try {
 await api(`/api/config/llms/${encodeURIComponent(llm.id)}/default`, {
 method: "POST",
 });
 setMsg("msgLlm", `已设 ${llm.name || llm.id} 为默认`, "ok");
 showToast("已设为默认", "success");
 loadLlms();
 loadHealth();
 } catch (e) {
 setMsg("msgLlm", e.message, "error");
 showToast("设置默认失败", "error");
 }
 });
 }
 const depBtn = card.querySelector(".btn-set-deputy");
 if (depBtn) {
 depBtn.addEventListener("click", async () => {
 try {
 await api(`/api/config/llms/${encodeURIComponent(llm.id)}/deputy`, {
 method: "POST",
 });
 setMsg("msgLlm", `已设 ${llm.name || llm.id} 为副模型`, "ok");
 showToast("已设为副模型（不改默认）", "success");
 loadLlms();
 loadHealth();
 } catch (e) {
 setMsg("msgLlm", e.message, "error");
 showToast("设置副模型失败", "error");
 }
 });
 }
 list.appendChild(card);
 }
 setMsg("msgLlm", `共 ${llms.length} 个 LLM`, "ok");
 if (typeof L.hydrateIconPark === "function") L.hydrateIconPark(list);
 } catch (e) {
 list.innerHTML = `<div class="card"><div class="card-body"><div class="card-sub">${escapeHtml(e.message)}</div></div></div>`;
 setMsg("msgLlm", e.message, "error");
 showToast("加载LLM失败", "error");
 }
 }

 function setLlmBalanceEl(llmId, state, text, title) {
 const id = String(llmId || "");
 let el = null;
 // 避免 CSS.escape 兼容问题：按 data 属性遍历
 document.querySelectorAll("[data-llm-balance]").forEach((node) => {
 if (node.getAttribute("data-llm-balance") === id) {
 el = node.querySelector(".llm-balance-value");
 }
 });
 if (!el) return;
 el.textContent = text || "—";
 el.classList.remove("is-loading", "is-ok", "is-miss", "is-err");
 if (state) el.classList.add(state);
 if (title) el.title = title;
 else el.removeAttribute("title");
 }

 function formatBalanceClient(res) {
 if (!res) return "—";
 if (res.display && String(res.display).trim()) return String(res.display).trim();
 const n = res.amount;
 if (n == null || n === "") return "—";
 const u = String(res.unit || "").toUpperCase();
 const num = Number(n);
 if (!Number.isFinite(num)) return String(n);
 if (u === "CNY" || u === "RMB" || u === "¥") return "¥" + num.toFixed(2);
 if (u === "USD" || u === "$") return "$" + num.toFixed(2);
 return num.toFixed(2) + (u ? " " + u : "");
 }

 async function refreshLlmBalance(llmId, forceRefresh) {
 if (!llmId) return;
 setLlmBalanceEl(llmId, "is-loading", "查询中…", "");
 try {
 // Always bypass short negative cache when user clicks refresh;
 // auto-load still uses server cache for successes.
 const q = forceRefresh ? "?refresh=true" : "";
 const res = await api(
 `/api/config/llms/${encodeURIComponent(llmId)}/balance${q}`
 );
 if (res && res.ok) {
 const text = formatBalanceClient(res);
 const note = [res.note, res.source ? "来源: " + res.source : ""]
 .filter(Boolean)
 .join(" · ");
 setLlmBalanceEl(
 llmId,
 res.local ? "is-miss" : "is-ok",
 text,
 note || "账户余额（尽力查询，因服务商而异）"
 );
 } else {
 const why = [res && res.error, res && res.hint]
 .filter(Boolean)
 .join(" — ");
 const isAuth = !!(res && res.auth_error);
 setLlmBalanceEl(
 llmId,
 isAuth ? "is-err" : "is-miss",
 (res && res.display) || (isAuth ? "密钥无效" : "暂不可查"),
 why ||
 "该服务商未开放余额 API（仅 DeepSeek 等少数有官方余额接口）"
 );
 }
 } catch (e) {
 setLlmBalanceEl(
 llmId,
 "is-err",
 "查询失败",
 e.message || String(e)
 );
 }
 }

 function modalityLabelLocal(model, name) {
 const blob = `${model || ""} ${name || ""}`.toLowerCase();
 if (/deepseek/.test(blob) && !/vl|vision/.test(blob)) return "文本";
 if (
 /gemini|gpt-4o|gpt-4\.1|gpt-5|gpt-4-turbo|gpt-4-vision|vision|vl-|qwen.*vl|claude-3|claude-4|claude-sonnet|claude-opus|grok.*vision|flash-lite|luna/.test(
 blob
 )
 )
 return "全模态";
 if (/dall|flux|image|midjourney|stable/.test(blob)) return "生图";
 if (/sora|runway|kling|pika|video/.test(blob)) return "视频";
 return "文本";
 }

 function updateLlmModalityHint() {
 const model = ($("llmModel")?.value || "").trim();
 const name = ($("llmName")?.value || "").trim();
 const hint = $("llmModalityHint");
 if (!hint) return;
 if (!model) {
 hint.textContent = "选择或拉取模型后显示：文本 / 全模态(识图) 等";
 hint.className = "field-hint llm-modality-hint";
 return;
 }
 const label = modalityLabelLocal(model, name);
 const map = {
 全模态: "支持文本 + 识图（多模态），适合对话与 analyze_image 等",
 文本: "文本对话/工具调用；识图请另配全模态模型",
 生图: "偏图像生成，不一定适合主对话",
 视频: "偏视频生成",
 };
 hint.textContent = `能力：${label} — ${map[label] || ""}`;
 hint.className =
 "field-hint llm-modality-hint" +
 (label === "全模态"
 ? " is-multi"
 : label === "文本"
 ? " is-text"
 : " is-media");
 }

 function fillLlmModelSelect(models, current) {
 const sel = $("llmModelSelect");
 if (!sel) return;
 const cur = (current || $("llmModel")?.value || "").trim();
 const list = Array.isArray(models) ? models : [];
 sel.innerHTML = "";
 const ph = document.createElement("option");
 ph.value = "";
 ph.textContent = list.length
 ? `— 共 ${list.length} 个，请选择 —`
 : "— 先填 Base URL / Key，再点「拉取模型」—";
 sel.appendChild(ph);
 let hasCur = false;
 for (const m of list) {
 const id = typeof m === "string" ? m : m.id;
 if (!id) continue;
 if (id === cur) hasCur = true;
 const op = document.createElement("option");
 op.value = id;
 const lab =
 typeof m === "object" && m.modality_label
 ? `${id} · ${m.modality_label}`
 : id;
 op.textContent = lab;
 if (typeof m === "object" && m.modality_hint) op.title = m.modality_hint;
 sel.appendChild(op);
 }
 if (cur && !hasCur) {
 const op = document.createElement("option");
 op.value = cur;
 op.textContent = cur + " · 当前";
 sel.appendChild(op);
 hasCur = true;
 }
 if (cur) sel.value = cur;
 }

 async function fetchLlmModels() {
 if (($("llmTransport")?.value || "api") === "cli") {
 setMsg("msgLlmEditor", "CLI 模式没有 /models 接口，请直接填写 model 或留空", "error");
 return;
 }
 const base_url = ($("llmBaseUrl")?.value || "").trim();
 // strip paste noise (spaces / zero-width) — mirrors backend clean
 let api_key = ($("llmApiKey")?.value || "").trim();
 api_key = api_key.replace(/[\u200b\u200c\u200d\ufeff\u00a0]/g, "").replace(/\s+/g, "");
 const id = ($("llmId")?.value || "").trim();
 if (!base_url) {
 setMsg("msgLlmEditor", "请先填写 Base URL", "error");
 showToast("请先填 Base URL", "error");
 return;
 }
 if (!api_key && !id) {
 setMsg("msgLlmEditor", "新建请填 API Key 后再拉取", "error");
 showToast("请先填 API Key", "error");
 return;
 }
 const usingSaved = !api_key && !!id;
 setMsg(
 "msgLlmEditor",
 usingSaved ? "拉取模型列表中…（使用已保存的 Key）" : "拉取模型列表中…"
 );
 try {
 const use_proxy = !!$("llmUseProxy")?.checked;
 const res = await api("/api/config/llms/models", {
 method: "POST",
 body: JSON.stringify({
 base_url,
 api_key,
 id: id || null,
 use_proxy,
 }),
 });
 if (!res.ok) {
 const msg =
 "拉取失败: " +
 (res.error || res.detail || "unknown") +
 (res.auth_error
 ? " — 请重新粘贴完整 API Key，点「保存」后再拉。"
 : "");
 setMsg("msgLlmEditor", msg, "error");
 showToast(res.auth_error ? "API Key 无效" : "拉取模型失败", "error");
 return;
 }
 const models = res.models || [];
 const cur = ($("llmModel")?.value || "").trim();
 fillLlmModelSelect(models, cur);
 // 若尚未填写 model，自动选第一个
 if (!cur && models.length) {
 const first = typeof models[0] === "string" ? models[0] : models[0].id;
 if (first && $("llmModel")) {
 $("llmModel").value = first;
 const sel = $("llmModelSelect");
 if (sel) sel.value = first;
 updateLlmModalityHint();
 }
 }
 setMsg(
 "msgLlmEditor",
 `已拉取 ${res.count ?? models.length} 个模型，请下拉选择` +
 (res.source_url ? `（${res.source_url}）` : ""),
 "ok"
 );
 showToast(`已拉取 ${res.count ?? models.length} 个模型`, "success");
 } catch (e) {
 setMsg("msgLlmEditor", e.message || String(e), "error");
 showToast("拉取失败", "error");
 }
 }

 const LLM_CLI_PRESETS = {
 grok_build: {
 name: "Grok Build",
 command: "grok",
 args: "--prompt-file {prompt_file} --output-format plain --max-turns 32 --always-approve",
 model: "grok-4.6",
 },
 };

 function isLlmCli(llm) {
 if (!llm) return false;
 const t = String(llm.transport || "").toLowerCase();
 if (t === "cli") return true;
 if (String(llm.provider || "").toLowerCase() === "cli") return true;
 if (t === "api") return false;
 if ((llm.cli_command || "").trim()) return true;
 const name = String(llm.name || "").toLowerCase();
 const key = String(llm.api_key || "").trim();
 const url = String(llm.base_url || "").trim();
 if ((name.includes("grok build") || name === "grok") && !key && !url) return true;
 return false;
 }

 function collectLlmFormPayload(opts) {
 opts = opts || {};
 let model = ($("llmModel")?.value || "").trim();
 const sel = $("llmModelSelect");
 if (!model && sel && sel.value) {
 model = (sel.value || "").trim();
 if (model && $("llmModel")) $("llmModel").value = model;
 }
 const selectEl = $("llmTransport");
 let transport = String(selectEl?.value || "").trim().toLowerCase();
 const cli_command = ($("llmCliCommand")?.value || "").trim();
 const cli_args = ($("llmCliArgs")?.value || "").trim();
 const cli_cwd = ($("llmCliCwd")?.value || "").trim();
 if (transport !== "api" && transport !== "cli") {
 transport = cli_command ? "cli" : "api";
 }
 const data = {
 id: ($("llmId")?.value || "").trim() || undefined,
 name: ($("llmName")?.value || "").trim() || "LLM",
 provider: transport === "cli" ? "cli" : ($("llmProvider")?.value || "openai"),
 base_url: ($("llmBaseUrl")?.value || "").trim(),
 model,
 enabled: !!$("llmEnabled")?.checked,
 is_default: !!$("llmDefault")?.checked,
 is_deputy: !!$("llmDeputy")?.checked && !$("llmDefault")?.checked,
 use_proxy: !!$("llmUseProxy")?.checked,
 transport,
 };
 if (transport === "cli") {
 data.cli_command = cli_command;
 data.cli_args = cli_args;
 data.cli_cwd = cli_cwd;
 } else {
 data.cli_command = "";
 data.cli_args = "";
 data.cli_cwd = "";
 }
 let key = ($("llmApiKey")?.value || "").trim();
 key = key.replace(/[\u200b\u200c\u200d\ufeff\u00a0]/g, "").replace(/\s+/g, "");
 if (opts.includeApiKey || key) data.api_key = key;
 return data;
 }

 function syncLlmTransportUi() {
 const cli = ($("llmTransport")?.value || "api") === "cli";
 document.querySelectorAll("#llmEditorModal .llm-api-only").forEach((el) => {
 el.hidden = cli;
 });
 document.querySelectorAll("#llmEditorModal .llm-cli-only").forEach((el) => {
 el.hidden = !cli;
 });
 const model = $("llmModel");
 if (model) {
 model.placeholder = cli
 ? "可选，传给 CLI 的 -m，如 grok-4.6"
 : "或手动输入 model id，如 grok-4.5";
 }
 const hint = $("llmModalityHint");
 if (hint) {
 if (cli) {
 hint.textContent = "CLI 把对话交给本机命令（如 grok）。Eva 不解析 tool_calls；本机 CLI 自己干活。";
 } else if (typeof updateLlmModalityHint === "function") {
 updateLlmModalityHint();
 }
 }
 }

 function applyLlmCliPreset() {
 const key = ($("llmCliPreset")?.value || "").trim();
 const preset = LLM_CLI_PRESETS[key];
 if (!preset) return;
 if ($("llmCliCommand")) $("llmCliCommand").value = preset.command;
 if ($("llmCliArgs")) $("llmCliArgs").value = preset.args;
 if (preset.model && $("llmModel") && !($("llmModel").value || "").trim()) {
 $("llmModel").value = preset.model;
 }
 if (preset.name && $("llmName") && !($("llmName").value || "").trim()) {
 $("llmName").value = preset.name;
 }
 }

 function openLlmEditor(llm) {
 const editingLlmId = llm.id || "";
 $("llmId").value = editingLlmId;
 $("llmName").value = llm.name || "";
 $("llmProvider").value = llm.provider && llm.provider !== "cli" ? llm.provider : "openai";
 $("llmBaseUrl").value = llm.base_url || "";
 $("llmApiKey").value = "";
 $("llmModel").value = llm.model || "";
 if ($("llmTransport")) $("llmTransport").value = isLlmCli(llm) ? "cli" : "api";
 if ($("llmCliCommand")) $("llmCliCommand").value = llm.cli_command || "";
 if ($("llmCliArgs")) $("llmCliArgs").value = llm.cli_args || "";
 if ($("llmCliCwd")) $("llmCliCwd").value = llm.cli_cwd || "";
 if ($("llmCliPreset")) $("llmCliPreset").value = "";
 if (isLlmCli(llm) && !($("llmCliCommand")?.value || "").trim()) {
 const n = String(llm.name || llm.model || "");
 if (/grok/i.test(n) && $("llmCliPreset")) {
 $("llmCliPreset").value = "grok_build";
 applyLlmCliPreset();
 }
 }
 syncLlmTransportUi();
 fillLlmModelSelect(
 llm.model ? [{ id: llm.model, modality_label: llm.modality_label || modalityLabelLocal(llm.model, llm.name) }] : [],
 llm.model || ""
 );
 $("llmEnabled").checked = llm.enabled !== false;
 $("llmDefault").checked = !!(llm.is_default || llm.default);
 if ($("llmDeputy")) $("llmDeputy").checked = !!llm.is_deputy && !llm.is_default;
 if ($("llmUseProxy")) $("llmUseProxy").checked = !!llm.use_proxy;
 const defEl = $("llmDefault");
 const depEl = $("llmDeputy");
 if (defEl && depEl && !defEl.dataset.deputyExclusive) {
  defEl.dataset.deputyExclusive = "1";
  defEl.addEventListener("change", () => {
   if (defEl.checked && depEl.checked) depEl.checked = false;
  });
  depEl.addEventListener("change", () => {
   if (depEl.checked && defEl.checked) defEl.checked = false;
  });
 }
 const titleEl = $("llmEditorTitle");
 if (titleEl)
 titleEl.innerHTML = editingLlmId
 ? '<span data-ipk="edit" data-ipk-class="ipk-sm"></span> 编辑 LLM'
 : '<span data-ipk="plus" data-ipk-class="ipk-sm"></span> 新 LLM';
 setMsg("msgLlmEditor", "");
 updateLlmModalityHint();
 openNestedEditor("llmEditorModal");
 // 已有 base_url 时自动尝试拉取（有保存的 key）
 if (editingLlmId && (llm.base_url || "").trim()) {
 fetchLlmModels().catch(() => {});
 }
 }

 function closeLlmEditor() {
 closeNestedEditor("llmEditorModal");
 }

 function bindLlmModelUi() {
 if (bindLlmModelUi._done) return;
 // 委托：设定 HTML 注入后也有效
 if (!window.__lilyLlmModelDelegate) {
 window.__lilyLlmModelDelegate = true;
 document.addEventListener("click", (e) => {
 const t = e.target;
 if (!(t instanceof Element)) return;
 if (t.closest("#btnFetchLlmModels")) {
 e.preventDefault();
 fetchLlmModels();
 }
 });
 document.addEventListener("change", (e) => {
 const t = e.target;
 if (!(t instanceof Element)) return;
 if (t.id === "llmModelSelect") {
 const v = (t.value || "").trim();
 if (v && $("llmModel")) {
 $("llmModel").value = v;
 updateLlmModalityHint();
 }
 }
 });
 document.addEventListener("input", (e) => {
 const t = e.target;
 if (!(t instanceof Element)) return;
 if (t.id === "llmModel" || t.id === "llmName") {
 if (t.id === "llmModel") {
 const v = (t.value || "").trim();
 const sel = $("llmModelSelect");
 if (sel && v) {
 const opt = Array.from(sel.options).find((o) => o.value === v);
 if (opt) sel.value = v;
 }
 }
 updateLlmModalityHint();
 }
 });
 }
 bindLlmModelUi._done = true;
 }
 bindLlmModelUi();

 // --- P0: 展示元数据（仅 UI 分组/角标，不改 tool 名与调用） ---
 // icon 名对应 IconPark 官方图标 key（见 static/js/icons.js）
 const DEFAULT_CAPABILITY_GROUPS = [
 { id: "vision", label: "识图分析", icon: "picture" },
 { id: "media", label: "生图 / 视频", icon: "video" },
 { id: "memory", label: "记忆 / 偏好", icon: "brain" },
 { id: "content", label: "内容营销", icon: "comment" },
 { id: "workspace", label: "工作区文件", icon: "folder-open" },
 { id: "network", label: "网络请求", icon: "network-tree" },
 { id: "office", label: "办公文档", icon: "doc-detail" },
 { id: "schedule", label: "任务 / 提醒", icon: "alarm-clock" },
 { id: "news", label: "资讯", icon: "newspaper-folding" },
 { id: "infra", label: "基础设施", icon: "server" },
 { id: "dev", label: "开发 / 运维", icon: "code" },
 { id: "other", label: "其它", icon: "all-application" },
 ];
 let CAPABILITY_GROUPS = DEFAULT_CAPABILITY_GROUPS.slice();

 async function loadCapabilityGroups() {
  try {
   const data = await api("/api/config/capability-groups");
   const items = Array.isArray(data?.groups)
    ? data.groups
    : Array.isArray(data)
    ? data
    : [];
   const mapped = items
    .map((g) => ({
     id: String(g.id || "").trim(),
     label: String(g.label || g.id || "").trim(),
     icon: String(g.icon || "all-application"),
     builtin: !!g.builtin,
    }))
    .filter((g) => g.id);
   if (mapped.length) {
    CAPABILITY_GROUPS = mapped;
    return CAPABILITY_GROUPS;
   }
  } catch (_) {}
  CAPABILITY_GROUPS = DEFAULT_CAPABILITY_GROUPS.slice();
  return CAPABILITY_GROUPS;
 }

 function groupDef(groupId) {
  const id = (groupId || "other").toString();
  return (
   CAPABILITY_GROUPS.find((x) => x.id === id) || {
    id,
    label: id,
    icon: "all-application",
    builtin: false,
   }
  );
 }

 function groupSelectHtml(currentId) {
  const cur = (currentId || "other").toString();
  const opts = CAPABILITY_GROUPS.map((g) => {
   const sel = g.id === cur ? " selected" : "";
   return (
    '<option value="' +
    escapeHtml(g.id) +
    '"' +
    sel +
    ">" +
    escapeHtml(g.label) +
    "</option>"
   );
  }).join("");
  return (
   '<select class="group-pick" title="分类">' + opts + "</select>"
  );
 }

 function bindGroupPick(selectEl, kind, id, currentId) {
  if (!selectEl || !id) return;
  selectEl.addEventListener("change", async () => {
   const next = (selectEl.value || "").trim();
   if (!next || next === currentId) return;
   try {
    const path =
     kind === "skill"
      ? "/api/config/skills/" + encodeURIComponent(id) + "/group"
      : "/api/config/tools/" + encodeURIComponent(id) + "/group";
    await api(path, {
     method: "PUT",
     body: JSON.stringify({ group: next }),
    });
    showToast("已移到「" + (groupDef(next).label || next) + "」", "success");
    loadSkills({ soft: true });
    if (typeof loadToolsPanel === "function") loadToolsPanel({ soft: true });
   } catch (err) {
    selectEl.value = currentId || "other";
    showToast((err && err.message) || "改分类失败", "error");
   }
  });
 }

 async function promptAddCapabilityGroup() {
  const label = (prompt("新分组名称") || "").trim();
  if (!label) return;
  try {
   await api("/api/config/capability-groups", {
    method: "POST",
    body: JSON.stringify({ label }),
   });
   await loadCapabilityGroups();
   showToast("已添加分组「" + label + "」", "success");
   loadSkills({ soft: true });
   if (typeof loadToolsPanel === "function") loadToolsPanel({ soft: true });
  } catch (err) {
   showToast((err && err.message) || "添加分组失败", "error");
  }
 }

 async function renameCapabilityGroup(groupId, currentLabel) {
  const next = prompt("分组名称", currentLabel || "");
  if (next == null) return;
  const label = String(next).trim();
  if (!label || label === currentLabel) return;
  try {
   await api(
    "/api/config/capability-groups/" + encodeURIComponent(groupId),
    { method: "PATCH", body: JSON.stringify({ label }) }
   );
   await loadCapabilityGroups();
   showToast("已重命名为「" + label + "」", "success");
   loadSkills({ soft: true });
   if (typeof loadToolsPanel === "function") loadToolsPanel({ soft: true });
  } catch (err) {
   showToast((err && err.message) || "重命名失败", "error");
  }
 }

 async function deleteCapabilityGroup(groupId, label) {
  if (groupId === "other") return;
  if (
   !confirm(
    "删除分组「" +
     (label || groupId) +
     "」？里面的技能和工具会移到「其它」。"
   )
  )
   return;
  try {
   await api(
    "/api/config/capability-groups/" + encodeURIComponent(groupId),
    { method: "DELETE" }
   );
   await loadCapabilityGroups();
   showToast("已删除分组", "success");
   loadSkills({ soft: true });
   if (typeof loadToolsPanel === "function") loadToolsPanel({ soft: true });
  } catch (err) {
   showToast((err && err.message) || "删除失败", "error");
  }
 }

 function ipk(name, cls) {
 try {
 if (L.icons && typeof L.icons.iconHtml === "function") {
 return L.icons.iconHtml(name, cls || "ipk-sm") || "";
 }
 if (window.IconParkUI && typeof window.IconParkUI.iconHtml === "function") {
 return window.IconParkUI.iconHtml(name, cls || "ipk-sm") || "";
 }
 } catch (_) {}
 return "";
 }

 function setGroupCollapsed(groupEl, collapsed) {
 if (!groupEl) return;
 const isCollapsed = !!collapsed;
 groupEl.classList.toggle("is-collapsed", isCollapsed);
 const btn = groupEl.querySelector(".panel-group-toggle") || groupEl.querySelector(".panel-group-header");
 if (btn) btn.setAttribute("aria-expanded", isCollapsed ? "false" : "true");
 const body = groupEl.querySelector(".panel-group-body");
 if (body) body.hidden = isCollapsed;
 }

 function setAllGroupsCollapsed(listEl, collapsed) {
 if (!listEl) return;
 listEl.querySelectorAll(".panel-group").forEach((g) => setGroupCollapsed(g, collapsed));
 }

 function injectPanelToolbar(listEl, panelKey) {
 if (!listEl || !listEl.parentElement) return;
 const host = listEl.parentElement;
 let bar = host.querySelector(".panel-collapse-toolbar[data-panel='" + panelKey + "']");
 if (!bar) {
 bar = document.createElement("div");
 bar.className = "panel-collapse-toolbar";
 bar.dataset.panel = panelKey;
 bar.innerHTML =
//  '<button type="button" class="btn ghost-sm btn-expand-all" title="展开全部分组">' +
//  ipk("expand-down-one", "ipk-xs") +
//  " 展开全部</button>" +
//  '<button type="button" class="btn ghost-sm btn-collapse-all" title="折叠全部分组">' +
//  ipk("right", "ipk-xs") +
//  " 全部折叠</button>" +
 '<span class="panel-collapse-hint">默认折叠 · 点击分组标题展开</span>';
 listEl.parentNode.insertBefore(bar, listEl);
 bar.querySelector(".btn-expand-all")?.addEventListener("click", () =>
 setAllGroupsCollapsed(listEl, false)
 );
 bar.querySelector(".btn-collapse-all")?.addEventListener("click", () =>
 setAllGroupsCollapsed(listEl, true)
 );
 }
 }

 /** @type {Record<string, { group: string, role?: string, note?: string }>} */
 const TOOL_META = {
 memory: { group: "memory", role: "primary", note: "长期记忆" },
 kb: { group: "memory", role: "primary", note: "知识库 Wiki" },
 workflow: { group: "schedule", role: "primary", note: "工作流" },
 workspace: { group: "workspace", role: "primary", note: "本地文件" },
 scheduled_task: {
  group: "schedule",
  role: "primary",
  note: "与「设定→任务」同一数据源",
 },
 get_current_time: { group: "dev", role: "primary" },
 calculator: { group: "dev", role: "primary" },
 system_info: { group: "dev", role: "primary" },
 create_tool: { group: "dev", role: "primary", note: "运行时创建 skill" },
 capability_groups: { group: "dev", role: "primary", note: "技能/工具分类" },
 read_skill: { group: "dev", role: "primary" },
 delete_tool: { group: "dev", role: "primary" },
 reload_runtime: { group: "dev", role: "primary" },
 list_api_models: { group: "dev", role: "primary" },
 server_health_check: { group: "dev", role: "primary" },
 terminal: { group: "dev", role: "primary" },
 document: { group: "office", role: "primary" },
 llms: { group: "dev", role: "primary" },
 integrations: { group: "infra", role: "primary" },
 };

 /** skill 包 id → 分组/角标（仅默认运行时技能） */
 const SKILL_META = {
 reload_runtime: { group: "dev", role: "primary" },
 list_api_models: { group: "dev", role: "primary" },
 server_health_check: { group: "dev", role: "primary" },
 terminal: { group: "dev", role: "primary" },
 document: { group: "office", role: "primary" },
 };

 const ROLE_LABEL = {
 primary: "主入口",
 equivalent: "等价",
 fallback: "后备",
 legacy: "已停用",
 dev: "开发/运维",
 };

 function resolveGroupMeta(name, table, itemMeta) {
 const staticM = (table && table[name]) || {};
 const itemM = itemMeta || {};
 const m = Object.assign({}, staticM, itemM);
 let groupId = (m.group || "").toString().trim() || "";
 if (!groupId) groupId = staticM.group || "other";
 const isDynamic = m.dynamic === true || m.dynamic === "true";
 const g = groupDef(groupId);
 let note = m.note || m.description_hint || m.tag || "";
 const ver = m.version ? "v" + m.version : "";
 if (isDynamic && !note) note = "动态创建（create_tool）" + (ver ? " · " + ver : "");
 else if (isDynamic && note && !String(note).includes("动态"))
 note = "动态 · " + note + (ver ? " · " + ver : "");
 else if (ver && note && !String(note).includes(ver)) note = note + " · " + ver;
 return {
 groupId: g.id,
 groupLabel: g.label,
 role: m.role || (isDynamic ? "primary" : ""),
 note,
 dynamic: isDynamic,
 };
 }

 function rolePillHtml(role, dynamic) {
 const pills = [];
 if (dynamic) {
 pills.push('<span class="pill role-dynamic">动态</span>');
 }
 if (role && ROLE_LABEL[role]) {
 pills.push(
 '<span class="pill role-' +
 escapeHtml(role) +
 '">' +
 escapeHtml(ROLE_LABEL[role]) +
 "</span>"
 );
 }
 return pills.join(" ");
 }

 /**
 * 创建可折叠分组（默认折叠）。返回 body 容器，卡片应 append 到 body。
 */
 function appendCollapsibleGroup(listEl, groupId, label, count, iconName, opts) {
 const options = opts || {};
 const group = document.createElement("div");
 group.className = "panel-group is-collapsed";
 group.dataset.groupId = groupId || "";

 const header = document.createElement("div");
 header.className = "panel-group-header";
 const toggle = document.createElement("button");
 toggle.type = "button";
 toggle.className = "panel-group-toggle";
 toggle.setAttribute("aria-expanded", "false");
 toggle.title = "点击展开 / 折叠";
 const chevron = ipk("right", "ipk-xs group-chevron-icon") || "›";
 const gicon = iconName ? ipk(iconName, "ipk-sm group-type-icon") : "";
 toggle.innerHTML =
 '<span class="group-chevron" aria-hidden="true">' +
 chevron +
 "</span>" +
 (gicon ? '<span class="group-type-icon-wrap">' + gicon + "</span>" : "") +
 '<span class="panel-title">' +
 escapeHtml(label) +
 '</span><span class="group-count">' +
 count +
 " 项</span>";
 header.appendChild(toggle);
 if (!options.locked) {
  const actions = document.createElement("div");
  actions.className = "panel-group-actions";
  actions.innerHTML =
   '<button type="button" class="btn icon-btn btn-rename-group" title="重命名分组">' +
   ipk("edit", "ipk-xs") +
   "</button>" +
   (groupId === "other"
    ? ""
    : '<button type="button" class="btn icon-btn btn-delete-group" title="删除分组，技能会移到其它">' +
      ipk("delete", "ipk-xs") +
      "</button>");
  actions.querySelector(".btn-rename-group")?.addEventListener("click", (e) => {
   e.preventDefault();
   e.stopPropagation();
   renameCapabilityGroup(groupId, label);
  });
  actions.querySelector(".btn-delete-group")?.addEventListener("click", (e) => {
   e.preventDefault();
   e.stopPropagation();
   deleteCapabilityGroup(groupId, label);
  });
  header.appendChild(actions);
 }

 const body = document.createElement("div");
 body.className = "panel-group-body";
 body.hidden = true;

 toggle.addEventListener("click", () => {
 const collapsed = group.classList.contains("is-collapsed");
 setGroupCollapsed(group, !collapsed);
 });

 group.appendChild(header);
 group.appendChild(body);
 listEl.appendChild(group);
 return body;
 }

 function groupItemsByMeta(items, nameKey, metaTable) {
 const buckets = new Map();
 for (const g of CAPABILITY_GROUPS) buckets.set(g.id, []);
 for (const item of items) {
 const name = item[nameKey] || item.id || item.name || "";
 const itemMeta = item.metadata || item.meta || {};
 const meta = resolveGroupMeta(name, metaTable, itemMeta);
 if (!buckets.has(meta.groupId)) buckets.set(meta.groupId, []);
 buckets.get(meta.groupId).push({ item, meta, name });
 }
 // 组内：主入口优先，再按名称
 const roleRank = { primary: 0, fallback: 1, equivalent: 2, dev: 3, "": 4 };
 for (const arr of buckets.values()) {
 arr.sort((a, b) => {
 const ra = roleRank[a.meta.role] ?? 4;
 const rb = roleRank[b.meta.role] ?? 4;
 if (ra !== rb) return ra - rb;
 return String(a.name).localeCompare(String(b.name));
 });
 }
 return buckets;
 }

 function orderedGroupsFor(bucketsMap) {
  const order = CAPABILITY_GROUPS.slice();
  const seen = new Set(order.map((g) => g.id));
  for (const id of bucketsMap.keys()) {
   if (!seen.has(id)) {
    order.push(groupDef(id));
    seen.add(id);
   }
  }
  return order;
 }

 function shouldShowGroup(g, rows) {
  if (rows && rows.length) return true;
  if (!g.builtin && g.id !== "other") return true;
  return false;
 }

 // --- Tools ---
 async function loadToolsPanel(opts = {}) {
 const soft = !!opts.soft;
 const list = $("toolList");
 if (!list) return;
 const keepUi = soft && _panelHasContent(list);
 if (!keepUi) {
  list.innerHTML = "";
  renderSkeleton(list, 4);
  setMsg("msgTools", "载入中…");
 }
 try {
 await loadCapabilityGroups();
 const data = await api("/api/config/tools");
 const catalog = Array.isArray(data.catalog)
 ? data.catalog
 : Array.isArray(data)
 ? data
 : [];
 const custom = Array.isArray(data.custom) ? data.custom : [];
 if (typeof L.setToolDisplayLabels === "function") {
 L.setToolDisplayLabels(catalog);
 }

 list.innerHTML = "";
 if (!catalog.length) {
 list.innerHTML =
 '<div class="card"><div class="card-body"><div class="card-sub">暂无工具</div></div></div>';
 } else {
 injectPanelToolbar(list, "tools");
 const buckets = groupItemsByMeta(catalog, "name", TOOL_META);
 let primaryCount = 0;
 for (const g of orderedGroupsFor(buckets)) {
 const rows = buckets.get(g.id) || [];
 if (!shouldShowGroup(g, rows)) continue;
 const body = appendCollapsibleGroup(
 list,
 g.id,
 g.label,
 rows.length,
 g.icon
 );
 for (const { item: t, meta, name } of rows) {
 if (meta.role === "primary") primaryCount += 1;
 const enabled = t.enabled !== false;
 const desc =
 (t.prompt_meta && t.prompt_meta.description) ||
 t.base_description ||
 t.description ||
 "";
 const src = t.source || "builtin";
 const label = t.display_name || meta.note || name;
 const how = (t.how_to_call || "").trim();
 const howLine = how
 ? '<div class="card-sub muted-line">下次这样说：' +
 escapeHtml(how) +
 "</div>"
 : "";
 const noteLine = meta.note
 ? '<div class="card-sub muted-line">' + escapeHtml(meta.note) + "</div>"
 : "";
 const card = document.createElement("div");
 card.className =
 "card" +
 (meta.role === "primary" ? " card-role-primary" : "") +
 (enabled ? "" : " card-disabled");
 const offNote =
 !enabled && t.disabled_reason
 ? '<div class="card-sub muted-line">已关闭（' +
 escapeHtml(
 t.disabled_reason === "skill" ? "所属 Skill 禁用" : "工具禁用"
 ) +
 "）— 勾选可重新开启</div>"
 : !enabled
 ? '<div class="card-sub muted-line">已关闭 — 勾选可重新开启</div>'
 : "";
 const ovBadge = t.has_prompt_override
 ? ' <span class="pill" title="已自定义描述或触发方式">已自定义</span>'
 : "";
 card.innerHTML = [
 '<div class="card-body">',
 ' <div class="card-title">' +
 escapeHtml(label) +
 " " +
 rolePillHtml(meta.role, meta.dynamic) +
 ' <span class="pill source-pill">' +
 escapeHtml(src) +
 "</span>" +
 ovBadge +
 "</div>",
 ' <div class="card-sub muted-line">调用名: <code class="tool-call-name">' +
 escapeHtml(name) +
 "</code></div>",
 ' <div class="card-sub">' +
 escapeHtml(desc.slice(0, 160)) +
 (desc.length > 160 ? "…" : "") +
 "</div>",
 howLine,
 noteLine,
 offNote,
 "</div>",
 '<div class="card-actions">',
 groupSelectHtml(meta.groupId),
 ' <button type="button" class="btn btn-edit-prompt icon-btn" title="编辑描述与触发">' +
 _ipk("edit", "ipk-sm") +
 "</button>",
 ' <label class="toggle tool-toggle-label" title="开关工具">',
 ' <input type="checkbox" class="toggle-tool"' +
 (enabled ? " checked" : "") +
 " />",
 ' <span class="toggle-txt">' +
 (enabled ? "开" : "关") +
 "</span>",
 " </label>",
 "</div>",
 ].join("\n");
 bindGroupPick(card.querySelector(".group-pick"), "tool", name, meta.groupId);
 card.querySelector(".btn-edit-prompt")?.addEventListener("click", () => {
 openPromptEditor({
 kind: "tool",
 id: name,
 label: label + " (" + name + ")",
 baseDescription: t.base_description || "",
 override: (t.prompt_meta && t.prompt_meta.description) || t.prompt_override || "",
 howToCall: (t.prompt_meta && t.prompt_meta.how_to_call) || "",
 baseHowToCall: t.base_how_to_call || "",
 sceneKeywords: (t.prompt_meta && t.prompt_meta.scene_keywords) || t.scene_keywords || [],
 baseSceneKeywords: t.base_scene_keywords || [],
 group: meta.groupId,
 });
 });
 const cb = card.querySelector(".toggle-tool");
 const txt = card.querySelector(".toggle-txt");
 cb.addEventListener("change", async (e) => {
 try {
 await api("/api/config/tools/toggle", {
 method: "POST",
 body: JSON.stringify({ name, enabled: e.target.checked }),
 });
 txt.textContent = e.target.checked ? "开" : "关";
 card.classList.toggle("card-disabled", !e.target.checked);
 setMsg(
 "msgTools",
 "" + label + " 已" + (e.target.checked ? "开启" : "关闭"),
 "ok"
 );
 showToast(
 label + " 已" + (e.target.checked ? "开启" : "关闭"),
 "success"
 );
 loadHealth();
 // refresh catalog so enabled flags stay consistent after rebuild
 loadToolsPanel();
 } catch (err) {
 e.target.checked = !e.target.checked;
 setMsg("msgTools", err.message, "error");
 showToast("切换失败", "error");
 }
 });
 body.appendChild(card);
 }
 }
 const nBuiltin = catalog.filter(
 (t) => (t.source || "builtin") === "builtin"
 ).length;
 const nSkill = catalog.length - nBuiltin;
 setMsg(
 "msgTools",
 "可调用 " +
 catalog.length +
 " · 主入口约 " +
 primaryCount +
 " · 内置 " +
 nBuiltin +
 " · 技能注册 " +
 nSkill +
 " · 自订 " +
 custom.length +
 "（与 Skills 包数不叠加 · 分组默认折叠）",
 "ok"
 );
 }

 renderCustomToolList(custom);
 if (!catalog.length) {
 setMsg(
 "msgTools",
 "可调用 0 · 自订 " + custom.length + "（与 Skills 包数不叠加）",
 "ok"
 );
 }
 } catch (e) {
 list.innerHTML =
 '<div class="card"><div class="card-body"><div class="card-sub">' +
 escapeHtml(e.message) +
 "</div></div></div>";
 setMsg("msgTools", e.message, "error");
 showToast("加载工具失败", "error");
 }
 }
 function renderCustomToolList(tools) {
 const list = $("customToolList");
 if (!list) return;
 list.innerHTML = "";
 if (!tools.length) {
 list.innerHTML =
 '<div class="card"><div class="card-body"><div class="card-sub">未有自订 HTTP 工具</div></div></div>';
 return;
 }
 for (const t of tools) {
 const card = document.createElement("div");
 card.className = "card";
 card.innerHTML = `
 <div class="card-body">
 <div class="card-title">${escapeHtml(t.name)}</div>
 <div class="card-sub">${escapeHtml(t.method || "GET")} · ${escapeHtml(t.url || "")}${t.enabled === false ? " · " + _ipkLabel("forbid", "停用", "ipk-xs") : ""}</div>
 </div>
 <div class="card-actions">
 <button type="button" class="btn edit-ct icon-btn" title="编辑">${_ipk("edit", "ipk-sm")}</button>
 <button type="button" class="btn danger delete-ct icon-btn" title="删除">${_ipk("delete", "ipk-sm")}</button>
 </div>`;
 card.querySelector(".edit-ct").addEventListener("click", () => openCustomToolEditor(t));
 card.querySelector(".delete-ct").addEventListener("click", () =>
 deleteCustomTool(t.id || t.name)
 );
 list.appendChild(card);
 }
 }

 async function appendBuiltinCapabilities(list, skills) {
  let catalog = [];
  try {
   const data = await api("/api/config/tools");
   catalog = Array.isArray(data.catalog)
    ? data.catalog
    : Array.isArray(data)
    ? data
    : [];
  } catch (_) {
   return;
  }
  const skillKeys = new Set();
  for (const s of skills || []) {
   for (const k of [s.id, s.name, s.display_name]) {
    if (k) skillKeys.add(String(k).toLowerCase());
   }
  }
  const builtins = catalog.filter((t) => {
   const src = t.source || "builtin";
   if (src === "skill") return false;
   const n = String(t.name || "").toLowerCase();
   const sid = String(t.skill_id || "").toLowerCase();
   if (skillKeys.has(n) || (sid && skillKeys.has(sid))) return false;
   return true;
  });
  if (!builtins.length) return;
  const buckets = groupItemsByMeta(builtins, "name", TOOL_META);
  const body = appendCollapsibleGroup(
   list,
   "builtin-core",
   "系统内置",
   builtins.length,
   "box",
   { locked: true }
  );
  for (const g of orderedGroupsFor(buckets)) {
   const rows = buckets.get(g.id) || [];
   for (const { item: t, meta, name } of rows) {
    const enabled = t.enabled !== false;
    const label = t.display_name || meta.note || name;
    const desc = (t.base_description || t.description || "").slice(0, 120);
    const card = document.createElement("div");
    card.className = "card" + (enabled ? "" : " card-disabled");
    card.innerHTML = [
     '<div class="card-body">',
     ' <div class="card-title">' +
      escapeHtml(label) +
      ' <span class="pill">内置</span></div>',
     desc
      ? ' <div class="card-sub">' +
        escapeHtml(desc) +
        (desc.length >= 120 ? "…" : "") +
        "</div>"
      : "",
     "</div>",
     '<div class="card-actions">',
     groupSelectHtml(meta.groupId),
     ' <button type="button" class="btn btn-edit-prompt icon-btn" title="编辑描述与触发">' +
      _ipk("edit", "ipk-sm") +
      "</button>",
     ' <label class="toggle tool-toggle-label" title="开关">',
     ' <input type="checkbox" class="toggle-tool"' +
      (enabled ? " checked" : "") +
      " />",
     ' <span class="toggle-txt">' + (enabled ? "开" : "关") + "</span>",
     " </label>",
     "</div>",
    ].join("\n");
    bindGroupPick(card.querySelector(".group-pick"), "tool", name, meta.groupId);
    card.querySelector(".btn-edit-prompt")?.addEventListener("click", () => {
     openPromptEditor({
      kind: "tool",
      id: name,
      label: label + " (" + name + ")",
      baseDescription: t.base_description || "",
      override:
       (t.prompt_meta && t.prompt_meta.description) || t.prompt_override || "",
      howToCall: (t.prompt_meta && t.prompt_meta.how_to_call) || "",
      baseHowToCall: t.base_how_to_call || "",
      sceneKeywords:
       (t.prompt_meta && t.prompt_meta.scene_keywords) || t.scene_keywords || [],
      baseSceneKeywords: t.base_scene_keywords || [],
      group: meta.groupId,
     });
    });
    const cb = card.querySelector(".toggle-tool");
    const txt = card.querySelector(".toggle-txt");
    cb.addEventListener("change", async (e) => {
     try {
      await api("/api/config/tools/toggle", {
       method: "POST",
       body: JSON.stringify({ name, enabled: e.target.checked }),
      });
      txt.textContent = e.target.checked ? "开" : "关";
      card.classList.toggle("card-disabled", !e.target.checked);
      showToast(label + " 已" + (e.target.checked ? "开启" : "关闭"), "success");
      if (typeof loadToolsPanel === "function") loadToolsPanel({ soft: true });
     } catch (err) {
      e.target.checked = !e.target.checked;
      showToast("切换失败", "error");
     }
    });
    body.appendChild(card);
   }
  }
 }

 // --- Skills ---
 async function loadSkills(opts = {}) {
 const soft = !!opts.soft;
 const list = $("skillList");
 if (!list) return;
 const keepUi = soft && _panelHasContent(list);
 if (!keepUi) {
  list.innerHTML = "";
  renderSkeleton(list, 3);
  setMsg("msgSkills", "载入中…");
 }
 try {
 await loadCapabilityGroups();
 let skills = await api("/api/config/skills");
 if (!Array.isArray(skills)) skills = skills.items || [];
 list.innerHTML = "";
 if (!skills.length) {
 injectPanelToolbar(list, "skills");
 await appendBuiltinCapabilities(list, []);
 if (!list.querySelector(".card")) {
  list.innerHTML =
   '<div class="card"><div class="card-body"><div class="card-sub">还没有业务能力。可导入 .evaskill，或用系统内置。</div></div></div>';
 }
 setMsg("msgSkills", "还没有业务能力包", "ok");
 return;
 }

 injectPanelToolbar(list, "skills");
 // 用 id 优先匹配分组（目录名）
 const forGroup = skills.map((s) => ({
 ...s,
 _key: s.id || s.name || "",
 }));
 const buckets = groupItemsByMeta(forGroup, "_key", SKILL_META);
 let primaryCount = 0;
 let enabledCount = 0;

 for (const g of orderedGroupsFor(buckets)) {
 const rows = buckets.get(g.id) || [];
 if (!shouldShowGroup(g, rows)) continue;
 const body = appendCollapsibleGroup(
 list,
 g.id,
 g.label,
 rows.length,
 g.icon
 );
 for (const { item: s, meta } of rows) {
 if (meta.role === "primary") primaryCount += 1;
 const enabled = s.enabled !== false;
 if (enabled) enabledCount += 1;
 const displayName = s.display_name || s.name || s.id;
 const how = (s.how_to_call || (s.spec && s.spec.trigger) || "").trim();
 const howLine = how
  ? `<div class="card-sub muted-line">下次这样说：${escapeHtml(how)}</div>`
  : "";
 const ready = s.integration_id
  ? s.integration_status === "ready"
  : true;
 const readyBadge = s.has_handler || s.tool_count
  ? ready
   ? ' <span class="pill integ-ok">可用</span>'
   : ' <span class="pill integ-warn">缺配置</span>'
  : "";
 const noteLine = meta.note
 ? `<div class="card-sub muted-line">${escapeHtml(meta.note)}</div>`
 : "";
 const protectedSkill = !!s.protected;
 const card = document.createElement("div");
 card.className =
 "card" +
 (meta.role === "primary" ? " card-role-primary" : "") +
 (enabled ? "" : " card-disabled");
 const ovBadge = s.has_prompt_override
 ? ' <span class="pill" title="已自定义描述或触发方式">已自定义</span>'
 : "";
 const integId = s.integration_id || "";
 const integSt = s.integration_status || "";
 let integBadge = "";
 if (integId) {
 const stLabel =
 integSt === "ready"
 ? "集成已配置"
 : integSt === "partial"
 ? "集成不完整"
 : "未配置集成";
 const stClass =
 integSt === "ready"
 ? "integ-ok"
 : integSt === "partial"
 ? "integ-warn"
 : "integ-miss";
 integBadge = ` <span class="pill ${stClass}" title="${escapeHtml(
 s.integration_name || integId
 )}">${escapeHtml(stLabel)}</span>`;
 }
 card.innerHTML = `
 ${
  protectedSkill
   ? ""
   : `<label class="skill-pick" title="选择后可导出"><input type="checkbox" class="skill-export-pick" data-skill-id="${escapeHtml(
      s.id || s.name || ""
     )}" /></label>`
 }
 <div class="card-body">
 <div class="card-title">${escapeHtml(displayName)}${
  protectedSkill ? ' <span class="pill">系统</span>' : ""
 }${ovBadge}${integBadge}${readyBadge}</div>
 <div class="card-sub">${escapeHtml(
 (s.description || "").slice(0, 140)
 )}${(s.description || "").length > 140 ? "…" : ""}</div>
 ${howLine}
 ${
 enabled
 ? ""
 : '<div class="card-sub muted-line">已关闭</div>'
 }
 </div>
 <div class="card-actions">
 ${groupSelectHtml(meta.groupId)}
 ${
 how
  ? `<button type="button" class="btn btn-try-skill icon-btn" title="填入调用说法">${_ipk(
   "play",
   "ipk-sm"
  )}</button>`
  : ""
 }
 ${
 integId
 ? `<button type="button" class="btn btn-open-integ icon-btn" title="配置集成">${_ipk(
 "connection",
 "ipk-sm"
 )}</button>`
 : ""
 }
 <button type="button" class="btn btn-edit-prompt icon-btn" title="编辑描述与触发">${_ipk(
 "edit",
 "ipk-sm"
 )}</button>
 ${
  protectedSkill
   ? ""
   : `<button type="button" class="btn btn-uninstall-skill icon-btn" title="${
      enabled ? "先关闭此技能" : "卸载此技能"
     }">${_ipk("delete", "ipk-sm")}</button>`
 }
 <label class="toggle tool-toggle-label">
 <input type="checkbox" class="toggle-skill" ${
 enabled ? "checked" : ""
 } />
 <span class="toggle-txt">${enabled ? "开" : "关"}</span>
 </label>
 </div>`;
 bindGroupPick(
  card.querySelector(".group-pick"),
  "skill",
  s.id || s.name || "",
  meta.groupId
 );
 card.querySelector(".btn-try-skill")?.addEventListener("click", () => {
  const input = document.getElementById("input");
  if (input && how) {
   input.value = how;
   input.dispatchEvent(new Event("input", { bubbles: true }));
   try { input.focus(); } catch (_) {}
  }
  if (typeof closeConfig === "function") closeConfig();
  showToast("已填入调用说法，直接发送即可试跑", "ok");
 });
 card.querySelector(".btn-open-integ")?.addEventListener("click", () => {
 switchTab("integrations");
 openIntegrationEditor(integId);
 });
 card.querySelector(".btn-edit-prompt")?.addEventListener("click", () => {
 openPromptEditor({
 kind: "skill",
 id: s.id || "",
 label: displayName + " (" + (s.id || "") + ")",
 baseDescription: s.base_description || s.description || "",
 override: (s.prompt_meta && s.prompt_meta.description) || s.prompt_override || "",
 howToCall: (s.prompt_meta && s.prompt_meta.how_to_call) || "",
 baseHowToCall: s.base_how_to_call || "",
 sceneKeywords: (s.prompt_meta && s.prompt_meta.scene_keywords) || s.scene_keywords || [],
 baseSceneKeywords: s.base_scene_keywords || [],
 group: meta.groupId,
 });
 });
 card.querySelector(".btn-uninstall-skill")?.addEventListener("click", async () => {
  const skillId = s.id || s.name;
  if (enabled) {
   try {
    await api("/api/config/skills/toggle", {
     method: "POST",
     body: JSON.stringify({ id: skillId, enabled: false }),
    });
    showToast(`${displayName} 已关闭。再点一次卸载才会从本机删除。`, "info", 4200);
    loadSkills();
    if (typeof loadToolsPanel === "function") loadToolsPanel();
    if (typeof loadHealth === "function") loadHealth();
   } catch (err) {
    setMsg("msgSkills", err.message, "error");
    showToast("关闭失败", "error");
   }
   return;
  }
  if (!confirm(`卸载「${displayName}」？文件将从本机 skills/ 删除，可再导入。`)) return;
  try {
   await api("/api/config/skills/" + encodeURIComponent(skillId), {
    method: "DELETE",
   });
   showToast(`${displayName} 已卸载`, "success");
   loadSkills();
   if (typeof loadToolsPanel === "function") loadToolsPanel();
  } catch (err) {
   setMsg("msgSkills", err.message, "error");
   showToast("卸载失败", "error");
  }
 });
 const cb = card.querySelector(".toggle-skill");
 const txt = card.querySelector(".toggle-txt");
 cb.addEventListener("change", async (e) => {
 try {
 // Prefer package id; also send folder name if different
 const skillId = s.id || s.name;
 await api("/api/config/skills/toggle", {
 method: "POST",
 body: JSON.stringify({ id: skillId, enabled: e.target.checked }),
 });
 txt.textContent = e.target.checked ? "开" : "关";
 card.classList.toggle("card-disabled", !e.target.checked);
 setMsg("msgSkills", `${displayName} 已更新`, "ok");
 showToast(`${displayName} 已更新`, "success");
 loadHealth();
 loadSkills();
 // skill tools appear under Tools — refresh that panel too
 if (typeof loadToolsPanel === "function") loadToolsPanel();
 } catch (err) {
 e.target.checked = !e.target.checked;
 setMsg("msgSkills", err.message, "error");
 showToast("切换失败", "error");
 }
 });
 body.appendChild(card);
 }
 }

 await appendBuiltinCapabilities(list, skills);
 setMsg(
 "msgSkills",
 `能力 ${skills.length} · 开着 ${enabledCount}。缺配置的点插头去填。`,
 "ok"
 );
 } catch (e) {
 list.innerHTML = `<div class="card"><div class="card-body"><div class="card-sub">${escapeHtml(
 e.message
 )}</div></div></div>`;
 setMsg("msgSkills", e.message, "error");
 showToast("加载Skills失败", "error");
 }
 }

 // --- MCP（扩展能力 · 普通人友好） ---
 let _mcpPresetsCache = null;

 function mcpStatusPill(m) {
 const st = m.status || {};
 if (m.enabled === false) {
 return '<span class="wf-status-pill wf-st-cancel">已停用</span>';
 }
 if (st.connected) {
 const n = st.tool_count || 0;
 return `<span class="wf-status-pill wf-st-ok">已连接 · ${n} 个能力</span>`;
 }
 if (st.error) {
 return '<span class="wf-status-pill wf-st-fail">连接失败</span>';
 }
 return '<span class="wf-status-pill wf-st-pending">未连接</span>';
 }

 function parseMcpEnvText(raw) {
 const t = (raw || "").trim();
 if (!t) return {};
 if (t.startsWith("{")) return JSON.parse(t);
 const env = {};
 t.split(/\r?\n/).forEach((line) => {
 const s = line.trim();
 if (!s || s.startsWith("#")) return;
 const i = s.indexOf("=");
 if (i <= 0) return;
 env[s.slice(0, i).trim()] = s.slice(i + 1).trim();
 });
 return env;
 }

 function formatMcpEnv(env) {
 if (!env || typeof env !== "object") return "";
 const keys = Object.keys(env);
 if (!keys.length) return "";
 // prefer KEY=val lines for ordinary users
 return keys.map((k) => `${k}=${env[k]}`).join("\n");
 }

 function parseMcpArgsText(raw) {
 return String(raw || "")
 .split(/\r?\n/)
 .map((s) => s.trim())
 .filter(Boolean);
 }

 async function ensureMcpPresets() {
 if (_mcpPresetsCache) return _mcpPresetsCache;
 try {
 const rows = await api("/api/config/mcp/presets");
 _mcpPresetsCache = Array.isArray(rows) ? rows : [];
 } catch {
 _mcpPresetsCache = [];
 }
 return _mcpPresetsCache;
 }

 async function renderMcpPresets() {
 const grid = $("mcpPresetGrid");
 if (!grid) return;
 const presets = await ensureMcpPresets();
 const usable = presets.filter((p) => p.id !== "custom");
 if (!usable.length) {
 grid.innerHTML =
 '<div class="wf-empty-hint">暂无预设，请用「自定义添加」</div>';
 return;
 }
 grid.innerHTML = usable
 .map(
 (p) => `
 <button type="button" class="mcp-preset-card" data-mcp-preset="${escapeHtml(
 p.id
 )}">
 <div class="mcp-preset-top">
 <span class="mcp-preset-emoji">${escapeHtml(p.emoji || "📦")}</span>
 <strong>${escapeHtml(p.title || p.name || p.id)}</strong>
 </div>
 <div class="mcp-preset-desc">${escapeHtml(p.desc || "")}</div>
 <div class="mcp-preset-meta">${escapeHtml(p.need || "")}</div>
 <div class="mcp-preset-cta">一键添加 →</div>
 </button>`
 )
 .join("");
 }

 async function addMcpFromPreset(presetId) {
 const presets = await ensureMcpPresets();
 const p = presets.find((x) => x.id === presetId);
 if (!p) {
 showToast("找不到该预设", "error");
 return;
 }
 if (p.id === "custom") {
 openMcpEditor({});
 return;
 }
 setMsg("msgMcp", `正在添加「${p.title}」…`);
 try {
 const res = await api("/api/config/mcp", {
 method: "POST",
 body: JSON.stringify({
 name: p.name || p.title,
 command: p.command,
 args: p.args || [],
 env: p.env || {},
 enabled: true,
 preset_id: p.id,
 label: p.title,
 }),
 });
 const ok = res.ok !== false && res.status && res.status.connected;
 setMsg(
 "msgMcp",
 res.message || (ok ? "已连接" : "已保存但连接失败"),
 ok ? "ok" : "error"
 );
 showToast(ok ? `「${p.title}」已就绪` : "已保存，连接失败", ok ? "success" : "error");
 await loadMcp();
 loadHealth();
 } catch (e) {
 setMsg("msgMcp", e.message, "error");
 showToast(e.message || "添加失败", "error");
 }
 }

 async function loadMcp(opts = {}) {
 const soft = !!opts.soft;
 const list = $("mcpList");
 if (!list) return;
 const keepUi = soft && list.querySelector(".card");
 if (!keepUi) {
  list.innerHTML = "";
  renderSkeleton(list, 2);
  setMsg("msgMcp", "载入中…");
 }
 renderMcpPresets();
 try {
 let mcpList = await api("/api/config/mcp");
 if (!Array.isArray(mcpList)) mcpList = mcpList.items || [];
 list.innerHTML = "";
 if (!mcpList.length) {
 list.innerHTML =
 '<div class="card"><div class="card-body"><div class="card-sub">还没有扩展。上面点一个「一键添加」即可，大多数情况不用填命令。</div></div></div>';
 setMsg("msgMcp", "暂无扩展", "ok");
 return;
 }
 for (const m of mcpList) {
 const card = document.createElement("div");
 card.className = "card mcp-server-card";
 const st = m.status || {};
 const cmdLine = [m.command, ...(m.args || [])].filter(Boolean).join(" ");
 const err =
 !st.connected && st.error
 ? `<div class="card-sub mcp-err">${escapeHtml(
 String(st.error).slice(0, 160)
 )}</div>`
 : "";
 const tools =
 st.connected && (st.tools || []).length
 ? `<div class="card-sub muted-line">能力：${escapeHtml(
 (st.tools || [])
 .slice(0, 6)
 .map((t) => String(t).replace(/^mcp_[^_]+_/, ""))
 .join("、")
 )}${(st.tools || []).length > 6 ? "…" : ""}</div>`
 : "";
 card.innerHTML = `
 <div class="card-body">
 <div class="card-title-row">
 <div class="card-title">${escapeHtml(m.label || m.name || m.id)}</div>
 ${mcpStatusPill(m)}
 </div>
 <div class="card-sub">${escapeHtml(cmdLine || "—")}</div>
 ${err}
 ${tools}
 </div>
 <div class="card-actions">
 <button type="button" class="btn edit-mcp" data-mcp-id="${escapeHtml(
 m.id || ""
 )}">改设置</button>
 <button type="button" class="btn danger del-mcp" data-mcp-id="${escapeHtml(
 m.id || ""
 )}">删除</button>
 </div>`;
 card.querySelector(".edit-mcp")?.addEventListener("click", () =>
 openMcpEditor(m)
 );
 card.querySelector(".del-mcp")?.addEventListener("click", () =>
 deleteMcp(m.id || m.name)
 );
 list.appendChild(card);
 }
 const okN = mcpList.filter((m) => m.status && m.status.connected).length;
 setMsg(
 "msgMcp",
 `共 ${mcpList.length} 个 · 已连接 ${okN} 个`,
 "ok"
 );
 if (typeof L.hydrateIconPark === "function") L.hydrateIconPark(list);
 } catch (e) {
 list.innerHTML = `<div class="card"><div class="card-body"><div class="card-sub">${escapeHtml(e.message)}</div></div></div>`;
 setMsg("msgMcp", e.message, "error");
 showToast("加载扩展失败", "error");
 }
 }

 // --- LLM editor ---
 async function saveLlmFromForm() {
 const data = collectLlmFormPayload();
 if (data.transport === "cli" && !data.cli_command) {
 setMsg("msgLlmEditor", "CLI 模式请填写命令，例如 grok", "error");
 showToast("请填写 CLI 命令", "error");
 return;
 }
 try {
 await api("/api/config/llms", {
 method: "POST",
 body: JSON.stringify(data),
 });
 setMsg("msgLlm", "保存成功", "ok");
 showToast("LLM 已保存", "success");
 closeLlmEditor();
 loadLlms();
 await loadHealth();
 } catch (e) {
 setMsg("msgLlm", e.message, "error");
 showToast("保存失败", "error");
 }
 }

 async function testLlmFromForm() {
 const data = collectLlmFormPayload({ includeApiKey: true });
 if (data.transport === "cli" && !data.cli_command) {
 setMsg("msgLlmEditor", "CLI 模式请填写命令，例如 grok", "error");
 showToast("请填写 CLI 命令", "error");
 return;
 }
 try {
 setMsg("msgLlmEditor", "测试中…");
 setMsg("msgLlm", "测试中…");
 // Always POST form body so unsaved key/base_url/model are tested
 const res = await api("/api/config/llms/test", {
 method: "POST",
 body: JSON.stringify(data),
 });
 const ok = res.ok !== false && !res.error;
 const msg = ok ? "连接成功" : "" + (res.error || res.detail || "失败");
 setMsg("msgLlmEditor", msg, ok ? "ok" : "error");
 setMsg("msgLlm", msg, ok ? "ok" : "error");
 if (ok) showToast("连接成功", "success");
 else showToast("连接失败", "error");
 } catch (e) {
 setMsg("msgLlmEditor", "" + e.message, "error");
 setMsg("msgLlm", "" + e.message, "error");
 showToast("测试失败", "error");
 }
 }

 async function deleteLlm(id) {
 if (!id) return;
 if (!confirm("确定删除呢个 LLM？")) return;
 try {
 await api(`/api/config/llms/${encodeURIComponent(id)}`, { method: "DELETE" });
 setMsg("msgLlm", "已删除", "ok");
 showToast("LLM 已删除", "success");
 loadLlms();
 await loadHealth();
 } catch (e) {
 setMsg("msgLlm", e.message, "error");
 showToast("删除失败", "error");
 }
 }

 // --- Custom tool editor ---
 function openCustomToolEditor(tool) {
 const editingCtId = tool.id || "";
 $("ctId").value = editingCtId;
 $("ctName").value = tool.name || "";
 $("ctMethod").value = tool.method || "GET";
 $("ctDesc").value = tool.description || "";
 $("ctUrl").value = tool.url || "";
 $("ctHeaders").value = tool.headers
 ? typeof tool.headers === "string"
 ? tool.headers
 : JSON.stringify(tool.headers, null, 2)
 : "";
 $("ctEnabled").checked = tool.enabled !== false;
 const title = $("ctEditorTitle");
 if (title)
 title.innerHTML = editingCtId
 ? '<span data-ipk="edit" data-ipk-class="ipk-sm"></span> 编辑 HTTP 工具'
 : '<span data-ipk="plus" data-ipk-class="ipk-sm"></span> 添加 HTTP 工具';
 openNestedEditor("customToolEditorModal");
 }

 function closeCustomToolEditor() {
 closeNestedEditor("customToolEditorModal");
 }

 async function saveCustomToolFromForm() {
 let headers = {};
 try {
 const h = $("ctHeaders").value.trim();
 if (h) headers = JSON.parse(h);
 } catch {
 setMsg("msgTools", "Headers JSON 格式错误", "error");
 showToast("Headers 格式错误", "error");
 return;
 }
 const data = {
 id: $("ctId").value || undefined,
 name: $("ctName").value,
 method: $("ctMethod").value,
 description: $("ctDesc").value,
 url: $("ctUrl").value,
 headers,
 enabled: $("ctEnabled").checked,
 };
 try {
 await api("/api/config/tools/custom", {
 method: "POST",
 body: JSON.stringify(data),
 });
 setMsg("msgTools", "保存成功", "ok");
 showToast("工具已保存", "success");
 closeCustomToolEditor();
 loadToolsPanel();
 } catch (e) {
 setMsg("msgTools", e.message, "error");
 showToast("保存失败", "error");
 }
 }

 async function deleteCustomTool(id) {
 if (!id) return;
 if (!confirm("确定删除？")) return;
 try {
 await api(`/api/config/tools/custom/${encodeURIComponent(id)}`, {
 method: "DELETE",
 });
 setMsg("msgTools", "已删除", "ok");
 showToast("工具已删除", "success");
 loadToolsPanel();
 } catch (e) {
 setMsg("msgTools", e.message, "error");
 showToast("删除失败", "error");
 }
 }

 // --- MCP editor ---
 function openMcpEditor(mcp) {
 const m = mcp || {};
 $("mcpId").value = m.id || "";
 $("mcpPresetId").value = m.preset_id || "";
 $("mcpName").value = m.label || m.name || "";
 $("mcpCommand").value = m.command || "";
 $("mcpArgs").value = Array.isArray(m.args) ? m.args.join("\n") : "";
 $("mcpEnv").value = formatMcpEnv(m.env);
 $("mcpEnabled").checked = m.enabled !== false;
 if ($("mcpEditorTitle")) {
 $("mcpEditorTitle").innerHTML = m.id
 ? '<span data-ipk="edit" data-ipk-class="ipk-sm"></span> 改扩展设置'
 : '<span data-ipk="plus" data-ipk-class="ipk-sm"></span> 自定义添加扩展';
 }
 if ($("mcpEditorLead")) {
 $("mcpEditorLead").textContent = m.id
 ? "改完点「保存并连接」。多数情况只改名称或启用即可。"
 : "也可从上方预设一键添加。命令一般是 npx，参数每行一条。";
 }
 openNestedEditor("mcpEditorModal");
 $("mcpName")?.focus();
 }

 function closeMcpEditor() {
 closeNestedEditor("mcpEditorModal");
 }

 async function saveMcpFromForm() {
 let env = {};
 try {
 env = parseMcpEnvText($("mcpEnv")?.value || "");
 } catch {
 setMsg("msgMcp", "环境变量格式不对（用 KEY=值 每行一条，或 JSON）", "error");
 showToast("环境变量格式错误", "error");
 return;
 }
 const name = ($("mcpName")?.value || "").trim();
 const command = ($("mcpCommand")?.value || "").trim();
 if (!name) {
 setMsg("msgMcp", "请填显示名称", "error");
 $("mcpName")?.focus();
 return;
 }
 if (!command) {
 setMsg("msgMcp", "请填启动命令，或回上面用预设一键添加", "error");
 $("mcpCommand")?.focus();
 return;
 }
 const data = {
 id: $("mcpId").value || undefined,
 name,
 command,
 args: parseMcpArgsText($("mcpArgs")?.value || ""),
 env,
 enabled: !!$("mcpEnabled")?.checked,
 preset_id: $("mcpPresetId")?.value || undefined,
 label: name,
 };
 try {
 setMsg("msgMcp", "保存并连接中…");
 const res = await api("/api/config/mcp", {
 method: "POST",
 body: JSON.stringify(data),
 });
 const ok = res.status && res.status.connected;
 setMsg(
 "msgMcp",
 res.message || (ok ? "已连接" : "已保存"),
 ok ? "ok" : "error"
 );
 showToast(ok ? "扩展已连接" : "已保存，连接失败", ok ? "success" : "error");
 closeMcpEditor();
 loadMcp();
 loadHealth();
 } catch (e) {
 setMsg("msgMcp", e.message, "error");
 showToast("保存失败", "error");
 }
 }

 async function deleteMcp(id) {
 if (!id) return;
 if (!confirm("确定删除这个扩展？对话里将不能再用它的能力。")) return;
 try {
 await api(`/api/config/mcp/${encodeURIComponent(id)}`, {
 method: "DELETE",
 });
 setMsg("msgMcp", "已删除", "ok");
 showToast("已删除扩展", "success");
 loadMcp();
 loadHealth();
 } catch (e) {
 setMsg("msgMcp", e.message, "error");
 showToast("删除失败", "error");
 }
 }

 async function reloadMcpServers() {
 try {
 setMsg("msgMcp", "重新连接中…");
 const res = await api("/api/config/mcp/reconnect", { method: "POST" });
 const n = (res.summary && res.summary.mcp_servers) || 0;
 setMsg("msgMcp", `已重连 · 当前 ${n} 个在线`, "ok");
 showToast("已重新连接", "success");
 loadMcp();
 loadHealth();
 } catch (e) {
 try {
 await api("/api/config/reload?reconnect_mcp=true", { method: "POST" });
 setMsg("msgMcp", "已触发 reload", "ok");
 loadMcp();
 loadHealth();
 } catch (e2) {
 setMsg("msgMcp", "" + e2.message, "error");
 showToast("重连失败", "error");
 }
 }
 }

 function settingsExportFilename() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return (
   "eva-settings-" +
   d.getFullYear() +
   pad(d.getMonth() + 1) +
   pad(d.getDate()) +
   ".json"
  );
 }

 function selectedSkillExportIds() {
  return Array.from(document.querySelectorAll(".skill-export-pick:checked"))
   .map((el) => el.getAttribute("data-skill-id") || "")
   .filter(Boolean);
 }

 function toggleSelectAllSkills() {
  const boxes = Array.from(document.querySelectorAll(".skill-export-pick"));
  if (!boxes.length) {
   showToast("没有可导出的业务技能", "error");
   return;
  }
  const allOn = boxes.every((el) => el.checked);
  boxes.forEach((el) => {
   el.checked = !allOn;
  });
  const n = boxes.filter((el) => el.checked).length;
  setMsg("msgSkills", n ? `已选 ${n} 个业务技能` : "已取消全选", "ok");
 }

 async function exportSkillPack() {
  try {
   const ids = selectedSkillExportIds();
   if (!ids.length) {
    setMsg("msgSkills", "请先勾选要导出的技能", "error");
    showToast("请先勾选要导出的技能", "error");
    return;
   }
   const q = "?ids=" + encodeURIComponent(ids.join(","));
   setMsg("msgSkills", "导出中…");
   const res = await fetch("/api/config/skills/export" + q, {
    credentials: "same-origin",
   });
   if (!res.ok) {
    let detail = "导出失败";
    try {
     const j = await res.json();
     detail = j.detail || detail;
    } catch (_) {}
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
   }
   const blob = await res.blob();
   const cd = res.headers.get("content-disposition") || "";
   let fname = "eva-skills.evaskill";
   const star = /filename\*=UTF-8''([^;]+)/i.exec(cd);
   const plain = /filename="?([^";]+)"?/i.exec(cd);
   if (star && star[1]) {
    try {
     fname = decodeURIComponent(star[1]);
    } catch (_) {}
   } else if (plain && plain[1]) {
    fname = plain[1];
   }
   const a = document.createElement("a");
   a.href = URL.createObjectURL(blob);
   a.download = fname;
   document.body.appendChild(a);
   a.click();
   a.remove();
   setTimeout(() => URL.revokeObjectURL(a.href), 2000);
   setMsg("msgSkills", `已导出 ${ids.length} 个技能`, "ok");
   showToast(`已导出 ${ids.length} 个技能`, "success");
  } catch (e) {
   setMsg("msgSkills", e.message || String(e), "error");
   showToast("导出失败", "error");
  }
 }

 async function importSkillPack(file) {
  const overwrite = confirm(
   "导入「" + file.name + "」\n\n确定覆盖已安装的同名技能？\n选「取消」则跳过已存在的包。"
  );
  const fd = new FormData();
  fd.append("file", file);
  try {
   setMsg("msgSkills", "导入中…");
   const res = await fetch(
    "/api/config/skills/import?overwrite=" + (overwrite ? "true" : "false"),
    { method: "POST", body: fd, credentials: "same-origin" }
   );
   const data = await res.json().catch(() => ({}));
   if (!res.ok) {
    throw new Error(data.detail || data.error || "导入失败");
   }
   const n = (data.installed || []).length;
   const skip = (data.skipped || []).length;
   const fail = (data.failed || []).length;
   const setup = Array.isArray(data.need_setup) ? data.need_setup : [];
   const bits = [`安装 ${n}`];
   if (skip) bits.push(`跳过 ${skip}`);
   if (fail) bits.push(`失败 ${fail}`);
   if (setup.length) bits.push(`${setup.length} 个集成待填写`);
   setMsg("msgSkills", bits.join(" · "), fail ? "error" : "ok");
   showToast(
    setup.length
     ? "已安装。账号密码不会随包导入，请填写集成。"
     : fail
     ? "导入完成（有失败项）"
     : "导入完成",
    fail ? "error" : setup.length ? "warn" : "success"
   );
   loadSkills();
   if (typeof loadToolsPanel === "function") loadToolsPanel();
   if (typeof loadIntegrations === "function") loadIntegrations({ soft: true });
   if (setup.length) {
    const names = setup.map((x) => x.name || x.id).join("、");
    const go = confirm(
     "技能已导入。以下连接需要到「设定→集成」填写地址/账号（密钥不会随包导入）：\n\n" +
      names +
      "\n\n现在去填写？"
    );
    if (go && typeof switchTab === "function") {
     switchTab("integrations");
     if (typeof loadIntegrations === "function") {
      loadIntegrations().then(() => {
       if (setup[0] && setup[0].id && typeof openIntegrationEditor === "function") {
        openIntegrationEditor(setup[0].id);
       }
      });
     }
    }
   }
  } catch (e) {
   setMsg("msgSkills", e.message || String(e), "error");
   showToast("导入失败", "error");
  }
 }

 async function exportSettings() {
  try {
   setMsg("msgAgent", "导出中…");
   const data = await api("/api/config/export");
   const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json;charset=utf-8",
   });
   const a = document.createElement("a");
   a.href = URL.createObjectURL(blob);
   a.download = settingsExportFilename();
   document.body.appendChild(a);
   a.click();
   a.remove();
   setTimeout(() => URL.revokeObjectURL(a.href), 2000);
   setMsg("msgAgent", "已导出设定", "ok");
   showToast("设定已导出", "success");
  } catch (e) {
   setMsg("msgAgent", e.message || String(e), "error");
   showToast("导出失败", "error");
  }
 }

 async function importSettingsFile(file) {
  if (!file) return;
  let parsed;
  try {
   parsed = JSON.parse(await file.text());
  } catch (_) {
   setMsg("msgAgent", "不是有效的 JSON 文件", "error");
   showToast("导入失败：文件格式不对", "error");
   return;
  }
  const ok = window.confirm(
   "导入将覆盖当前设定（人设、LLM、集成、工具、MCP）。\n知识库、工作流、对话记录不会改动。\n确定导入？"
  );
  if (!ok) return;
  try {
   setMsg("msgAgent", "导入中…");
   const res = await api("/api/config/import", {
    method: "POST",
    body: JSON.stringify(parsed),
   });
   if (res?.config) state.config = res.config;
   L.renderAgentForm?.(res.config || state.config);
   if (typeof L.refreshVoiceLangFromPersona === "function") {
    L.refreshVoiceLangFromPersona();
   }
   loadLlms({ soft: true });
   loadToolsPanel({ soft: true });
   loadMcp({ soft: true });
   loadIntegrations({ soft: true });
   loadHealth();
   setMsg("msgAgent", "设定已导入", "ok");
   showToast("设定已导入", "success");
  } catch (e) {
   setMsg("msgAgent", e.message || String(e), "error");
   showToast("导入失败", "error");
  }
 }

 /**
  * 设定弹窗 HTML 异步注入后才存在的按钮：统一事件委托。
  * 避免远程服务器上 config-modal.html 慢于 JS 执行时 addEventListener 绑空。
  */
 function bindConfigDelegatedUi() {
 if (bindConfigDelegatedUi._done) return;
 bindConfigDelegatedUi._done = true;

 bindNestedBackdropClose("llmEditorModal", closeLlmEditor);
 document.addEventListener("change", (ev) => {
  const el = ev.target;
  if (!(el instanceof Element)) return;
  if (el.id === "llmTransport") syncLlmTransportUi();
  if (el.id === "llmCliPreset") applyLlmCliPreset();
 });
 bindNestedBackdropClose("customToolEditorModal", closeCustomToolEditor);
 bindNestedBackdropClose("mcpEditorModal", closeMcpEditor);

 document.addEventListener("click", (e) => {
  const t = e.target;
  if (!(t instanceof Element)) return;

  const card = t.closest("[data-mcp-preset]");
  if (card && card.closest("#mcpPresetGrid")) {
   e.preventDefault();
   addMcpFromPreset(card.getAttribute("data-mcp-preset") || "");
   return;
  }

  // 点在图标上时取最近带 id 的按钮
  const btn = t.closest(
   "button[id], .btn[id], a[id], [role='button'][id]"
  );
  if (!btn || !btn.id) return;

  switch (btn.id) {
   case "btnAddLlm":
    openLlmEditor({});
    break;
   case "btnCancelLlm":
   case "btnCloseLlmEditor":
    closeLlmEditor();
    break;
   case "btnSaveLlm":
    saveLlmFromForm();
    break;
   case "btnTestLlm":
    testLlmFromForm();
    break;
   case "btnAddCustomTool":
    openCustomToolEditor({});
    break;
   case "btnAddToolGroup":
   case "btnAddSkillGroup":
    promptAddCapabilityGroup();
    break;
   case "btnCancelCustomTool":
   case "btnCloseCustomToolEditor":
    closeCustomToolEditor();
    break;
   case "btnSaveCustomTool":
    saveCustomToolFromForm();
    break;
   case "btnAddMcp":
    openMcpEditor({});
    break;
   case "btnCancelMcp":
   case "btnCloseMcpEditor":
    closeMcpEditor();
    break;
   case "btnSaveMcp":
    saveMcpFromForm();
    break;
   case "btnReloadMcp":
    reloadMcpServers();
    break;
   case "btnRefreshEvolution":
    loadEvolutionPanel();
    break;
   case "btnExportSettings":
    exportSettings();
    break;
   case "btnImportSettings":
    $("cfgImportInput")?.click();
    break;
   case "btnSelectAllSkills":
    toggleSelectAllSkills();
    break;
   case "btnExportSkills":
    exportSkillPack();
    break;
   case "btnImportSkills":
    $("cfgSkillImportInput")?.click();
    break;
   case "btnCancelPrompt":
   case "btnClosePromptEditor":
    closePromptEditor();
    break;
   case "btnSavePrompt":
    savePromptFromForm();
    break;
   case "btnResetPrompt":
    resetPromptFromForm();
    break;
   default:
    break;
  }
 });

 document.addEventListener("change", (e) => {
  const t = e.target;
  if (!(t instanceof Element)) return;
  if (t.id === "cfgSkillImportInput") {
   const file = t.files && t.files[0];
   t.value = "";
   if (file) importSkillPack(file);
   return;
  }
  if (t.id === "cfgImportInput") {
   const file = t.files && t.files[0];
   t.value = "";
   if (file) importSettingsFile(file);
  }
 });
 }

 // 立即注册委托（不依赖 DOM 是否已注入）
 bindConfigDelegatedUi();

 // Export
 async function loadOfficePairing() {
  bindOfficePairingOnce();
  const codeEl = $("officePairCode");
  const meta = $("officePairMeta");
  const msg = $("msgOffice");
  if (!codeEl) return;
  try {
    let data = await api("/api/auth/hub/pairing");
    if (!(data.active && data.pairing_code)) {
      try {
        data = await api("/api/auth/hub/pairing/refresh", { method: "POST" });
      } catch (_) {}
    }
    if (data.active && data.pairing_code) {
      codeEl.value = data.pairing_code;
      const min = Math.max(1, Math.ceil((data.remaining_sec || 0) / 60));
      if (meta) meta.textContent = `约 ${min} 分钟内有效，一次性使用。`;
    } else {
      codeEl.value = "";
      if (meta) meta.textContent = "没有有效连接码，点「刷新连接码」。";
    }
    if (msg) msg.textContent = "";
  } catch (e) {
    codeEl.value = "";
    if (meta) meta.textContent = "请先登录。";
    if (msg) msg.textContent = e.message || "无法读取连接码";
  }
 }

 function bindOfficePairingOnce() {
  if (bindOfficePairingOnce.done) return;
  bindOfficePairingOnce.done = true;
  document.addEventListener("click", async (e) => {
    const t = e.target;
    if (!(t instanceof Element)) return;
    if (t.closest("#btnOfficeCopy")) {
      const v = ($("officePairCode")?.value || "").trim();
      const msg = $("msgOffice");
      if (!v) {
        if (msg) msg.textContent = "没有可复制的连接码";
        return;
      }
      try {
        await navigator.clipboard.writeText(v);
        if (msg) msg.textContent = "已复制";
      } catch (_) {
        if (msg) msg.textContent = "复制失败，请手动选中";
      }
      return;
    }
    if (t.closest("#btnOfficeRefresh")) {
      const msg = $("msgOffice");
      try {
        const data = await api("/api/auth/hub/pairing/refresh", { method: "POST" });
        if ($("officePairCode")) $("officePairCode").value = data.pairing_code || "";
        if ($("officePairMeta")) $("officePairMeta").textContent = "已刷新，30 分钟内有效。";
        if (msg) msg.textContent = "已生成新连接码";
      } catch (err) {
        if (msg) msg.textContent = err.message || "刷新失败";
      }
    }
  });
 }
 bindOfficePairingOnce();

 L.switchTab = switchTab;
 L.switchConfigGroup = switchConfigGroup;
 L.loadOfficePairing = loadOfficePairing;
 L.openConfig = openConfig;
 L.bindConfigDelegatedUi = bindConfigDelegatedUi;
 L.openNestedEditor = openNestedEditor;
 L.closeNestedEditor = closeNestedEditor;
 L.closeLlmEditor = closeLlmEditor;
 L.closeCustomToolEditor = closeCustomToolEditor;
 L.closeMcpEditor = closeMcpEditor;
 L.closeIntegrationEditor = closeIntegrationEditor;
 L.closeConfig = closeConfig;
 // --- Prompt override editor (tool / skill): 描述 + 触发方式 ---
 function parseSceneKeywordsInput(raw) {
 return String(raw || "")
 .split(/[,，、;；\n]+/)
 .map((s) => s.trim())
 .filter(Boolean)
 .filter((s, i, arr) => arr.findIndex((x) => x.toLowerCase() === s.toLowerCase()) === i)
 .slice(0, 24);
 }

 function closePromptEditor() {
 closeNestedEditor("promptEditorModal");
 }

 function openPromptEditor(opts) {
 const kind = opts.kind === "skill" ? "skill" : "tool";
 const id = opts.id || "";
 if (!id) return;
 const baseDesc = opts.baseDescription || "";
 const baseHow = opts.baseHowToCall || "";
 const baseKw = Array.isArray(opts.baseSceneKeywords) ? opts.baseSceneKeywords : [];
 const ovDesc = opts.override || "";
 const ovHow = opts.howToCall || "";
 const ovKw = Array.isArray(opts.sceneKeywords) ? opts.sceneKeywords : [];
 $("promptTargetKind").value = kind;
 $("promptTargetId").value = id;
 $("promptTargetLabel").value = opts.label || id;
 $("promptBaseDesc").value = baseDesc;
 $("promptCustomDesc").value = ovDesc || baseDesc;
 $("promptHowToCall").value = ovHow || baseHow;
 $("promptSceneKeywords").value = ovKw.join(", ");
 const groupSel = $("promptGroup");
 const groupCur = (opts.group || "").toString() || "other";
 if ($("promptTargetGroup")) $("promptTargetGroup").value = groupCur;
 if (groupSel) {
  groupSel.innerHTML = CAPABILITY_GROUPS.map((g) => {
   const sel = g.id === groupCur ? " selected" : "";
   return (
    '<option value="' +
    escapeHtml(g.id) +
    '"' +
    sel +
    ">" +
    escapeHtml(g.label) +
    "</option>"
   );
  }).join("");
  groupSel.value = groupCur;
 }
 const howHint = $("promptHowHint");
 if (howHint) {
 howHint.dataset.base = baseHow;
 howHint.textContent = baseHow
 ? "代码默认：" + baseHow
 : "用户以后怎么喊它，会出现在卡片「下次这样说」。";
 }
 const kwHint = $("promptKwHint");
 if (kwHint) {
 kwHint.textContent = baseKw.length
 ? "代码默认：" + baseKw.join("、") + "。这里只填额外的词。"
 : "没有代码默认关键词。逗号分隔，用于模型选工具。";
 }
 const titleEl = $("promptEditorTitle");
 if (titleEl) {
 titleEl.innerHTML =
 (typeof _ipk === "function" ? _ipk("edit", "ipk-sm") + " " : "") +
 (kind === "skill" ? "编辑 Skill 描述与触发" : "编辑 Tool 描述与触发");
 }
 const hintEl = $("promptEditorHint");
 if (hintEl) {
 hintEl.textContent =
 kind === "skill"
 ? "Skill 包说明和触发方式。保存到配置，不改代码；与包同名的 Tool 会把这里当后备。"
 : "Tool 的说明（模型选工具时看到）和触发方式。保存到配置，不改代码。";
 }
 setMsg("msgPrompt", "");
 if (typeof L.hydrateIconPark === "function") {
 L.hydrateIconPark($("promptEditorModal"));
 }
 openNestedEditor("promptEditorModal");
 }

 async function resetPromptFromForm() {
 const kind = $("promptTargetKind")?.value || "tool";
 const id = $("promptTargetId")?.value || "";
 if (!id) return;
 if (!confirm("清除自定义描述和触发方式，恢复代码默认？")) return;
 try {
 const path =
 kind === "skill"
 ? `/api/config/skills/${encodeURIComponent(id)}/prompt`
 : `/api/config/tools/${encodeURIComponent(id)}/prompt`;
 await api(path, {
 method: "PUT",
 body: JSON.stringify({
 description: "",
 how_to_call: "",
 scene_keywords: [],
 }),
 });
 $("promptCustomDesc").value = $("promptBaseDesc").value || "";
 $("promptHowToCall").value = $("promptHowHint")?.dataset.base || "";
 $("promptSceneKeywords").value = "";
 setMsg("msgPrompt", "已恢复默认", "ok");
 showToast("已恢复默认", "success");
 closePromptEditor();
 if (kind === "skill") loadSkills();
 else loadToolsPanel();
 } catch (e) {
 setMsg("msgPrompt", e.message, "error");
 showToast("恢复失败", "error");
 }
 }

 async function savePromptFromForm() {
 const kind = $("promptTargetKind")?.value || "tool";
 const id = $("promptTargetId")?.value || "";
 if (!id) return;
 const baseDesc = ($("promptBaseDesc")?.value || "").trim();
 const baseHow = ($("promptHowHint")?.dataset.base || "").trim();
 const desc = ($("promptCustomDesc")?.value || "").trim();
 const how = ($("promptHowToCall")?.value || "").trim();
 const kws = parseSceneKeywordsInput($("promptSceneKeywords")?.value || "");
 const description = desc === baseDesc ? "" : desc;
 const how_to_call = how === baseHow ? "" : how;
 const group = ($("promptGroup")?.value || "").trim();
 const prevGroup = ($("promptTargetGroup")?.value || "").trim();
 const groupChanged = !!(group && group !== prevGroup);
 if (!description && !how_to_call && !kws.length && !groupChanged) {
 setMsg(
 "msgPrompt",
 "没有相对代码默认的改动。要清空覆盖请点「恢复默认」。",
 "error"
 );
 return;
 }
 try {
 if (description || how_to_call || kws.length) {
  const path =
   kind === "skill"
    ? `/api/config/skills/${encodeURIComponent(id)}/prompt`
    : `/api/config/tools/${encodeURIComponent(id)}/prompt`;
  await api(path, {
   method: "PUT",
   body: JSON.stringify({
    description,
    how_to_call,
    scene_keywords: kws,
   }),
  });
 }
 if (groupChanged) {
  const gpath =
   kind === "skill"
    ? `/api/config/skills/${encodeURIComponent(id)}/group`
    : `/api/config/tools/${encodeURIComponent(id)}/group`;
  await api(gpath, {
   method: "PUT",
   body: JSON.stringify({ group }),
  });
 }
 setMsg("msgPrompt", "已保存", "ok");
 showToast(groupChanged && !description && !how_to_call && !kws.length ? "分类已保存" : "描述与触发方式已保存", "success");
 closePromptEditor();
 if (kind === "skill") loadSkills();
 else loadToolsPanel();
 } catch (e) {
 setMsg("msgPrompt", e.message, "error");
 showToast("保存失败", "error");
 }
 }

 // --- Integrations (skill connection configs) ---
 let _integCache = [];

 function integStatusLabel(st) {
 if (st === "ready") return "已就绪";
 if (st === "partial") return "部分配置";
 return "未配置";
 }

 async function loadIntegrations(opts = {}) {
 const soft = !!opts.soft;
 const list = $("integrationList");
 if (!list) return;
 const keepUi = soft && list.querySelector(".card");
 if (!keepUi) {
  list.innerHTML = "";
  renderSkeleton(list, 3);
  setMsg("msgIntegrations", "载入中…");
 }
 try {
 const data = await api("/api/config/integrations");
 const items = Array.isArray(data?.items) ? data.items : [];
 _integCache = items;
 list.innerHTML = "";
 if (!items.length) {
 list.innerHTML =
 '<div class="card"><div class="card-body"><div class="card-sub">暂无集成项</div></div></div>';
 setMsg("msgIntegrations", "0 个", "ok");
 return;
 }
 for (const it of items) {
 const card = document.createElement("div");
 const st = it.status || "empty";
 card.className =
 "card" + (st === "empty" ? " card-disabled" : "");
 const missingSkills = Array.isArray(it.skills_missing) ? it.skills_missing : [];
 const skills = (it.skills || []).join(", ") || "—";
 const skillNote = missingSkills.length
  ? ` · 技能未安装: ${missingSkills.join(", ")}`
  : "";
 const cfg = it.config || {};
 const summaryBits = [];
 if (cfg.base_url) summaryBits.push(cfg.base_url);
 if (cfg.host)
 summaryBits.push(
 `${cfg.user || ""}@${cfg.host}${cfg.port ? ":" + cfg.port : ""}`
 );
 if (cfg.proxy_url) summaryBits.push("proxy " + cfg.proxy_url);
 if (cfg.llm_id) summaryBits.push("识图模型 " + cfg.llm_id);
 if (cfg.hosts && typeof cfg.hosts === "object" && !Array.isArray(cfg.hosts)) {
 const names = Object.keys(cfg.hosts);
 if (names.length) {
 summaryBits.push(
 `${names.length} 台主机: ${names.slice(0, 4).join(", ")}${
 names.length > 4 ? "…" : ""
 }`
 );
 }
 }
 if (cfg.url) summaryBits.push(cfg.url);
 if (cfg.items && typeof cfg.items === "object") {
  const inames = Array.isArray(cfg.items)
   ? cfg.items.map((r) => r && r.name).filter(Boolean)
   : Object.keys(cfg.items);
  if (inames.length) {
   summaryBits.push(
    `${inames.length} 条明细: ${inames.slice(0, 4).join(", ")}${
     inames.length > 4 ? "…" : ""
    }`
   );
  }
 }
 const secrets = it.secrets || {};
 const secHint = Object.keys(secrets)
 .filter((k) => secrets[k])
 .map((k) => k.replace(/_set$/, ""))
 .join(", ");
 card.innerHTML = `
 <div class="card-body">
 <div class="card-title">${escapeHtml(it.name || it.id)}
 <span class="pill integ-${
 st === "ready" ? "ok" : st === "partial" ? "warn" : "miss"
 }">${escapeHtml(integStatusLabel(st))}</span>
 ${it.builtin ? "" : ' <span class="pill">自定义</span>'}${
  it.layout === "content"
   ? ' <span class="pill">内容式</span>'
   : it.layout === "single"
    ? ' <span class="pill">单一</span>'
    : ""
 }
 </div>
 <div class="card-sub">${escapeHtml(it.description || "")}</div>
 <div class="card-sub muted-line">id: <code>${escapeHtml(
 it.id
 )}</code> · 技能: ${escapeHtml(skills)}${escapeHtml(skillNote)}</div>
 <div class="card-sub muted-line">${escapeHtml(
 summaryBits.join(" · ") || "（无连接摘要）"
 )}${
 secHint
 ? " · 密钥: " + escapeHtml(secHint) + " 已设置"
 : ""
 }</div>
 </div>
 <div class="card-actions">
 <button type="button" class="btn edit-integ icon-btn" title="编辑">${_ipk(
 "edit",
 "ipk-sm"
 )}</button>
 <button type="button" class="btn danger del-integ icon-btn" title="清空/删除">${_ipk(
 "delete",
 "ipk-sm"
 )}</button>
 </div>`;
 card
 .querySelector(".edit-integ")
 ?.addEventListener("click", () => openIntegrationEditor(it.id));
 card.querySelector(".del-integ")?.addEventListener("click", () =>
 deleteIntegration(it.id, it.builtin, it.name)
 );
 list.appendChild(card);
 }
 setMsg(
 "msgIntegrations",
 `${items.length} 个集成 · 就绪 ${
 items.filter((x) => x.status === "ready").length
 }`,
 "ok"
 );
 } catch (e) {
 list.innerHTML = "";
 setMsg("msgIntegrations", e.message, "error");
 }
 }

 function closeIntegrationEditor() {
 closeNestedEditor("integrationEditorModal");
 }

 function integFieldHintHtml(f) {
 return f && f.hint
 ? `<span class="field-hint integ-field-hint">${escapeHtml(f.hint)}</span>`
 : "";
 }

 function integFieldIsFull(f, key, type) {
 const span = f && f.span;
 const k = String(key || "").toLowerCase();
 if (
 f &&
 (f.full === true || span === "full" || span === 2 || span === "2")
 )
 return true;
 if (
 type === "url" ||
 type === "textarea" ||
 type === "json" ||
 type === "llm"
 )
 return true;
 if (k.includes("url") || k.includes("token")) return true;
 if (
 k === "api_key" ||
 k === "key" ||
 k.endsWith("_secret") ||
 k.endsWith("_key")
 )
 return true;
 return false;
 }

 function integFieldLabel(isFull, extraClass) {
 const lab = document.createElement("label");
 lab.className =
 "integ-field" +
 (isFull ? " is-full full" : "") +
 (extraClass ? " " + extraClass : "");
 return lab;
 }

 /** 自定义集成与通用连接的默认字段（与编辑态同一套渲染） */
 const CUSTOM_INTEG_FIELDS = [
 {
 key: "base_url",
 label: "Base URL",
 type: "url",
 placeholder: "https://api.example.com 或 http://192.168.1.1:8080",
 hint: "服务根地址；无 URL 的本地服务可留空",
 },
 {
 key: "host",
 label: "主机",
 type: "text",
 placeholder: "192.168.1.100",
 hint: "可选；无 URL 的主机 / 局域网服务常用",
 },
 {
 key: "port",
 label: "端口",
 type: "number",
 placeholder: "80",
 },
 {
 key: "user",
 label: "用户名",
 type: "text",
 placeholder: "admin",
 },
 {
 key: "password",
 label: "密码",
 type: "password",
 secret: true,
 placeholder: "可选",
 hint: "留空表示不修改已有密码",
 },
 {
 key: "token",
 label: "Token / API Key",
 type: "password",
 secret: true,
 placeholder: "可选",
 hint: "有 Token 时通常优先于账号密码",
 },
 ];

 const HOSTS_TABLE_FIELD = {
 key: "hosts",
 label: "主机列表",
 type: "hosts_table",
 hint: "配置名用于技能参数；检测端口用于批量体检。",
 };

 const INTEG_FIELD_TYPES = [
  { value: "text", label: "文本" },
  { value: "url", label: "地址" },
  { value: "password", label: "密码" },
  { value: "number", label: "数字" },
 ];
 const INTEG_KEY_ALIAS = {
  地址: "url",
  链接: "url",
  网址: "url",
  账号: "user",
  用户名: "user",
  密码: "password",
  Token: "token",
  token: "token",
  令牌: "token",
  名称: "name",
  内容: "content",
  备注: "note",
 };
 const DEFAULT_CONN_FIELDS = [
  {
   key: "url",
   label: "地址",
   type: "url",
   placeholder: "https://… 或主机:端口",
   hint: "服务地址、Webhook、RPC 都可以写在这里",
  },
  { key: "user", label: "账号", type: "text", placeholder: "可选" },
  {
   key: "password",
   label: "密码",
   type: "password",
   secret: true,
   placeholder: "可选",
   hint: "留空表示不修改已有密码",
  },
  {
   key: "token",
   label: "Token",
   type: "password",
   secret: true,
   placeholder: "可选",
  },
 ];
 const DEFAULT_ITEM_COLUMNS = [
  { key: "name", label: "名称", type: "text" },
  { key: "content", label: "内容", type: "text" },
  { key: "note", label: "备注", type: "text" },
 ];

 function slugIntegFieldKey(label, used) {
  const taken = used instanceof Set ? used : new Set();
  const raw = String(label || "").trim();
  let base = INTEG_KEY_ALIAS[raw] || "";
  if (!base) {
   base = raw
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
  }
  if (!base || !/^[a-z]/.test(base)) base = "field";
  base = base.slice(0, 32);
  let cand = base;
  let i = 2;
  while (taken.has(cand)) {
   cand = (base + "_" + i).slice(0, 40);
   i += 1;
  }
  taken.add(cand);
  return cand;
 }

 function integTypeSelectHtml(current) {
  const cur = String(current || "text");
  return (
   '<select data-integ-ftype>' +
   INTEG_FIELD_TYPES.map((t) => {
    const sel = t.value === cur ? " selected" : "";
    return (
     '<option value="' +
     t.value +
     '"' +
     sel +
     ">" +
     t.label +
     "</option>"
    );
   }).join("") +
   "</select>"
  );
 }

 function integLayoutOf(it) {
  if (!it) return "single";
  if (it.layout === "content" || it.layout === "single") return it.layout;
  const fields = Array.isArray(it.fields) ? it.fields : [];
  if (
   fields.some(
    (f) =>
     f &&
     (f.type === "items_table" ||
      f.key === "items" ||
      integIsRecordKey(f.key))
   )
  )
   return "content";
  if (it.config && it.config.items && typeof it.config.items === "object") {
   const blob = it.config.items;
   const n = Array.isArray(blob) ? blob.length : Object.keys(blob).length;
   if (n) return "content";
  }
  return "single";
 }

 function integUseBuilder(it, isNewCustom) {
  if (isNewCustom) return true;
  if (!it || it.builtin || it.catalog) return false;
  const fields = Array.isArray(it.fields) ? it.fields : [];
  if (
   fields.some(
    (f) =>
     f &&
     (f.type === "hosts_table" || f.key === "hosts" || f.key === "hosts_json")
   )
  )
   return false;
  const hosts = it.config && it.config.hosts;
  if (hosts && typeof hosts === "object" && Object.keys(hosts).length) return false;
  return true;
 }

 /**
 * 统一渲染集成字段（新建 / 编辑共用）。
 * @param {HTMLElement} fieldsHost
 * @param {Array} fields schema fields
 * @param {object} cfg current config values
 * @param {object} secrets *_set flags
 * @param {{ meta?: 'new'|'none', wide?: boolean }} opts
 */
 function renderIntegSchemaFields(fieldsHost, fields, cfg, secrets, opts) {
 const list = Array.isArray(fields) ? fields.slice() : [];
 const config = cfg || {};
 const sec = secrets || {};
 if (!list.length) {
 Object.keys(config).forEach((k) => {
 if (k === "hosts" || k === "hosts_json") return;
 list.push({
 key: k,
 label: k,
 type: /pass|token|secret/i.test(k) ? "password" : "text",
 secret: /pass|token|secret/i.test(k),
 });
 });
 if (config.hosts && typeof config.hosts === "object") {
 list.unshift({ ...HOSTS_TABLE_FIELD });
 }
 }
 for (const f of list) {
 const key = f.key;
 if (
 f.type === "hosts_table" ||
 key === "hosts" ||
 key === "hosts_json"
 ) {
 fieldsHost.appendChild(
 buildIntegHostsTable(config.hosts || {}, sec, f)
 );
 continue;
 }
 if (f.type === "items_table" || key === "items") {
 fieldsHost.appendChild(
 buildIntegItemsTable(config.items || {}, sec, f, { editableCols: false })
 );
 continue;
 }
 if (f.type === "llm") {
  const lab = integFieldLabel(true);
  lab.innerHTML = `<span class="integ-field-name">${escapeHtml(
   f.label || key
  )}</span>${
   f.hint
    ? `<span class="field-hint integ-field-hint">${escapeHtml(f.hint)}</span>`
    : ""
  }<select data-integ-key="${escapeHtml(key)}">
   <option value="">请选择设定→模型里的一条</option>
  </select>`;
  const sel = lab.querySelector("select");
  const current = config[key] != null ? String(config[key]) : "";
  fieldsHost.appendChild(lab);
  (async () => {
   try {
    let llms = await api("/api/config/llms");
    if (!Array.isArray(llms)) llms = llms.items || [];
    for (const x of llms) {
     if (!x || x.enabled === false) continue;
     const o = document.createElement("option");
     o.value = String(x.id || "");
     const nm = String(x.name || x.model || x.id || "未命名");
     const md = String(x.model || "");
     o.textContent = md && md !== nm ? `${nm} · ${md}` : nm;
     if (o.value && o.value === current) o.selected = true;
     sel.appendChild(o);
    }
    if (current && !sel.value) {
     const o = document.createElement("option");
     o.value = current;
     o.textContent = current + "（当前）";
     o.selected = true;
     sel.appendChild(o);
    }
   } catch (_) {}
  })();
  continue;
 }
 const type = String(f.type || "text").toLowerCase();
 const isSecret = !!(f.secret || type === "password");
 const isFull = integFieldIsFull(f, key, type);
 const hintHtml = integFieldHintHtml(f);
 const setFlag = sec[key + "_set"];
 const ph = isSecret
 ? setFlag
 ? "已设置 · 留空不修改"
 : f.placeholder || "输入密钥"
 : f.placeholder || "";
 const current =
 config[key] != null && config[key] !== "" ? String(config[key]) : "";
 if (
 type === "bool" ||
 type === "boolean" ||
 type === "checkbox"
 ) {
 const lab = integFieldLabel(isFull, "is-check check");
 const on =
 config[key] === true ||
 config[key] === 1 ||
 config[key] === "1" ||
 config[key] === "true";
 lab.innerHTML = `<input data-integ-key="${escapeHtml(
 key
 )}" type="checkbox"${on ? " checked" : ""} /><span class="integ-field-copy"><span class="integ-field-name">${escapeHtml(
 f.label || key
 )}</span>${hintHtml}</span>`;
 fieldsHost.appendChild(lab);
 continue;
 }
 const options = Array.isArray(f.options) ? f.options : [];
 const nameHtml = `<span class="integ-field-name">${escapeHtml(
 f.label || key
 )}</span>${hintHtml}`;
 if (type === "select" || (options.length && type !== "llm")) {
 const lab = integFieldLabel(isFull);
 const optsHtml = options
 .map((opt) => {
 const val =
 opt && typeof opt === "object"
 ? opt.value != null
 ? String(opt.value)
 : String(opt.label || "")
 : String(opt ?? "");
 const labText =
 opt && typeof opt === "object"
 ? String(opt.label || val)
 : val;
 return `<option value="${escapeHtml(val)}">${escapeHtml(labText)}</option>`;
 })
 .join("");
 lab.innerHTML = `${nameHtml}<select data-integ-key="${escapeHtml(
 key
 )}">${
 f.placeholder
 ? `<option value="">${escapeHtml(f.placeholder)}</option>`
 : ""
 }${optsHtml}</select>`;
 const sel = lab.querySelector("select");
 if (current) sel.value = current;
 if (current && sel.value !== current) {
 const o = document.createElement("option");
 o.value = current;
 o.textContent = current;
 o.selected = true;
 sel.appendChild(o);
 }
 fieldsHost.appendChild(lab);
 continue;
 }
 if (type === "textarea" || type === "json") {
 const lab = integFieldLabel(true);
 let rows = parseInt(f.rows, 10);
 if (!Number.isFinite(rows) || rows < 2) rows = 3;
 if (rows > 12) rows = 12;
 lab.innerHTML = `${nameHtml}<textarea data-integ-key="${escapeHtml(
 key
 )}" rows="${rows}" placeholder="${escapeHtml(ph)}"></textarea>`;
 const ta = lab.querySelector("textarea");
 if (!isSecret && current) ta.value = current;
 fieldsHost.appendChild(lab);
 continue;
 }
 const lab = integFieldLabel(isFull);
 const inputType =
 isSecret ? "password" : type === "number" ? "number" : "text";
 lab.innerHTML = `${nameHtml}<input data-integ-key="${escapeHtml(
 key
 )}" type="${inputType}" placeholder="${escapeHtml(
 ph
 )}" autocomplete="${isSecret ? "new-password" : "off"}" />`;
 const input = lab.querySelector("input");
 if (!isSecret && current) {
 input.value = current;
 }
 fieldsHost.appendChild(lab);
 }
 }

 function integIsRecordKey(k) {
  const key = String(k || "");
  if (
   key === "items" ||
   key === "groups" ||
   key === "members" ||
   key === "hosts" ||
   key === "hosts_json"
  )
   return true;
  return /^(group|member|bot)\d*_/i.test(key);
 }

 function integConnFieldsFromSchema(fields, cfg) {
  const list = [];
  const seen = new Set();
  (Array.isArray(fields) ? fields : []).forEach((f) => {
   if (!f || !f.key) return;
   if (
    f.type === "items_table" ||
    f.type === "hosts_table" ||
    integIsRecordKey(f.key)
   )
    return;
   list.push({
    key: f.key,
    label: f.label || f.key,
    type: f.type || "text",
    secret: !!f.secret,
    placeholder: f.placeholder || "",
    hint: f.hint || "",
   });
   seen.add(f.key);
  });
  if (!list.length) {
   DEFAULT_CONN_FIELDS.forEach((f) => {
    list.push({ ...f });
    seen.add(f.key);
   });
  }
  Object.keys(cfg || {}).forEach((k) => {
   if (seen.has(k) || k.startsWith("_") || integIsRecordKey(k)) return;
   list.push({
    key: k,
    label: k,
    type: /pass|token|secret/i.test(k) ? "password" : "text",
    secret: /pass|token|secret/i.test(k),
   });
  });
  return list;
 }

 function integItemColumnsFromSchema(fields, items) {
  const f = (Array.isArray(fields) ? fields : []).find(
   (x) => x && (x.type === "items_table" || x.key === "items")
  );
  if (f && Array.isArray(f.columns) && f.columns.length) {
   return f.columns.map((c) => ({
    key: c.key,
    label: c.label || c.key,
    type: c.type || "text",
    secret: !!c.secret,
   }));
  }
  const blob = items && typeof items === "object" ? items : {};
  const rows = Array.isArray(blob) ? blob : Object.values(blob);
  const keys = [];
  rows.forEach((row) => {
   if (!row || typeof row !== "object") return;
   Object.keys(row).forEach((k) => {
    if (k && !keys.includes(k)) keys.push(k);
   });
  });
  if (!keys.length) return DEFAULT_ITEM_COLUMNS.map((c) => ({ ...c }));
  if (!keys.includes("name")) keys.unshift("name");
  return keys.map((k) => ({
   key: k,
   label: k === "name" ? "名称" : k === "content" ? "内容" : k === "note" ? "备注" : k,
   type: /pass|token|secret/i.test(k) ? "password" : "text",
   secret: /pass|token|secret/i.test(k),
  }));
 }

 function buildIntegConnBuilder(fields, cfg, secrets) {
  const wrap = document.createElement("div");
  wrap.className = "integ-conn-builder";
  wrap.setAttribute("data-integ-conn-builder", "1");
  wrap.innerHTML =
   '<div class="integ-builder-head"><span class="integ-builder-title">连接字段</span>' +
   '<span class="field-hint">可增删、改名。技能用键名读取，例如 url / token。</span>' +
   '<div class="cfg-tool-cluster"><button type="button" class="cfg-tool" data-integ-add-conn>' +
   '<span data-ipk="plus" data-ipk-class="ipk-xs"></span><span>添加字段</span></button></div></div>' +
   '<div class="integ-conn-cols"><span>显示名</span><span>键名</span><span>类型</span><span>值</span><span></span></div>' +
   '<div class="integ-builder-rows" data-integ-conn-rows></div>';
  const rows = wrap.querySelector("[data-integ-conn-rows]");
  const list = integConnFieldsFromSchema(fields, cfg);
  list.forEach((f) => appendIntegConnRow(rows, f, cfg, secrets));
  wrap.querySelector("[data-integ-add-conn]")?.addEventListener("click", () => {
   appendIntegConnRow(
    rows,
    { key: "", label: "", type: "text", secret: false },
    {},
    {}
   );
   const last = rows.querySelector(".integ-conn-row:last-child [data-integ-flabel]");
   last?.focus();
  });
  return wrap;
 }

 function appendIntegConnRow(host, field, cfg, secrets) {
  if (!host) return;
  const f = field || {};
  const key = String(f.key || "");
  const type = String(f.type || "text");
  const isSecret = !!(f.secret || type === "password");
  const setFlag = secrets && key && secrets[key + "_set"];
  const ph = isSecret
   ? setFlag
    ? "已设置 · 留空不修改"
    : f.placeholder || "可选"
   : f.placeholder || "";
  const current =
   !isSecret && cfg && cfg[key] != null && cfg[key] !== ""
    ? String(cfg[key])
    : "";
  const row = document.createElement("div");
  row.className = "integ-conn-row";
  row.innerHTML =
   '<input data-integ-flabel type="text" placeholder="字段名，如 地址" value="' +
   escapeHtml(f.label || "") +
   '" autocomplete="off" />' +
   '<input data-integ-fkey type="text" placeholder="键名" value="' +
   escapeHtml(key) +
   '" autocomplete="off" />' +
   integTypeSelectHtml(isSecret ? "password" : type) +
   '<input data-integ-fval type="' +
   (isSecret ? "password" : type === "number" ? "number" : "text") +
   '" placeholder="' +
   escapeHtml(ph) +
   '" value="' +
   escapeHtml(current) +
   '" autocomplete="' +
   (isSecret ? "new-password" : "off") +
   '" />' +
   '<button type="button" class="btn icon-btn integ-conn-del" title="删除字段">' +
   (typeof L.ipk === "function" ? L.ipk("delete", "ipk-xs") : "×") +
   "</button>";
  const labelEl = row.querySelector("[data-integ-flabel]");
  const keyEl = row.querySelector("[data-integ-fkey]");
  const typeEl = row.querySelector("[data-integ-ftype]");
  const valEl = row.querySelector("[data-integ-fval]");
  if (keyEl && !key) keyEl.dataset.auto = "1";
  labelEl?.addEventListener("input", () => {
   if (!keyEl || keyEl.dataset.auto !== "1") return;
   const used = new Set();
   host.querySelectorAll("[data-integ-fkey]").forEach((el) => {
    if (el !== keyEl && el.value) used.add(el.value.trim());
   });
   keyEl.value = slugIntegFieldKey(labelEl.value, used);
  });
  keyEl?.addEventListener("input", () => {
   keyEl.dataset.auto = "0";
  });
  typeEl?.addEventListener("change", () => {
   if (!valEl) return;
   const t = typeEl.value;
   valEl.type = t === "password" ? "password" : t === "number" ? "number" : "text";
  });
  row.querySelector(".integ-conn-del")?.addEventListener("click", () => {
   row.remove();
  });
  host.appendChild(row);
 }

 function collectIntegConnFromBuilder(root) {
  const fields = [];
  const values = {};
  const used = new Set();
  root.querySelectorAll(".integ-conn-row").forEach((row) => {
   let label = (row.querySelector("[data-integ-flabel]")?.value || "").trim();
   let key = (row.querySelector("[data-integ-fkey]")?.value || "").trim();
   const type = (row.querySelector("[data-integ-ftype]")?.value || "text").trim();
   const valEl = row.querySelector("[data-integ-fval]");
   const val = valEl ? String(valEl.value || "") : "";
   if (!label && !key && !val) return;
   if (!key) key = slugIntegFieldKey(label || "field", used);
   else if (used.has(key)) key = slugIntegFieldKey(key, used);
   else used.add(key);
   if (!label) label = key;
   const secret = type === "password";
   fields.push({
    key,
    label,
    type,
    secret,
    placeholder: secret ? "可选" : "",
   });
   values[key] = val;
  });
  return { fields, values };
 }

 function buildIntegItemsTable(itemsObj, secrets, fieldMeta, opts) {
  const options = opts || {};
  const wrap = document.createElement("div");
  wrap.className = "integ-items-wrap";
  wrap.setAttribute("data-integ-items-table", "1");
  const columns = integItemColumnsFromSchema(
   fieldMeta && fieldMeta.columns
    ? [{ type: "items_table", columns: fieldMeta.columns }]
    : fieldMeta
     ? [fieldMeta]
     : [],
   itemsObj
  );
  wrap._integColumns = columns;
  const hint =
   (fieldMeta && fieldMeta.hint) ||
   "每行一条明细。列可改，例如企微用户、多个 bot 的 webhook。";
  wrap.innerHTML =
   '<div class="integ-items-head">' +
   '<div class="integ-items-title">' +
   escapeHtml((fieldMeta && fieldMeta.label) || "明细") +
   "</div>" +
   '<p class="field-hint" style="margin:0">' +
   escapeHtml(hint) +
   "</p></div>" +
   (options.editableCols
    ? '<div class="integ-items-cols" data-integ-item-cols></div>'
    : "") +
   '<div class="integ-items-table-scroll"><table class="integ-items-table">' +
   "<thead><tr data-integ-item-thead></tr></thead>" +
   '<tbody data-integ-items-body></tbody></table></div>' +
   '<div class="integ-items-actions"><div class="cfg-tool-cluster">' +
   '<button type="button" class="cfg-tool is-primary" data-integ-add-item>' +
   '<span data-ipk="plus" data-ipk-class="ipk-xs"></span><span>添加一行</span></button></div></div>';
  const paintHead = () => {
   const tr = wrap.querySelector("[data-integ-item-thead]");
   if (!tr) return;
   tr.innerHTML =
    wrap._integColumns
     .map((c) => "<th>" + escapeHtml(c.label || c.key) + "</th>")
     .join("") + "<th></th>";
  };
  const paintCols = () => {
   const box = wrap.querySelector("[data-integ-item-cols]");
   if (!box) return;
   box.innerHTML = "";
   wrap._integColumns.forEach((c, idx) => {
    const chip = document.createElement("div");
    chip.className = "integ-item-col";
    chip.innerHTML =
     '<input data-col-label type="text" value="' +
     escapeHtml(c.label || "") +
     '" placeholder="列名" />' +
     '<input data-col-key type="text" value="' +
     escapeHtml(c.key || "") +
     '" placeholder="键" />' +
     integTypeSelectHtml(c.secret ? "password" : c.type) +
     (c.key === "name"
      ? ""
      : '<button type="button" class="btn icon-btn" data-col-del title="删除列">×</button>');
    const labelEl = chip.querySelector("[data-col-label]");
    const keyEl = chip.querySelector("[data-col-key]");
    const typeEl = chip.querySelector("[data-integ-ftype]");
    labelEl?.addEventListener("change", () => {
     c.label = labelEl.value.trim() || c.key;
     if (keyEl && (!c.key || keyEl.dataset.auto === "1")) {
      const used = new Set(wrap._integColumns.map((x) => x.key));
      used.delete(c.key);
      c.key = slugIntegFieldKey(c.label, used);
      keyEl.value = c.key;
     }
     paintHead();
     refreshItemRowInputs(wrap);
    });
    keyEl?.addEventListener("change", () => {
     const used = new Set(wrap._integColumns.map((x) => x.key));
     used.delete(c.key);
     c.key = slugIntegFieldKey(keyEl.value || c.label, used);
     keyEl.value = c.key;
     paintHead();
     refreshItemRowInputs(wrap);
    });
    typeEl?.addEventListener("change", () => {
     c.type = typeEl.value;
     c.secret = typeEl.value === "password";
     refreshItemRowInputs(wrap);
    });
    chip.querySelector("[data-col-del]")?.addEventListener("click", () => {
     wrap._integColumns.splice(idx, 1);
     paintCols();
     paintHead();
     refreshItemRowInputs(wrap);
    });
    box.appendChild(chip);
   });
   const addWrap = document.createElement("div");
   addWrap.className = "cfg-tool-cluster";
   const add = document.createElement("button");
   add.type = "button";
   add.className = "cfg-tool";
   add.textContent = "添加列";
   add.addEventListener("click", () => {
    const used = new Set(wrap._integColumns.map((x) => x.key));
    const key = slugIntegFieldKey("列", used);
    wrap._integColumns.push({ key, label: "列", type: "text", secret: false });
    paintCols();
    paintHead();
    refreshItemRowInputs(wrap);
   });
   addWrap.appendChild(add);
   box.appendChild(addWrap);
  };
  paintHead();
  paintCols();
  const body = wrap.querySelector("[data-integ-items-body]");
  const blob = itemsObj && typeof itemsObj === "object" ? itemsObj : {};
  const names = Array.isArray(blob)
   ? blob.map((r, i) => (r && r.name) || "item_" + (i + 1))
   : Object.keys(blob);
  const rows = Array.isArray(blob)
   ? blob
   : names.map((n) => ({ name: n, ...(blob[n] || {}) }));
  if (!rows.length) appendIntegItemRow(body, wrap, {}, secrets);
  else rows.forEach((row) => appendIntegItemRow(body, wrap, row, secrets));
  wrap.querySelector("[data-integ-add-item]")?.addEventListener("click", () => {
   appendIntegItemRow(body, wrap, {}, secrets);
  });
  return wrap;
 }

 function refreshItemRowInputs(wrap) {
  const body = wrap.querySelector("[data-integ-items-body]");
  if (!body) return;
  const secrets = {};
  const snapshot = [];
  body.querySelectorAll("tr.integ-item-row").forEach((tr) => {
   const row = {};
   tr.querySelectorAll("[data-item-k]").forEach((el) => {
    row[el.getAttribute("data-item-k")] = el.value;
   });
   snapshot.push(row);
  });
  body.innerHTML = "";
  snapshot.forEach((row) => appendIntegItemRow(body, wrap, row, secrets));
 }

 function appendIntegItemRow(tbody, wrap, row, secrets) {
  if (!tbody) return;
  const tr = document.createElement("tr");
  tr.className = "integ-item-row";
  const cols = (wrap && wrap._integColumns) || DEFAULT_ITEM_COLUMNS;
  const name = String((row && row.name) || "");
  tr.innerHTML =
   cols
    .map((c) => {
     const isSecret = !!(c.secret || c.type === "password");
     const setFlag =
      secrets &&
      (secrets[`items.${name}.${c.key}_set`] ||
       secrets[`item_password_set.${name}`]);
     const ph = isSecret ? (setFlag ? "已设置·留空不改" : "可选") : "";
     const val =
      !isSecret && row && row[c.key] != null ? String(row[c.key]) : "";
     const itype =
      isSecret ? "password" : c.type === "number" ? "number" : "text";
     return (
      "<td><input data-item-k=\"" +
      escapeHtml(c.key) +
      '" type="' +
      itype +
      '" placeholder="' +
      escapeHtml(ph || c.label || "") +
      '" value="' +
      escapeHtml(val) +
      '" autocomplete="' +
      (isSecret ? "new-password" : "off") +
      '" /></td>'
     );
    })
    .join("") +
   '<td><button type="button" class="btn danger icon-btn integ-item-del" title="删除行">' +
   (typeof L.ipk === "function" ? L.ipk("delete", "ipk-xs") : "×") +
   "</button></td>";
  tr.querySelector(".integ-item-del")?.addEventListener("click", () => {
   tr.remove();
  });
  tbody.appendChild(tr);
 }

 function snapshotIntegBuilderState(fieldsHost) {
  const conn = fieldsHost?.querySelector("[data-integ-conn-builder]")
   ? collectIntegConnFromBuilder(fieldsHost)
   : { fields: [], values: {} };
  const packed = collectIntegItemsFromForm(fieldsHost);
  if (packed) fieldsHost._integItemsSnap = packed;
  const fields = (conn.fields || []).slice();
  const config = { ...(conn.values || {}) };
  const itemsPack = packed || fieldsHost._integItemsSnap;
  if (itemsPack) {
   config.items = itemsPack.items || {};
   if (
    !fields.some((f) => f && (f.type === "items_table" || f.key === "items"))
   ) {
    fields.push({
     key: "items",
     label: "明细",
     type: "items_table",
     columns: itemsPack.columns || DEFAULT_ITEM_COLUMNS,
    });
   }
  }
  return { fields, config };
 }

 function bindIntegTemplateRadios(fieldsHost, base) {
  const paint = () => {
   const mode =
    fieldsHost.querySelector('input[name="integTemplate"]:checked')?.value ||
    base.layout ||
    "single";
   const snap = snapshotIntegBuilderState(fieldsHost);
   const hasConn = (snap.fields || []).some(
    (f) => f && f.key && f.type !== "items_table"
   );
   paintIntegCustomForm(fieldsHost, {
    layout: mode,
    fields: hasConn ? snap.fields : base.fields || [],
    config: { ...(base.config || {}), ...(snap.config || {}) },
    secrets: base.secrets || {},
   });
  };
  fieldsHost.querySelectorAll('input[name="integTemplate"]').forEach((r) => {
   r.addEventListener("change", paint);
  });
  paint();
 }

 function collectIntegItemsFromForm(root) {
  const wrap = root?.querySelector("[data-integ-items-table]");
  if (!wrap) return null;
  const cols = wrap._integColumns || DEFAULT_ITEM_COLUMNS;
  const items = {};
  wrap.querySelectorAll("tr.integ-item-row").forEach((tr, idx) => {
   const row = {};
   cols.forEach((c) => {
    const el = tr.querySelector('[data-item-k="' + c.key + '"]');
    row[c.key] = el ? String(el.value || "") : "";
   });
   let name = String(row.name || "").trim();
   const hasAny = Object.keys(row).some(
    (k) => k !== "name" && String(row[k] || "").trim()
   );
   if (!name && !hasAny) return;
   if (!name) name = "item_" + (idx + 1);
   row.name = name;
   const clean = {};
   Object.keys(row).forEach((k) => {
    const col = cols.find((c) => c.key === k);
    const secret = col && (col.secret || col.type === "password");
    if (secret && !String(row[k] || "").trim()) return;
    clean[k] = row[k];
   });
   items[name] = clean;
  });
  return { items, columns: cols };
 }

 function collectIntegBuilderSchema(id, name, layout) {
  const root = $("integFields");
  if (!root || !root.querySelector("[data-integ-conn-builder]")) return null;
  const conn = collectIntegConnFromBuilder(root);
  const fields = conn.fields.slice();
  if (layout === "content") {
   const packed = collectIntegItemsFromForm(root);
   const columns =
    (packed && packed.columns) || DEFAULT_ITEM_COLUMNS.map((c) => ({ ...c }));
   fields.push({
    key: "items",
    label: "明细",
    type: "items_table",
    columns,
    hint: "每行一条明细，技能用 items 读取。",
   });
  }
  return {
   id,
   name: name || id,
   description: "",
   builtin: false,
   layout,
   skills: [],
   fields,
   required_for_ready: fields
    .filter((f) => f.key === "url" || f.key === "base_url" || f.key === "host")
    .map((f) => f.key),
  };
 }

 function applyIntegBuilderSchema(id, config) {
  const root = $("integFields");
  const layoutRaw =
   root?.querySelector('input[name="integTemplate"]:checked')?.value || "";
  const layout =
   layoutRaw === "content"
    ? "content"
    : layoutRaw === "single"
     ? "single"
     : "";
  const displayName = ($("integNewName")?.value || "").trim();
  const schema = collectIntegBuilderSchema(
   id,
   displayName || id,
   layout || "single"
  );
  if (schema) {
   schema.layout = layout || "single";
   config._schema = schema;
   if (schema.layout === "single") config.items = {};
  }
  return displayName;
 }

 function paintIntegCustomForm(fieldsHost, opts) {
  const o = opts || {};
  const layout = o.layout === "content" ? "content" : "single";
  const cfg = o.config || {};
  const secrets = o.secrets || {};
  const fields = o.fields || [];
  if (cfg.items && !fieldsHost._integItemsSnap) {
   fieldsHost._integItemsSnap = {
    items: cfg.items,
    columns: integItemColumnsFromSchema(fields, cfg.items),
   };
  }
  const meta = fieldsHost.querySelector(".integ-meta-block");
  let n = meta ? meta.nextSibling : fieldsHost.firstChild;
  while (n) {
   const nxt = n.nextSibling;
   n.remove();
   n = nxt;
  }
  fieldsHost.appendChild(buildIntegConnBuilder(fields, cfg, secrets));
  if (layout === "content") {
   const itemField =
    (Array.isArray(fields) ? fields : []).find(
     (f) => f && (f.type === "items_table" || f.key === "items")
    ) || {
     key: "items",
     label: "明细",
     type: "items_table",
     columns: DEFAULT_ITEM_COLUMNS,
    };
   fieldsHost.appendChild(
    buildIntegItemsTable(cfg.items || {}, secrets, itemField, {
     editableCols: true,
    })
   );
  }
  if (typeof L.hydrateIconPark === "function") L.hydrateIconPark(fieldsHost);
 }

 function openIntegrationEditor(id, isNewCustom) {
 const box = $("integrationEditorModal");
 if (!box) return;
 const fieldsHost = $("integFields");
 if (!fieldsHost) return;
 fieldsHost.innerHTML = "";
 fieldsHost._integItemsSnap = null;
 setMsg("msgIntegEditor", "");
 const lead = box.querySelector(".kb-editor-lead");
 const modalEl = box.querySelector(".modal");

 if (modalEl) modalEl.classList.add("cfg-editor-modal-lg");
 if (isNewCustom) {
 $("integId").value = "";
 $("integEditorTitle").innerHTML =
 '<span data-ipk="plus" data-ipk-class="ipk-sm"></span> 新建自定义集成';
 if (lead) {
 lead.textContent =
 "通用连接：地址、账号、Token。需要用户表或多条 bot 时选「内容式」。";
 }
 $("integEditorDesc").textContent =
 "id 建议小写字母开头（如 my_api）。保存后技能用键名读取这些字段。";

 const meta = document.createElement("div");
 meta.className = "integ-meta-block";
 meta.innerHTML = `
 <label class="integ-field">
 <span class="integ-field-name">集成 id <em class="agent-opt-hint">保存后不可改</em></span>
 <input id="integNewId" type="text" placeholder="my_service" autocomplete="off" />
 </label>
 <label class="integ-field">
 <span class="integ-field-name">显示名称</span>
 <input id="integNewName" type="text" placeholder="我的服务" autocomplete="off" />
 </label>
 <div class="integ-template-row">
 <span class="integ-template-label">配置方式</span>
 <label class="integ-template-opt"><input type="radio" name="integTemplate" value="single" checked /> 单一集成配置</label>
 <label class="integ-template-opt"><input type="radio" name="integTemplate" value="content" /> 内容式集成配置</label>
 </div>
 <p class="field-hint integ-template-hint">单一：只填链接信息。内容式：链接信息 + 明细表（用户、多个 bot、多条 webhook）。</p>`;
 fieldsHost.appendChild(meta);
 bindIntegTemplateRadios(fieldsHost, {
  layout: "single",
  fields: [],
  config: {},
  secrets: {},
 });

 openNestedEditor("integrationEditorModal");
 if (typeof L.hydrateIconPark === "function") L.hydrateIconPark(box);
 requestAnimationFrame(() => $("integNewId")?.focus());
 return;
 }

 const it =
 _integCache.find((x) => x.id === id) ||
 ({ id, name: id, fields: [], config: {}, secrets: {} });
 $("integId").value = it.id || id;
 $("integEditorTitle").innerHTML =
 '<span data-ipk="edit" data-ipk-class="ipk-sm"></span> 编辑 · ' +
 escapeHtml(it.name || id);
 if (lead) {
 lead.textContent =
 "配置技能连接参数；密钥留空表示不修改。";
 }
 $("integEditorDesc").textContent =
 (it.description || "") +
 (it.skills && it.skills.length
 ? " · 关联技能: " + it.skills.join(", ")
 : "");

 const fields = Array.isArray(it.fields) ? it.fields.slice() : [];
 const cfg = it.config || {};
 const secrets = it.secrets || {};
 if (integUseBuilder(it, false)) {
  const layout = integLayoutOf(it);
  const meta = document.createElement("div");
  meta.className = "integ-meta-block";
  meta.innerHTML = `
 <label class="integ-field">
 <span class="integ-field-name">集成 id</span>
 <input type="text" value="${escapeHtml(it.id || id)}" readonly class="prompt-readonly" />
 </label>
 <label class="integ-field">
 <span class="integ-field-name">显示名称</span>
 <input id="integNewName" type="text" value="${escapeHtml(it.name || "")}" autocomplete="off" />
 </label>
 <div class="integ-template-row">
 <span class="integ-template-label">配置方式</span>
 <label class="integ-template-opt"><input type="radio" name="integTemplate" value="single"${layout === "content" ? "" : " checked"} /> 单一集成配置</label>
 <label class="integ-template-opt"><input type="radio" name="integTemplate" value="content"${layout === "content" ? " checked" : ""} /> 内容式集成配置</label>
 </div>
 <p class="field-hint integ-template-hint">单一：只填链接信息。内容式：链接信息 + 明细表（用户、多个 bot、多条 webhook）。</p>`;
  fieldsHost.appendChild(meta);
  bindIntegTemplateRadios(fieldsHost, {
   layout,
   fields,
   config: cfg,
   secrets,
  });
 } else {
  renderIntegSchemaFields(fieldsHost, fields, cfg, secrets);
 }
 openNestedEditor("integrationEditorModal");
 if (typeof L.hydrateIconPark === "function") L.hydrateIconPark(box);
 }

 function buildIntegHostsTable(hostsObj, secrets, fieldMeta) {
 const wrap = document.createElement("div");
 wrap.className = "integ-hosts-wrap";
 wrap.setAttribute("data-integ-hosts-table", "1");
 const hint = fieldMeta && fieldMeta.hint ? fieldMeta.hint : "";
 wrap.innerHTML = `
 <div class="integ-hosts-head">
 <div class="integ-hosts-title">${escapeHtml(
 (fieldMeta && fieldMeta.label) || "主机列表"
 )}</div>
 ${
 hint
 ? `<p class="field-hint" style="margin:0">${escapeHtml(hint)}</p>`
 : ""
 }
 </div>
 <div class="integ-hosts-table-scroll">
 <table class="integ-hosts-table">
 <thead>
 <tr>
 <th>配置名</th>
 <th>主机 IP/域名</th>
 <th>用户</th>
 <th>SSH端口</th>
 <th>密码</th>
 <th>密钥路径</th>
 <th>检测端口</th>
 <th></th>
 </tr>
 </thead>
 <tbody id="integHostsBody"></tbody>
 </table>
 </div>
 <div class="integ-hosts-actions">
 <div class="cfg-tool-cluster">
 <button type="button" class="cfg-tool is-primary" id="btnIntegAddHost">
 <span data-ipk="plus" data-ipk-class="ipk-xs"></span><span>添加主机</span>
 </button>
 </div>
 <span class="field-hint">配置名自定；检测端口逗号分隔，如 22,80,443</span>
 </div>`;
 const body = wrap.querySelector("#integHostsBody");
 const hosts =
 hostsObj && typeof hostsObj === "object" && !Array.isArray(hostsObj)
 ? hostsObj
 : {};
 const names = Object.keys(hosts);
 if (!names.length) {
 appendIntegHostRow(body, { name: "" }, secrets);
 } else {
 names.forEach((name) => {
 appendIntegHostRow(
 body,
 { name, ...(hosts[name] || {}) },
 secrets
 );
 });
 }
 wrap.querySelector("#btnIntegAddHost")?.addEventListener("click", () => {
 appendIntegHostRow(body, { name: "" }, secrets);
 const last = body.querySelector("tr:last-child input[data-h=name]");
 last?.focus();
 });
 return wrap;
 }

 function appendIntegHostRow(tbody, row, secrets) {
 if (!tbody) return;
 const tr = document.createElement("tr");
 tr.className = "integ-host-row";
 const name = row.name || "";
 const pwSet =
 secrets &&
 (secrets[`host_password_set.${name}`] ||
 secrets[`hosts.${name}.password_set`]);
 const ports = Array.isArray(row.ports)
 ? row.ports.join(",")
 : row.ports != null
 ? String(row.ports)
 : "";
 tr.innerHTML = `
 <td><input data-h="name" type="text" placeholder="host1" value="${escapeHtml(
 name
 )}" autocomplete="off" /></td>
 <td><input data-h="host" type="text" placeholder="192.168.1.100" value="${escapeHtml(
 String(row.host || "")
 )}" autocomplete="off" /></td>
 <td><input data-h="user" type="text" placeholder="admin" value="${escapeHtml(
 String(row.user || "")
 )}" autocomplete="off" /></td>
 <td><input data-h="port" type="number" min="1" max="65535" value="${escapeHtml(
 String(row.port != null ? row.port : 22)
 )}" /></td>
 <td><input data-h="password" type="password" placeholder="${
 pwSet ? "已设置·留空不改" : "可选"
 }" autocomplete="new-password" /></td>
 <td><input data-h="key_path" type="text" placeholder="~/.ssh/id_rsa" value="${escapeHtml(
 String(row.key_path || "")
 )}" autocomplete="off" /></td>
 <td><input data-h="ports" type="text" placeholder="22,80,443" value="${escapeHtml(
 ports
 )}" autocomplete="off" /></td>
 <td><button type="button" class="btn danger icon-btn integ-host-del" title="删除行">${
 typeof L.ipk === "function" ? L.ipk("delete", "ipk-xs") : "×"
 }</button></td>`;
 tr.querySelector(".integ-host-del")?.addEventListener("click", () => {
 tr.remove();
 });
 tbody.appendChild(tr);
 }

 function collectIntegHostsFromForm() {
 const body = $("integHostsBody");
 if (!body) return null;
 const hosts = {};
 body.querySelectorAll("tr.integ-host-row").forEach((tr) => {
 const g = (k) =>
 (tr.querySelector(`[data-h="${k}"]`)?.value || "").trim();
 const name = g("name");
 if (!name) return;
 let port = parseInt(g("port"), 10);
 if (!Number.isFinite(port) || port <= 0) port = 22;
 const portsRaw = g("ports");
 const ports = portsRaw
 ? portsRaw
 .split(/[,，\s]+/)
 .map((x) => parseInt(x, 10))
 .filter((n) => Number.isFinite(n) && n > 0)
 : [];
 const row = {
 host: g("host"),
 user: g("user"),
 port,
 key_path: g("key_path"),
 ports,
 };
 const pw = g("password");
 if (pw) row.password = pw;
 hosts[name] = row;
 });
 return hosts;
 }

 function collectIntegFormConfig() {
 const cfg = {};
 const root = $("integFields");
 if (!root) return cfg;
 const hasHostsTable = !!root.querySelector("[data-integ-hosts-table]");
 const hasConnBuilder = !!root.querySelector("[data-integ-conn-builder]");
 if (hasConnBuilder) {
  const conn = collectIntegConnFromBuilder(root);
  Object.assign(cfg, conn.values);
 } else {
  root.querySelectorAll("[data-integ-key]").forEach((el) => {
   const k = el.getAttribute("data-integ-key");
   if (!k || k === "_extra_json") return;
   if (hasHostsTable && (k === "hosts" || k === "hosts_json")) return;
   if (el instanceof HTMLInputElement && el.type === "checkbox") {
    cfg[k] = !!el.checked;
    return;
   }
   cfg[k] = el.value;
  });
 }
 if (hasHostsTable) {
 const hosts = collectIntegHostsFromForm() || {};
 cfg.hosts = hosts;
 cfg.hosts_json = JSON.stringify(hosts);
 }
 const layout =
  root.querySelector('input[name="integTemplate"]:checked')?.value || "";
 const packed = collectIntegItemsFromForm(root);
 if (hasConnBuilder && layout === "single") cfg.items = {};
 else if (packed) cfg.items = packed.items;
 const extra = root.querySelector('[data-integ-key="_extra_json"]');
 if (extra && String(extra.value || "").trim()) {
 try {
 const o = JSON.parse(extra.value);
 if (o && typeof o === "object") Object.assign(cfg, o);
 } catch (_) {
 throw new Error("其它 JSON 格式无效");
 }
 }
 return cfg;
 }

 async function saveIntegration() {
 try {
 let id = ($("integId")?.value || "").trim();
 const isNew = !id;
 if (isNew) {
 id = ($("integNewId")?.value || "").trim();
 if (!id) {
 setMsg("msgIntegEditor", "请填写集成 id", "error");
 return;
 }
 }
 const config = collectIntegFormConfig();
 const displayName = applyIntegBuilderSchema(id, config);
 const body = { config };
 if (isNew || displayName) {
 body.name = displayName || id;
 }
 await api(`/api/config/integrations/${encodeURIComponent(id)}`, {
 method: "PUT",
 body: JSON.stringify(body),
 });
 setMsg("msgIntegEditor", "已保存", "ok");
 setMsg("msgIntegrations", "已保存 " + id, "ok");
 showToast("集成已保存（技能下次调用即生效）", "success");
 closeIntegrationEditor();
 await loadIntegrations();
 loadSkills();
 } catch (e) {
 setMsg("msgIntegEditor", e.message, "error");
 showToast("保存失败", "error");
 }
 }

 async function testIntegration() {
 const id = ($("integId")?.value || "").trim();
 if (!id) {
 setMsg("msgIntegEditor", "请先保存或选择已有集成再测试", "error");
 return;
 }
 setMsg("msgIntegEditor", "测试中…");
 try {
 // save first so test uses latest fields; empty secret keeps the stored one
 await saveIntegrationQuiet(id);
 const res = await api(
 `/api/config/integrations/${encodeURIComponent(id)}/test`,
 { method: "POST" }
 );
 const ok = !!(res && res.ok === true && !res.error);
 const detail = (res && (res.error || res.detail || res.message)) || "";
 if (ok) {
 setMsg(
 "msgIntegEditor",
 "测试通过: " + (detail || "连接正常"),
 "ok"
 );
 showToast("连接测试通过", "success");
 } else {
 setMsg(
 "msgIntegEditor",
 "测试失败: " + (detail || "未知错误"),
 "error"
 );
 showToast("连接测试失败", "error");
 }
 } catch (e) {
 setMsg("msgIntegEditor", e.message, "error");
 }
 }

 async function saveIntegrationQuiet(id) {
 const config = collectIntegFormConfig();
 applyIntegBuilderSchema(id, config);
 // Empty password/token means keep stored secret — drop so PUT does not wipe.
 Object.keys(config).forEach((k) => {
  if (typeof config[k] === "boolean") return;
  if (k === "_schema" || k === "items" || k === "hosts") return;
  if (/pass|token|secret|api_key|^key$/i.test(k) && !String(config[k] || "").trim()) {
   delete config[k];
  }
 });
 await api(`/api/config/integrations/${encodeURIComponent(id)}`, {
 method: "PUT",
 body: JSON.stringify({ config }),
 });
 }

 async function deleteIntegration(id, builtin, name) {
 const label = name || id;
 const msg = builtin
 ? `清空内置集成「${label}」的全部配置？技能将无法连接，直到重新填写。`
 : `删除自定义集成「${label}」？`;
 if (!confirm(msg)) return;
 try {
 await api(`/api/config/integrations/${encodeURIComponent(id)}`, {
 method: "DELETE",
 });
 setMsg("msgIntegrations", "已删除/清空 " + id, "ok");
 showToast("已更新", "success");
 closeIntegrationEditor();
 await loadIntegrations();
 loadSkills();
 } catch (e) {
 setMsg("msgIntegrations", e.message, "error");
 }
 }

 function bindIntegrationUi() {
 if (bindIntegrationUi._bound) return;
 bindIntegrationUi._bound = true;
 // 与设定选项卡相同：委托绑定，不依赖注入时机
 document.addEventListener("click", (e) => {
  const t = e.target;
  if (!(t instanceof Element)) return;
  const btn = t.closest("button[id], .btn[id]");
  if (!btn || !btn.id) return;
  switch (btn.id) {
   case "btnRefreshIntegrations":
    loadIntegrations();
    break;
   case "btnAddIntegration":
    openIntegrationEditor("", true);
    break;
   case "btnSaveInteg":
    saveIntegration();
    break;
   case "btnTestInteg":
    testIntegration();
    break;
   case "btnCancelInteg":
   case "btnCloseIntegEditor":
    closeIntegrationEditor();
    break;
   case "btnDeleteInteg": {
    const id = ($("integId")?.value || "").trim();
    if (!id) {
     setMsg("msgIntegEditor", "新建项请取消，或先保存后再删", "error");
     return;
    }
    const it = _integCache.find((x) => x.id === id);
    deleteIntegration(id, it?.builtin, it?.name);
    break;
   }
   default:
    break;
  }
 });
 bindNestedBackdropClose("integrationEditorModal", closeIntegrationEditor);
 }
 bindIntegrationUi();
 L.bindIntegrationUi = bindIntegrationUi;

 // --- Storage / database (inline in 设定 → 存储 tab) ---
 const ST_PORT_DEFAULT = {
  sqlite: 0,
  postgresql: 5432,
  mysql: 3306,
  mariadb: 3306,
  mssql: 1433,
 };

 const ST_BACKEND_LABEL = {
  sqlite: "本地 SQLite",
  postgresql: "PostgreSQL",
  mysql: "MySQL",
  mariadb: "MariaDB",
  mssql: "SQL Server",
 };

 function storageIsRemote() {
  const b = ($("stBackend") && $("stBackend").value) || "sqlite";
  return b !== "sqlite";
 }

 function syncStorageFormMode() {
  const remote = storageIsRemote();
  document.querySelectorAll(".stRemoteOnly").forEach((el) => {
   if (!remote) {
    el.style.display = "none";
    return;
   }
   el.style.display = el.classList.contains("full") ? "flex" : "";
  });
  const sw = $("stSqliteWrap");
  if (sw) sw.style.display = remote ? "none" : "";
  const port = $("stPort");
  const backend = ($("stBackend") && $("stBackend").value) || "sqlite";
  if (port && remote) {
   port.placeholder =
    "默认 " + String(ST_PORT_DEFAULT[backend] || "") + "（0 表示用默认）";
  }
 }

 function collectStoragePayload() {
  const backend = ($("stBackend") && $("stBackend").value) || "sqlite";
  return {
   backend,
   host: ($("stHost") && $("stHost").value.trim()) || "127.0.0.1",
   port: parseInt(($("stPort") && $("stPort").value) || "0", 10) || 0,
   database: ($("stDatabase") && $("stDatabase").value.trim()) || "eva",
   username: ($("stUsername") && $("stUsername").value.trim()) || "",
   password: ($("stPassword") && $("stPassword").value) || "",
   ssl: !!( $("stSsl") && $("stSsl").checked ),
   sqlite_path: ($("stSqlitePath") && $("stSqlitePath").value.trim()) || "eva.db",
  };
 }

 function updateStorageTabSummary(s) {
  const el = $("storageTabSummary");
  if (!el) return;
  const b = (s && s.backend) || "sqlite";
  const label = ST_BACKEND_LABEL[b] || b;
  if (b === "sqlite") {
   el.textContent =
    "当前后端：" + label + "（" + ((s && s.sqlite_path) || "eva.db") + "）";
  } else {
   const host = (s && s.host) || "";
   const port = (s && (s.port_effective || s.port)) || "";
   const db = (s && s.database) || "";
   el.textContent =
    "当前后端：" + label + " · " + host + (port ? ":" + port : "") + "/" + db;
  }
 }

 async function loadStorage(opts = {}) {
  const soft = !!opts.soft;
  try {
   bindStorageUi();
   if (!soft) setMsg("msgStorage", "载入中…");
   const d = await api("/api/storage");
   const s = (d && d.storage) || {};
   if ($("stBackend")) $("stBackend").value = s.backend || "sqlite";
   if ($("stHost")) $("stHost").value = s.host || "127.0.0.1";
   if ($("stPort")) $("stPort").value = s.port > 0 ? s.port : "";
   if ($("stDatabase")) $("stDatabase").value = s.database || "eva";
   if ($("stUsername")) $("stUsername").value = s.username || "";
   if ($("stPassword")) $("stPassword").value = "";
   if ($("stSsl")) $("stSsl").checked = !!s.ssl;
   if ($("stSqlitePath")) $("stSqlitePath").value = s.sqlite_path || "eva.db";
   syncStorageFormMode();
   updateStorageTabSummary(s);
   const tip = s.password_set ? "（已保存密码，留空则不修改）" : "";
   setMsg(
    "msgStorage",
    "当前：" + (ST_BACKEND_LABEL[s.backend] || s.backend || "sqlite") + tip,
    "ok"
   );
  } catch (e) {
   setMsg("msgStorage", "载入失败：" + (e.message || e), "err");
  }
 }

 function bindStorageUi() {
  const backend = $("stBackend");
  if (backend && !backend._stBound) {
   backend._stBound = true;
   backend.addEventListener("change", syncStorageFormMode);
  }
  const btnTest = $("btnTestStorage");
  if (btnTest && !btnTest._stBound) {
   btnTest._stBound = true;
   btnTest.addEventListener("click", async () => {
    setMsg("msgStorage", "测试连接中…");
    try {
     const res = await api("/api/storage/test", {
      method: "POST",
      body: JSON.stringify(collectStoragePayload()),
     });
     if (res && res.ok) setMsg("msgStorage", res.message || "连接成功", "ok");
     else
      setMsg(
       "msgStorage",
       (res && (res.error || res.message)) || "连接失败",
       "err"
      );
    } catch (e) {
     setMsg("msgStorage", "测试失败：" + (e.message || e), "err");
    }
   });
  }
  const btnSave = $("btnSaveStorage");
  if (btnSave && !btnSave._stBound) {
   btnSave._stBound = true;
   btnSave.addEventListener("click", async () => {
    setMsg("msgStorage", "保存并初始化中…");
    try {
     const res = await api("/api/storage", {
      method: "PUT",
      body: JSON.stringify(collectStoragePayload()),
     });
     const mig = (res && res.summary && res.summary.migrated) || {};
     const bits = Object.keys(mig)
      .filter((k) => mig[k])
      .map((k) => k + ":" + mig[k]);
     const extra = bits.length ? " 已导入 " + bits.join(", ") : "";
     setMsg("msgStorage", (res.message || "已保存") + extra, "ok");
     if ($("stPassword")) $("stPassword").value = "";
     if (res && res.storage) updateStorageTabSummary(res.storage);
     showToast("存储配置已应用", "ok");
    } catch (e) {
     setMsg("msgStorage", "保存失败：" + (e.message || e), "err");
    }
   });
  }
 }

 function renderUpdatePanel(d) {
  const local = (d && d.local) || {};
  const remote = (d && d.remote) || {};
  const ch = (d && d.channel) || {};
  const repo = ch.repo || local.repo || "";
  if ($("updRepo") && !$("updRepo").value) $("updRepo").value = repo;
  const ver = local.version ? "v" + String(local.version).replace(/^v/i, "") : "";
  const tag = local.tag ? " 已应用 " + local.tag : "";
  const bits = ["当前 " + (ver || "未知") + tag];
  if (repo) bits.push("仓库 " + repo);
  if (ch.has_token) bits.push("已保存 Token");
  if (d && d.pending) bits.push("已下载更新包，待启动器应用");
  if (d && d.newer) {
    bits.push("有新版本 " + (remote.tag || remote.version || ""));
  } else if (d && d.ok) {
    bits.push("已是最新");
  }
  if ($("updSummary")) $("updSummary").textContent = bits.join(" · ");
  const notes = $("updNotes");
  if (notes) {
    const body = [];
    if (d && d.error) body.push(String(d.error));
    if (remote.name) body.push(String(remote.name));
    if (remote.published_at) body.push("发布于 " + String(remote.published_at));
    if (remote.notes) body.push(String(remote.notes));
    notes.textContent = body.join("\n");
  }
 }

 function bindUpdateUi() {
  const saveBtn = $("btnSaveUpdChannel");
  if (saveBtn && !saveBtn._updBound) {
   saveBtn._updBound = true;
   saveBtn.addEventListener("click", async () => {
    setMsg("msgUpdate", "保存中…");
    try {
     const payload = { repo: ($("updRepo") && $("updRepo").value.trim()) || "" };
     const tok = ($("updToken") && $("updToken").value.trim()) || "";
     if (tok) payload.token = tok;
     const res = await api("/api/system/update/channel", {
      method: "PUT",
      body: JSON.stringify(payload),
     });
     if ($("updToken")) $("updToken").value = "";
     setMsg(
      "msgUpdate",
      "已保存仓库" + (res && res.channel && res.channel.has_token ? "和 Token" : ""),
      "ok"
     );
    } catch (e) {
     setMsg("msgUpdate", "保存失败：" + (e.message || e), "err");
    }
   });
  }
  const checkBtn = $("btnCheckUpdate");
  if (checkBtn && !checkBtn._updBound) {
   checkBtn._updBound = true;
   checkBtn.addEventListener("click", () => loadAppUpdate({ force: true }));
  }
  const applyBtn = $("btnApplyUpdate");
  if (applyBtn && !applyBtn._updBound) {
   applyBtn._updBound = true;
   applyBtn.addEventListener("click", async () => {
    setMsg("msgUpdate", "正在下载并应用…");
    try {
     const res = await api("/api/system/update/apply", { method: "POST", body: "{}" });
     renderUpdatePanel(res || {});
     if (res && res.ok && (res.replaced || res.pending)) {
      setMsg("msgUpdate", res.message || "已处理", "ok");
      showToast(res.replaced ? "程序已更新，请重启 Eva" : "更新包已下载", "success");
     } else {
      setMsg(
       "msgUpdate",
       (res && (res.error || res.message)) || "没有可应用的更新",
       res && res.ok ? "ok" : "err"
      );
     }
    } catch (e) {
     setMsg("msgUpdate", "更新失败：" + (e.message || e), "err");
    }
   });
  }
 }

 async function loadAppUpdate(opts = {}) {
  const soft = !!opts.soft;
  const force = !!opts.force;
  try {
   bindUpdateUi();
   if (!soft) setMsg("msgUpdate", "检查中…");
   const path = force ? "/api/system/update/check" : "/api/system/update";
   const d = force
    ? await api(path, { method: "POST", body: "{}" })
    : await api(path);
   renderUpdatePanel(d || {});
   if (d && d.ok) {
    setMsg(
     "msgUpdate",
     d.newer
      ? "发现新版本 " + ((d.remote && (d.remote.tag || d.remote.version)) || "")
      : "已是最新",
     "ok"
    );
   } else {
    setMsg("msgUpdate", (d && d.error) || "检查失败", "err");
   }
  } catch (e) {
   setMsg("msgUpdate", "检查失败：" + (e.message || e), "err");
  }
 }

 L.loadConfig = loadConfig;
 L.renderAgentForm = renderAgentForm;
 L.collectAgentFormPayload = collectAgentFormPayload;
 L.loadEvolutionPanel = loadEvolutionPanel;
 L.addPersonaOption = addPersonaOption;
 L.removePersonaOption = removePersonaOption;
 L.getMsSelection = getMsSelection;
 L.loadLlms = loadLlms;
 L.loadToolsPanel = loadToolsPanel;
 L.loadSkills = loadSkills;
 L.loadMcp = loadMcp;
 L.loadIntegrations = loadIntegrations;
 L.loadStorage = loadStorage;
 L.loadAppUpdate = loadAppUpdate;
 L.openIntegrationEditor = openIntegrationEditor;
 L.openLlmEditor = openLlmEditor;
 L.openCustomToolEditor = openCustomToolEditor;
 L.openMcpEditor = openMcpEditor;
 L.openPromptEditor = openPromptEditor;
 L.closePromptEditor = closePromptEditor;
 L.deleteLlm = deleteLlm;
 L.deleteCustomTool = deleteCustomTool;
 L.deleteMcp = deleteMcp;
})(window.Lily);
