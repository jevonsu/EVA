/**
 * Lily - Session persona modal + evolution table
 */
((L) => {
 "use strict";
 const { $, state, escapeHtml, showToast } = L;
 const api = (...a) => L.api(...a);
 const EVO_PAGE_SIZE = 10;

 function evoQueryTable(items, opts) {
  const q = String((opts && opts.q) || "").trim().toLowerCase();
  const kind = String((opts && opts.kind) || "").trim();
  const tag = String((opts && opts.tag) || "").trim();
  const source = String((opts && opts.source) || "").trim();
  const scope = String((opts && opts.scope) || "").trim();
  const pageSize = Math.max(1, Number((opts && opts.pageSize) || EVO_PAGE_SIZE));
  let rows = Array.isArray(items) ? items.slice() : [];
  rows = rows.filter((e) => {
   if (kind && String(e.kind || "") !== kind) return false;
   if (source && String(e.source || "") !== source) return false;
   if (scope && String(e.scope || "") !== scope) return false;
   if (tag) {
    const ids = e.tags || [];
    const names = e.tag_names || [];
    if (!ids.includes(tag) && !names.includes(tag)) return false;
   }
   if (q) {
    const blob = [
     e.content || "",
     e.kind || "",
     e.kind_label || "",
     (e.tag_names || []).join(" "),
     (e.tags || []).join(" "),
    ].join(" ").toLowerCase();
    if (!blob.includes(q)) return false;
   }
   return true;
  });
  const total = rows.length;
  const pages = Math.max(1, Math.ceil(total / pageSize) || 1);
  let page = Math.max(1, Number((opts && opts.page) || 1));
  if (page > pages) page = pages;
  const start = (page - 1) * pageSize;
  return { items: rows.slice(start, start + pageSize), total, page, pages, pageSize, empty: total === 0 };
 }

 L.evoQueryTable = evoQueryTable;
 L.EVO_PAGE_SIZE = EVO_PAGE_SIZE;

 function spMsg(text, kind) {
  const el = $("msgSessionPersona");
  if (!el) return;
  el.textContent = text || "";
  el.className = "form-msg" + (kind ? " " + kind : "");
 }

 const IDENTITY_DEFAULTS = {
  language: [
   { id: "inherit_public", label: "跟随公共" },
   { id: "zh-Hans", label: "简体中文" },
   { id: "zh-Hant", label: "繁体中文" },
   { id: "en", label: "English" },
   { id: "ja", label: "日本語" },
   { id: "follow_user", label: "自动跟随用户" },
  ],
  speech_style: [
   { id: "inherit_public", label: "跟随公共" },
   { id: "natural", label: "自然口语（说人话）" },
   { id: "concise", label: "简洁直接" },
   { id: "gentle", label: "温和耐心" },
   { id: "formal", label: "正式专业" },
   { id: "humorous", label: "轻松幽默" },
   { id: "detailed", label: "详细讲解" },
   { id: "custom", label: "自定义" },
  ],
  answer_detail: [
   { id: "inherit_public", label: "跟随公共" },
   { id: "brief", label: "简要" },
   { id: "balanced", label: "适中" },
   { id: "detailed", label: "详尽" },
  ],
  terminology: [
   { id: "inherit_public", label: "跟随公共" },
   { id: "plain", label: "少用术语，必要时先解释" },
   { id: "balanced", label: "适度使用术语" },
   { id: "technical", label: "可以使用专业术语" },
  ],
 };

 const LANG_ALIASES = {
  "跟随公共": "inherit_public",
  inherit: "inherit_public",
  inherit_public: "inherit_public",
  "自动跟随用户": "follow_user",
  "跟随用户": "follow_user",
  follow_user: "follow_user",
  "简体中文": "zh-Hans",
  "簡體中文": "zh-Hans",
  "繁体中文": "zh-Hant",
  "繁體中文": "zh-Hant",
  English: "en",
  "英文": "en",
  "英语": "en",
  "日本語": "ja",
  "日语": "ja",
  "日語": "ja",
 };

 function currentMode() {
  return $("spModeOverride") && $("spModeOverride").checked ? "override" : "inherit";
 }

 function identitySelectHtml(options, selected) {
  const opts = Array.isArray(options) ? options : [];
  const cur = selected == null ? "" : String(selected);
  let html = opts.map((o) => {
   const id = escapeHtml(o.id == null ? o : o.id);
   const label = escapeHtml(o.label == null ? o : o.label);
   const sel = String(o.id == null ? o : o.id) === cur ? " selected" : "";
   return `<option value="${id}"${sel}>${label}</option>`;
  }).join("");
  if (cur && !opts.some((o) => String(o.id == null ? o : o.id) === cur)) {
   const safe = escapeHtml(cur);
   html = `<option value="${safe}" selected>${safe}</option>` + html;
  }
  return html;
 }

 function fillIdentitySelect(sel, options, selected) {
  if (!sel) return "";
  const html = identitySelectHtml(options, selected);
  sel.innerHTML = html;
  if (selected) sel.value = selected;
  return html;
 }

 function mapLanguageId(raw) {
  const s = String(raw || "").trim();
  if (!s) return "";
  if (LANG_ALIASES[s]) return LANG_ALIASES[s];
  const low = s.toLowerCase();
  if (LANG_ALIASES[low]) return LANG_ALIASES[low];
  return s;
 }

 function sessionChoices() {
  const c = _spCache && _spCache.identity_choices;
  return {
   language: (c && c.language) || IDENTITY_DEFAULTS.language,
   speech_style: (c && c.speech_style) || IDENTITY_DEFAULTS.speech_style,
   answer_detail: (c && c.answer_detail) || IDENTITY_DEFAULTS.answer_detail,
   terminology: (c && c.terminology) || IDENTITY_DEFAULTS.terminology,
   copy: (c && c.copy) || {},
  };
 }

 function publicChoicesFromAgent(agent) {
  const c = (agent && agent.identity_choices) || {};
  const dropInherit = (arr) => (arr || []).filter((o) => (o.id || o) !== "inherit_public");
  return {
   language: dropInherit(c.language) || IDENTITY_DEFAULTS.language.filter((o) => o.id !== "inherit_public"),
   speech_style: dropInherit(c.speech_style) || IDENTITY_DEFAULTS.speech_style.filter((o) => o.id !== "inherit_public"),
   answer_detail: dropInherit(c.answer_detail) || IDENTITY_DEFAULTS.answer_detail.filter((o) => o.id !== "inherit_public"),
   terminology: dropInherit(c.terminology) || IDENTITY_DEFAULTS.terminology.filter((o) => o.id !== "inherit_public"),
  };
 }

 function fillSessionIdentityForm(agent, publicAgent, opts) {
  const a = agent || {};
  const pub = publicAgent || {};
  const prefill = !!(opts && opts.prefillFromPublic);
  const set = (id, v) => { const el = $(id); if (el) el.value = v || ""; };
  const name = prefill ? (a.name || pub.name || "") : (a.name || "");
  set("spAgentName", name);
  const lang = mapLanguageId(prefill ? (a.language || pub.language || "inherit_public") : (a.language || "inherit_public"));
  const style = prefill ? (a.speech_style || pub.speech_style || "inherit_public") : (a.speech_style || "inherit_public");
  const detail = prefill ? (a.answer_detail || pub.answer_detail || "inherit_public") : (a.answer_detail || "inherit_public");
  const term = prefill ? (a.terminology || pub.terminology || "inherit_public") : (a.terminology || "inherit_public");
  const ch = sessionChoices();
  fillIdentitySelect($("spLanguage"), ch.language, lang);
  fillIdentitySelect($("spSpeechStyle"), ch.speech_style, style);
  fillIdentitySelect($("spAnswerDetail"), ch.answer_detail, detail);
  fillIdentitySelect($("spTerminology"), ch.terminology, term);
  set("spRoleBackground", prefill ? (a.background || pub.background || "") : (a.background || ""));
  set("spSpeechCustom", prefill ? (a.speech_style_custom || pub.speech_style_custom || "") : (a.speech_style_custom || ""));
 }

 function collectSessionPersona() {
  return {
   name: $("spAgentName")?.value || "",
   language: $("spLanguage")?.value || "inherit_public",
   background: $("spRoleBackground")?.value || "",
   speech_style: $("spSpeechStyle")?.value || "inherit_public",
   speech_style_custom: $("spSpeechCustom")?.value || "",
   answer_detail: $("spAnswerDetail")?.value || "inherit_public",
   terminology: $("spTerminology")?.value || "inherit_public",
  };
 }

 function setModeUi(mode) {
  if ($("spModeInherit")) $("spModeInherit").checked = mode !== "override";
  if ($("spModeOverride")) $("spModeOverride").checked = mode === "override";
  const form = $("spForm");
  if (form) form.classList.toggle("is-inherit", mode !== "override");
  const fields = form && form.querySelectorAll("input, select, textarea");
  if (fields) fields.forEach((el) => { el.disabled = mode !== "override"; });
  const help = $("spModeHelp");
  if (help) {
   const copy = sessionChoices().copy || {};
   help.textContent = mode === "override"
    ? (copy.override_mode || "独立人设：只配置本会话的助手身份与沟通偏好，不含角色扮演，也不会沿用公共角色扮演。某一栏选「跟随公共」只作用于该栏，不等于总体模式的「跟随公共人设」。")
    : (copy.inherit_mode || "跟随公共人设：本会话完整使用当前公共人设（含公共角色扮演，若已启用）。每轮请求开始读取最新公共快照，不会改写公共配置。");
  }
 }

 L.identitySelectHtml = identitySelectHtml;
 L.fillIdentitySelect = fillIdentitySelect;
 L.mapLanguageId = mapLanguageId;
 L.collectSessionPersona = collectSessionPersona;
 L.IDENTITY_DEFAULTS = IDENTITY_DEFAULTS;

 function showPersonaModal(open) {
  const el = $("sessionPersonaBackdrop");
  if (!el) return;
  el.classList.toggle("hidden", !open);
 }

 let _spCache = null;
 let _spSessionId = "";

 async function ensureSessionId() {
  let sid = _spSessionId || (state && state.sessionId) || "";
  if (sid) return sid;
  const created = await api("/api/sessions", { method: "POST", body: { title: "新对话" } });
  sid = created && (created.session_id || created.sessionId);
  if (!sid) throw new Error("无法创建会话");
  if (state) {
   state.sessionId = sid;
   if (typeof L.loadSessions === "function") await L.loadSessions();
   if (typeof L.openSession === "function") await L.openSession(sid, created.title || "新对话");
  }
  return sid;
 }

 async function openSessionPersona(sessionId) {
  _spSessionId = sessionId || (state && state.sessionId) || "";
  spMsg("", "");
  showPersonaModal(true);
  try {
   if (!_spSessionId) _spSessionId = await ensureSessionId();
   const data = await api("/api/sessions/" + encodeURIComponent(_spSessionId) + "/persona");
   _spCache = data;
   setModeUi(data.mode || "inherit");
   const src = $("spSourceLine");
   if (src) src.textContent = "当前生效：" + (data.source_label || "—") + (data.session_title ? " · " + data.session_title : "");
   const hint = $("spRoleHint");
   if (hint) {
    hint.textContent = data.role_change_hint || "";
    hint.hidden = !data.show_role_change_hint && data.mode !== "override";
    if (data.mode === "override" && data.role_change_hint) hint.hidden = false;
   }
   const formAgent = data.mode === "override" ? data.agent : {};
   fillSessionIdentityForm(formAgent || {}, data.public_agent || {}, {
    prefillFromPublic: data.mode !== "override",
   });
  } catch (e) {
   spMsg(e.message || String(e), "error");
  }
 }

 async function saveSessionPersona(mode) {
  spMsg("保存中…", "");
  try {
   const sid = await ensureSessionId();
   const body = { mode: mode || currentMode(), agent: collectSessionPersona() };
   const data = await api("/api/sessions/" + encodeURIComponent(sid) + "/persona", {
    method: "PATCH",
    body,
   });
   if (data && data.ok === false) throw new Error(data.error || data.detail || "保存失败");
   _spCache = data;
   setModeUi(data.mode || body.mode);
   const src = $("spSourceLine");
   if (src) src.textContent = "当前生效：" + (data.source_label || "—");
   if (data.mode === "override") {
    fillSessionIdentityForm(data.agent || {}, data.public_agent || {}, { prefillFromPublic: false });
   } else if (data.public_agent) {
    fillSessionIdentityForm({}, data.public_agent, { prefillFromPublic: true });
   }
   spMsg("已保存", "ok");
   showToast("本对话人设已保存", "success");
   if (data.role_change_hint && (data.mode === "override" || data.show_role_change_hint)) {
    const hint = $("spRoleHint");
    if (hint) { hint.textContent = data.role_change_hint; hint.hidden = false; }
   }
  } catch (e) {
   spMsg(e.message || String(e), "error");
   showToast("保存失败", "error");
  }
 }

 let _boundSp = false;
 let _boundEvo = false;

 function bindSessionPersonaUi() {
  if (_boundSp) return;
  if (!$("sessionPersonaBackdrop") && !$("btnSessionPersona")) return;
  _boundSp = true;
  const close = () => showPersonaModal(false);
  $("btnCloseSessionPersona")?.addEventListener("click", close);
  $("sessionPersonaBackdrop")?.addEventListener("click", (e) => {
   if (e.target === $("sessionPersonaBackdrop")) close();
  });
  $("btnSessionPersona")?.addEventListener("click", () => openSessionPersona(state && state.sessionId));
  $("btnSpSave")?.addEventListener("click", () => saveSessionPersona(currentMode()));
  $("btnSpRestore")?.addEventListener("click", async () => {
   setModeUi("inherit");
   await saveSessionPersona("inherit");
   if (_spCache && _spCache.public_agent) {
    fillSessionIdentityForm({}, _spCache.public_agent, { prefillFromPublic: true });
   }
  });
  $("spModeInherit")?.addEventListener("change", () => {
   setModeUi("inherit");
   if (_spCache && _spCache.public_agent) {
    fillSessionIdentityForm({}, _spCache.public_agent, { prefillFromPublic: true });
   }
  });
  $("spModeOverride")?.addEventListener("change", () => {
   setModeUi("override");
   const saved = _spCache && _spCache.mode === "override" ? (_spCache.agent || {}) : {};
   fillSessionIdentityForm(saved, (_spCache && _spCache.public_agent) || {}, {
    prefillFromPublic: !(_spCache && _spCache.mode === "override"),
   });
  });
 }

 /* -------- evolution table -------- */
 const evoState = {
  scope: "session",
  q: "",
  kind: "",
  tag: "",
  source: "",
  page: 1,
  loading: false,
  kinds: [],
  tags: [],
 };

 function evoStatus(text, isError) {
  const el = $("evoTableStatus");
  if (!el) return;
  el.textContent = text || "";
  el.classList.toggle("is-error", !!isError);
 }

 function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return escapeHtml(String(iso));
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
 }

 function fillSelect(sel, items, valueKey, labelKey, emptyLabel, current) {
  if (!sel) return;
  const cur = current || sel.value || "";
  const opts = [`<option value="">${escapeHtml(emptyLabel || "全部")}</option>`];
  (items || []).forEach((it) => {
   const v = typeof it === "string" ? it : it[valueKey];
   const l = typeof it === "string" ? it : it[labelKey] || it[valueKey];
   opts.push(`<option value="${escapeHtml(v)}">${escapeHtml(l)}</option>`);
  });
  sel.innerHTML = opts.join("");
  if (cur) sel.value = cur;
 }

 async function loadEvolutionTable() {
  const body = $("evoTableBody");
  if (!body) return;
  const sid = (state && state.sessionId) || "";
  const scope = $("evoScope")?.value || evoState.scope || "session";
  evoState.scope = scope;
  evoState.q = $("evoSearch")?.value || "";
  evoState.kind = $("evoKindFilter")?.value || "";
  evoState.tag = $("evoTagFilter")?.value || "";
  evoState.source = $("evoSourceFilter")?.value || "";
  if (scope === "session" && !sid) {
   body.innerHTML = `<tr><td colspan="7"><p class="evo-persona-empty">请先打开一个会话，再查看当前会话的演化人格。</p></td></tr>`;
   if ($("evoPager")) $("evoPager").textContent = "";
   evoStatus("", false);
   return;
  }
  evoState.loading = true;
  evoStatus("载入中…", false);
  const params = new URLSearchParams({
   scope,
   session_id: sid,
   q: evoState.q,
   kind: evoState.kind,
   tag: evoState.tag,
   source: evoState.source,
   page: String(evoState.page || 1),
   page_size: String(EVO_PAGE_SIZE),
  });
  try {
   const data = await api("/api/evolution/entries?" + params.toString());
   evoState.loading = false;
   evoState.tags = data.tags || evoState.tags;
   fillSelect($("evoTagFilter"), evoState.tags, "id", "name", "全部标签", evoState.tag);
   if (data.need_session) {
    body.innerHTML = `<tr><td colspan="7"><p class="evo-persona-empty">请先打开一个会话。</p></td></tr>`;
    evoStatus("", false);
    return;
   }
   const items = data.items || [];
   if (data.empty) {
    body.innerHTML = `<tr><td colspan="7"><p class="evo-persona-empty">没有符合条件的演化条目。</p></td></tr>`;
   } else {
    body.innerHTML = items.map((e) => {
     const tags = (e.tag_names || []).map((n) => `<span class="evo-pill">${escapeHtml(n)}</span>`).join("") || "—";
     return `<tr>
      <td class="evo-content">${escapeHtml(e.content || "")}</td>
      <td>${tags}</td>
      <td>${escapeHtml(e.kind_label || e.kind || "")}</td>
      <td>${escapeHtml(e.source_label || e.source || "")}</td>
      <td>${escapeHtml(e.scope_label || e.scope || "")}</td>
      <td>${fmtTime(e.updated_at)}</td>
      <td>
        <button type="button" class="cfg-tool evo-edit" data-id="${escapeHtml(e.id)}" data-scope="${escapeHtml(e.scope)}">编辑</button>
        <button type="button" class="cfg-tool evo-del" data-id="${escapeHtml(e.id)}" data-scope="${escapeHtml(e.scope)}">删除</button>
      </td>
     </tr>`;
    }).join("");
   }
   const pages = data.pages || 1;
   evoState.page = data.page || 1;
   if ($("evoPager")) {
    $("evoPager").innerHTML =
     `<span>共 ${Number(data.total || 0)} 条 · 第 ${evoState.page}/${pages} 页（每页 ${EVO_PAGE_SIZE} 条）</span>` +
     `<button type="button" class="cfg-tool" id="evoPrev" ${evoState.page <= 1 ? "disabled" : ""}>上一页</button>` +
     `<button type="button" class="cfg-tool" id="evoNext" ${evoState.page >= pages ? "disabled" : ""}>下一页</button>`;
    $("evoPrev")?.addEventListener("click", () => { evoState.page = Math.max(1, evoState.page - 1); loadEvolutionTable(); });
    $("evoNext")?.addEventListener("click", () => { evoState.page += 1; loadEvolutionTable(); });
   }
   const meta = $("evoPersonaMeta");
   if (meta) meta.textContent = scope === "global" ? "公共演化人格（全实例，非长期记忆）" : (scope === "all" ? "当前会话 + 公共演化" : "当前会话演化人格");
   evoStatus("", false);
   body.querySelectorAll(".evo-edit").forEach((btn) => {
    btn.addEventListener("click", () => openEntryEditor(items.find((x) => x.id === btn.getAttribute("data-id"))));
   });
   body.querySelectorAll(".evo-del").forEach((btn) => {
    btn.addEventListener("click", () => deleteEntry(btn.getAttribute("data-id"), btn.getAttribute("data-scope")));
   });
  } catch (e) {
   evoState.loading = false;
   body.innerHTML = `<tr><td colspan="7"><p class="evo-persona-empty">无法读取：${escapeHtml(e.message || e)}</p></td></tr>`;
   evoStatus(e.message || String(e), true);
  }
 }

 function openEntryEditor(entry) {
  const box = $("evoEditor");
  if (!box) return;
  box.hidden = false;
  $("evoEditorTitle").textContent = entry && entry.id ? "编辑条目" : "新建条目";
  $("evoEditId").value = (entry && entry.id) || "";
  const scope = (entry && entry.scope) || ($("evoScope")?.value === "global" ? "global" : "session");
  $("evoEditScopeSelect").value = scope;
  $("evoEditKind").value = (entry && entry.kind) || "fact";
  $("evoEditContent").value = (entry && entry.content) || "";
  renderEditTags((entry && entry.tags) || []);
  const msg = $("msgEvoEditor");
  if (msg) { msg.textContent = ""; msg.className = "form-msg"; }
 }

 function renderEditTags(selected) {
  const host = $("evoEditTags");
  if (!host) return;
  const sel = new Set(selected || []);
  host.innerHTML = (evoState.tags || []).map((t) => {
   const id = escapeHtml(t.id);
   const name = escapeHtml(t.name);
   const checked = sel.has(t.id) ? " checked" : "";
   return `<label class="evo-pill"><input type="checkbox" value="${id}"${checked} /> ${name}</label>`;
  }).join("") || '<span class="field-hint">暂无标签，请先在标签管理中新建。</span>';
 }

 function selectedEditTags() {
  return Array.from(($("evoEditTags") || document).querySelectorAll("input[type=checkbox]:checked")).map((x) => x.value);
 }

 async function saveEntry() {
  const msg = $("msgEvoEditor");
  const content = ($("evoEditContent")?.value || "").trim();
  if (!content) {
   if (msg) { msg.textContent = "请填写内容"; msg.className = "form-msg error"; }
   return;
  }
  const id = $("evoEditId")?.value || "";
  const scope = $("evoEditScopeSelect")?.value || "session";
  const sid = (state && state.sessionId) || "";
  if (scope === "session" && !sid) {
   if (msg) { msg.textContent = "请先打开一个会话"; msg.className = "form-msg error"; }
   return;
  }
  if (msg) { msg.textContent = "保存中…"; msg.className = "form-msg"; }
  const payload = {
   scope,
   session_id: sid,
   kind: $("evoEditKind")?.value || "fact",
   content,
   tags: selectedEditTags(),
  };
  try {
   if (id) {
    await api("/api/evolution/entries/" + encodeURIComponent(id), { method: "PATCH", body: payload });
   } else {
    await api("/api/evolution/entries", { method: "POST", body: payload });
   }
   if (msg) { msg.textContent = "已保存"; msg.className = "form-msg ok"; }
   $("evoEditor").hidden = true;
   await loadEvolutionTable();
  } catch (e) {
   if (msg) { msg.textContent = e.message || String(e); msg.className = "form-msg error"; }
   showToast("条目保存失败", "error");
  }
 }

 async function deleteEntry(id, scope) {
  if (!id) return;
  if (!confirm("确定删除这条演化要点？自动压缩不会再把它复活。")) return;
  try {
   const sid = (state && state.sessionId) || "";
   const q = new URLSearchParams({ scope: scope || "session", session_id: sid });
   await api("/api/evolution/entries/" + encodeURIComponent(id) + "?" + q.toString(), { method: "DELETE" });
   showToast("已删除", "success");
   await loadEvolutionTable();
  } catch (e) {
   showToast("删除失败: " + (e.message || e), "error");
   evoStatus(e.message || String(e), true);
  }
 }

 async function loadKindsAndTags() {
  try {
   const kinds = await api("/api/evolution/kinds");
   evoState.kinds = (kinds && kinds.kinds) || [];
   fillSelect($("evoKindFilter"), evoState.kinds, "id", "label", "全部类型", evoState.kind);
   fillSelect($("evoEditKind"), evoState.kinds, "id", "label", "事实", "fact");
  } catch (_) {}
  try {
   const tags = await api("/api/evolution/tags");
   evoState.tags = (tags && tags.tags) || [];
   fillSelect($("evoTagFilter"), evoState.tags, "id", "name", "全部标签", evoState.tag);
  } catch (_) {}
 }

 function renderTagManager() {
  const host = $("evoTagList");
  if (!host) return;
  if (!evoState.tags.length) {
   host.innerHTML = '<p class="evo-persona-empty">还没有标签。</p>';
   return;
  }
  host.innerHTML = evoState.tags.map((t) => `
    <div class="agent-row" data-tag-id="${escapeHtml(t.id)}">
      <input type="text" maxlength="32" value="${escapeHtml(t.name)}" class="evo-tag-name" />
      <button type="button" class="cfg-tool evo-tag-rename">重命名</button>
      <button type="button" class="cfg-tool evo-tag-del">删除</button>
    </div>`).join("");
  host.querySelectorAll(".evo-tag-rename").forEach((btn) => {
   btn.addEventListener("click", async () => {
    const row = btn.closest("[data-tag-id]");
    const id = row.getAttribute("data-tag-id");
    const name = row.querySelector(".evo-tag-name")?.value || "";
    const msg = $("msgEvoTags");
    try {
     await api("/api/evolution/tags/" + encodeURIComponent(id), { method: "PATCH", body: { name } });
     if (msg) { msg.textContent = "已重命名"; msg.className = "form-msg ok"; }
     await loadKindsAndTags();
     renderTagManager();
     await loadEvolutionTable();
    } catch (e) {
     if (msg) { msg.textContent = e.message || String(e); msg.className = "form-msg error"; }
    }
   });
  });
  host.querySelectorAll(".evo-tag-del").forEach((btn) => {
   btn.addEventListener("click", async () => {
    const row = btn.closest("[data-tag-id]");
    const id = row.getAttribute("data-tag-id");
    if (!confirm("删除标签不会删除条目，只会从条目上移除该标签。确定吗？")) return;
    const msg = $("msgEvoTags");
    try {
     const res = await api("/api/evolution/tags/" + encodeURIComponent(id), { method: "DELETE" });
     const n = (res && res.unbound && res.unbound.total) || 0;
     if (msg) { msg.textContent = n ? `已删除标签，并已从 ${n} 条中解除关联` : "已删除标签（无关联条目）"; msg.className = "form-msg ok"; }
     await loadKindsAndTags();
     renderTagManager();
     await loadEvolutionTable();
    } catch (e) {
     if (msg) { msg.textContent = e.message || String(e); msg.className = "form-msg error"; }
    }
   });
  });
 }

 function bindEvolutionTable() {
  if (!$("evoPersonaSection")) return;
  if (_boundEvo) {
   loadKindsAndTags().then(() => loadEvolutionTable());
   return;
  }
  _boundEvo = true;
  loadKindsAndTags().then(() => loadEvolutionTable());
  ["evoScope", "evoKindFilter", "evoTagFilter", "evoSourceFilter"].forEach((id) => {
   $(id)?.addEventListener("change", () => { evoState.page = 1; loadEvolutionTable(); });
  });
  let timer = null;
  $("evoSearch")?.addEventListener("input", () => {
   clearTimeout(timer);
   timer = setTimeout(() => { evoState.page = 1; loadEvolutionTable(); }, 200);
  });
  $("btnRefreshEvolution")?.addEventListener("click", () => loadEvolutionTable());
  $("btnEvoAddEntry")?.addEventListener("click", () => openEntryEditor(null));
  $("btnEvoCancelEntry")?.addEventListener("click", () => { if ($("evoEditor")) $("evoEditor").hidden = true; });
  $("btnEvoSaveEntry")?.addEventListener("click", saveEntry);
  $("btnEvoManageTags")?.addEventListener("click", () => {
   if ($("evoTagMgr")) $("evoTagMgr").hidden = false;
   renderTagManager();
  });
  $("btnEvoCloseTags")?.addEventListener("click", () => { if ($("evoTagMgr")) $("evoTagMgr").hidden = true; });
  $("btnEvoAddTag")?.addEventListener("click", async () => {
   const name = $("evoNewTagName")?.value || "";
   const msg = $("msgEvoTags");
   try {
    await api("/api/evolution/tags", { method: "POST", body: { name } });
    if ($("evoNewTagName")) $("evoNewTagName").value = "";
    if (msg) { msg.textContent = "已新建标签"; msg.className = "form-msg ok"; }
    await loadKindsAndTags();
    renderTagManager();
   } catch (e) {
    if (msg) { msg.textContent = e.message || String(e); msg.className = "form-msg error"; }
   }
  });
 }

 function initSessionPersona() {
  bindSessionPersonaUi();
  bindEvolutionTable();
 }

 L.openSessionPersona = openSessionPersona;
 L.loadEvolutionTable = loadEvolutionTable;
 L.initSessionPersona = initSessionPersona;
 L.fillSessionIdentityForm = fillSessionIdentityForm;

 if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initSessionPersona);
 } else {
  initSessionPersona();
 }
})(window.Lily);
