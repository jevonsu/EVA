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
 const setSidebarOpen = (...a) => L.setSidebarOpen(...a);

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
 setSidebarOpen(false);
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
  document.querySelector(".tab.active")?.dataset.tab ||
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

 function switchTab(name, opts = {}) {
 const soft = !!opts.soft;
 document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
 document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("active", p.dataset.panel === name));
 // soft：有内容时不先清空再 skeleton，对话生成中也能立刻看到上次数据
 if (name === "tasks") loadTasks({ soft });
 if (name === "memory") loadMemory($("memSearch")?.value || "", { soft });
 if (name === "kb") typeof L.loadKb === "function" && L.loadKb($("kbSearch")?.value || "", { soft });
 if (name === "workflows")
  typeof L.loadWorkflows === "function" && L.loadWorkflows({ soft });
 if (name === "workspace")
  typeof L.loadWorkspace === "function" && L.loadWorkspace(undefined, { soft });
 if (name === "webhooks")
  typeof L.loadWebhooks === "function" && L.loadWebhooks({ soft });
 if (name === "llm") loadLlms({ soft });
 if (name === "tools") loadToolsPanel({ soft });
 if (name === "skills") loadSkills({ soft });
 if (name === "mcp") loadMcp({ soft });
 if (name === "integrations") loadIntegrations({ soft });
 const activeTab = document.querySelector(`.tab[data-tab="${name}"]`);
 if (activeTab) activeTab.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
 const body = document.querySelector(".modal-body");
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
  document.querySelector(".tab.active")?.dataset.tab || "agent";
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
  // 已启用扮演时展开折叠，便于查看/改人设
  const rpOn = !!$("cfgRoleplayEnabled")?.checked;
  syncRoleplayFieldsUi({ openDetails: rpOn });
  if (rpOn) {
   const d = $("roleplayDetails");
   if (d) d.open = true;
  }
  _setText("cfgDecisionTree", a.decision_tree || "");
  _setText("cfgLanguageCalibrator", a.language_calibrator || "");
  _setText("cfgSop", a.sop || "");
  _setText("cfgHardBoundaries", a.hard_boundaries || "");
  _setText("cfgGreeting", a.greeting || "");
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
   decision_tree: $("cfgDecisionTree")?.value || "",
   language_calibrator: $("cfgLanguageCalibrator")?.value || "",
   sop: $("cfgSop")?.value || "",
   hard_boundaries: $("cfgHardBoundaries")?.value || "",
   greeting: $("cfgGreeting")?.value || "",
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
 const da = a && (a.is_default || a.default) ? 0 : 1;
 const db = b && (b.is_default || b.default) ? 0 : 1;
 return da - db;
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
 const enabled = llm.enabled !== false;
 card.className =
 "card llm-card" +
 (isDefault ? " is-default" : "") +
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
 <span class="pill ${modClass}" title="${escapeHtml(
 modHint || modLabel
 )}">${escapeHtml(modLabel)}</span>
 </div>
 <div class="card-sub">${escapeHtml(llm.provider || "—")} · <code>${escapeHtml(
 llm.model || "—"
 )}</code>${enabled ? "" : " · " + _ipkLabel("forbid", "停用", "ipk-xs")}</div>
 <div class="card-sub muted-line">${escapeHtml(llm.base_url || "")}</div>
 <div class="card-sub llm-balance-line" data-llm-balance="${escapeHtml(lid)}">
 <span class="llm-balance-label">余额</span>
 <span class="llm-balance-value is-loading">查询中…</span>
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
 <button type="button" class="btn llm-balance-refresh icon-btn" title="刷新余额" data-llm-id="${escapeHtml(
 lid
 )}">${_ipk("refresh", "ipk-sm")}</button>
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
 list.appendChild(card);
 // 异步拉余额，不阻塞列表
 if (lid) refreshLlmBalance(lid, false);
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

 async function refreshLlmBalance(llmId, forceRefresh) {
 if (!llmId) return;
 setLlmBalanceEl(llmId, "is-loading", "查询中…", "");
 try {
 const q = forceRefresh ? "?refresh=true" : "";
 const res = await api(
 `/api/config/llms/${encodeURIComponent(llmId)}/balance${q}`
 );
 if (res && res.ok) {
 const note = [res.note, res.source ? "来源: " + res.source : ""]
 .filter(Boolean)
 .join(" · ");
 setLlmBalanceEl(
 llmId,
 res.local ? "is-miss" : "is-ok",
 res.display || String(res.amount ?? "—"),
 note || "账户余额（尽力查询，因服务商而异）"
 );
 } else {
 const why = [res && res.error, res && res.hint]
 .filter(Boolean)
 .join(" — ");
 setLlmBalanceEl(
 llmId,
 "is-miss",
 (res && res.display) || "暂不可查",
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
 const base_url = ($("llmBaseUrl")?.value || "").trim();
 const api_key = ($("llmApiKey")?.value || "").trim();
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
 setMsg("msgLlmEditor", "拉取模型列表中…");
 try {
 const res = await api("/api/config/llms/models", {
 method: "POST",
 body: JSON.stringify({ base_url, api_key, id: id || null }),
 });
 if (!res.ok) {
 setMsg(
 "msgLlmEditor",
 "拉取失败: " + (res.error || res.detail || "unknown"),
 "error"
 );
 showToast("拉取模型失败", "error");
 return;
 }
 const models = res.models || [];
 fillLlmModelSelect(models, $("llmModel")?.value);
 setMsg(
 "msgLlmEditor",
 `已拉取 ${res.count ?? models.length} 个模型，请下拉选择`,
 "ok"
 );
 showToast(`已拉取 ${res.count ?? models.length} 个模型`, "success");
 } catch (e) {
 setMsg("msgLlmEditor", e.message, "error");
 showToast("拉取失败", "error");
 }
 }

 function openLlmEditor(llm) {
 const editingLlmId = llm.id || "";
 $("llmId").value = editingLlmId;
 $("llmName").value = llm.name || "";
 $("llmProvider").value = llm.provider || "openai";
 $("llmBaseUrl").value = llm.base_url || "";
 $("llmApiKey").value = "";
 $("llmModel").value = llm.model || "";
 fillLlmModelSelect(
 llm.model ? [{ id: llm.model, modality_label: llm.modality_label || modalityLabelLocal(llm.model, llm.name) }] : [],
 llm.model || ""
 );
 $("llmEnabled").checked = llm.enabled !== false;
 $("llmDefault").checked = !!(llm.is_default || llm.default);
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
 const CAPABILITY_GROUPS = [
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
 const btn = groupEl.querySelector(".panel-group-header");
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
 // 每类唯一主入口（等价工具已合并移除）
 analyze_image_auto: { group: "vision", role: "primary", note: "产品识图唯一入口" },
 grok_media: { group: "media", role: "primary", note: "生图/改图/图生视频" },
 memory: { group: "memory", role: "primary", note: "长期记忆" },
 kb: { group: "memory", role: "primary", note: "知识库 Wiki" },
 workflow: { group: "schedule", role: "primary", note: "工作流" },
 product_multi_platform_publisher: { group: "content", role: "primary" },
 workspace: { group: "workspace", role: "primary", note: "本地文件唯一入口" },
 http: { group: "network", role: "primary", note: "HTTP 唯一入口" },
 office: { group: "office", role: "primary", note: "Excel/PDF/PPT/Word" },
 scheduled_task: {
  group: "schedule",
  role: "primary",
  note: "与「设定→任务」同一数据源",
 },
 reminders: {
  group: "schedule",
  role: "legacy",
  note: "已停用·请用定时任务",
 },
 search_ai_news: { group: "news", role: "primary", note: "AI/科技资讯" },
 nas: { group: "infra", role: "primary" },
 nocodb: { group: "infra", role: "primary" },
 qb_manager: { group: "infra", role: "primary" },
 get_current_time: { group: "dev", role: "primary" },
 calculator: { group: "dev", role: "primary" },
 system_info: { group: "dev", role: "primary" },
 create_tool: { group: "dev", role: "primary", note: "运行时创建 skill" },
 read_skill: { group: "dev", role: "primary" },
 delete_tool: { group: "dev", role: "primary" },
 reload_runtime: { group: "dev", role: "primary" },
 run_py: { group: "dev", role: "primary", note: "跑脚本 + pip 装包" },
 list_api_models: { group: "dev", role: "primary" },
 server_health_check: { group: "dev", role: "primary" },
 };

 /** skill 包 id → 分组/角标（与 TOOL_META 对齐，仅展示） */
 const SKILL_META = {
 analyze_image_auto: { group: "vision", role: "primary" },
 grok_media: { group: "media", role: "primary" },
 product_multi_platform_publisher: { group: "content", role: "primary" },
 http: { group: "network", role: "primary" },
 office: { group: "office", role: "primary" },
 Tasks: { group: "schedule", role: "primary" },
 tasks: { group: "schedule", role: "primary" },
 reminders: { group: "schedule", role: "primary" },
 search_ai_news: { group: "news", role: "primary" },
 nas: { group: "infra", role: "primary" },
 nocodb: { group: "infra", role: "primary" },
 qb_manager: { group: "infra", role: "primary" },
 run_py: { group: "dev", role: "primary" },
 reload_runtime: { group: "dev", role: "primary" },
 list_api_models: { group: "dev", role: "primary" },
 server_health_check: { group: "dev", role: "primary" },
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
 // item 覆盖 static，但 group=other 不覆盖更好的 static 分组
 const m = Object.assign({}, staticM, itemM);
 let groupId = (m.group || "").toString().toLowerCase() || "other";
 if (!groupId || groupId === "other") {
 groupId =
 (itemM.group && itemM.group !== "other" && itemM.group) ||
 staticM.group ||
 "other";
 }
 if (
 (groupId === "other" || !groupId) &&
 staticM.group &&
 staticM.group !== "other"
 ) {
 groupId = staticM.group;
 }
 const isDynamic = m.dynamic === true || m.dynamic === "true";
 if (!groupId) groupId = "other";
 const g =
 CAPABILITY_GROUPS.find((x) => x.id === groupId) ||
 CAPABILITY_GROUPS[CAPABILITY_GROUPS.length - 1];
 let note = m.note || m.description_hint || m.tag || "";
 const ver = m.version ? "v" + m.version : "";
 if (isDynamic && !note) note = "动态创建（create_tool）" + (ver ? " · " + ver : "");
 else if (isDynamic && note && !String(note).includes("动态"))
 note = "动态 · " + note + (ver ? " · " + ver : "");
 else if (ver && note && !String(note).includes(ver)) note = note + " · " + ver;
 return {
 groupId: g.id,
 groupLabel:
 isDynamic && g.id === "other" ? "其它 / 动态创建" : g.label,
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
 function appendCollapsibleGroup(listEl, groupId, label, count, iconName) {
 const group = document.createElement("div");
 group.className = "panel-group is-collapsed";
 group.dataset.groupId = groupId || "";

 const header = document.createElement("button");
 header.type = "button";
 header.className = "panel-group-header";
 header.setAttribute("aria-expanded", "false");
 header.title = "点击展开 / 折叠";
 const chevron = ipk("right", "ipk-xs group-chevron-icon") || "›";
 const gicon = iconName ? ipk(iconName, "ipk-sm group-type-icon") : "";
 header.innerHTML =
 '<span class="group-chevron" aria-hidden="true">' +
 chevron +
 "</span>" +
 (gicon ? '<span class="group-type-icon-wrap">' + gicon + "</span>" : "") +
 '<h4 class="panel-title">' +
 escapeHtml(label) +
 '</h4><span class="group-count">' +
 count +
 " 项</span>";

 const body = document.createElement("div");
 body.className = "panel-group-body";
 body.hidden = true;

 header.addEventListener("click", () => {
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
 for (const g of CAPABILITY_GROUPS) {
 const rows = buckets.get(g.id) || [];
 if (!rows.length) continue;
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
 const desc = t.description || "";
 const src = t.source || "builtin";
 const label = t.display_name || meta.note || name;
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
 ? ' <span class="pill" title="已自定义提示词">自定义提示</span>'
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
 noteLine,
 offNote,
 "</div>",
 '<div class="card-actions">',
 ' <button type="button" class="btn btn-edit-prompt icon-btn" title="编辑提示词">' +
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
 card.querySelector(".btn-edit-prompt")?.addEventListener("click", () => {
 openPromptEditor({
 kind: "tool",
 id: name,
 label: label + " (" + name + ")",
 baseDescription: t.base_description || "",
 override: t.prompt_override || "",
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
 let skills = await api("/api/config/skills");
 if (!Array.isArray(skills)) skills = skills.items || [];
 list.innerHTML = "";
 if (!skills.length) {
 list.innerHTML =
 '<div class="card"><div class="card-body"><div class="card-sub">未有 skill</div></div></div>';
 setMsg("msgSkills", "0 个能力包", "ok");
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

 for (const g of CAPABILITY_GROUPS) {
 const rows = buckets.get(g.id) || [];
 if (!rows.length) continue;
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
 const noteLine = meta.note
 ? `<div class="card-sub muted-line">${escapeHtml(meta.note)}</div>`
 : "";
 const card = document.createElement("div");
 card.className =
 "card" +
 (meta.role === "primary" ? " card-role-primary" : "") +
 (enabled ? "" : " card-disabled");
 const ovBadge = s.has_prompt_override
 ? ' <span class="pill" title="已自定义提示词">自定义提示</span>'
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
 <div class="card-body">
 <div class="card-title">${escapeHtml(displayName)} ${rolePillHtml(
 meta.role,
 meta.dynamic
 )} <span class="pill source-pill">v${escapeHtml(
 s.version || "?"
 )}</span>${ovBadge}${integBadge}</div>
 <div class="card-sub muted-line">包 id: <code class="tool-call-name">${escapeHtml(
 s.id || ""
 )}</code></div>
 <div class="card-sub">${escapeHtml(
 (s.description || "").slice(0, 180)
 )}</div>
 <div class="card-sub muted-line">${
 s.has_handler ? "handler" : "no-handler"
 }${
 s.tool_count ? ` · 注册 tools ${s.tool_count}` : " · 见 handler 注册"
 }${
 integId
 ? ` · 集成 <code>${escapeHtml(integId)}</code>`
 : ""
 }</div>
 ${
 enabled
 ? ""
 : '<div class="card-sub muted-line">已关闭 — 勾选可重新开启（刷新后仍会显示）</div>'
 }
 ${noteLine}
 </div>
 <div class="card-actions">
 ${
 integId
 ? `<button type="button" class="btn btn-open-integ icon-btn" title="配置集成">${_ipk(
 "connection",
 "ipk-sm"
 )}</button>`
 : ""
 }
 <button type="button" class="btn btn-edit-prompt icon-btn" title="编辑提示词">${_ipk(
 "edit",
 "ipk-sm"
 )}</button>
 <label class="toggle tool-toggle-label">
 <input type="checkbox" class="toggle-skill" ${
 enabled ? "checked" : ""
 } />
 <span class="toggle-txt">${enabled ? "开" : "关"}</span>
 </label>
 </div>`;
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
 override: s.prompt_override || "",
 });
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

 setMsg(
 "msgSkills",
 `能力包 ${skills.length} · 已启用 ${enabledCount} · 主入口约 ${primaryCount}（与 Tools 不叠加 · 分组默认折叠）`,
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
 const data = {
 id: $("llmId").value || undefined,
 name: $("llmName").value,
 provider: $("llmProvider").value,
 base_url: $("llmBaseUrl").value,
 model: $("llmModel").value,
 enabled: $("llmEnabled").checked,
 is_default: $("llmDefault").checked,
 };
 const key = ($("llmApiKey").value || "").trim();
 if (key) data.api_key = key;
 try {
 await api("/api/config/llms", {
 method: "POST",
 body: JSON.stringify(data),
 });
 setMsg("msgLlm", "保存成功", "ok");
 showToast("LLM 已保存", "success");
 closeLlmEditor();
 loadLlms();
 loadHealth();
 } catch (e) {
 setMsg("msgLlm", e.message, "error");
 showToast("保存失败", "error");
 }
 }

 async function testLlmFromForm() {
 const id = $("llmId").value;
 try {
 setMsg("msgLlm", "测试中…");
 if (id) {
 const res = await api(`/api/config/llms/${encodeURIComponent(id)}/test`, {
 method: "POST",
 });
 const ok = res.ok !== false && !res.error;
 setMsg("msgLlm", ok ? "连接成功" : "" + (res.error || res.detail || "失败"), ok ? "ok" : "error");
 if (ok) showToast("连接成功", "success");
 else showToast("连接失败", "error");
 } else {
 const data = {
 name: $("llmName").value || "test",
 provider: $("llmProvider").value,
 base_url: $("llmBaseUrl").value,
 api_key: $("llmApiKey").value || "",
 model: $("llmModel").value,
 };
 const res = await api("/api/config/llms/test", {
 method: "POST",
 body: JSON.stringify(data),
 });
 const ok = res.ok !== false && !res.error;
 setMsg("msgLlm", ok ? "连接成功" : "" + (res.error || res.detail || "失败"), ok ? "ok" : "error");
 if (ok) showToast("连接成功", "success");
 else showToast("连接失败", "error");
 }
 } catch (e) {
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
 loadHealth();
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

 /**
  * 设定弹窗 HTML 异步注入后才存在的按钮：统一事件委托。
  * 避免远程服务器上 config-modal.html 慢于 JS 执行时 addEventListener 绑空。
  */
 function bindConfigDelegatedUi() {
 if (bindConfigDelegatedUi._done) return;
 bindConfigDelegatedUi._done = true;

 bindNestedBackdropClose("llmEditorModal", closeLlmEditor);
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
   case "btnAgentGoKb":
    switchTab("kb");
    break;
   case "btnAgentGoWf":
    switchTab("workflows");
    break;
   default:
    break;
  }
 });
 }

 // 立即注册委托（不依赖 DOM 是否已注入）
 bindConfigDelegatedUi();

 // Export
 L.switchTab = switchTab;
 L.openConfig = openConfig;
 L.bindConfigDelegatedUi = bindConfigDelegatedUi;
 L.openNestedEditor = openNestedEditor;
 L.closeNestedEditor = closeNestedEditor;
 L.closeLlmEditor = closeLlmEditor;
 L.closeCustomToolEditor = closeCustomToolEditor;
 L.closeMcpEditor = closeMcpEditor;
 L.closeIntegrationEditor = closeIntegrationEditor;
 L.closeConfig = closeConfig;
 // --- Prompt override editor (tool / skill) ---
 function openPromptEditor(opts) {
 const kind = opts.kind === "skill" ? "skill" : "tool";
 const id = opts.id || "";
 if (!id) return;
 $("promptTargetKind").value = kind;
 $("promptTargetId").value = id;
 $("promptTargetLabel").value = opts.label || id;
 $("promptBaseDesc").value = opts.baseDescription || "";
 $("promptCustomDesc").value =
 opts.override || opts.baseDescription || "";
 $("promptEditorTitle").innerHTML =
 (typeof _ipk === "function" ? _ipk("edit", "ipk-sm") + " " : "") +
 (kind === "skill" ? "编辑 Skill 提示词" : "编辑 Tool 提示词");
 $("promptEditorHint").textContent =
 kind === "skill"
 ? "Skill 包说明；若存在与包同名的 Tool，也会作为该 Tool 的后备提示词。保存到配置，不改代码。"
 : "Tool 的 function description（模型选工具时看到的说明）。保存到配置，不改代码。";
 setMsg("msgPrompt", "");
 $("promptEditor").classList.remove("hidden");
 $("promptEditor").scrollIntoView({ behavior: "smooth", block: "nearest" });
 }

 $("btnCancelPrompt")?.addEventListener("click", () => {
 $("promptEditor")?.classList.add("hidden");
 });

 $("btnResetPrompt")?.addEventListener("click", async () => {
 const kind = $("promptTargetKind")?.value || "tool";
 const id = $("promptTargetId")?.value || "";
 if (!id) return;
 if (!confirm("清除自定义提示词，恢复代码默认？")) return;
 try {
 const path =
 kind === "skill"
 ? `/api/config/skills/${encodeURIComponent(id)}/prompt`
 : `/api/config/tools/${encodeURIComponent(id)}/prompt`;
 await api(path, {
 method: "PUT",
 body: JSON.stringify({ description: "" }),
 });
 $("promptCustomDesc").value = $("promptBaseDesc").value || "";
 setMsg("msgPrompt", "已恢复默认", "ok");
 showToast("已恢复默认提示词", "success");
 $("promptEditor").classList.add("hidden");
 if (kind === "skill") loadSkills();
 else loadToolsPanel();
 } catch (e) {
 setMsg("msgPrompt", e.message, "error");
 showToast("恢复失败", "error");
 }
 });

 $("btnSavePrompt")?.addEventListener("click", async () => {
 const kind = $("promptTargetKind")?.value || "tool";
 const id = $("promptTargetId")?.value || "";
 const text = ($("promptCustomDesc")?.value || "").trim();
 if (!id) return;
 if (!text) {
 setMsg("msgPrompt", "内容为空将清除覆盖；请用「恢复默认」或填写内容", "error");
 return;
 }
 try {
 const path =
 kind === "skill"
 ? `/api/config/skills/${encodeURIComponent(id)}/prompt`
 : `/api/config/tools/${encodeURIComponent(id)}/prompt`;
 await api(path, {
 method: "PUT",
 body: JSON.stringify({ description: text }),
 });
 setMsg("msgPrompt", "已保存", "ok");
 showToast("提示词已保存", "success");
 $("promptEditor").classList.add("hidden");
 if (kind === "skill") loadSkills();
 else loadToolsPanel();
 } catch (e) {
 setMsg("msgPrompt", e.message, "error");
 showToast("保存失败", "error");
 }
 });

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
 const skills = (it.skills || []).join(", ") || "—";
 const cfg = it.config || {};
 const summaryBits = [];
 if (cfg.base_url) summaryBits.push(cfg.base_url);
 if (cfg.host)
 summaryBits.push(
 `${cfg.user || ""}@${cfg.host}${cfg.port ? ":" + cfg.port : ""}`
 );
 if (cfg.proxy_url) summaryBits.push("proxy " + cfg.proxy_url);
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
 ${it.builtin ? "" : ' <span class="pill">自定义</span>'}
 </div>
 <div class="card-sub">${escapeHtml(it.description || "")}</div>
 <div class="card-sub muted-line">id: <code>${escapeHtml(
 it.id
 )}</code> · 技能: ${escapeHtml(skills)}</div>
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
 const modalEl = $("integrationEditorModal")?.querySelector(".modal");
 if (modalEl) modalEl.classList.remove("cfg-editor-modal-lg");
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
 hint: "可选；NAS / 单机服务常用",
 },
 {
 key: "port",
 label: "端口",
 type: "number",
 placeholder: "445",
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
 hint: "配置名用于技能参数（如 host=nas）；检测端口用于批量体检。",
 };

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
 const lab = document.createElement("label");
 const isSecret = !!(f.secret || f.type === "password");
 const isFull =
 f.type === "url" ||
 f.type === "password" ||
 (key && (key.includes("url") || key.includes("token"))) ||
 f.full === true;
 lab.className = isFull ? "full" : "";
 const setFlag = sec[key + "_set"];
 const ph = isSecret
 ? setFlag
 ? "已设置 · 留空不修改"
 : f.placeholder || "输入密钥"
 : f.placeholder || "";
 const inputType =
 isSecret ? "password" : f.type === "number" ? "number" : "text";
 lab.innerHTML = `${escapeHtml(f.label || key)}${
 f.hint
 ? ` <span class="field-hint">${escapeHtml(f.hint)}</span>`
 : ""
 }<input data-integ-key="${escapeHtml(key)}" type="${inputType}" placeholder="${escapeHtml(
 ph
 )}" autocomplete="${isSecret ? "new-password" : "off"}" />`;
 const input = lab.querySelector("input");
 if (!isSecret && config[key] != null && config[key] !== "") {
 input.value = String(config[key]);
 }
 fieldsHost.appendChild(lab);
 }
 }

 function openIntegrationEditor(id, isNewCustom) {
 const box = $("integrationEditorModal");
 if (!box) return;
 const fieldsHost = $("integFields");
 if (!fieldsHost) return;
 fieldsHost.innerHTML = "";
 setMsg("msgIntegEditor", "");
 const lead = box.querySelector(".kb-editor-lead");
 const modalEl = box.querySelector(".modal");

 if (isNewCustom) {
 if (modalEl) modalEl.classList.remove("cfg-editor-modal-lg");
 $("integId").value = "";
 $("integEditorTitle").innerHTML =
 '<span data-ipk="plus" data-ipk-class="ipk-sm"></span> 新建自定义集成';
 if (lead) {
 lead.textContent =
 "配置技能连接参数；密钥留空表示不修改。与编辑内置集成同一套表单。";
 }
 $("integEditorDesc").textContent =
 "用于扩展技能连接；保存后可在列表中再编辑。id 建议小写字母开头（如 my_api）。";

 // 元信息区（仅新建）
 const meta = document.createElement("div");
 meta.className = "full integ-meta-block";
 meta.innerHTML = `
 <label>集成 id <em class="agent-opt-hint">保存后不可改</em>
 <input id="integNewId" type="text" placeholder="my_service" autocomplete="off" />
 </label>
 <label class="full">显示名称
 <input id="integNewName" type="text" placeholder="我的服务" />
 </label>
 <div class="integ-template-row">
 <span class="integ-template-label">表单模板</span>
 <label class="integ-template-opt"><input type="radio" name="integTemplate" value="generic" checked /> 通用连接（URL / 账号）</label>
 <label class="integ-template-opt"><input type="radio" name="integTemplate" value="hosts" /> 多机主机表（NetOps 风格）</label>
 </div>`;
 fieldsHost.appendChild(meta);

 const body = document.createElement("div");
 body.className = "full integ-fields-body form-grid";
 body.id = "integFieldsBody";
 fieldsHost.appendChild(body);

 const paintTemplate = () => {
 const mode =
 fieldsHost.querySelector('input[name="integTemplate"]:checked')
 ?.value || "generic";
 body.innerHTML = "";
 if (modalEl) {
 modalEl.classList.toggle("cfg-editor-modal-lg", mode === "hosts");
 }
 if (mode === "hosts") {
 renderIntegSchemaFields(
 body,
 [
 { ...HOSTS_TABLE_FIELD },
 {
 key: "default_ssh_password",
 label: "默认 SSH 密码",
 type: "password",
 secret: true,
 placeholder: "可选",
 hint: "单机未填密码时回落此值",
 },
 ],
 {},
 {}
 );
 } else {
 renderIntegSchemaFields(body, CUSTOM_INTEG_FIELDS, {}, {});
 }
 // 其它 JSON 放底部，两种模板都有
 const extra = document.createElement("label");
 extra.className = "full";
 extra.innerHTML = `其它字段 JSON <span class="field-hint">可选，合并进配置</span>
 <textarea data-integ-key="_extra_json" rows="2" placeholder='{"region":"cn"}'></textarea>`;
 body.appendChild(extra);
 };
 fieldsHost.querySelectorAll('input[name="integTemplate"]').forEach((r) => {
 r.addEventListener("change", paintTemplate);
 });
 paintTemplate();

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
 "配置技能连接参数；密钥留空表示不修改。与新建自定义集成同一套表单。";
 }
 $("integEditorDesc").textContent =
 (it.description || "") +
 (it.skills && it.skills.length
 ? " · 关联技能: " + it.skills.join(", ")
 : "");

 const fields = Array.isArray(it.fields) ? it.fields.slice() : [];
 const cfg = it.config || {};
 const secrets = it.secrets || {};
 const needsWide =
 String(it.id || id) === "netops" ||
 fields.some(
 (f) =>
 f.type === "hosts_table" ||
 f.key === "hosts" ||
 f.key === "hosts_json"
 );
 if (modalEl) modalEl.classList.toggle("cfg-editor-modal-lg", needsWide);

 renderIntegSchemaFields(fieldsHost, fields, cfg, secrets);
 openNestedEditor("integrationEditorModal");
 if (typeof L.hydrateIconPark === "function") L.hydrateIconPark(box);
 }

 function buildIntegHostsTable(hostsObj, secrets, fieldMeta) {
 const wrap = document.createElement("div");
 wrap.className = "full integ-hosts-wrap";
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
 <button type="button" class="btn icon-inline" id="btnIntegAddHost">
 <span data-ipk="plus" data-ipk-class="ipk-xs"></span> 添加主机
 </button>
 <span class="field-hint">配置名例：nas、router；检测端口逗号分隔，如 22,80,443</span>
 </div>`;
 const body = wrap.querySelector("#integHostsBody");
 const hosts =
 hostsObj && typeof hostsObj === "object" && !Array.isArray(hostsObj)
 ? hostsObj
 : {};
 const names = Object.keys(hosts);
 if (!names.length) {
 appendIntegHostRow(body, { name: "nas" }, secrets);
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
 <td><input data-h="name" type="text" placeholder="nas" value="${escapeHtml(
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
 const hasHostsTable = !!root?.querySelector("[data-integ-hosts-table]");
 // 优先从 body 容器收集（新建时字段在 #integFieldsBody）
 const scope = $("integFieldsBody") || root;
 if (!scope) return cfg;
 scope.querySelectorAll("[data-integ-key]").forEach((el) => {
 const k = el.getAttribute("data-integ-key");
 if (!k || k === "_extra_json") return;
 if (hasHostsTable && (k === "hosts" || k === "hosts_json")) return;
 cfg[k] = el.value;
 });
 if (hasHostsTable) {
 const hosts = collectIntegHostsFromForm() || {};
 cfg.hosts = hosts;
 cfg.hosts_json = JSON.stringify(hosts);
 }
 const extra = scope.querySelector('[data-integ-key="_extra_json"]');
 if (extra && String(extra.value || "").trim()) {
 try {
 const o = JSON.parse(extra.value);
 if (o && typeof o === "object") Object.assign(cfg, o);
 } catch (_) {
 throw new Error("其它 JSON 格式无效");
 }
 }
 // 去掉空字符串非密钥字段可选：保留空串以便清空 host 等
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
 const body = { config };
 if (isNew) {
 body.name = ($("integNewName")?.value || "").trim() || id;
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
 // save first so test uses latest non-secret fields; secrets only if typed
 await saveIntegrationQuiet(id);
 const res = await api(
 `/api/config/integrations/${encodeURIComponent(id)}/test`,
 { method: "POST" }
 );
 if (res.ok) {
 setMsg(
 "msgIntegEditor",
 "测试通过: " + (res.detail || res.status_code || "ok"),
 "ok"
 );
 showToast("连接测试通过", "success");
 } else {
 setMsg(
 "msgIntegEditor",
 "测试失败: " + (res.error || res.detail || "unknown"),
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

 L.loadConfig = loadConfig;
 L.renderAgentForm = renderAgentForm;
 L.collectAgentFormPayload = collectAgentFormPayload;
 L.addPersonaOption = addPersonaOption;
 L.removePersonaOption = removePersonaOption;
 L.getMsSelection = getMsSelection;
 L.loadLlms = loadLlms;
 L.loadToolsPanel = loadToolsPanel;
 L.loadSkills = loadSkills;
 L.loadMcp = loadMcp;
 L.loadIntegrations = loadIntegrations;
 L.openIntegrationEditor = openIntegrationEditor;
 L.openLlmEditor = openLlmEditor;
 L.openCustomToolEditor = openCustomToolEditor;
 L.openMcpEditor = openMcpEditor;
 L.openPromptEditor = openPromptEditor;
 L.deleteLlm = deleteLlm;
 L.deleteCustomTool = deleteCustomTool;
 L.deleteMcp = deleteMcp;
})(window.Lily);
