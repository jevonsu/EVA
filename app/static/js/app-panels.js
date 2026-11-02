/**
 * Lily - Panels (Tasks + Memory)
 */
((L) => {
 "use strict";
 const {
   $,
   els,
   state,
   showToast,
   debounce,
   timeAgo,
   renderSkeleton,
   escapeHtml,
   setMsg,
   formatSchedule,
   formatTime,
   api,
 } = L;
 const _ipk = (n, c) => (typeof L.ipk === "function" ? L.ipk(n, c) : "");
 const _ipkLabel = (n, t, c) =>
   typeof L.ipkLabel === "function" ? L.ipkLabel(n, t, c) : t || "";

 // ==================== Tasks（优先 /api/tasks，回落 static JSON） ====================
 function normalizeTask(st) {
 // API TaskInfo 或 static scheduled_tasks.json 统一成卡片模型
 let schedDesc = null;
 let cron = st.cron;
 let interval_seconds = st.interval_seconds ?? null;
 let prompt = st.prompt || st.notes || "";

 if (cron !== null && typeof cron === "object") {
 schedDesc = cron.description || null;
 if (cron.type === "interval" || st.task_type === "interval") {
 const mins = cron.interval_minutes || 360;
 interval_seconds = mins * 60;
 }
 cron = cron.raw || cron.cron || "";
 }
 if (st.task_type === "interval" && !interval_seconds) {
 interval_seconds = (st.cron?.interval_minutes || 360) * 60;
 }

 const meta = st.metadata || {};
 const t = {
 id: st.id,
 name: st.name,
 _schedule_desc: schedDesc,
 cron: typeof cron === "string" ? cron : st.cron_expr || "",
 interval_seconds,
 run_once: !!st.run_once,
 enabled: st.enabled !== false && st.status !== "cancelled",
 status: st.status || (st.enabled === false ? "disabled" : "active"),
 last_run_at: st.last_run_at,
 last_result: st.last_result || "",
 last_error: st.last_error || "",
 prompt,
 session_id: st.session_id || null,
 last_session_id: meta.last_session_id || st.last_session_id || st.session_id || null,
 always_new_session: !!meta.always_new_session,
 _source: st._source || "api",
 };
 return t;
 }

 function renderTaskCard(t) {
 const card = document.createElement("div");
 card.className = "card task-card";
 const enabled = t.enabled !== false;
 const status = t.status || "—";
 const err = t.last_error ? String(t.last_error) : "";
 const fullResult = t.last_result ? String(t.last_result) : "";
 const resultPreview = fullResult
 ? fullResult.slice(0, 220) + (fullResult.length > 220 ? "…" : "")
 : "";
 const sourceTag =
   t._source === "static"
     ? ` <span class="pill" style="background:#fde68a">${_ipkLabel("page", "静态", "ipk-xs")}</span>`
     : ` <span class="pill" style="background:#e8d5f5">${_ipkLabel("lightning", "运行时", "ipk-xs")}</span>`;
 const desc = t.description || t.prompt || "";
 const replySid = t.last_session_id || t.session_id;
 let replyLabel = "回复：自动（首次执行后固定）";
 if (t.always_new_session) replyLabel = "回复：每次新建对话";
 else if (t.session_id) {
 const row = findSessionRow(_sessionListCache.rows, t.session_id);
 replyLabel = row
 ? "回复对话：" + sessionDisplayName(row)
 : "回复：已指定对话";
 }

 card.innerHTML = `
 <div class="card-body task-body">
 <div class="card-title">${escapeHtml(t.name || t.id || "未命名")}${sourceTag}</div>
 <div class="task-badges">
 <span class="pill">${escapeHtml(formatSchedule(t))}</span>
 <span class="pill ${enabled ? "pill-on" : ""}">${enabled ? _ipkLabel("check-one", "启用", "ipk-xs") : _ipkLabel("forbid", "停用", "ipk-xs")}</span>
 <span class="pill">${escapeHtml(String(status))}</span>
 </div>
 <div class="card-sub">${escapeHtml(replyLabel)}</div>
 <div class="card-sub">上次执行：${escapeHtml(formatTime(t.last_run_at))}</div>
 ${
 resultPreview
 ? `<details class="task-details"><summary>上次结果预览</summary><pre class="task-pre"></pre></details>` : ""}
 <div class="card-sub">${escapeHtml(desc.slice(0, 160))}${desc.length > 160 ? "…" : ""}</div>

 ${err ? `<div class="card-sub task-err">${escapeHtml(err.slice(0, 200))}</div>` : ""}
 ${t.prompt ? `<details class="task-details"><summary>任务 Prompt</summary><pre class="task-pre prompt-pre"></pre></details>` : ""}
 </div>
 <div class="card-actions task-actions">
 ${
 replySid
 ? `<button type="button" class="btn btn-open-task-chat icon-inline" title="打开回复对话">${_ipk(
 "message",
 "ipk-xs"
 )} 打开对话</button>`
 : ""
 }
 <button type="button" class="btn btn-edit-task icon-inline" ${!t.id || t._source === "static" ? "disabled" : ""} title="编辑任务配置">${_ipk("edit", "ipk-xs")} 编辑</button>
 <button type="button" class="btn primary btn-run-task icon-inline" ${t._source === "static" && !t.id ? "disabled" : ""}>${_ipk("play-one", "ipk-xs")} 立即跑</button>
 <button type="button" class="btn danger btn-del-task icon-inline" ${!t.id ? "disabled" : ""} title="删除">${_ipk("delete", "ipk-xs")}</button>
 </div>`;
 if (resultPreview) {
 card.querySelector(".task-pre").textContent = fullResult;
 }
 if (err) {
 card.querySelector(".task-err").textContent = "错误: " + err;
 }
 if (t.prompt) {
 card.querySelector(".prompt-pre").textContent = t.prompt;
 }
 const editBtn = card.querySelector(".btn-edit-task");
 if (editBtn && !editBtn.disabled) {
 editBtn.addEventListener("click", () => openTaskEditor(t));
 }
 const runBtn = card.querySelector(".btn-run-task");
 if (runBtn && !runBtn.disabled) {
 runBtn.addEventListener("click", () => runTask(t.id, t.name));
 }
 const delBtn = card.querySelector(".btn-del-task");
 if (delBtn && !delBtn.disabled) {
 delBtn.addEventListener("click", () => deleteTask(t.id, t.name));
 }
 const openBtn = card.querySelector(".btn-open-task-chat");
 if (openBtn && replySid) {
 openBtn.addEventListener("click", () => {
 if (typeof L.openSession === "function") {
 L.openSession(replySid, t.name || "任务对话");
 showToast("已打开任务回复对话", "success");
 } else {
 showToast("无法打开对话", "error");
 }
 });
 }
 return card;
 }

 async function loadTasks(opts = {}) {
 const soft = !!(opts && opts.soft);
 // 配置弹窗 HTML 异步注入后才有按钮，必须在此绑定
 bindTaskFormUi();
 const list = $("taskList");
 if (!list) return;
 const keepUi = soft && list.querySelector(".card");
 if (!keepUi) {
  list.innerHTML = "";
  renderSkeleton(list, 4);
  setMsg("msgTasks", "载入中…");
 }
 try {
 await fetchSessionList(false);
 let tasks = [];
 let source = "api";
 try {
 const apiRows = await api("/api/tasks");
 tasks = (Array.isArray(apiRows) ? apiRows : []).map((t) =>
 normalizeTask({ ...t, _source: "api" })
 );
 } catch (_) {
 source = "static";
 const resp = await fetch("/static/scheduled_tasks.json");
 if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
 const schedList = await resp.json();
 tasks = (Array.isArray(schedList) ? schedList : []).map((t) =>
 normalizeTask({ ...t, _source: "static" })
 );
 }

 list.innerHTML = "";
 if (!tasks.length) {
 list.innerHTML =
 '<div class="card"><div class="card-body"><div class="card-sub">暂无任务</div></div></div>';
 setMsg("msgTasks", "0 条", "ok");
 return;
 }
 for (const t of tasks) {
 list.appendChild(renderTaskCard(t));
 }
 setMsg(
 "msgTasks",
 `共 ${tasks.length} 条任务（${source === "api" ? "运行时" : "静态回落"}）`,
 "ok"
 );
 } catch (e) {
 list.innerHTML = `<div class="card"><div class="card-body"><div class="card-sub">${escapeHtml(e.message)}</div></div></div>`;
 setMsg("msgTasks", e.message, "error");
 showToast("加载任务失败", "error");
 }
 }

 async function runTask(id, name) {
 if (!id) return;
 if (!confirm(`立即执行「${name || id}」？`)) return;
 setMsg("msgTasks", "执行中…");
 try {
 await api(`/api/tasks/${encodeURIComponent(id)}/run`, { method: "POST" });
 setMsg("msgTasks", "已触发执行，稍后刷新看结果", "ok");
 showToast("任务已触发", "success");
 setTimeout(() => loadTasks(), 1500);
 setTimeout(() => loadTasks(), 4000);
 } catch (e) {
 setMsg("msgTasks", "执行失败: " + e.message, "error");
 showToast("执行失败: " + e.message, "error");
 }
 }

 async function deleteTask(id, name) {
 if (!id) return;
 if (!confirm(`删除任务「${name || id}」？此操作不可恢复。`)) return;
 try {
 await api(`/api/tasks/${encodeURIComponent(id)}`, { method: "DELETE" });
 setMsg("msgTasks", "已删除", "ok");
 showToast("任务已删除", "success");
 loadTasks();
 } catch (e) {
 setMsg("msgTasks", e.message, "error");
 showToast("删除失败", "error");
 }
 }

 // ---- 人性化新建 / 编辑任务表单 ----
 let _taskSchedMode = "interval"; // interval | daily | cron | once
 let _taskSessionMode = "auto"; // auto | current | pick | always_new
 let _taskSessionsCache = [];
 /** @type {string|null} 非空 = 编辑模式 task id */
 let _editTaskId = null;

 const SESSION_SPECIAL = {
   AUTO: "__auto__",
   CURRENT: "__current__",
   NEW: "__new__",
   ALWAYS_NEW: "__always_new__",
 };
 let _sessionListCache = { at: 0, rows: [] };

 function sessionDisplayName(s) {
   if (!s) return "未命名对话";
   const title = String(s.title || "").trim();
   return title || "未命名对话";
 }

 function sessionOptionLabel(s) {
   const title = sessionDisplayName(s);
   const n = s && s.message_count != null ? ` · ${s.message_count} 条` : "";
   return `${title}${n}`;
 }

 function findSessionRow(rows, sid) {
   if (!sid) return null;
   return (
     (rows || []).find((s) => (s.session_id || s.id) === sid) || null
   );
 }

 async function fetchSessionList(force) {
   const now = Date.now();
   if (
     !force &&
     _sessionListCache.rows.length &&
     now - _sessionListCache.at < 4000
   ) {
     return _sessionListCache.rows;
   }
   try {
     const rows = await api("/api/sessions");
     _sessionListCache = {
       at: now,
       rows: Array.isArray(rows) ? rows : [],
     };
     _taskSessionsCache = _sessionListCache.rows;
   } catch (_) {
     if (!_sessionListCache.rows.length) {
       _sessionListCache = { at: 0, rows: [] };
     }
   }
   return _sessionListCache.rows;
 }

 /**
  * Fill a <select> with special options + existing conversations (by title).
  * @param {HTMLSelectElement|null} sel
  * @param {{
  *   special?: Array<{value:string,label:string}>,
  *   selected?: string,
  *   extra?: Array<{value:string,label:string}>,
  *   emptyLabel?: string,
  *   force?: boolean
  * }} [opts]
  */
 async function populateSessionSelect(sel, opts) {
   if (!sel) return [];
   opts = opts || {};
   const rows = await fetchSessionList(!!opts.force);
   const prev = opts.selected != null ? String(opts.selected) : sel.value;
   sel.innerHTML = "";
   for (const sp of opts.special || []) {
     const op = document.createElement("option");
     op.value = sp.value;
     op.textContent = sp.label;
     sel.appendChild(op);
   }
   if (rows.length) {
     if ((opts.special || []).length) {
       const sep = document.createElement("option");
       sep.disabled = true;
       sep.value = "";
       sep.textContent = "—— 已有对话 ——";
       sel.appendChild(sep);
     }
     for (const s of rows) {
       const id = s.session_id || s.id || "";
       if (!id) continue;
       const op = document.createElement("option");
       op.value = id;
       op.textContent = sessionOptionLabel(s);
       sel.appendChild(op);
     }
   } else if (!(opts.special || []).length) {
     const op = document.createElement("option");
     op.value = "";
     op.textContent = opts.emptyLabel || "（还没有对话，先去主界面聊几句）";
     sel.appendChild(op);
   }
   for (const extra of opts.extra || []) {
     if (!extra || !extra.value) continue;
     if (![...sel.options].some((o) => o.value === extra.value)) {
       const op = document.createElement("option");
       op.value = extra.value;
       op.textContent = extra.label || sessionDisplayName({ title: extra.value });
       sel.appendChild(op);
     }
   }
   if (prev && [...sel.options].some((o) => o.value === prev && !o.disabled)) {
     sel.value = prev;
   } else if (
     opts.selected == null &&
     (opts.special || []).length &&
     sel.options.length
   ) {
     sel.selectedIndex = 0;
   }
   return rows;
 }

 function currentSessionSpecialLabel() {
   const cur = (state && state.sessionId) || "";
   if (!cur) return "当前打开的对话（请先在主界面打开一个）";
   const row = findSessionRow(_sessionListCache.rows, cur);
   const name = row ? sessionDisplayName(row) : "当前对话";
   return `当前打开的对话 · ${name}`;
 }

 function taskSessionSpecials() {
   return [
     {
       value: SESSION_SPECIAL.AUTO,
       label: "自动固定（首次新建，之后都发到那里）",
     },
     { value: SESSION_SPECIAL.CURRENT, label: currentSessionSpecialLabel() },
     { value: SESSION_SPECIAL.ALWAYS_NEW, label: "每次执行都新建对话" },
   ];
 }

 function wfSessionSpecials() {
   return [
     {
       value: SESSION_SPECIAL.AUTO,
       label: "自动固定（首次新建，之后都发到那里）",
     },
     { value: SESSION_SPECIAL.CURRENT, label: currentSessionSpecialLabel() },
     { value: SESSION_SPECIAL.ALWAYS_NEW, label: "每次运行都新建对话" },
   ];
 }

 function wfRunSessionSpecials() {
   return [
     {
       value: SESSION_SPECIAL.NEW,
       label: "新建一个对话（本轮所有步骤共用）",
     },
     { value: SESSION_SPECIAL.CURRENT, label: currentSessionSpecialLabel() },
   ];
 }

 function resolveSessionSelectValue(raw) {
   const v = String(raw || "").trim();
   if (!v || v === SESSION_SPECIAL.AUTO) {
     return { session_id: null, always_new_session: false, mode: "auto" };
   }
   if (v === SESSION_SPECIAL.ALWAYS_NEW || v === SESSION_SPECIAL.NEW) {
     return { session_id: null, always_new_session: true, mode: "always_new" };
   }
   if (v === SESSION_SPECIAL.CURRENT) {
     return {
       session_id: (state && state.sessionId) || null,
       always_new_session: false,
       mode: "current",
     };
   }
   return { session_id: v, always_new_session: false, mode: "pick" };
 }

 const TASK_SCHED_OPTS = [
 {
 id: "interval",
 label: "每隔一段时间",
 hint: "适合轮询、巡检",
 },
 {
 id: "daily",
 label: "每天固定时刻",
 hint: "按本地钟点，转成 Cron",
 },
 {
 id: "cron",
 label: "高级 Cron",
 hint: "熟悉表达式时使用",
 },
 {
 id: "once",
 label: "只跑一次",
 hint: "创建后尽快执行一次",
 },
 ];

 /** 「到点让 AI 做什么」常用指令模板 */
 const TASK_PROMPT_TPLS = [
 {
 id: "briefing",
 label: "每日简报",
 name: "每天早报",
 sched: "daily",
 text:
 "请用简洁中文写一份今日简报：\n" +
 "1）需要我关注的待办/风险（若无信息则说明）\n" +
 "2）可用工具时，优先查任务列表与系统健康\n" +
 "3）最后用 3 条以内行动建议收尾\n" +
 "不要编造数据；查不到就明确说查不到。",
 },
 {
 id: "health",
 label: "系统巡检",
 name: "系统健康巡检",
 sched: "interval",
 text:
 "请做一次轻量系统巡检并简洁汇报：\n" +
 "1）后端健康 / 默认 LLM 是否可用\n" +
 "2）工具与技能是否大体正常（无需逐个测）\n" +
 "3）有明显异常则说明原因与建议\n" +
 "回复控制在短段落内。",
 },
 {
 id: "kb_digest",
 label: "知识库摘要",
 name: "知识库要点回顾",
 sched: "daily",
 text:
 "请用 kb list/search 看知识库里实际有哪些页面，用条目列出要点。\n" +
 "库是空的就直接说空，不要编造 SOP 或流程步骤。",
 },
 {
 id: "reminder_msg",
 label: "定点提醒",
 name: "定点提醒",
 sched: "once",
 text:
 "这是一条定时提醒。请直接用简洁中文告诉我：\n" +
 "「提醒：」+ 下面事项（若事项为空则提示我补充）\n" +
 "【提醒事项】\n" +
 "（请把要提醒的内容写在这里）",
 },
 {
 id: "custom_blank",
 label: "空白草稿",
 name: "",
 sched: null,
 text:
 "请按以下要求执行（到点自动运行）：\n" +
 "目标：\n" +
 "步骤：\n" +
 "1. \n" +
 "2. \n" +
 "输出格式：简洁中文，先结论后细节。\n" +
 "约束：不编造；需要工具时再调用。",
 },
 ];

 function renderTaskSchedChips() {
 const host = $("taskSchedChips");
 if (!host) return;
 host.innerHTML = "";
 for (const o of TASK_SCHED_OPTS) {
 const btn = document.createElement("button");
 btn.type = "button";
 btn.className =
 "kb-chip kb-chip-card" + (_taskSchedMode === o.id ? " is-on" : "");
 btn.innerHTML =
 `<span class="kb-chip-name">${escapeHtml(o.label)}</span>` +
 `<span class="kb-chip-desc">${escapeHtml(o.hint)}</span>`;
 btn.addEventListener("click", () => {
 _taskSchedMode = o.id;
 renderTaskSchedChips();
 renderTaskSchedFields();
 });
 host.appendChild(btn);
 }
 }

 function applyTaskPromptTemplate(tpl) {
 if (!tpl) return;
 const ta = $("taskPrompt");
 if (!ta) return;
 const cur = (ta.value || "").trim();
 if (cur && cur !== tpl.text) {
 if (!confirm("当前指令非空。用模板覆盖？")) return;
 }
 ta.value = tpl.text || "";
 // 名称空时顺带填推荐名
 const nameEl = $("taskName");
 if (nameEl && !(nameEl.value || "").trim() && tpl.name) {
 nameEl.value = tpl.name;
 }
 // 按模板推荐调度方式
 if (tpl.sched && TASK_SCHED_OPTS.some((x) => x.id === tpl.sched)) {
 _taskSchedMode = tpl.sched;
 renderTaskSchedChips();
 renderTaskSchedFields();
 }
 ta.focus();
 setMsg("msgTaskEditor", "已填入模板「" + tpl.label + "」，可再修改", "ok");
 }

 function renderTaskPromptTemplates() {
 const host = $("taskPromptTpls");
 if (!host) return;
 host.innerHTML = "";
 for (const tpl of TASK_PROMPT_TPLS) {
 const btn = document.createElement("button");
 btn.type = "button";
 btn.className = "kb-chip task-tpl-chip";
 btn.textContent = tpl.label;
 btn.title = (tpl.text || "").slice(0, 120) + (tpl.text && tpl.text.length > 120 ? "…" : "");
 btn.addEventListener("click", () => applyTaskPromptTemplate(tpl));
 host.appendChild(btn);
 }
 }

 function taskSelectedValueFromMode(mode, sessionId) {
 if (mode === "always_new") return SESSION_SPECIAL.ALWAYS_NEW;
 if (mode === "current") return SESSION_SPECIAL.CURRENT;
 if (mode === "pick" && sessionId) return sessionId;
 return SESSION_SPECIAL.AUTO;
 }

 async function renderTaskSessionSelect(selected) {
 const sel = $("taskSessionSelect");
 const hint = $("taskSessionHint");
 if (!sel) return;
 const extra = [];
 if (
 selected &&
 selected !== SESSION_SPECIAL.AUTO &&
 selected !== SESSION_SPECIAL.CURRENT &&
 selected !== SESSION_SPECIAL.ALWAYS_NEW &&
 selected !== SESSION_SPECIAL.NEW
 ) {
 extra.push({ value: selected, label: "已绑定的对话" });
 }
 await populateSessionSelect(sel, {
 special: taskSessionSpecials(),
 selected: selected || SESSION_SPECIAL.AUTO,
 extra,
 force: true,
 });
 if (hint) {
 hint.textContent =
 "从列表里选一个聊天，不用填 ID。任务跑完后回复会出现在那里。";
 }
 }

 function renderTaskSchedFields() {
 const host = $("taskSchedFields");
 const hint = $("taskSchedHint");
 if (!host) return;
 host.innerHTML = "";
 if (_taskSchedMode === "interval") {
 host.innerHTML = `
 <label class="kb-label">每隔多少分钟
 <input id="taskIntervalMin" class="task-field-input" type="number" min="1" max="10080" value="60" />
 </label>`;
 if (hint) hint.textContent = "例如 60 = 每小时；1440 = 每天一次（从创建时起算）。";
 } else if (_taskSchedMode === "daily") {
 host.innerHTML = `
 <label class="kb-label">每天几点（0–23）
 <input id="taskDailyHour" class="task-field-input" type="number" min="0" max="23" value="9" />
 </label>
 <label class="kb-label">几分（0–59）
 <input id="taskDailyMin" class="task-field-input" type="number" min="0" max="59" value="0" />
 </label>`;
 if (hint)
 hint.textContent =
 "按你电脑本地时区理解时刻；后端以 UTC Cron 存储（会自动换算近似）。";
 } else if (_taskSchedMode === "cron") {
 host.innerHTML = `
 <label class="kb-label full-span">Cron 表达式
 <input id="taskCron" class="task-field-input" type="text" placeholder="0 9 * * *  或  */30 * * * *" />
 </label>`;
 if (hint)
 hint.textContent =
 "格式：分 时 日 月 周。例：0 9 * * * = 每天 9:00（调度器时区 UTC）。";
 } else {
 host.innerHTML =
 '<p class="field-hint full-span" style="margin:0">保存后可在列表点「立即跑」；适合「做完就结束」的临时任务。</p>';
 if (hint) hint.textContent = "一次性任务，创建后可马上点「立即跑」。";
 }
 }

 function getTaskPageModal() {
 return $("taskPageModal") || $("taskEditor");
 }

 /** 将 UTC cron「分 时 * * *」近似还原为本地时分（与 localDailyToUtcCron 对偶） */
 function utcCronToLocalDaily(cron) {
 const parts = String(cron || "")
 .trim()
 .split(/\s+/);
 if (parts.length < 5) return null;
 if (parts[2] !== "*" || parts[3] !== "*" || parts[4] !== "*") return null;
 const utcM = parseInt(parts[0], 10);
 const utcH = parseInt(parts[1], 10);
 if (Number.isNaN(utcM) || Number.isNaN(utcH)) return null;
 const now = new Date();
 const d = new Date(
 Date.UTC(
 now.getUTCFullYear(),
 now.getUTCMonth(),
 now.getUTCDate(),
 utcH,
 utcM,
 0
 )
 );
 return { hour: d.getHours(), minute: d.getMinutes() };
 }

 function inferTaskSchedFromTask(t) {
 if (!t) return { mode: "interval", fields: {} };
 if (t.run_once) return { mode: "once", fields: {} };
 if (t.interval_seconds) {
 const mins = Math.max(
 1,
 Math.round(Number(t.interval_seconds) / 60) || 60
 );
 return { mode: "interval", fields: { minutes: mins } };
 }
 const cron = typeof t.cron === "string" ? t.cron.trim() : "";
 if (cron) {
 const daily = utcCronToLocalDaily(cron);
 if (daily) {
 return {
 mode: "daily",
 fields: { hour: daily.hour, minute: daily.minute, cron },
 };
 }
 return { mode: "cron", fields: { cron } };
 }
 return { mode: "interval", fields: { minutes: 60 } };
 }

 function inferTaskSessionFromTask(t) {
 if (!t) return { mode: "auto", session_id: null };
 if (t.always_new_session) return { mode: "always_new", session_id: null };
 const sid = t.session_id || null;
 if (!sid) return { mode: "auto", session_id: null };
 const cur = (state && state.sessionId) || null;
 if (cur && sid === cur) return { mode: "current", session_id: sid };
 return { mode: "pick", session_id: sid };
 }

 function setTaskEditorChrome(isEdit) {
 const titleEl = $("taskEditorTitle");
 if (titleEl) {
 titleEl.innerHTML = isEdit
 ? '<span data-ipk="edit" data-ipk-class="ipk-sm"></span> 编辑定时任务'
 : '<span data-ipk="alarm-clock" data-ipk-class="ipk-sm"></span> 新建定时任务';
 }
 const lead = document.querySelector("#taskPageModal .kb-editor-lead");
 if (lead) {
 lead.textContent = isEdit
 ? "修改名称、指令、调度或结果对话；运行历史会保留"
 : "用白话填写：叫什么、多久跑、到点让 AI 做什么";
 }
 const enLabel = document.querySelector(
 ".task-enabled-line"
 );
 if (enLabel) {
 const textNode = Array.from(enLabel.childNodes).find(
 (n) => n.nodeType === 3 && n.textContent.trim()
 );
 // checkbox + text; rewrite trailing text via last text content
 // safer: set whole label after checkbox
 const cb = $("taskEnabled");
 if (cb && enLabel.contains(cb)) {
 enLabel.innerHTML = "";
 enLabel.appendChild(cb);
 enLabel.appendChild(
 document.createTextNode(
 isEdit ? " 启用此任务" : " 创建后立即启用"
 )
 );
 }
 }
 const saveBtn = $("btnSaveTask");
 if (saveBtn) {
 saveBtn.innerHTML = isEdit
 ? '<span data-ipk="save" data-ipk-class="ipk-xs"></span> 保存修改'
 : '<span data-ipk="save" data-ipk-class="ipk-xs"></span> 保存任务';
 }
 }

 /**
 * 打开任务编辑器。
 * @param {object|null} [task] 传入 normalizeTask 结果则进入编辑；省略/空=新建
 */
 async function openTaskEditor(task) {
 bindTaskFormUi();
 const modal = getTaskPageModal();
 if (!modal) {
 setMsg("msgTasks", "任务表单未加载，请关闭设定后重开，或刷新页面", "error");
 showToast("任务表单未就绪，请刷新页面", "error");
 return;
 }
 const isEdit = !!(task && task.id);
 _editTaskId = isEdit ? String(task.id) : null;

 if (isEdit) {
 if ($("taskName")) $("taskName").value = task.name || "";
 if ($("taskPrompt")) $("taskPrompt").value = task.prompt || "";
 if ($("taskEnabled")) $("taskEnabled").checked = task.enabled !== false;
 const sched = inferTaskSchedFromTask(task);
 _taskSchedMode = sched.mode;
 const sess = inferTaskSessionFromTask(task);
 _taskSessionMode = sess.mode;
 renderTaskSchedChips();
 renderTaskSchedFields();
 renderTaskPromptTemplates();
 await renderTaskSessionSelect(
 taskSelectedValueFromMode(sess.mode, sess.session_id)
 );
 // fill schedule field values after render
 if (_taskSchedMode === "interval") {
 const el = $("taskIntervalMin");
 if (el) el.value = String(sched.fields.minutes || 60);
 } else if (_taskSchedMode === "daily") {
 const hEl = $("taskDailyHour");
 const mEl = $("taskDailyMin");
 if (hEl) hEl.value = String(sched.fields.hour ?? 9);
 if (mEl) mEl.value = String(sched.fields.minute ?? 0);
 } else if (_taskSchedMode === "cron") {
 const el = $("taskCron");
 if (el) el.value = sched.fields.cron || task.cron || "";
 }
 } else {
 if ($("taskName")) $("taskName").value = "";
 if ($("taskPrompt")) $("taskPrompt").value = "";
 if ($("taskEnabled")) $("taskEnabled").checked = true;
 _taskSchedMode = "interval";
 _taskSessionMode = "auto";
 renderTaskSchedChips();
 renderTaskSchedFields();
 renderTaskPromptTemplates();
 await renderTaskSessionSelect(SESSION_SPECIAL.AUTO);
 }

 setTaskEditorChrome(isEdit);
 setMsg("msgTaskEditor", isEdit ? "正在编辑已有任务" : "");
 modal.classList.remove("hidden");
 document.body.classList.add("task-page-modal-open");
 if (typeof L.hydrateIconPark === "function") L.hydrateIconPark(modal);
 requestAnimationFrame(() => $("taskName")?.focus());
 }

 function closeTaskEditor() {
 const modal = getTaskPageModal();
 if (modal) modal.classList.add("hidden");
 document.body.classList.remove("task-page-modal-open");
 _editTaskId = null;
 setMsg("msgTaskEditor", "");
 }

 function localDailyToUtcCron(hour, minute) {
 // Approximate: convert local wall clock to UTC cron hour/min
 const now = new Date();
 const local = new Date(
 now.getFullYear(),
 now.getMonth(),
 now.getDate(),
 hour,
 minute,
 0,
 0
 );
 const utcH = local.getUTCHours();
 const utcM = local.getUTCMinutes();
 return `${utcM} ${utcH} * * *`;
 }

 async function saveTaskFromForm() {
 const name = ($("taskName")?.value || "").trim();
 const prompt = ($("taskPrompt")?.value || "").trim();
 if (!name) {
 setMsg("msgTaskEditor", "请填写任务名称", "error");
 return;
 }
 if (!prompt) {
 setMsg("msgTaskEditor", "请填写「到点让 AI 做什么」", "error");
 return;
 }
 const body = {
 name,
 prompt,
 enabled: !!$("taskEnabled")?.checked,
 run_once: false,
 cron: null,
 interval_seconds: null,
 session_id: null,
 metadata: {},
 };
 // 结果发到哪个对话（下拉，不用填 ID）
 const picked = resolveSessionSelectValue($("taskSessionSelect")?.value);
 _taskSessionMode = picked.mode;
 if (picked.mode === "always_new") {
 body.metadata.always_new_session = true;
 body.session_id = null;
 } else if (picked.mode === "current") {
 if (!picked.session_id) {
 setMsg("msgTaskEditor", "请先在主界面打开一个对话，或改选其它对话", "error");
 return;
 }
 body.session_id = picked.session_id;
 } else if (picked.mode === "pick") {
 if (!picked.session_id) {
 setMsg("msgTaskEditor", "请选择要接收结果的对话", "error");
 return;
 }
 body.session_id = picked.session_id;
 } else {
 body.session_id = null;
 }
 const editingId = _editTaskId;
 try {
 if (_taskSchedMode === "interval") {
 const mins = parseInt($("taskIntervalMin")?.value, 10) || 60;
 body.interval_seconds = Math.max(60, mins * 60);
 } else if (_taskSchedMode === "daily") {
 const h = Math.min(23, Math.max(0, parseInt($("taskDailyHour")?.value, 10) || 9));
 const m = Math.min(59, Math.max(0, parseInt($("taskDailyMin")?.value, 10) || 0));
 body.cron = localDailyToUtcCron(h, m);
 } else if (_taskSchedMode === "cron") {
 const c = ($("taskCron")?.value || "").trim();
 if (!c) {
 setMsg("msgTaskEditor", "请填写 Cron 表达式", "error");
 return;
 }
 body.cron = c;
 } else {
 body.run_once = true;
 }
 if (editingId) {
 await api(`/api/tasks/${encodeURIComponent(editingId)}`, {
 method: "PUT",
 body: JSON.stringify(body),
 });
 setMsg("msgTasks", "任务已更新", "ok");
 setMsg("msgTaskEditor", "已保存修改", "ok");
 showToast("定时任务已更新", "success");
 } else {
 await api("/api/tasks", { method: "POST", body: JSON.stringify(body) });
 setMsg("msgTasks", "任务已创建", "ok");
 setMsg("msgTaskEditor", "已创建", "ok");
 showToast("定时任务已创建", "success");
 }
 closeTaskEditor();
 loadTasks();
 } catch (e) {
 setMsg("msgTaskEditor", e.message, "error");
 showToast(editingId ? "保存失败" : "创建失败", "error");
 }
 }

 function bindTaskFormUi() {
 // 仅依赖事件委托即可；保留函数供 loadTasks / 注入后调用
 if (bindTaskFormUi._bound) return;
 if (!$("btnNewTask") && !$("taskPageModal") && !$("btnSaveTask")) return;
 bindTaskFormUi._bound = true;
 // 遮罩点击关闭
 $("taskPageModal")?.addEventListener("click", (e) => {
 if (e.target === $("taskPageModal")) closeTaskEditor();
 });
 }

 // 全局事件委托（设定 HTML 同步/异步注入都有效）
 if (!window.__lilyTaskFormDelegate) {
 window.__lilyTaskFormDelegate = true;
 document.addEventListener(
 "click",
 (e) => {
 const t = e.target;
 if (!(t instanceof Element)) return;
 if (t.closest("#btnNewTask")) {
 e.preventDefault();
 e.stopPropagation();
 openTaskEditor();
 return;
 }
 if (t.closest("#btnSaveTask")) {
 e.preventDefault();
 e.stopPropagation();
 saveTaskFromForm();
 return;
 }
 if (t.closest("#btnCancelTask") || t.closest("#btnCloseTaskPage")) {
 e.preventDefault();
 e.stopPropagation();
 closeTaskEditor();
 return;
 }
 if (t.closest("#btnRefreshTaskSessions")) {
 e.preventDefault();
 e.stopPropagation();
 renderTaskSessionSelect($("taskSessionSelect")?.value);
 }
 },
 true
 );
 }
 bindTaskFormUi();

 // ==================== Memory（含骨架屏 + 防抖搜索） ====================
 /** @type {string|null} 非空 = 编辑模式 memory id */
 let _editMemoryId = null;

 const MEM_KIND_META = {
 preference: {
 label: "偏好",
 hint: "适合：口味、风格、默认参数、沟通习惯。对话相关时会优先被检索到。",
 example:
 "例：做 PPT 时默认 16:9 横版、中文标题、简洁风格。",
 chips: ["风格", "沟通", "默认参数"],
 },
 fact: {
 label: "事实",
 hint: "适合：客观信息，如项目路径、资料目录、常用账号所在位置（不要写密码）。",
 example: "例：设计稿在 workspace/design 目录。",
 chips: ["项目", "路径"],
 },
 template: {
 label: "模板",
 hint: "适合：固定流程、检查清单、提示词骨架，方便以后按步骤做。",
 example: "例：服装配图流程：先确认产品信息 → 平台 → 出 4 张提示词…",
 chips: ["流程", "模板", "提示词"],
 },
 habit: {
 label: "习惯",
 hint: "适合：每次/总是要做的事（比偏好更固定一点）。",
 example: "例：每次生成视频前先确认时长和画幅。",
 chips: ["每次", "习惯"],
 },
 rule: {
 label: "规则",
 hint: "适合：必须遵守的硬规则。可勾选「始终生效」，条目请尽量少、写清楚。",
 example: "例：查不到就说查不到，不要编造产品参数。",
 chips: ["always", "原则", "安全"],
 },
 note: {
 label: "笔记",
 hint: "一般备忘，检索优先级低于偏好/规则。",
 example: "例：下周要整理宜家玻璃杯素材。",
 chips: ["备忘", "待办"],
 },
 };

 function memKindLabel(kind) {
 const k = (kind || "note").toLowerCase();
 return (MEM_KIND_META[k] && MEM_KIND_META[k].label) || kind || "笔记";
 }

 function parseMemTags(raw) {
 return String(raw || "")
 .split(/[,，、\s]+/)
 .map((s) => s.trim())
 .filter(Boolean);
 }

 function setMemTags(list) {
 const input = $("memTags");
 if (!input) return;
 // unique preserve order
 const seen = new Set();
 const out = [];
 for (const t of list) {
 const x = String(t).trim();
 if (!x || seen.has(x.toLowerCase())) continue;
 seen.add(x.toLowerCase());
 out.push(x);
 }
 input.value = out.join(", ");
 }

 function toggleMemTag(tag) {
 const cur = parseMemTags($("memTags")?.value || "");
 const lower = tag.toLowerCase();
 const has = cur.some((t) => t.toLowerCase() === lower);
 const next = has
 ? cur.filter((t) => t.toLowerCase() !== lower)
 : cur.concat([tag]);
 setMemTags(next);
 syncMemChips();
 }

 function syncMemChips() {
 const host = $("memTagChips");
 if (!host) return;
 const kind = ($("memKind")?.value || "preference").toLowerCase();
 const meta = MEM_KIND_META[kind] || MEM_KIND_META.note;
 const selected = new Set(
 parseMemTags($("memTags")?.value || "").map((t) => t.toLowerCase())
 );
 const chips = meta.chips || [];
 host.innerHTML = chips
 .map((c) => {
 const on = selected.has(String(c).toLowerCase());
 return (
 '<button type="button" class="mem-chip' +
 (on ? " is-on" : "") +
 '" data-tag="' +
 escapeHtml(c) +
 '">' +
 escapeHtml(c) +
 "</button>"
 );
 })
 .join("");
 host.querySelectorAll(".mem-chip").forEach((btn) => {
 btn.addEventListener("click", () =>
 toggleMemTag(btn.getAttribute("data-tag") || "")
 );
 });
 }

 function updateMemFormHints() {
 const kind = ($("memKind")?.value || "preference").toLowerCase();
 const meta = MEM_KIND_META[kind] || MEM_KIND_META.note;
 const kindHint = $("memKindHint");
 const contentHint = $("memContentHint");
 const examples = $("memExamples");
 if (kindHint) kindHint.textContent = meta.hint || "";
 if (contentHint) contentHint.textContent = "写完整句子（场景 + 要求），匹配更准。";
 if (examples) {
 const ex = (meta.example || "").replace(/^例[：:]/, "").trim();
 examples.textContent = ex ? "示例：" + ex : "";
 examples.hidden = !ex;
 }
 const ta = $("memContent");
 if (ta && !String(ta.value || "").trim()) {
 const ph = (meta.example || "").replace(/^例[：:]/, "").trim();
 if (ph) ta.placeholder = ph;
 }
 syncMemChips();
 }

 function bindMemoryDelegatedUi() {
 // 设定 HTML 异步注入：按钮必须委托到 document，不能在脚本执行时绑空。
 if (bindMemoryDelegatedUi._done) return;
 bindMemoryDelegatedUi._done = true;
 document.addEventListener("click", (e) => {
  const t = e.target;
  if (!(t instanceof Element)) return;
  if (t.id === "memoryAddModal") {
   closeMemoryAddModal();
   return;
  }
  if (t.closest("#btnOpenMemAdd")) {
   e.preventDefault();
   openMemoryAddModal();
   return;
  }
  if (t.closest("#btnCloseMemAdd") || t.closest("#btnCancelMemAdd")) {
   e.preventDefault();
   closeMemoryAddModal();
  }
 });
 }

 function initMemoryForm() {
 bindMemoryDelegatedUi();
 if (initMemoryForm._fields) return;
 const kindEl = $("memKind");
 const tagsEl = $("memTags");
 if (!kindEl && !tagsEl) return;
 initMemoryForm._fields = true;
 kindEl?.addEventListener("change", updateMemFormHints);
 tagsEl?.addEventListener("input", debounce(syncMemChips, 120));
 updateMemFormHints();
 }
 bindMemoryDelegatedUi();

 async function loadMemory(q = "", opts = {}) {
 // 兼容 loadMemory({ soft: true })
 if (q && typeof q === "object" && !Array.isArray(q)) {
  opts = q;
  q = $("memSearch")?.value || "";
 }
 const soft = !!(opts && opts.soft);
 initMemoryForm();
 const list = $("memoryList");
 if (!list) return;
 const keepUi = soft && list.querySelector(".card");
 if (!keepUi) {
  list.innerHTML = "";
  renderSkeleton(list, 3);
  setMsg("msgMemory", "载入中…");
 }
 try {
 let rows;
 const query = (q || "").trim();
 if (query) {
 rows = await api(`/api/memory/search?q=${encodeURIComponent(query)}&limit=50`);
 } else {
 rows = await api("/api/memory?limit=100");
 }
 const items = Array.isArray(rows) ? rows : rows.items || rows.memories || [];
 list.innerHTML = "";
 if (!items.length) {
 list.innerHTML =
 '<div class="card"><div class="card-body"><div class="card-sub">暂无正式记忆。点「暂存草稿」写入候选，或到「评审」处理待审项。</div></div></div>';
 setMsg("msgMemory", "0 条", "ok");
 return;
 }
 for (const m of items) {
 const card = document.createElement("div");
 card.className = "card mem-card";
 const kind = (m.kind || "note").toLowerCase();
 const kindText = memKindLabel(kind);
 const tagsArr = Array.isArray(m.tags) ? m.tags : [];
 const tags = tagsArr.length ? tagsArr.join(" · ") : "";
 const always =
 tagsArr.some((t) => /^(always|全局|pin)$/i.test(String(t))) ||
 kind === "rule";
 card.innerHTML = `
 <div class="card-body">
 <div class="card-title">
 <span class="mem-kind-pill kind-${escapeHtml(kind)}">${escapeHtml(kindText)}</span>
 ${always ? '<span class="mem-kind-pill kind-rule">始终</span>' : ""}
 ${tags ? `<span class="card-sub" style="display:inline">${escapeHtml(tags)}</span>` : ""}
 </div>
 <div class="mem-content"></div>
 <div class="card-sub">${escapeHtml(formatTime(m.created_at))}</div>
 </div>
 <div class="card-actions">
 <button type="button" class="btn btn-edit-mem icon-inline" title="编辑记忆" ${!m.id ? "disabled" : ""}>${_ipk("edit","ipk-sm")} 编辑</button>
 <button type="button" class="btn danger btn-del-mem" title="删除">${_ipk("delete","ipk-sm")}</button>
 </div>`;
 card.querySelector(".mem-content").textContent = m.content || m.text || "";
 const editBtn = card.querySelector(".btn-edit-mem");
 if (editBtn && !editBtn.disabled) {
 editBtn.addEventListener("click", () => openMemoryAddModal(m));
 }
 card.querySelector(".btn-del-mem").addEventListener("click", () => deleteMemory(m.id));
 list.appendChild(card);
 }
 setMsg("msgMemory", `共 ${items.length} 条（对话时按匹配注入，非整库）`, "ok");
 } catch (e) {
 list.innerHTML = `<div class="card"><div class="card-body"><div class="card-sub">${escapeHtml(e.message)}</div></div></div>`;
 setMsg("msgMemory", e.message, "error");
 showToast("加载记忆失败", "error");
 }
 }

 async function deleteMemory(id) {
 if (!id) return;
 if (!confirm("删除这条记忆？")) return;
 try {
 await api(`/api/memory/${encodeURIComponent(id)}`, { method: "DELETE" });
 setMsg("msgMemory", "已删除", "ok");
 showToast("记忆已删除", "success");
 await loadMemory($("memSearch")?.value || "");
 } catch (e) {
 setMsg("msgMemory", e.message, "error");
 showToast("删除失败", "error");
 }
 }

 function setMemoryEditorChrome(isEdit) {
 const titleEl = $("memAddTitle");
 if (titleEl) {
 titleEl.innerHTML = isEdit
 ? '<span data-ipk="edit" data-ipk-class="ipk-sm"></span> 编辑记忆'
 : '<span data-ipk="brain" data-ipk-class="ipk-sm"></span> 新增记忆';
 }
 const lead = $("memAddLead");
 if (lead) {
 lead.textContent = isEdit
 ? "修改内容、类型或标签；创建时间保持不变。"
 : "内容写完整一句话（场景 + 要求）；类型说明用途；标签方便以后搜到。列表卡片可点「编辑」修改。";
 }
 const saveBtn = $("btnAddMemory");
 if (saveBtn) {
 saveBtn.innerHTML = isEdit
 ? '<span data-ipk="save" data-ipk-class="ipk-xs"></span> 保存修改'
 : '<span data-ipk="save" data-ipk-class="ipk-xs"></span> 保存';
 }
 }

 function resetMemoryForm() {
 if ($("memContent")) $("memContent").value = "";
 if ($("memTags")) $("memTags").value = "";
 if ($("memAlways")) $("memAlways").checked = false;
 if ($("memKind")) $("memKind").value = "preference";
 updateMemFormHints();
 }

 function fillMemoryForm(m) {
 if (!m) {
 resetMemoryForm();
 return;
 }
 if ($("memContent")) $("memContent").value = m.content || m.text || "";
 const kind = (m.kind || "preference").toLowerCase();
 if ($("memKind")) {
 const sel = $("memKind");
 const ok = [...sel.options].some((o) => o.value === kind);
 sel.value = ok ? kind : "note";
 }
 const tagsArr = Array.isArray(m.tags) ? m.tags.slice() : [];
 const always = tagsArr.some((t) =>
 /^(always|全局|pin|始终|永久规则|standing)$/i.test(String(t))
 );
 // strip pin tags from input display when checkbox covers them
 const displayTags = tagsArr.filter(
 (t) => !/^(always|全局|pin|始终|永久规则|standing)$/i.test(String(t))
 );
 setMemTags(displayTags);
 if ($("memAlways")) $("memAlways").checked = always;
 updateMemFormHints();
 }

 /**
 * 打开记忆表单。
 * @param {object|null} [memory] 传入列表项则进入编辑；省略=新增
 */
 function openMemoryAddModal(memory) {
 initMemoryForm();
 const isEdit = !!(memory && memory.id);
 _editMemoryId = isEdit ? String(memory.id) : null;
 if (isEdit) fillMemoryForm(memory);
 else resetMemoryForm();
 setMemoryEditorChrome(isEdit);
 if (typeof L.openNestedEditor === "function") {
 L.openNestedEditor("memoryAddModal");
 } else {
 $("memoryAddModal")?.classList.remove("hidden");
 document.body.classList.add("cfg-nested-open");
 }
 if (typeof L.hydrateIconPark === "function")
 L.hydrateIconPark($("memoryAddModal"));
 requestAnimationFrame(() => $("memContent")?.focus());
 }

 function closeMemoryAddModal() {
 _editMemoryId = null;
 if (typeof L.closeNestedEditor === "function") {
 L.closeNestedEditor("memoryAddModal");
 } else {
 $("memoryAddModal")?.classList.add("hidden");
 }
 }

 async function addMemory() {
 initMemoryForm();
 const content = ($("memContent")?.value || "").trim();
 if (!content) {
 setMsg("msgMemory", "请填写内容（完整一句话）", "error");
 showToast("请填写记忆内容", "error");
 return;
 }
 if (content.length < 6) {
 setMsg("msgMemory", "内容太短，请写完整场景与要求", "error");
 showToast("内容太短，请写完整一点", "error");
 return;
 }
 let kind = ($("memKind")?.value || "preference").trim() || "preference";
 let tags = parseMemTags($("memTags")?.value || "");
 const always = !!$("memAlways")?.checked;
 if (always) {
 if (!tags.some((t) => /^(always|全局|pin)$/i.test(t))) tags.push("always");
 if (kind === "note" || kind === "preference") {
 // 始终生效更适合 rule
 kind = "rule";
 }
 } else {
 // 编辑时取消「始终生效」要去掉 pin 类标签
 tags = tags.filter(
 (t) => !/^(always|全局|pin|始终|永久规则|standing)$/i.test(String(t))
 );
 }
 // 密钥/密码粗检
 if (/(sk-|api[_-]?key\s*[:=]|password\s*[:=]|Bearer\s+ey)/i.test(content)) {
 if (
 !confirm(
 "内容里可能含密钥/Token。建议写到配置 integrations，不要进记忆。仍要保存吗？"
 )
 ) {
 return;
 }
 }
 const editingId = _editMemoryId;
 try {
 if (editingId) {
 await api(`/api/memory/${encodeURIComponent(editingId)}`, {
 method: "PUT",
 body: JSON.stringify({ content, kind, tags }),
 });
 setMsg("msgMemory", "已更新", "ok");
 showToast("记忆已更新", "success");
 } else {
 await api("/api/memory", {
 method: "POST",
 body: JSON.stringify({ content, kind, tags }),
 });
 setMsg("msgMemory", "已写入暂存，请到「评审」批准", "ok");
 showToast("已写入暂存（需评审批准）", "success");
 }
 resetMemoryForm();
 closeMemoryAddModal();
 await loadMemory($("memSearch")?.value || "");
 } catch (e) {
 setMsg("msgMemory", e.message, "error");
 showToast(
 (editingId ? "保存失败: " : "新增失败: ") + e.message,
 "error"
 );
 }
 }


 // ==================== Knowledge Base Wiki ====================
 let _kbEditingId = "";
 let _kbCollectionOptions = [
 "default",
 "sop",
 "product",
 "handbook",
 "daily",
 "reference",
 ];

 const KB_COLL_META = {
 sop: { label: "SOP 流程", hint: "标准作业、操作步骤、输出格式" },
 product: { label: "产品参数", hint: "规格、清单、事实（勿写流程）" },
 handbook: { label: "手册红线", hint: "合规、错误处理、禁止事项" },
 reference: { label: "参考模板", hint: "提示词、话术、示例" },
 daily: { label: "日常纪要", hint: "临时说明，用完可归档" },
 default: { label: "未分类", hint: "暂未分区时使用" },
 };

 const KB_TAG_SUGGEST = {
 sop: ["步骤", "检查清单", "标准"],
 product: ["参数", "规格", "清单"],
 handbook: ["红线", "合规", "禁止"],
 reference: ["提示词", "模板", "示例"],
 daily: ["临时", "纪要"],
 default: ["备忘"],
 };

 const KB_CONTENT_TPL = {
 sop: `# 标题（SOP）

## 目标
一句话说明本流程解决什么问题。

## 触发条件
- 何时启动本 SOP

## 步骤
1. …
2. …
3. …

## 输出格式
\`\`\`
（用户可见结构）
\`\`\`

## 规则 / 禁止
- …
`,
 product: `# 产品名称

## 基本信息
- 品类：
- 规格：
- 材质/颜色：

## 要点
- …

## 注意事项
- 勿与竞品/未证实数据混写
`,
 handbook: `# 手册 / 红线

## 必须遵守
- …

## 禁止
- …

## 异常处理
- …
`,
 reference: `# 参考 / 模板

## 适用场景
…

## 模板正文
…

## 自检清单
- [ ]
`,
 daily: `# 纪要

## 背景
…

## 结论
…
`,
 default: `# 标题

正文…
`,
 };

 function kbCollLabel(id) {
 const k = String(id || "default").trim() || "default";
 const m = KB_COLL_META[k];
 return m ? `${k} · ${m.label}` : k;
 }

 function kbCollHint(id) {
 const k = String(id || "default").trim() || "default";
 return (KB_COLL_META[k] && KB_COLL_META[k].hint) || "大类分区，用于精准检索。";
 }

 async function refreshKbCollectionOptions() {
 try {
 const data = await api("/api/kb/collections");
 const opts = Array.isArray(data?.options)
 ? data.options
 : Array.isArray(data)
 ? data.map((x) => x.name || x.id).filter(Boolean)
 : [];
 if (opts.length) _kbCollectionOptions = opts;
 } catch (_) {
 /* keep last options */
 }
 return _kbCollectionOptions;
 }

 function getKbCollectionValue() {
 return ($("kbCollection")?.value || "default").trim() || "default";
 }

 function updateKbEditorMeta() {
 const coll = getKbCollectionValue();
 const pill = $("kbMetaColl");
 if (pill) {
 pill.textContent = kbCollLabel(coll);
 pill.title = kbCollHint(coll);
 }
 const n = String($("kbContent")?.value || "").length;
 const chars = $("kbMetaChars");
 if (chars) chars.textContent = n + " 字";
 const cc = $("kbCharCount");
 if (cc) cc.textContent = n + " 字";
 const tplHint = $("kbTplHint");
 if (tplHint) {
 tplHint.textContent = ( $("kbContent")?.value || "" ).trim()
  ? "将覆盖现有正文（需确认）"
  : "空正文时一键起稿 · " + kbCollLabel(coll);
 }
 }

 function setKbCollectionValue(name) {
 const v = String(name || "default").trim() || "default";
 if ($("kbCollection")) $("kbCollection").value = v;
 const root = $("kbCollectionMs");
 if (root) root.dataset.selected = v;
 const hint = $("kbCollectionHint");
 if (hint) hint.textContent = kbCollHint(v);
 renderKbQuickColl(v);
 renderKbTagChips(v);
 updateKbEditorMeta();
 }

 function closeKbCollectionMs(except) {
 document.querySelectorAll("#kbCollectionMs.agent-ms.is-open").forEach((el) => {
 if (except && el === except) return;
 el.classList.remove("is-open");
 const t = el.querySelector(".agent-ms-trigger");
 if (t) t.setAttribute("aria-expanded", "false");
 });
 }

 function renderKbQuickColl(selected) {
 const host = $("kbQuickColl");
 if (!host) return;
 const prefer = ["sop", "product", "handbook", "reference", "daily", "default"];
 const opts = prefer.filter((id) =>
 (_kbCollectionOptions || []).some(
 (o) => String(o).toLowerCase() === id || o === id
 )
 );
 // if catalog empty of presets, still show prefer keys that exist in list OR always show core 5
 const core = ["sop", "product", "handbook", "reference", "daily"];
 const base = core.filter((id) =>
 opts.includes(id) ||
 (_kbCollectionOptions || []).some((o) => String(o).toLowerCase() === id)
 );
 const all = (base.length ? base : core).slice(0, 6);
 const sel = String(selected || getKbCollectionValue()).toLowerCase();
 host.innerHTML = "";
 for (const id of all) {
 const meta = KB_COLL_META[id] || { label: id, hint: "" };
 const btn = document.createElement("button");
 btn.type = "button";
 btn.className =
 "kb-chip kb-chip-card" + (id.toLowerCase() === sel ? " is-on" : "");
 btn.title = meta.hint || id;
 btn.innerHTML =
 '<span class="kb-chip-name">' +
 escapeHtml(meta.label || id) +
 "</span>" +
 (meta.hint
  ? '<span class="kb-chip-desc">' + escapeHtml(meta.hint) + "</span>"
  : "");
 btn.addEventListener("click", () => {
 setKbCollectionValue(id);
 renderKbCollectionMs(id);
 // 新建且正文为空时，切换分类自动提示可用模板
 if (!_kbEditingId && !String($("kbContent")?.value || "").trim()) {
  const th = $("kbTplHint");
  if (th) th.textContent = "可点「插入分类模板」生成「" + meta.label + "」结构";
 }
 });
 host.appendChild(btn);
 }
 }

 function parseKbTags() {
 return String($("kbTags")?.value || "")
 .split(/[,，、\s]+/)
 .map((s) => s.trim())
 .filter(Boolean);
 }

 function setKbTags(list) {
 const uniq = [];
 const seen = new Set();
 for (const t of list || []) {
 const x = String(t || "").trim();
 if (!x) continue;
 const k = x.toLowerCase();
 if (seen.has(k)) continue;
 seen.add(k);
 uniq.push(x);
 }
 if ($("kbTags")) $("kbTags").value = uniq.join(", ");
 }

 function renderKbTagChips(coll) {
 const host = $("kbTagChips");
 if (!host) return;
 const c = String(coll || getKbCollectionValue() || "default");
 const suggest = KB_TAG_SUGGEST[c] || KB_TAG_SUGGEST.default || [];
 const cur = new Set(parseKbTags().map((t) => t.toLowerCase()));
 host.innerHTML = "";
 for (const tag of suggest) {
 const btn = document.createElement("button");
 btn.type = "button";
 const on = cur.has(tag.toLowerCase());
 btn.className = "kb-chip" + (on ? " is-on" : "");
 btn.textContent = tag;
 btn.addEventListener("click", () => {
 const list = parseKbTags();
 const i = list.findIndex((t) => t.toLowerCase() === tag.toLowerCase());
 if (i >= 0) list.splice(i, 1);
 else list.push(tag);
 setKbTags(list);
 renderKbTagChips(c);
 });
 host.appendChild(btn);
 }
 }

 function insertKbTemplate() {
 const ta = $("kbContent");
 if (!ta) return;
 const coll = getKbCollectionValue();
 const tpl = KB_CONTENT_TPL[coll] || KB_CONTENT_TPL.default;
 const cur = (ta.value || "").trim();
 if (cur) {
 if (!confirm("正文非空。用当前分类模板覆盖正文？")) return;
 }
 ta.value = tpl;
 ta.focus();
 updateKbEditorMeta();
 setMsg("msgKbEditor", "已插入「" + kbCollLabel(coll) + "」模板", "ok");
 showToast("已插入模板", "success");
 }

 function renderKbCollectionMs(selected) {
 const root = $("kbCollectionMs");
 if (!root) return;
 const opts = Array.from(
 new Set(
 (_kbCollectionOptions || [])
 .map((x) => String(x || "").trim())
 .filter(Boolean)
 )
 );
 let sel = String(selected || getKbCollectionValue() || "default").trim();
 if (sel && !opts.some((o) => o.toLowerCase() === sel.toLowerCase())) {
 opts.unshift(sel);
 }
 if (!opts.length) opts.push("default");
 if (!sel) sel = opts[0];
 setKbCollectionValue(sel);

 const wasOpen = root.classList.contains("is-open");
 root.innerHTML = "";
 if (wasOpen) root.classList.add("is-open");
 if (!root.dataset.placeholder) {
 root.dataset.placeholder =
 root.getAttribute("data-placeholder") || "选择分类";
 }

 const trigger = document.createElement("button");
 trigger.type = "button";
 trigger.className = "agent-ms-trigger";
 trigger.setAttribute("aria-haspopup", "listbox");
 trigger.setAttribute("aria-expanded", wasOpen ? "true" : "false");
 const text = document.createElement("span");
 text.className = "agent-ms-trigger-text";
 text.textContent = kbCollLabel(sel);
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
 closeKbCollectionMs(root);
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
 list.setAttribute("aria-multiselectable", "false");

 for (const opt of opts) {
 const on = opt.toLowerCase() === sel.toLowerCase();
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
 lab.textContent = kbCollLabel(opt);
 lab.title = kbCollHint(opt);

 const del = document.createElement("button");
 del.type = "button";
 del.className = "agent-ms-item-del";
 del.title = "删除分类选项";
 del.setAttribute("aria-label", "删除 " + opt);
 del.textContent = "×";
 del.addEventListener("click", async (e) => {
 e.preventDefault();
 e.stopPropagation();
 if (opt.toLowerCase() === "default") {
 setMsg("msgKb", "不能删除 default", "error");
 return;
 }
 if (
 !confirm(
 `从下拉列表移除分类「${opt}」？\n已用该分类的页面不会自动改分类。`
 )
 ) {
 return;
 }
 try {
 const res = await api(
 `/api/kb/collections/${encodeURIComponent(opt)}`,
 { method: "DELETE" }
 );
 _kbCollectionOptions = res.options || _kbCollectionOptions;
 const next =
 getKbCollectionValue().toLowerCase() === opt.toLowerCase()
 ? "sop"
 : getKbCollectionValue();
 renderKbCollectionMs(next);
 setMsg("msgKb", `已移除分类选项「${opt}」`, "ok");
 } catch (err) {
 setMsg("msgKb", err.message, "error");
 }
 });

 item.appendChild(check);
 item.appendChild(lab);
 item.appendChild(del);

 const pick = (e) => {
 if (e.target.closest(".agent-ms-item-del")) return;
 e.preventDefault();
 e.stopPropagation();
 setKbCollectionValue(opt);
 renderKbCollectionMs(opt);
 root.classList.remove("is-open");
 };
 item.addEventListener("click", pick);
 item.addEventListener("keydown", (e) => {
 if (e.key === "Enter" || e.key === " ") pick(e);
 });
 list.appendChild(item);
 }
 panel.appendChild(list);

 const addRow = document.createElement("div");
 addRow.className = "agent-ms-add";
 const addInput = document.createElement("input");
 addInput.type = "text";
 addInput.placeholder = "新分类 id，如 ops / training";
 addInput.addEventListener("click", (e) => e.stopPropagation());
 const doAdd = async () => {
 const name = (addInput.value || "").trim();
 if (!name) {
 setMsg("msgKb", "请输入分类名", "error");
 return;
 }
 try {
 const res = await api("/api/kb/collections", {
 method: "POST",
 body: JSON.stringify({ name }),
 });
 _kbCollectionOptions = res.options || _kbCollectionOptions;
 addInput.value = "";
 renderKbCollectionMs(name);
 setMsg("msgKb", `已添加分类「${name}」`, "ok");
 showToast("分类已添加", "success");
 } catch (err) {
 setMsg("msgKb", err.message, "error");
 }
 };
 addInput.addEventListener("keydown", (e) => {
 if (e.key !== "Enter") return;
 e.preventDefault();
 e.stopPropagation();
 doAdd();
 });
 const addBtn = document.createElement("button");
 addBtn.type = "button";
 addBtn.className = "btn";
 addBtn.textContent = "添加";
 addBtn.addEventListener("click", (e) => {
 e.preventDefault();
 e.stopPropagation();
 doAdd();
 });
 addRow.appendChild(addInput);
 addRow.appendChild(addBtn);
 panel.appendChild(addRow);
 root.appendChild(panel);
 }

 function fillKbFilterSelect() {
 const sel = $("kbFilterCollection");
 if (!sel) return;
 const cur = sel.value || "";
 const opts = ["", ...(_kbCollectionOptions || [])];
 sel.innerHTML = "";
 for (const o of opts) {
 const op = document.createElement("option");
 op.value = o;
 op.textContent = o ? kbCollLabel(o) : "全部分类";
 sel.appendChild(op);
 }
 if (opts.includes(cur)) sel.value = cur;
 else sel.value = "";
 }

 async function loadKb(q = "", opts = {}) {
 if (q && typeof q === "object" && !Array.isArray(q)) {
  opts = q;
  q = $("kbSearch")?.value || "";
 }
 const soft = !!(opts && opts.soft);
 initKbPanel();
 const list = $("kbPageList");
 if (!list) return;
 const keepUi = soft && list.querySelector(".card");
 if (!keepUi) {
  list.innerHTML = "";
  setMsg("msgKb", "载入中…");
 }
 try {
 await refreshKbCollectionOptions();
 fillKbFilterSelect();
 let rows;
 const query = (q || "").trim();
 const coll = ($("kbFilterCollection")?.value || "").trim();
 if (query) {
 let url = `/api/kb/search?q=${encodeURIComponent(query)}&limit=50`;
 if (coll) url += `&collection=${encodeURIComponent(coll)}`;
 rows = await api(url);
 } else {
 let url = "/api/kb/pages?limit=100";
 if (coll) url += `&collection=${encodeURIComponent(coll)}`;
 rows = await api(url);
 }
 if (!Array.isArray(rows)) rows = [];
 if (!rows.length) {
 list.innerHTML =
 '<div class="card"><div class="card-body"><div class="card-sub">暂无页面</div></div></div>';
 setMsg("msgKb", "0 页", "ok");
 return;
 }
 for (const p of rows) {
 const card = document.createElement("div");
 card.className = "card";
 const tags = (p.tags || []).join(", ");
 const pin = p.pinned ? " · 置顶" : "";
 const collId = p.collection || "default";
 card.innerHTML = `
 <div class="card-body">
 <div class="card-title">${escapeHtml(p.title || p.id)}</div>
 <div class="card-sub"><span class="kb-coll-badge" title="${escapeHtml(
 kbCollHint(collId)
 )}">${escapeHtml(kbCollLabel(collId))}</span>${pin}${
 tags ? " · " + escapeHtml(tags) : ""
 } · v${escapeHtml(String(p.version || 1))}</div>
 <div class="card-sub muted-line">${escapeHtml(
 (p.preview || p.snippet || "").slice(0, 120)
 )}</div>
 </div>
 <div class="card-actions">
 <button type="button" class="btn edit-kb icon-btn" title="编辑">${_ipk(
 "edit",
 "ipk-sm"
 )}</button>
 <button type="button" class="btn danger del-kb icon-btn" title="删除">${_ipk(
 "delete",
 "ipk-sm"
 )}</button>
 </div>`;
 card.querySelector(".edit-kb").addEventListener("click", () => openKbEditor(p.id));
 card.querySelector(".del-kb").addEventListener("click", () => deleteKbPage(p.id));
 list.appendChild(card);
 }
 setMsg(
 "msgKb",
 coll ? `${kbCollLabel(coll)} · ${rows.length} 页` : `共 ${rows.length} 页`,
 "ok"
 );
 } catch (e) {
 setMsg("msgKb", e.message, "error");
 }
 }

 function getKbPageModal() {
 return $("kbPageModal");
 }

 function openKbPageModal() {
 const modal = getKbPageModal();
 if (!modal) return;
 modal.classList.remove("hidden");
 document.body.classList.add("kb-page-modal-open");
 if (typeof L.hydrateIconPark === "function") L.hydrateIconPark(modal);
 }

 function closeKbPageModal() {
 const modal = getKbPageModal();
 if (modal) modal.classList.add("hidden");
 document.body.classList.remove("kb-page-modal-open");
 closeKbCollectionMs();
 _kbEditingId = "";
 setMsg("msgKbEditor", "");
 }

 async function openKbEditor(pageId) {
 const modal = getKbPageModal();
 if (!modal) {
 setMsg("msgKb", "知识页弹窗未加载，请刷新页面", "error");
 return;
 }
 await refreshKbCollectionOptions();
 _kbEditingId = pageId || "";
 $("kbPageId").value = _kbEditingId;
 $("kbChangelog").value = "";
 setMsg("msgKbEditor", "");
 const lead = $("kbEditorLead");
 const clWrap = $("kbChangelogWrap");
 if (pageId) {
 try {
 const p = await api(`/api/kb/pages/${encodeURIComponent(pageId)}`);
 $("kbTitle").value = p.title || "";
 setKbCollectionValue(p.collection || "default");
 renderKbCollectionMs(p.collection || "default");
 setKbTags(p.tags || []);
 $("kbContent").value = p.content || "";
 $("kbPinned").checked = !!p.pinned;
 $("kbEditorTitle").innerHTML =
 '<span data-ipk="edit" data-ipk-class="ipk-sm"></span> 编辑知识页 · v' +
 (p.version || 1);
 if (lead) lead.textContent = "修改后保存即热更新；长文建议用 Markdown 标题分段。";
 if (clWrap) clWrap.classList.remove("hidden");
 } catch (e) {
 setMsg("msgKb", e.message, "error");
 return;
 }
 } else {
 $("kbTitle").value = "";
 setKbCollectionValue("sop");
 renderKbCollectionMs("sop");
 setKbTags([]);
 $("kbContent").value = "";
 $("kbPinned").checked = false;
 $("kbEditorTitle").innerHTML =
 '<span data-ipk="plus" data-ipk-class="ipk-sm"></span> 新建知识页';
 if (lead)
 lead.textContent =
 "先选分类 → 标题 → 标签 → 正文。可用「插入分类模板」快速起稿。";
 if (clWrap) clWrap.classList.add("hidden");
 }
 openKbPageModal();
 updateKbEditorMeta();
 requestAnimationFrame(() => $("kbTitle")?.focus());
 }

 async function saveKbPage() {
 const title = ($("kbTitle")?.value || "").trim();
 if (!title) {
 setMsg("msgKbEditor", "请填写标题", "error");
 setMsg("msgKb", "请填写标题", "error");
 return;
 }
 const body = {
 title,
 content: $("kbContent")?.value || "",
 tags: parseKbTags(),
 collection: getKbCollectionValue(),
 pinned: !!$("kbPinned")?.checked,
 changelog: ($("kbChangelog")?.value || "").trim(),
 };
 try {
 if (_kbEditingId) {
 await api(`/api/kb/pages/${encodeURIComponent(_kbEditingId)}`, {
 method: "PATCH",
 body: JSON.stringify(body),
 });
 setMsg("msgKb", "已更新", "ok");
 setMsg("msgKbEditor", "已更新", "ok");
 showToast("知识库页面已更新", "success");
 } else {
 await api("/api/kb/pages", {
 method: "POST",
 body: JSON.stringify(body),
 });
 setMsg("msgKb", "已创建", "ok");
 setMsg("msgKbEditor", "已创建", "ok");
 showToast("知识库页面已创建", "success");
 }
 closeKbPageModal();
 await loadKb($("kbSearch")?.value || "");
 } catch (e) {
 setMsg("msgKb", e.message, "error");
 setMsg("msgKbEditor", e.message, "error");
 showToast("保存失败", "error");
 }
 }

 async function deleteKbPage(id) {
 if (!id || !confirm("确定删除该知识库页面？")) return;
 try {
 await api(`/api/kb/pages/${encodeURIComponent(id)}`, { method: "DELETE" });
 setMsg("msgKb", "已删除", "ok");
 await loadKb($("kbSearch")?.value || "");
 } catch (e) {
 setMsg("msgKb", e.message, "error");
 }
 }

 function bindKbDelegatedUi() {
 if (bindKbDelegatedUi._done) return;
 bindKbDelegatedUi._done = true;
 document.addEventListener("click", (e) => {
  const t = e.target;
  if (!(t instanceof Element)) return;
  if (t.id === "kbPageModal") {
   closeKbPageModal();
   return;
  }
  if (t.closest("#btnSearchKb") || t.closest("#btnRefreshKb")) {
   e.preventDefault();
   loadKb($("kbSearch")?.value || "");
   return;
  }
  if (t.closest("#btnNewKbPage")) {
   e.preventDefault();
   openKbEditor("");
   return;
  }
  if (t.closest("#btnSaveKb")) {
   e.preventDefault();
   saveKbPage();
   return;
  }
  if (t.closest("#btnCancelKb") || t.closest("#btnCloseKbPage")) {
   e.preventDefault();
   closeKbPageModal();
   return;
  }
  if (t.closest("#btnKbTpl")) {
   e.preventDefault();
   insertKbTemplate();
  }
 });
 }

 function initKbPanel() {
 bindKbDelegatedUi();
 if (initKbPanel._done) return;
 if (!$("kbPageModal") && !$("kbSearch") && !$("btnNewKbPage")) return;
 initKbPanel._done = true;
 $("kbTags")?.addEventListener("input", () =>
  renderKbTagChips(getKbCollectionValue())
 );
 $("kbContent")?.addEventListener("input", () => updateKbEditorMeta());
 $("kbSearch")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") loadKb($("kbSearch").value.trim());
 });
 $("kbFilterCollection")?.addEventListener("change", () => {
  loadKb($("kbSearch")?.value || "");
 });
 document.addEventListener("click", () => closeKbCollectionMs());
 }
 bindKbDelegatedUi();

// ==================== Workflows（普通人友好版） ====================
 let _wfEditingId = "";
 let _wfToolsCache = null;
 let _wfCurrentRunId = "";
 let _wfJsonSyncLock = false;
 let _wfCreatePhase = "edit"; // pick | edit
 let _wfSelectedTplId = "";
 let _wfTplFilter = "all";
 let _wfDirty = false;

 const WF_STATUS_META = {
 succeeded: { label: "已完成", cls: "wf-st-ok" },
 failed: { label: "出问题了", cls: "wf-st-fail" },
 waiting_human: { label: "等你确认", cls: "wf-st-wait" },
 running: { label: "正在跑", cls: "wf-st-run" },
 cancelled: { label: "已停下", cls: "wf-st-cancel" },
 pending: { label: "排队中", cls: "wf-st-pending" },
 approved: { label: "已确认", cls: "wf-st-ok" },
 rejected: { label: "已拒绝", cls: "wf-st-cancel" },
 ok: { label: "完成", cls: "wf-st-ok" },
 skipped: { label: "已跳过", cls: "wf-st-pending" },
 };

 const WF_TERMINAL = new Set([
 "succeeded",
 "failed",
 "waiting_human",
 "cancelled",
 ]);

 /** 常用动作：普通人点选，不必写 tool / JSON */
 const WF_ACTIONS = {
 list_files: {
 id: "list_files",
 label: "看文件夹",
 emoji: "📁",
 hint: "列出某个文件夹里的文件",
 type: "tool",
 tool: "workspace",
 fields: [
 {
 key: "path",
 label: "哪个文件夹？",
 placeholder: "工作区根目录",
 default: ".",
 pick: "dir",
 },
 ],
 buildArgs: (f) => ({ action: "list", path: f.path || "." }),
 match: (s) =>
 s.type === "tool" &&
 s.tool === "workspace" &&
 (s.args || {}).action === "list",
 readFields: (s) => ({ path: (s.args || {}).path || "." }),
 },
 write_file: {
 id: "write_file",
 label: "写文本文件",
 emoji: "📝",
 hint: "在工作区新建/覆盖一个文本文件",
 type: "tool",
 tool: "workspace",
 fields: [
 {
 key: "path",
 label: "文件路径",
 placeholder: "例：temp/备注.txt",
 default: "temp/note.txt",
 pick: "file",
 },
 {
 key: "content",
 label: "文件内容",
 placeholder: "可写 {{inputs.备注}} 引用运行时填写的内容",
 default: "{{inputs.note}}",
 multiline: true,
 },
 ],
 buildArgs: (f) => ({
 action: "write",
 path: f.path || "temp/note.txt",
 content: f.content || "",
 }),
 match: (s) =>
 s.type === "tool" &&
 s.tool === "workspace" &&
 (s.args || {}).action === "write",
 readFields: (s) => ({
 path: (s.args || {}).path || "",
 content: (s.args || {}).content || "",
 }),
 },
 read_file: {
 id: "read_file",
 label: "读文件",
 emoji: "📖",
 hint: "读取工作区里某个文件的内容",
 type: "tool",
 tool: "workspace",
 fields: [
 {
 key: "path",
 label: "文件路径",
 placeholder: "点选工作区里的文件",
 default: "",
 pick: "file",
 },
 ],
 buildArgs: (f) => ({ action: "read", path: f.path || "" }),
 match: (s) =>
 s.type === "tool" &&
 s.tool === "workspace" &&
 (s.args || {}).action === "read",
 readFields: (s) => ({ path: (s.args || {}).path || "" }),
 },
 search_kb: {
 id: "search_kb",
 label: "查知识库",
 emoji: "📚",
 hint: "按关键词搜索知识页",
 type: "tool",
 tool: "kb",
 fields: [
 {
 key: "query",
 label: "搜什么？",
 placeholder: "例：每周整理工作区",
 default: "{{inputs.query}}",
 },
 ],
 buildArgs: (f) => ({ action: "search", query: f.query || "" }),
 match: (s) =>
 s.type === "tool" &&
 s.tool === "kb" &&
 ["search", "query", "find", ""].includes(
 String((s.args || {}).action || "search")
 ),
 readFields: (s) => ({
 query: (s.args || {}).query || (s.args || {}).q || "",
 }),
 },
 get_time: {
 id: "get_time",
 label: "看当前时间",
 emoji: "⏰",
 hint: "获取服务器当前时间",
 type: "tool",
 tool: "get_current_time",
 fields: [],
 buildArgs: () => ({}),
 match: (s) => s.type === "tool" && s.tool === "get_current_time",
 readFields: () => ({}),
 },
 note: {
 id: "note",
 label: "写一句说明",
 emoji: "💬",
 hint: "只记一句话，不调用任何工具（适合步骤说明）",
 type: "note",
 fields: [
 {
 key: "message",
 label: "要写的说明",
 placeholder: "例：这一步检查完成",
 default: "",
 multiline: true,
 },
 ],
 match: (s) => (s.type || "") === "note",
 readFields: (s) => ({ message: s.message || s.content || "" }),
 },
 gate: {
 id: "gate",
 label: "停一下问我",
 emoji: "✋",
 hint: "跑到这里会暂停，等你点「继续」或「停下」",
 type: "human_gate",
 fields: [
 {
 key: "prompt",
 label: "要问你的话",
 placeholder: "例：确认内容无误再继续？",
 default: "确认没问题再继续？",
 multiline: true,
 },
 ],
 match: (s) => (s.type || "") === "human_gate",
 readFields: (s) => ({
 prompt: s.prompt || s.message || "确认没问题再继续？",
 }),
 },
 agent: {
 id: "agent",
 label: "让 AI 想一步",
 emoji: "🤖",
 hint: "调用对话 Agent（可选用工具）产出文字；适合策略/文案/Prompt",
 type: "agent",
 fields: [
 {
 key: "prompt",
 label: "给 AI 的任务说明",
 placeholder:
 "例：根据上一步结果写一段摘要。可写 {{inputs.brief}} / {{steps.xxx.output}}",
 default:
 "请根据用户输入完成这一步，输出清晰可执行结果。\n用户：{{inputs.brief}}",
 multiline: true,
 },
 {
 key: "use_tools",
 label: "允许 AI 调工具",
 type: "boolean",
 default: true,
 },
 ],
 match: (s) => (s.type || "").toLowerCase() === "agent",
 readFields: (s) => ({
 prompt: s.prompt || s.message || "",
 use_tools: s.use_tools !== false,
 }),
 },
 custom: {
 id: "custom",
 label: "其他能力",
 emoji: "⋯",
 hint: "选任意已安装能力（偏进阶）",
 type: "tool",
 fields: [],
 match: () => false,
 readFields: (s) => ({}),
 },
 };

 const WF_TEMPLATES = [
 {
 id: "blank",
 title: "从零开始",
 desc: "空白流程，自己加步骤",
 emoji: "✨",
 group: "blank",
 name: "",
 description: "",
 inputs: {},
 steps: [],
 },
 {
 id: "hello",
 title: "看文件夹并留言",
 desc: "最简单示例：列目录 → 写备注文件",
 emoji: "📁",
 group: "simple",
 recommended: true,
 name: "看文件夹并留言",
 description: "列出工作区文件，并写一条备注到 temp",
 inputs: {
 note: { type: "string", default: "今天整理了一下", label: "备注内容" },
 },
 steps: [
 {
 id: "list1",
 type: "tool",
 tool: "workspace",
 args: { action: "list", path: "." },
 save_as: "listing",
 },
 {
 id: "write1",
 type: "tool",
 tool: "workspace",
 args: {
 action: "write",
 path: "temp/workflow_note.txt",
 content: "备注：{{inputs.note}}\n",
 },
 },
 {
 id: "done",
 type: "note",
 message: "完成啦：已列目录并写好备注文件。",
 },
 ],
 },
 {
 id: "confirm_write",
 title: "确认后再写文件",
 desc: "先问你一声，同意才写入",
 emoji: "✋",
 group: "simple",
 name: "确认后再写文件",
 description: "运行中会暂停，确认后才写入文件",
 inputs: {
 content: {
 type: "string",
 default: "请修改这段文字",
 label: "要写入的内容",
 },
 },
 steps: [
 {
 id: "ask",
 type: "human_gate",
 prompt: "确认要把内容写进 temp/confirm_note.txt 吗？",
 },
 {
 id: "write1",
 type: "tool",
 tool: "workspace",
 args: {
 action: "write",
 path: "temp/confirm_note.txt",
 content: "{{inputs.content}}",
 },
 },
 { id: "done", type: "note", message: "已按你的确认写好文件。" },
 ],
 },
 {
 id: "kb_check",
 title: "查知识库",
 desc: "输入关键词，搜索知识页",
 emoji: "📚",
 group: "simple",
 name: "查知识库",
 description: "按关键词检索知识库",
 inputs: {
 query: { type: "string", default: "", label: "搜索关键词" },
 },
 steps: [
 {
 id: "search1",
 type: "tool",
 tool: "kb",
 args: { action: "search", query: "{{inputs.query}}" },
 },
 { id: "done", type: "note", message: "知识库检索完成，结果见上一步。" },
 ],
 },
 ];

 function wfStatusPill(status) {
 const m = WF_STATUS_META[status] || {
 label: status || "—",
 cls: "wf-st-pending",
 };
 return `<span class="wf-status-pill ${m.cls}">${escapeHtml(m.label)}</span>`;
 }

 function wfSlugFromLabel(label, fallback) {
 const raw = String(label || "")
 .trim()
 .toLowerCase();
 // Keep ascii word chars; Chinese → fallback key
 let s = raw.replace(/[^a-z0-9_]+/g, "_").replace(/^_|_$/g, "");
 if (!s || /[^\x00-\x7f]/.test(String(label || ""))) {
 // Chinese labels: generate key_n
 s = fallback || "field";
 }
 if (!s) s = fallback || "field";
 if (/^\d/.test(s)) s = "f_" + s;
 return s.slice(0, 32);
 }

 function detectActionId(step) {
 const s = step || {};
 const type = (s.type || "tool").toLowerCase();
 if (type === "note") return "note";
 if (type === "human_gate") return "gate";
 if (type === "agent") return "agent";
 for (const id of [
 "list_files",
 "write_file",
 "read_file",
 "search_kb",
 "get_time",
 "agent",
 ]) {
 if (WF_ACTIONS[id] && WF_ACTIONS[id].match(s)) return id;
 }
 const tool = (s.tool || s.name || "").trim();
 if (tool) return "tool:" + tool;
 return "custom";
 }

 function isToolActionId(actionId) {
 return String(actionId || "").startsWith("tool:");
 }

 function toolNameFromActionId(actionId) {
 return String(actionId || "").slice(5);
 }

 function wfToolByName(name) {
 const n = (name || "").trim();
 if (!n || !_wfToolsCache) return null;
 return _wfToolsCache.find((t) => t.name === n) || null;
 }

 function normalizeWfTool(t) {
 if (!t) return null;
 const name = t.name || t.id || "";
 if (!name) return null;
 const params = t.parameters || {};
 return {
 name,
 label: t.display_name || t.label || name,
 description: t.description || t.base_description || "",
 source: t.source || "builtin",
 parameters: params,
 enabled: t.enabled !== false,
 };
 }

 async function ensureWfTools(force) {
 if (_wfToolsCache && !force) return _wfToolsCache;
 const map = new Map();
 const addList = (arr) => {
 if (!Array.isArray(arr)) return;
 for (const raw of arr) {
 const t = normalizeWfTool(raw);
 if (!t || map.has(t.name)) {
 // merge richer params if missing
 if (t && map.has(t.name)) {
 const old = map.get(t.name);
 if (
 !Object.keys(old.parameters?.properties || {}).length &&
 Object.keys(t.parameters?.properties || {}).length
 ) {
 map.set(t.name, { ...old, parameters: t.parameters });
 }
 if (!old.description && t.description) old.description = t.description;
 if (!old.label || old.label === old.name) old.label = t.label;
 }
 continue;
 }
 map.set(t.name, t);
 }
 };
 try {
 const list = await api("/api/tools");
 addList(Array.isArray(list) ? list : []);
 } catch {
 /* try config catalog */
 }
 try {
 const data = await api("/api/config/tools");
 const catalog = Array.isArray(data?.catalog)
 ? data.catalog
 : Array.isArray(data)
 ? data
 : [];
 addList(catalog);
 if (Array.isArray(data?.custom)) addList(data.custom);
 } catch {
 /* ignore */
 }
 _wfToolsCache = Array.from(map.values()).sort((a, b) => {
 // skills first-ish, then label
 const sa = a.source === "skill" ? 0 : a.source === "mcp" ? 2 : 1;
 const sb = b.source === "skill" ? 0 : b.source === "mcp" ? 2 : 1;
 if (sa !== sb) return sa - sb;
 return String(a.label).localeCompare(String(b.label), "zh");
 });
 if (!_wfToolsCache.length) {
 _wfToolsCache = [
 {
 name: "workspace",
 label: "本地工作区",
 description: "读写本地工作区文件",
 source: "builtin",
 parameters: {},
 enabled: true,
 },
 {
 name: "kb",
 label: "知识库",
 description: "搜索知识页",
 source: "builtin",
 parameters: {},
 enabled: true,
 },
 {
 name: "memory",
 label: "长期记忆",
 description: "记忆读写",
 source: "builtin",
 parameters: {},
 enabled: true,
 },
 {
 name: "get_current_time",
 label: "当前时间",
 description: "",
 source: "builtin",
 parameters: {},
 enabled: true,
 },
 ];
 }
 return _wfToolsCache;
 }

 function getWfPageModal() {
 return $("wfPageModal");
 }

 function closeWfPageModal() {
 if (
 _wfDirty &&
 _wfCreatePhase === "edit" &&
 !confirm("还没保存，确定关闭吗？未保存的修改会丢失。")
 ) {
 return;
 }
 const modal = getWfPageModal();
 if (modal) modal.classList.add("hidden");
 document.body.classList.remove("wf-page-modal-open");
 _wfEditingId = "";
 _wfSelectedTplId = "";
 _wfCreatePhase = "edit";
 _wfDirty = false;
 setMsg("msgWfEdit", "");
 }

 function closeWfRunModal() {
 $("wfRunModal")?.classList.add("hidden");
 document.body.classList.remove("wf-run-modal-open");
 setMsg("msgWfRun", "");
 }

 function closeWfRunDetailModal() {
 $("wfRunDetailModal")?.classList.add("hidden");
 document.body.classList.remove("wf-run-detail-open");
 }

 // ---- Inputs（运行时要问什么） ----
 function collectInputsFromBuilder() {
 const host = $("wfInputsBuilder");
 const out = {};
 if (!host) return out;
 const used = new Set();
 host.querySelectorAll(".wf-input-row").forEach((row, idx) => {
 const label = (row.querySelector(".wf-in-label")?.value || "").trim();
 let key = (row.querySelector(".wf-in-key")?.value || "").trim();
 if (!key) key = wfSlugFromLabel(label, "field_" + (idx + 1));
 if (!key) return;
 let base = key;
 let n = 2;
 while (used.has(key)) {
 key = base + "_" + n;
 n += 1;
 }
 used.add(key);
 const keyEl = row.querySelector(".wf-in-key");
 if (keyEl && keyEl.value !== key) keyEl.value = key;
 const type = (row.querySelector(".wf-in-type")?.value || "string").trim();
 const def = row.querySelector(".wf-in-default")?.value ?? "";
 out[key] = { type: type || "string", default: def, label: label || key };
 });
 return out;
 }

 function renderInputsBuilder(inputs) {
 const host = $("wfInputsBuilder");
 if (!host) return;
 const obj =
 inputs && typeof inputs === "object" && !Array.isArray(inputs) ? inputs : {};
 const keys = Object.keys(obj);
 host.innerHTML = "";
 if (!keys.length) {
 host.innerHTML =
 '<div class="wf-empty-hint">大多数流程不用填。内容每次不同时，再加一项即可。</div>';
 return;
 }
 keys.forEach((key) => {
 const meta = obj[key];
 const type =
 typeof meta === "object" && meta ? meta.type || "string" : "string";
 const def =
 typeof meta === "object" && meta && "default" in meta
 ? meta.default
 : typeof meta !== "object"
 ? meta
 : "";
 const label =
 typeof meta === "object" && meta && meta.label
 ? meta.label
 : key;
 host.appendChild(makeInputRow(key, type, def, label));
 });
 }

 function makeInputRow(key, type, defVal, label) {
 const row = document.createElement("div");
 row.className = "wf-input-row wf-input-row-friendly";
 row.innerHTML = `
 <div class="wf-in-main">
 <label class="kb-label">问你什么（中文即可）
 <input class="wf-in-label task-field-input" type="text" placeholder="例：备注内容、关键词" value="${escapeHtml(
 String(label || "")
 )}" />
 </label>
 <label class="kb-label">默认答案
 <input class="wf-in-default task-field-input" type="text" placeholder="可不填，运行时再改" value="${escapeHtml(
 String(defVal ?? "")
 )}" />
 </label>
 </div>
 <div class="wf-in-side">
 <label class="kb-label">答案类型
 <select class="wf-in-type task-field-input">
 <option value="string"${type === "string" ? " selected" : ""}>文字</option>
 <option value="number"${type === "number" ? " selected" : ""}>数字</option>
 <option value="boolean"${type === "boolean" ? " selected" : ""}>是 / 否</option>
 </select>
 </label>
 <details class="wf-in-adv">
 <summary>系统名（一般不用改）</summary>
 <input class="wf-in-key task-field-input" type="text" placeholder="自动生成" value="${escapeHtml(
 String(key || "")
 )}" />
 <p class="field-hint" style="margin:4px 0 0">步骤里用 {{inputs.系统名}} 引用</p>
 </details>
 <button type="button" class="btn ghost-sm wf-in-remove" title="删除">删除</button>
 </div>`;
 return row;
 }

 function addInputRow() {
 const host = $("wfInputsBuilder");
 if (!host) return;
 host.querySelector(".wf-empty-hint")?.remove();
 const n = host.querySelectorAll(".wf-input-row").length + 1;
 host.appendChild(makeInputRow("field_" + n, "string", "", ""));
 syncInputsJsonFromBuilder();
 const last = host.querySelector(".wf-input-row:last-child .wf-in-label");
 last?.focus();
 }

 function syncInputsJsonFromBuilder() {
 if (_wfJsonSyncLock) return;
 const ta = $("wfInputs");
 if (!ta) return;
 _wfJsonSyncLock = true;
 try {
 ta.value = JSON.stringify(collectInputsFromBuilder(), null, 2);
 } finally {
 _wfJsonSyncLock = false;
 }
 updateWfEditStats();
 }

 function syncInputsBuilderFromJson() {
 if (_wfJsonSyncLock) return;
 try {
 const obj = JSON.parse($("wfInputs")?.value || "{}");
 _wfJsonSyncLock = true;
 renderInputsBuilder(obj);
 } catch {
 /* keep */
 } finally {
 _wfJsonSyncLock = false;
 }
 }

 // ---- Steps（常用动作 + 全部技能） ----
 function toolOptionsHtml(selected) {
 const tools = _wfToolsCache || [];
 if (!tools.length) {
 return `<option value="${escapeHtml(selected || "")}">${escapeHtml(
 selected || "选择能力"
 )}</option>`;
 }
 const skills = tools.filter((t) => t.source === "skill");
 const builtins = tools.filter((t) => t.source !== "skill" && t.source !== "mcp");
 const mcps = tools.filter((t) => t.source === "mcp");
 const opt = (t) =>
 `<option value="${escapeHtml(t.name)}"${
 t.name === selected ? " selected" : ""
 }>${escapeHtml(t.label || t.name)}</option>`;
 let html = "";
 if (skills.length)
 html += `<optgroup label="技能">${skills.map(opt).join("")}</optgroup>`;
 if (builtins.length)
 html += `<optgroup label="内置">${builtins.map(opt).join("")}</optgroup>`;
 if (mcps.length)
 html += `<optgroup label="MCP">${mcps.map(opt).join("")}</optgroup>`;
 if (!html) html = tools.map(opt).join("");
 // ensure selected present
 if (selected && !tools.some((t) => t.name === selected)) {
 html =
 `<option value="${escapeHtml(selected)}" selected>${escapeHtml(
 selected
 )}</option>` + html;
 }
 return html;
 }

 function actionOptionsHtml(selected) {
 const common = Object.values(WF_ACTIONS)
 .filter((a) => a.id !== "custom")
 .map(
 (a) =>
 `<option value="${a.id}"${a.id === selected ? " selected" : ""}>${
 a.emoji
 } ${a.label}</option>`
 )
 .join("");
 const tools = _wfToolsCache || [];
 const skills = tools.filter((t) => t.source === "skill");
 const others = tools.filter((t) => t.source !== "skill");
 const optTool = (t) => {
 const aid = "tool:" + t.name;
 return `<option value="${escapeHtml(aid)}"${
 aid === selected ? " selected" : ""
 }>${escapeHtml(t.label || t.name)}</option>`;
 };
 let groups = `<optgroup label="常用动作">${common}</optgroup>`;
 if (skills.length)
 groups += `<optgroup label="技能（${skills.length}）">${skills
 .map(optTool)
 .join("")}</optgroup>`;
 if (others.length)
 groups += `<optgroup label="其他能力（${others.length}）">${others
 .map(optTool)
 .join("")}</optgroup>`;
 // selected tool not in list
 if (isToolActionId(selected)) {
 const n = toolNameFromActionId(selected);
 if (!tools.some((t) => t.name === n)) {
 groups =
 `<option value="${escapeHtml(selected)}" selected>${escapeHtml(
 n
 )}</option>` + groups;
 }
 }
 groups += `<optgroup label="其它"><option value="custom"${
 selected === "custom" ? " selected" : ""
 }>⋯ 手动指定</option></optgroup>`;
 return groups;
 }

 function wfPathDisplayLabel(path, mode) {
 const p = String(path || "").trim();
 if (!p || p === "." || p === "./") {
 return mode === "file" ? "尚未选择文件" : "工作区根目录";
 }
 return p;
 }

 function fieldInputsHtml(action, fields) {
 const defs = action.fields || [];
 if (!defs.length && action.id !== "custom") {
 return '<p class="field-hint" style="margin:0">这一步不用额外填写。</p>';
 }
 return defs
 .map((d) => {
 const val = fields[d.key] != null ? fields[d.key] : d.default || "";
 if (d.type === "boolean") {
 const checked =
 val === true || val === "true" || val === 1 || val === "1";
 return `<label class="kb-check-line">
 <input class="wf-fld" type="checkbox" data-fld="${escapeHtml(
 d.key
 )}" data-ftype="boolean"${checked ? " checked" : ""} />
 <span>${escapeHtml(d.label)}</span>
 </label>`;
 }
 if (d.pick === "dir" || d.pick === "file") {
 const mode = d.pick === "file" ? "file" : "dir";
 const pathVal =
 val === undefined || val === null ? d.default || "" : String(val);
 const display = wfPathDisplayLabel(pathVal, mode);
 return `<div class="wf-path-field" data-pick-mode="${mode}">
 <div class="kb-label">${escapeHtml(d.label)}</div>
 <div class="wf-path-row">
 <div class="wf-path-display" title="${escapeHtml(pathVal || ".")}">
 <span class="wf-path-ico" aria-hidden="true">${
 mode === "file" ? "📄" : "📁"
 }</span>
 <span class="wf-path-text">${escapeHtml(display)}</span>
 </div>
 <button type="button" class="btn ghost-sm wf-path-browse" data-pick-mode="${mode}">浏览</button>
 </div>
 <input type="hidden" class="wf-fld" data-fld="${escapeHtml(
 d.key
 )}" data-ftype="path" value="${escapeHtml(pathVal)}" />
 <div class="wf-path-browser hidden" data-browse-for="${escapeHtml(
 d.key
 )}"></div>
 </div>`;
 }
 if (d.multiline) {
 return `<label class="kb-label">${escapeHtml(d.label)}
 <textarea class="wf-fld task-prompt-ta" data-fld="${escapeHtml(
 d.key
 )}" rows="2" placeholder="${escapeHtml(
 d.placeholder || ""
 )}">${escapeHtml(String(val))}</textarea>
 </label>`;
 }
 return `<label class="kb-label">${escapeHtml(d.label)}
 <input class="wf-fld task-field-input" data-fld="${escapeHtml(
 d.key
 )}" type="text" placeholder="${escapeHtml(
 d.placeholder || ""
 )}" value="${escapeHtml(String(val))}" />
 </label>`;
 })
 .join("");
 }

 function wfNormalizeBrowsePath(path) {
 const p = String(path || "").trim();
 if (!p || p === "." || p === "./") return ".";
 return p.replace(/\\/g, "/").replace(/^\/+/, "");
 }

 function wfParentDirOfFile(filePath) {
 const p = wfNormalizeBrowsePath(filePath);
 if (!p || p === ".") return ".";
 const i = p.lastIndexOf("/");
 if (i <= 0) return ".";
 return p.slice(0, i) || ".";
 }

 async function loadWfBrowse(dirPath, dirsOnly) {
 const q = new URLSearchParams();
 const p = wfNormalizeBrowsePath(dirPath);
 if (p && p !== ".") q.set("path", p);
 if (dirsOnly) q.set("dirs_only", "true");
 return api("/api/workspace/browse?" + q.toString());
 }

 function renderWfPathBrowser(host, data, mode) {
 if (!host || !data) return;
 const cur = data.path || ".";
 const display = data.path_display || cur;
 const parent = data.parent; // null | "" | "foo"
 const entries = Array.isArray(data.entries) ? data.entries : [];
 const dirs = entries.filter((e) => e.type === "dir");
 const files = mode === "file" ? entries.filter((e) => e.type === "file") : [];

 const crumbs = [];
 crumbs.push(
 `<button type="button" class="wf-bc-item" data-browse-nav="." title="工作区根目录">工作区</button>`
 );
 if (cur && cur !== ".") {
 const parts = cur.split("/").filter(Boolean);
 let acc = "";
 parts.forEach((part, idx) => {
 acc = acc ? acc + "/" + part : part;
 const last = idx === parts.length - 1;
 crumbs.push(`<span class="wf-bc-sep">/</span>`);
 if (last) {
 crumbs.push(
 `<span class="wf-bc-cur">${escapeHtml(part)}</span>`
 );
 } else {
 crumbs.push(
 `<button type="button" class="wf-bc-item" data-browse-nav="${escapeHtml(
 acc
 )}">${escapeHtml(part)}</button>`
 );
 }
 });
 }

 const upBtn =
 parent === null
 ? ""
 : `<button type="button" class="btn ghost-sm wf-browse-up" data-browse-nav="${escapeHtml(
 parent === "" ? "." : parent
 )}">↑ 上级</button>`;

 const dirRows = dirs
 .map(
 (e) => `
 <button type="button" class="wf-browse-item is-dir" data-browse-enter="${escapeHtml(
 e.path
 )}" title="${escapeHtml(e.path)}">
 <span class="wf-browse-ico">📁</span>
 <span class="wf-browse-name">${escapeHtml(e.name)}</span>
 <span class="wf-browse-go">打开</span>
 </button>`
 )
 .join("");

 const fileRows = files
 .map(
 (e) => `
 <button type="button" class="wf-browse-item is-file" data-browse-pick="${escapeHtml(
 e.path
 )}" title="${escapeHtml(e.path)}">
 <span class="wf-browse-ico">📄</span>
 <span class="wf-browse-name">${escapeHtml(e.name)}</span>
 <span class="wf-browse-go">选这个</span>
 </button>`
 )
 .join("");

 const empty =
 !dirRows && !fileRows
 ? `<div class="wf-browse-empty">${
 mode === "dir"
 ? "这里没有子文件夹"
 : "这里没有可选项"
 }</div>`
 : "";

 const quick =
 mode === "dir"
 ? `<div class="wf-browse-quick">
 <button type="button" class="btn ghost-sm" data-browse-pick="." data-browse-nav-pick=".">根目录</button>
 <button type="button" class="btn ghost-sm" data-browse-enter="temp">temp</button>
 <button type="button" class="btn ghost-sm" data-browse-enter="uploads">uploads</button>
 <button type="button" class="btn ghost-sm" data-browse-enter="images">images</button>
 </div>`
 : `<div class="wf-browse-quick">
 <button type="button" class="btn ghost-sm" data-browse-enter=".">根目录</button>
 <button type="button" class="btn ghost-sm" data-browse-enter="temp">temp</button>
 <button type="button" class="btn ghost-sm" data-browse-enter="uploads">uploads</button>
 </div>`;

 host.innerHTML = `
 <div class="wf-browse-panel">
 <div class="wf-browse-head">
 <div class="wf-browse-crumbs">${crumbs.join("")}</div>
 <div class="wf-browse-head-actions">
 ${upBtn}
 <button type="button" class="btn ghost-sm wf-browse-close">收起</button>
 </div>
 </div>
 ${quick}
 <div class="wf-browse-list">
 ${dirRows}
 ${fileRows}
 ${empty}
 </div>
 ${
 mode === "dir"
 ? `<div class="wf-browse-foot">
 <button type="button" class="btn primary wf-browse-use-here" data-browse-pick="${escapeHtml(
 cur
 )}">✓ 就选这个文件夹</button>
 </div>`
 : `<p class="field-hint" style="margin:8px 0 0">点文件夹进入；点文件即可选中。</p>`
 }
 </div>`;
 host.dataset.browsePath = cur;
 host.dataset.browseMode = mode;
 }

 async function openWfPathBrowser(pathField, startPath) {
 const browser = pathField.querySelector(".wf-path-browser");
 if (!browser) return;
 const mode = pathField.dataset.pickMode || "dir";
 const dirsOnly = mode === "dir";
 let dir =
 startPath != null
 ? startPath
 : mode === "file"
 ? wfParentDirOfFile(
 pathField.querySelector(".wf-fld")?.value || ""
 )
 : pathField.querySelector(".wf-fld")?.value || ".";
 if (mode === "file" && (!dir || dir === ".")) dir = ".";
 browser.classList.remove("hidden");
 browser.innerHTML =
 '<div class="wf-browse-panel"><div class="wf-browse-empty">加载中…</div></div>';
 try {
 const data = await loadWfBrowse(dir, dirsOnly);
 renderWfPathBrowser(browser, data, mode);
 } catch (e) {
 // if path missing (e.g. temp not exist), fall back to root
 try {
 const data = await loadWfBrowse(".", dirsOnly);
 renderWfPathBrowser(browser, data, mode);
 setMsg("msgWfEdit", "原路径不存在，已回到工作区根目录", "ok");
 } catch (e2) {
 browser.innerHTML = `<div class="wf-browse-panel"><div class="wf-browse-empty">加载失败：${escapeHtml(
 e2.message || String(e2)
 )}</div></div>`;
 }
 }
 }

 function setWfPathFieldValue(pathField, path) {
 if (!pathField) return;
 const mode = pathField.dataset.pickMode || "dir";
 let v = String(path ?? "").trim();
 if (mode === "dir" && (!v || v === "./")) v = ".";
 const input = pathField.querySelector(".wf-fld");
 if (input) input.value = v;
 const text = pathField.querySelector(".wf-path-text");
 if (text) text.textContent = wfPathDisplayLabel(v, mode);
 const disp = pathField.querySelector(".wf-path-display");
 if (disp) disp.title = v || ".";
 const browser = pathField.querySelector(".wf-path-browser");
 if (browser) browser.classList.add("hidden");
 _wfDirty = true;
 syncStepsJsonFromBuilder();
 updateWfEditStats();
 }

 function schemaParamLabel(key, prop) {
 if (!prop || typeof prop !== "object") return key;
 return (
 prop.title ||
 (prop.description ? String(prop.description).split(/[。.\n]/)[0] : "") ||
 key
 );
 }

 function schemaFieldsHtml(tool, args) {
 const schema = (tool && tool.parameters) || {};
 const props = schema.properties || {};
 const required = Array.isArray(schema.required) ? schema.required : [];
 const keys = Object.keys(props);
 const argsObj = args && typeof args === "object" ? args : {};

 if (!keys.length) {
 // no schema: freeform JSON (collapsed default empty)
 const argsStr = Object.keys(argsObj).length
 ? JSON.stringify(argsObj, null, 2)
 : "";
 return `
 <p class="field-hint" style="margin:0 0 8px">这个能力没有固定参数表单，需要时再填下面高级参数。</p>
 <details class="wf-in-adv"${argsStr ? " open" : ""}>
 <summary>高级参数（JSON，可空）</summary>
 <textarea class="wf-st-args task-prompt-ta" rows="3" placeholder="{}">${escapeHtml(
 argsStr
 )}</textarea>
 </details>`;
 }

 const fields = keys
 .map((k) => {
 const p = props[k] || {};
 const req = required.includes(k);
 const label = schemaParamLabel(k, p);
 const desc = p.description ? String(p.description).slice(0, 80) : "";
 let val = argsObj[k];
 if (val === undefined) val = p.default !== undefined ? p.default : "";
 const type = Array.isArray(p.type) ? p.type[0] : p.type || "string";
 const isBool = type === "boolean";
 const isNum = type === "number" || type === "integer";
 const isLong =
 type === "string" &&
 (String(p.description || "").length > 40 ||
 k.match(/prompt|content|text|body|query|message|note/i));
 const enums = Array.isArray(p.enum) ? p.enum : null;

 if (isBool) {
 const checked = val === true || val === "true" || val === 1;
 return `<label class="kb-check-line wf-schema-field">
 <input type="checkbox" class="wf-fld" data-fld="${escapeHtml(
 k
 )}" data-ftype="boolean"${checked ? " checked" : ""} />
 <span>${escapeHtml(label)}${req ? " *" : ""}</span>
 </label>`;
 }
 if (enums && enums.length) {
 const opts = enums
 .map(
 (e) =>
 `<option value="${escapeHtml(String(e))}"${
 String(e) === String(val) ? " selected" : ""
 }>${escapeHtml(String(e))}</option>`
 )
 .join("");
 return `<label class="kb-label wf-schema-field">${escapeHtml(label)}${
 req ? " *" : ""
 }
 <select class="wf-fld task-field-input" data-fld="${escapeHtml(
 k
 )}" data-ftype="string">${opts}</select>
 ${desc ? `<span class="field-hint">${escapeHtml(desc)}</span>` : ""}
 </label>`;
 }
 if (isLong) {
 return `<label class="kb-label wf-schema-field">${escapeHtml(label)}${
 req ? " *" : ""
 }
 <textarea class="wf-fld task-prompt-ta" data-fld="${escapeHtml(
 k
 )}" data-ftype="string" rows="2" placeholder="${escapeHtml(
 desc || k
 )}">${escapeHtml(val == null ? "" : String(val))}</textarea>
 </label>`;
 }
 return `<label class="kb-label wf-schema-field">${escapeHtml(label)}${
 req ? " *" : ""
 }
 <input class="wf-fld task-field-input" type="${
 isNum ? "number" : "text"
 }" data-fld="${escapeHtml(k)}" data-ftype="${
 isNum ? "number" : "string"
 }" value="${escapeHtml(
 val == null ? "" : String(val)
 )}" placeholder="${escapeHtml(desc || k)}" />
 </label>`;
 })
 .join("");

 // leftover keys in args not in schema
 const extra = Object.keys(argsObj).filter((k) => !props[k]);
 let extraHtml = "";
 if (extra.length) {
 const extraObj = {};
 extra.forEach((k) => {
 extraObj[k] = argsObj[k];
 });
 extraHtml = `<details class="wf-in-adv" open>
 <summary>额外参数（JSON）</summary>
 <textarea class="wf-st-args task-prompt-ta" rows="2">${escapeHtml(
 JSON.stringify(extraObj, null, 2)
 )}</textarea>
 </details>`;
 } else {
 extraHtml = `<details class="wf-in-adv">
 <summary>额外参数（JSON，可选）</summary>
 <textarea class="wf-st-args task-prompt-ta" rows="2" placeholder="{}"></textarea>
 </details>`;
 }
 return fields + extraHtml;
 }

 function makeStepCard(step, index) {
 const s = step || {};
 const actionId = detectActionId(s);
 const id = s.id || `step_${index + 1}`;
 const card = document.createElement("div");
 card.className = "wf-step-card";
 card.dataset.action = actionId;

 let hint = "";
 let body = "";
 let type = "tool";

 if (actionId === "note" || actionId === "gate" || WF_ACTIONS[actionId]) {
 const action = WF_ACTIONS[actionId] || WF_ACTIONS.custom;
 type = action.type || "tool";
 hint = action.hint || "";
 const fields = action.readFields ? action.readFields(s) : {};
 if (actionId === "custom") {
 body = `
 <div class="wf-step-tool-row">
 <label class="kb-label">选择能力
 <select class="wf-st-tool task-field-input">${toolOptionsHtml(
 s.tool || s.name || ""
 )}</select>
 </label>
 </div>
 <div class="wf-st-tool-params">${schemaFieldsHtml(
 wfToolByName(s.tool || s.name || ""),
 s.args || {}
 )}</div>`;
 } else {
 body = fieldInputsHtml(action, fields);
 }
 } else if (isToolActionId(actionId)) {
 const tname = toolNameFromActionId(actionId);
 const tool = wfToolByName(tname);
 type = "tool";
 hint =
 (tool && (tool.description || "").slice(0, 100)) ||
 "来自系统已安装的能力";
 const srcTag =
 tool && tool.source === "skill"
 ? "技能"
 : tool && tool.source === "mcp"
 ? "MCP"
 : "内置";
 hint = `【${srcTag}】` + (hint || tname);
 body = `
 <div class="wf-step-tool-meta">
 <span class="pill">${escapeHtml(srcTag)}</span>
 <code class="tool-call-name">${escapeHtml(tname)}</code>
 </div>
 ${schemaFieldsHtml(tool, s.args || {})}`;
 } else {
 type = "tool";
 hint = "手动指定能力";
 body = schemaFieldsHtml(null, s.args || {});
 }
 card.dataset.type = type;
 if (type === "agent") card.classList.add("wf-step-agent");
 if (type === "human_gate") card.classList.add("wf-step-gate");

 card.innerHTML = `
 <div class="wf-step-head">
 <span class="wf-step-idx">${index + 1}</span>
 <div class="wf-step-title-block">
 <select class="wf-st-action task-field-input">${actionOptionsHtml(
 actionId
 )}</select>
 <div class="wf-step-hint">${escapeHtml(hint)}</div>
 </div>
 <div class="wf-step-head-actions">
 <button type="button" class="btn ghost-sm wf-st-up" title="上移">↑</button>
 <button type="button" class="btn ghost-sm wf-st-down" title="下移">↓</button>
 <button type="button" class="btn ghost-sm danger wf-st-remove" title="删除">删除</button>
 </div>
 </div>
 <div class="wf-step-body">${body}</div>
 <input type="hidden" class="wf-st-id" value="${escapeHtml(id)}" />`;

 // when custom tool select changes, refresh param form
 const toolSel = card.querySelector(".wf-st-tool");
 if (toolSel) {
 toolSel.addEventListener("change", () => {
 const host = card.querySelector(".wf-st-tool-params");
 if (host) {
 host.innerHTML = schemaFieldsHtml(wfToolByName(toolSel.value), {});
 }
 syncStepsJsonFromBuilder();
 });
 }
 return card;
 }

 function collectFieldsFromCard(card) {
 const out = {};
 card.querySelectorAll(".wf-fld").forEach((el) => {
 const k = el.dataset.fld;
 if (!k) return;
 const ftype = el.dataset.ftype || "string";
 if (el.type === "checkbox" || ftype === "boolean") {
 out[k] = !!el.checked;
 } else if (ftype === "number") {
 const n = Number(el.value);
 out[k] = el.value === "" || Number.isNaN(n) ? el.value : n;
 } else {
 out[k] = el.value;
 }
 });
 return out;
 }

 function collectExtraArgs(card) {
 const raw = (card.querySelector(".wf-st-args")?.value || "").trim();
 if (!raw) return {};
 try {
 const o = JSON.parse(raw);
 return typeof o === "object" && o && !Array.isArray(o) ? o : {};
 } catch {
 return {};
 }
 }

 function collectStepsFromBuilder() {
 const host = $("wfStepsBuilder");
 const steps = [];
 if (!host) return steps;
 host.querySelectorAll(".wf-step-card").forEach((card, idx) => {
 const id =
 (card.querySelector(".wf-st-id")?.value || "").trim() ||
 `step_${idx + 1}`;
 const actionId =
 (card.querySelector(".wf-st-action")?.value || "").trim() ||
 "custom";
 const fields = collectFieldsFromCard(card);

 if (actionId === "note") {
 steps.push({
 id,
 type: "note",
 message: fields.message || "",
 });
 return;
 }
 if (actionId === "gate") {
 steps.push({
 id,
 type: "human_gate",
 prompt: fields.prompt || "确认没问题再继续？",
 });
 return;
 }
 if (actionId === "agent") {
 steps.push({
 id,
 type: "agent",
 prompt: fields.prompt || "",
 use_tools: fields.use_tools !== false && fields.use_tools !== "false",
 save_as: id,
 });
 return;
 }
 if (actionId === "custom") {
 const tool = (card.querySelector(".wf-st-tool")?.value || "").trim();
 steps.push({
 id,
 type: "tool",
 tool,
 args: { ...collectExtraArgs(card), ...fields },
 save_as: id,
 });
 return;
 }
 if (isToolActionId(actionId)) {
 const tool = toolNameFromActionId(actionId);
 steps.push({
 id,
 type: "tool",
 tool,
 args: { ...collectExtraArgs(card), ...fields },
 save_as: id,
 });
 return;
 }
 const action = WF_ACTIONS[actionId];
 if (action && action.type === "tool") {
 steps.push({
 id,
 type: "tool",
 tool: action.tool,
 args: action.buildArgs ? action.buildArgs(fields) : fields,
 save_as: id,
 });
 return;
 }
 steps.push({
 id,
 type: "tool",
 tool: action?.tool || "",
 args: fields,
 save_as: id,
 });
 });
 return steps;
 }

 function reindexStepCards() {
 const host = $("wfStepsBuilder");
 if (!host) return;
 host.querySelectorAll(".wf-step-card").forEach((card, i) => {
 const idx = card.querySelector(".wf-step-idx");
 if (idx) idx.textContent = String(i + 1);
 });
 }

 async function renderStepsBuilder(steps) {
 await ensureWfTools();
 const host = $("wfStepsBuilder");
 if (!host) return;
 host.innerHTML = "";
 const arr = Array.isArray(steps) ? steps : [];
 if (!arr.length) {
 host.innerHTML =
 '<div class="wf-empty-hint">还没有步骤<br><span style="opacity:.85">点上方的能力按钮加一步即可</span></div>';
 return;
 }
 arr.forEach((s, i) => host.appendChild(makeStepCard(s, i)));
 updateWfEditStats();
 }

 function syncStepsJsonFromBuilder() {
 if (_wfJsonSyncLock) return;
 const ta = $("wfSteps");
 if (!ta) return;
 _wfJsonSyncLock = true;
 try {
 ta.value = JSON.stringify(collectStepsFromBuilder(), null, 2);
 } finally {
 _wfJsonSyncLock = false;
 }
 updateWfEditStats();
 }

 async function syncStepsBuilderFromJson() {
 if (_wfJsonSyncLock) return;
 try {
 const arr = JSON.parse($("wfSteps")?.value || "[]");
 if (!Array.isArray(arr)) throw new Error("不是数组");
 _wfJsonSyncLock = true;
 await renderStepsBuilder(arr);
 } catch (e) {
 setMsg("msgWfEdit", "步骤配置无效: " + e.message, "error");
 } finally {
 _wfJsonSyncLock = false;
 }
 }

 function defaultStepForAction(actionId, n) {
 if (actionId === "note") {
 return {
 id: `note_${n}`,
 type: "note",
 message: "这一步完成",
 };
 }
 if (actionId === "gate") {
 return {
 id: `gate_${n}`,
 type: "human_gate",
 prompt: "确认没问题再继续？",
 };
 }
 if (actionId === "agent") {
 return {
 id: `agent_${n}`,
 type: "agent",
 prompt:
 "请根据用户输入完成这一步，输出清晰可执行结果。\n用户：{{inputs.brief}}",
 use_tools: true,
 save_as: `agent_${n}`,
 };
 }
 if (isToolActionId(actionId)) {
 const tool = toolNameFromActionId(actionId);
 const t = wfToolByName(tool);
 const args = {};
 const props = t?.parameters?.properties || {};
 Object.keys(props).forEach((k) => {
 if (props[k] && props[k].default !== undefined) {
 args[k] = props[k].default;
 }
 });
 return {
 id: `s_${n}`,
 type: "tool",
 tool,
 args,
 save_as: `s_${n}`,
 };
 }
 if (actionId === "custom") {
 return {
 id: `step_${n}`,
 type: "tool",
 tool: (_wfToolsCache && _wfToolsCache[0]?.name) || "workspace",
 args: {},
 };
 }
 const a = WF_ACTIONS[actionId];
 if (a && a.type === "agent") {
 return {
 id: `agent_${n}`,
 type: "agent",
 prompt: (a.fields || []).find((f) => f.key === "prompt")?.default || "",
 use_tools: true,
 save_as: `agent_${n}`,
 };
 }
 if (!a || a.type !== "tool") {
 return {
 id: `step_${n}`,
 type: "tool",
 tool: "workspace",
 args: {},
 };
 }
 const fields = {};
 (a.fields || []).forEach((f) => {
 fields[f.key] = f.default ?? "";
 });
 return {
 id: `${actionId}_${n}`,
 type: "tool",
 tool: a.tool,
 args: a.buildArgs ? a.buildArgs(fields) : {},
 save_as: `${actionId}_${n}`,
 };
 }

 async function addStepByAction(actionId) {
 const host = $("wfStepsBuilder");
 if (!host) return;
 await ensureWfTools();
 host.querySelector(".wf-empty-hint")?.remove();
 const n = host.querySelectorAll(".wf-step-card").length + 1;
 const step = defaultStepForAction(actionId || "list_files", n);
 host.appendChild(makeStepCard(step, n - 1));
 reindexStepCards();
 syncStepsJsonFromBuilder();
 // scroll to new card
 const last = host.querySelector(".wf-step-card:last-child");
 last?.scrollIntoView({ behavior: "smooth", block: "nearest" });
 }

 /** 兼容旧调用 */
 async function addStepCard(type) {
 if (type === "note") return addStepByAction("note");
 if (type === "human_gate") return addStepByAction("gate");
 return addStepByAction("custom");
 }

 function moveStepCard(card, dir) {
 const host = $("wfStepsBuilder");
 if (!host || !card) return;
 if (dir < 0 && card.previousElementSibling) {
 host.insertBefore(card, card.previousElementSibling);
 } else if (dir > 0 && card.nextElementSibling) {
 host.insertBefore(card.nextElementSibling, card);
 }
 reindexStepCards();
 syncStepsJsonFromBuilder();
 }

 async function changeStepAction(card, actionId) {
 const id = (card.querySelector(".wf-st-id")?.value || "").trim();
 const idx = Array.from(card.parentElement?.children || []).indexOf(card);
 await ensureWfTools();
 const step = defaultStepForAction(actionId, idx + 1);
 if (id) step.id = id;
 const neu = makeStepCard(step, idx);
 card.replaceWith(neu);
 reindexStepCards();
 syncStepsJsonFromBuilder();
 }

 // ---- 全部能力选择器 ----
 let _wfSkillSrc = "all";

 function sourceLabel(src) {
 if (src === "skill") return "技能";
 if (src === "mcp") return "MCP";
 return "内置";
 }

 function renderWfSkillPickerList() {
 const list = $("wfSkillPickerList");
 const hint = $("wfSkillPickerHint");
 if (!list) return;
 const q = ($("wfSkillSearch")?.value || "").trim().toLowerCase();
 const tools = _wfToolsCache || [];
 let rows = tools.slice();
 if (_wfSkillSrc !== "all") {
 rows = rows.filter((t) => (t.source || "builtin") === _wfSkillSrc);
 }
 if (q) {
 rows = rows.filter((t) => {
 const blob = `${t.name} ${t.label} ${t.description}`.toLowerCase();
 return blob.includes(q);
 });
 }
 if (hint) {
 const nSkill = tools.filter((t) => t.source === "skill").length;
 const nAll = tools.length;
 const nOff = tools.filter((t) => t.enabled === false).length;
 hint.textContent = `共 ${nAll} 个能力 · 技能 ${nSkill}${
 nOff ? " · 已关闭 " + nOff + "（仍可加入）" : ""
 }。点一项加入步骤，参数会自动变成表单。`;
 }
 if (!rows.length) {
 list.innerHTML =
 '<div class="wf-empty-hint">没有匹配的能力。试试换个关键词，或切换「全部 / 技能 / 内置」。</div>';
 return;
 }
 list.innerHTML = rows
 .map((t) => {
 const desc = (t.description || "").replace(/\s+/g, " ").slice(0, 90);
 const off =
 t.enabled === false
 ? '<span class="pill" style="opacity:.75">已关闭</span>'
 : "";
 return `<button type="button" class="wf-skill-item${
 t.enabled === false ? " is-disabled" : ""
 }" data-wf-tool="${escapeHtml(t.name)}">
 <div class="wf-skill-item-top">
 <strong>${escapeHtml(t.label || t.name)}</strong>
 <span class="pill">${escapeHtml(sourceLabel(t.source))}</span>${off}
 </div>
 <div class="wf-skill-item-name"><code>${escapeHtml(t.name)}</code></div>
 ${
 desc
 ? `<div class="wf-skill-item-desc">${escapeHtml(desc)}${
 (t.description || "").length > 90 ? "…" : ""
 }</div>`
 : ""
 }
 </button>`;
 })
 .join("");
 }

 async function openWfSkillPicker() {
 await ensureWfTools(true); // force refresh so new skills appear
 const box = $("wfSkillPicker");
 if (!box) return;
 box.classList.remove("hidden");
 renderWfSkillPickerList();
 $("wfSkillSearch")?.focus();
 }

 function closeWfSkillPicker() {
 $("wfSkillPicker")?.classList.add("hidden");
 }

 async function addStepFromToolName(toolName) {
 if (!toolName) return;
 await addStepByAction("tool:" + toolName);
 setMsg("msgWfEdit", "已添加：" + (wfToolByName(toolName)?.label || toolName), "ok");
 }

 // ---- Templates / create phases ----
 function tplStepCount(t) {
 return Array.isArray(t?.steps) ? t.steps.length : 0;
 }
 function tplHasAgent(t) {
 return (t?.steps || []).some(
 (s) => String(s?.type || "").toLowerCase() === "agent"
 );
 }
 function tplInputCount(t) {
 return Object.keys(t?.inputs || {}).length;
 }

 function renderWfTemplates() {
 const grid = $("wfTemplateGrid");
 if (!grid) return;
 const filter = _wfTplFilter || "all";
 const list = WF_TEMPLATES.filter((t) => {
 if (filter === "all") return true;
 if (filter === "blank") return t.group === "blank" || t.id === "blank";
 return t.group === filter;
 });
 if (!list.length) {
 grid.innerHTML =
 '<div class="wf-empty-hint">这一类暂时没有模板。</div>';
 return;
 }
 grid.innerHTML = list
 .map((t) => {
 const steps = tplStepCount(t);
 const inputs = tplInputCount(t);
 const hasAi = tplHasAgent(t);
 const selected = t.id === _wfSelectedTplId ? " is-selected" : "";
 const rec = t.recommended ? " is-recommended" : "";
 return `
 <button type="button" class="wf-tpl-card${selected}${rec}" data-wf-tpl="${escapeHtml(
 t.id
 )}" aria-pressed="${t.id === _wfSelectedTplId ? "true" : "false"}">
 <div class="wf-tpl-card-top">
 <span class="wf-tpl-emoji" aria-hidden="true">${escapeHtml(
 t.emoji || "📋"
 )}</span>
 <div class="wf-tpl-card-title">${escapeHtml(t.title)}</div>
 </div>
 <div class="wf-tpl-card-desc">${escapeHtml(t.desc)}</div>
 <div class="wf-tpl-card-meta">
 <span class="wf-tpl-meta-pill">${steps} 步</span>
 ${
 inputs
 ? `<span class="wf-tpl-meta-pill">${inputs} 个填写项</span>`
 : ""
 }
 ${hasAi ? '<span class="wf-tpl-meta-pill ai">含 AI</span>' : ""}
 </div>
 <div class="wf-tpl-card-cta">用这个 →</div>
 </button>`;
 })
 .join("");
 }

 function setWfTplFilter(group) {
 _wfTplFilter = group || "all";
 document.querySelectorAll("#wfTplFilters [data-wf-tpl-group]").forEach((btn) => {
 btn.classList.toggle(
 "is-active",
 (btn.getAttribute("data-wf-tpl-group") || "") === _wfTplFilter
 );
 });
 renderWfTemplates();
 }

 function updateWfCreateStepIndicators(phase) {
 const bar = $("wfCreateSteps");
 if (!bar) return;
 bar.querySelectorAll("[data-wf-phase-ind]").forEach((el) => {
 const n = el.getAttribute("data-wf-phase-ind");
 el.classList.remove("is-active", "is-done");
 if (phase === "pick" && n === "1") el.classList.add("is-active");
 if (phase === "edit") {
 if (n === "1") el.classList.add("is-done");
 if (n === "2") el.classList.add("is-active");
 }
 });
 }

 function setWfCreatePhase(phase) {
 _wfCreatePhase = phase === "pick" ? "pick" : "edit";
 const pick = $("wfPhasePick");
 const edit = $("wfPhaseEdit");
 const footPick = $("wfFooterPick");
 const footEdit = $("wfFooterEdit");
 const createSteps = $("wfCreateSteps");
 const isNew = !_wfEditingId;

 if (_wfCreatePhase === "pick") {
 pick?.classList.remove("hidden");
 edit?.classList.add("hidden");
 footPick?.removeAttribute("hidden");
 footEdit?.setAttribute("hidden", "");
 if (createSteps) {
 createSteps.hidden = false;
 }
 updateWfCreateStepIndicators("pick");
 } else {
 pick?.classList.add("hidden");
 edit?.classList.remove("hidden");
 footPick?.setAttribute("hidden", "");
 footEdit?.removeAttribute("hidden");
 if (createSteps) {
 createSteps.hidden = !isNew;
 }
 updateWfCreateStepIndicators("edit");
 updateWfEditToolbar();
 updateWfEditStats();
 updateWfNameMeta();
 }
 }

 function updateWfEditToolbar() {
 const chip = $("wfTplChip");
 const chipLabel = $("wfTplChipLabel");
 const chipEmoji = $("wfTplChipEmoji");
 const changeBtn = $("btnWfChangeTemplate");
 const isNew = !_wfEditingId;
 const t = WF_TEMPLATES.find((x) => x.id === _wfSelectedTplId);
 if (isNew && t) {
 if (chip) chip.hidden = false;
 if (chipLabel) chipLabel.textContent = t.title || t.id;
 if (chipEmoji) chipEmoji.textContent = t.emoji || "📋";
 if (changeBtn) changeBtn.hidden = false;
 } else if (isNew) {
 if (chip) chip.hidden = false;
 if (chipLabel) chipLabel.textContent = "自定义流程";
 if (chipEmoji) chipEmoji.textContent = "✨";
 if (changeBtn) changeBtn.hidden = false;
 } else {
 if (chip) chip.hidden = true;
 if (changeBtn) changeBtn.hidden = true;
 }
 }

 function updateWfEditStats() {
 const el = $("wfEditStats");
 const inputs = collectInputsFromBuilder();
 const steps = collectStepsFromBuilder();
 const nIn = Object.keys(inputs || {}).length;
 const nSt = (steps || []).length;
 const nAi = (steps || []).filter(
 (s) => String(s.type || "").toLowerCase() === "agent"
 ).length;
 if (el) {
 el.textContent =
 `${nSt} 步` +
 (nAi ? ` · ${nAi} AI` : "") +
 (nIn ? ` · ${nIn} 填写项` : "");
 }
 const inSum = $("wfInputsSummary");
 if (inSum) {
 inSum.textContent = nIn ? `已设 ${nIn} 项` : "可选 · 无";
 }
 const stHint = $("wfStepsHint");
 if (stHint) {
 stHint.textContent = nSt
 ? `共 ${nSt} 步，从上到下执行`
 : "点上方按钮加一步";
 }
 }

 function updateWfNameMeta() {
 const name = ($("wfName")?.value || "").trim();
 const countEl = $("wfNameCount");
 const hintEl = $("wfNameHint");
 if (countEl) {
 const raw = $("wfName")?.value || "";
 countEl.textContent = `${raw.length}/80`;
 }
 if (hintEl) {
 hintEl.textContent = name
 ? "看起来不错，保存后会出现在列表里"
 : "起个好认的名字，方便以后找";
 }
 $("wfName")?.classList.toggle("wf-section-invalid", !name && _wfDirty);
 }

 async function applyWfTemplate(tplId, opts) {
 const t = WF_TEMPLATES.find((x) => x.id === tplId);
 if (!t) return;
 const force = !!(opts && opts.force);
 const goEdit = opts && opts.goEdit !== false;

 if (
 !force &&
 _wfCreatePhase === "edit" &&
 _wfDirty &&
 _wfSelectedTplId &&
 _wfSelectedTplId !== tplId
 ) {
 const ok = confirm("换模板会覆盖当前名称、参数和步骤，确定换吗？");
 if (!ok) return;
 }

 _wfSelectedTplId = t.id;
 if (t.name && $("wfName")) $("wfName").value = t.name;
 else if ($("wfName") && t.id === "blank") $("wfName").value = "";
 if ($("wfDesc")) $("wfDesc").value = t.description || "";
 if ($("wfInputs"))
 $("wfInputs").value = JSON.stringify(t.inputs || {}, null, 2);
 if ($("wfSteps"))
 $("wfSteps").value = JSON.stringify(t.steps || [], null, 2);
 renderInputsBuilder(t.inputs || {});
 await renderStepsBuilder(t.steps || []);
 _wfDirty = false;
 renderWfTemplates();

 if (goEdit || _wfCreatePhase === "edit") {
 setWfCreatePhase("edit");
 const moreBasics = document.querySelector("#wfPhaseEdit .wf-more-basics");
 if (moreBasics) moreBasics.open = !!(t.description || "").trim();
 const inSec = $("wfSectionInputs");
 if (inSec) inSec.open = Object.keys(t.inputs || {}).length > 0;
 setMsg(
 "msgWfEdit",
 t.id === "blank"
 ? "空白流程：先起名，再点上方按钮加步骤"
 : `已套用「${t.title}」，可改名字和步骤`,
 "ok"
 );
 requestAnimationFrame(() => {
 $("wfName")?.focus();
 $("wfName")?.select?.();
 });
 } else {
 setMsg("msgWfEdit", "", "");
 }
 updateWfEditStats();
 updateWfNameMeta();
 }

 // ---- List ----
 async function loadWorkflows(opts = {}) {
 const soft = !!(opts && opts.soft);
 initWorkflowPanel();
 const list = $("workflowList");
 const runsEl = $("workflowRunList");
 if (!list) return;
 const keepUi = soft && list.querySelector(".card");
 if (!keepUi) {
  list.innerHTML = "";
  if (runsEl) runsEl.innerHTML = "";
  setMsg("msgWorkflows", "载入中…");
 }
 try {
 await fetchSessionList(false);
 const items = await api("/api/workflows");
 const arr = Array.isArray(items) ? items : [];
 if (!arr.length) {
 list.innerHTML =
 '<div class="card"><div class="card-body"><div class="card-sub">还没有流程。点右上角「新建流程」，选一个模板就能开始。</div></div></div>';
 } else {
 for (const w of arr) {
 const card = document.createElement("div");
 card.className =
 "card wf-def-card" + (w.enabled === false ? " card-disabled" : "");
 card.dataset.wfId = w.id || "";
 const enPill =
 w.enabled === false
 ? '<span class="wf-status-pill wf-st-cancel">已停用</span>'
 : '<span class="wf-status-pill wf-st-ok">可用</span>';
 const aiPill = w.has_agent_steps
 ? '<span class="wf-status-pill wf-st-run">含 AI</span>'
 : "";
 const schedLabel = wfScheduleLabel(w.schedule);
 const schedPill = schedLabel
 ? `<span class="wf-status-pill wf-st-run">${escapeHtml(schedLabel)}</span>`
 : "";
 const sessRow = w.default_session_id
 ? findSessionRow(_sessionListCache.rows, w.default_session_id)
 : null;
 let sessLabel = "运行时选择对话";
 if (w.always_new_session) sessLabel = "每次新建对话";
 else if (sessRow) sessLabel = "对话：" + sessionDisplayName(sessRow);
 else if (w.default_session_id) sessLabel = "已指定对话";
 const stepN = w.step_count || 0;
 card.innerHTML = `
 <div class="card-body">
 <div class="card-title-row">
 <div class="card-title">${escapeHtml(w.name || w.id)}</div>
 ${enPill}${aiPill}${schedPill}
 </div>
 <div class="card-sub">一共 ${stepN} 步 · ${escapeHtml(sessLabel)} · 点「开始」按顺序自动做${
 w.has_agent_steps ? "（AI 步骤会后台跑，可看进度）" : ""
 }${schedLabel ? " · 已定时" : ""}</div>
 <div class="card-sub muted-line">${escapeHtml(
 w.description || "暂无说明"
 )}</div>
 </div>
 <div class="card-actions wf-card-actions">
 <button type="button" class="btn primary run-wf icon-inline" data-wf-id="${escapeHtml(
 w.id || ""
 )}" title="开始">
 ${_ipk("play", "ipk-sm")} 开始
 </button>
 <button type="button" class="btn edit-wf" data-wf-id="${escapeHtml(
 w.id || ""
 )}">改一改</button>
 <button type="button" class="btn danger del-wf icon-btn" data-wf-id="${escapeHtml(
 w.id || ""
 )}" title="删除">${_ipk("delete", "ipk-sm")}</button>
 </div>`;
 list.appendChild(card);
 }
 }
 setMsg(
 "msgWorkflows",
 arr.length ? `共 ${arr.length} 个流程` : "暂无流程",
 "ok"
 );

 const runs = await api("/api/workflows/runs?limit=50");
 const toolbar = $("wfRunsToolbar");
 const selectAll = $("wfRunSelectAll");
 if (selectAll) selectAll.checked = false;
 if (runsEl && Array.isArray(runs)) {
 if (!runs.length) {
 if (toolbar) toolbar.hidden = true;
 runsEl.innerHTML =
 '<div class="card"><div class="card-body"><div class="card-sub">还没有跑过。选一个流程点「开始」试试。</div></div></div>';
 } else {
 if (toolbar) toolbar.hidden = false;
 for (const r of runs) {
 const c = document.createElement("div");
 c.className = "card wf-run-card";
 c.dataset.runId = r.id || "";
 const when = r.created_at
 ? String(r.created_at).replace("T", " ").slice(0, 16)
 : "";
 const title = r.workflow_name || r.workflow_id || "流程";
 const who =
 r.trigger === "ui"
 ? "你点的"
 : r.trigger === "agent"
 ? "AI 触发"
 : r.trigger || "";
 const runSess = r.session_id
 ? findSessionRow(_sessionListCache.rows, r.session_id)
 : null;
 const sessBit = runSess
 ? " · " + sessionDisplayName(runSess)
 : "";
 c.innerHTML = `
 <label class="wf-run-check" title="勾选删除">
 <input type="checkbox" class="wf-run-cb" data-run-id="${escapeHtml(
 r.id || ""
 )}" />
 </label>
 <div class="card-body">
 <div class="card-title-row">
 <div class="card-title">${escapeHtml(title)}</div>
 ${wfStatusPill(r.status)}
 </div>
 <div class="card-sub">${escapeHtml(when)} · 做了 ${
 r.step_count || 0
 } 步${who ? " · " + who : ""}${escapeHtml(sessBit)}${
 r.error ? " · " + escapeHtml(String(r.error).slice(0, 48)) : ""
 }</div>
 </div>
 <div class="card-actions">
 <button type="button" class="btn ghost-sm view-run" data-run-id="${escapeHtml(
 r.id || ""
 )}">看看详情</button>
 ${
 r.session_id
 ? `<button type="button" class="btn ghost-sm open-run-session" data-session-id="${escapeHtml(
 r.session_id
 )}">打开对话</button>`
 : ""
 }
 ${
 r.status === "waiting_human"
 ? `<button type="button" class="btn primary ghost-sm resume-run" data-run-id="${escapeHtml(
 r.id || ""
 )}">去确认</button>`
 : ""
 }
 <button type="button" class="btn ghost-sm danger del-run" data-run-id="${escapeHtml(
 r.id || ""
 )}" title="删除这条">删除</button>
 </div>`;
 runsEl.appendChild(c);
 }
 updateWfRunSelectionUi();
 }
 }
 if (typeof L.hydrateIconPark === "function") {
 L.hydrateIconPark(list);
 if (runsEl) L.hydrateIconPark(runsEl);
 }
 } catch (e) {
 setMsg("msgWorkflows", e.message, "error");
 }
 }

 function wfScheduleLabel(sched) {
 if (!sched || typeof sched !== "object" || sched.enabled === false) return "";
 if (sched.mode === "off") return "";
 if (sched.run_once || sched.mode === "once") return "跑一次";
 if (sched.interval_seconds) {
 const mins = Math.max(1, Math.round(Number(sched.interval_seconds) / 60) || 60);
 return `每 ${mins} 分钟`;
 }
 if (sched.cron) return `cron ${sched.cron}`;
 return "";
 }

 let _wfSchedMode = "off";
 const WF_SCHED_OPTS = [
 { id: "off", label: "不定时", hint: "只手动点开始" },
 { id: "interval", label: "每隔一段时间", hint: "巡检 / 轮询" },
 { id: "daily", label: "每天固定时刻", hint: "按本地钟点" },
 { id: "cron", label: "高级 Cron", hint: "5 段表达式" },
 { id: "once", label: "只跑一次", hint: "保存后尽快执行" },
 ];

 function renderWfSchedChips() {
 const host = $("wfSchedChips");
 if (!host) return;
 host.innerHTML = "";
 for (const o of WF_SCHED_OPTS) {
 const btn = document.createElement("button");
 btn.type = "button";
 btn.className =
 "kb-chip kb-chip-card" + (_wfSchedMode === o.id ? " is-on" : "");
 btn.innerHTML = `<strong>${escapeHtml(o.label)}</strong><span>${escapeHtml(o.hint)}</span>`;
 btn.addEventListener("click", () => {
 _wfSchedMode = o.id;
 renderWfSchedChips();
 renderWfSchedFields();
 });
 host.appendChild(btn);
 }
 }

 function renderWfSchedFields() {
 const host = $("wfSchedFields");
 const hint = $("wfSchedHint");
 if (!host) return;
 host.innerHTML = "";
 if (_wfSchedMode === "interval") {
 host.innerHTML = `
 <label class="kb-label">每隔多少分钟
 <input id="wfIntervalMin" class="task-field-input" type="number" min="1" max="10080" value="60" />
 </label>`;
 if (hint) hint.textContent = "保存后写入定时任务。例如 60 = 每小时自动跑这个流程。";
 } else if (_wfSchedMode === "daily") {
 host.innerHTML = `
 <label class="kb-label">每天几点（0–23）
 <input id="wfDailyHour" class="task-field-input" type="number" min="0" max="23" value="9" />
 </label>
 <label class="kb-label">几分（0–59）
 <input id="wfDailyMin" class="task-field-input" type="number" min="0" max="59" value="0" />
 </label>`;
 if (hint) hint.textContent = "按电脑本地时区，保存时换成 UTC Cron。";
 } else if (_wfSchedMode === "cron") {
 host.innerHTML = `
 <label class="kb-label full-span">Cron 表达式
 <input id="wfCron" class="task-field-input" type="text" placeholder="0 1 * * *  或  */30 * * * *" />
 </label>`;
 if (hint) hint.textContent = "格式：分 时 日 月 周（调度器时区 UTC）。";
 } else if (_wfSchedMode === "once") {
 host.innerHTML =
 '<p class="field-hint full-span" style="margin:0">保存后会建一条只跑一次的定时任务。</p>';
 if (hint) hint.textContent = "一次性。适合「稍后自动跑完这个流程」。";
 } else {
 if (hint) hint.textContent = "可选。保存后会写入「设定 → 定时任务」，到点自动跑这个流程。";
 }
 }

 function applyWfScheduleToForm(sched) {
 const s = sched && typeof sched === "object" ? sched : {};
 if (!s.enabled || s.mode === "off") {
 _wfSchedMode = "off";
 } else if (s.run_once || s.mode === "once") {
 _wfSchedMode = "once";
 } else if (s.interval_seconds || s.mode === "interval") {
 _wfSchedMode = "interval";
 } else if (s.mode === "daily" && s.cron) {
 _wfSchedMode = "daily";
 } else if (s.cron && utcCronToLocalDaily(s.cron) && s.mode !== "cron") {
 _wfSchedMode = "daily";
 } else if (s.cron || s.mode === "cron") {
 _wfSchedMode = "cron";
 } else {
 _wfSchedMode = "off";
 }
 renderWfSchedChips();
 renderWfSchedFields();
 if (_wfSchedMode === "interval") {
 const el = $("wfIntervalMin");
 if (el) el.value = String(Math.max(1, Math.round(Number(s.interval_seconds || 3600) / 60)));
 } else if (_wfSchedMode === "daily") {
 const daily = utcCronToLocalDaily(s.cron) || { hour: 9, minute: 0 };
 const hEl = $("wfDailyHour");
 const mEl = $("wfDailyMin");
 if (hEl) hEl.value = String(daily.hour);
 if (mEl) mEl.value = String(daily.minute);
 } else if (_wfSchedMode === "cron") {
 const el = $("wfCron");
 if (el) el.value = s.cron || "";
 }
 }

 function wfSelectedValueFromDef(w) {
 if (!w) return SESSION_SPECIAL.AUTO;
 if (w.always_new_session) return SESSION_SPECIAL.ALWAYS_NEW;
 if (w.default_session_id) {
 const cur = (state && state.sessionId) || "";
 if (cur && w.default_session_id === cur) return SESSION_SPECIAL.CURRENT;
 return w.default_session_id;
 }
 return SESSION_SPECIAL.AUTO;
 }

 async function renderWfDefaultSessionSelect(selected) {
 const sel = $("wfDefaultSessionSelect");
 if (!sel) return;
 const extra = [];
 if (
 selected &&
 selected !== SESSION_SPECIAL.AUTO &&
 selected !== SESSION_SPECIAL.CURRENT &&
 selected !== SESSION_SPECIAL.ALWAYS_NEW
 ) {
 extra.push({ value: selected, label: "已指定的对话" });
 }
 await populateSessionSelect(sel, {
 special: wfSessionSpecials(),
 selected: selected || SESSION_SPECIAL.AUTO,
 extra,
 force: true,
 });
 }

 async function renderWfRunSessionSelect(selected) {
 const sel = $("wfRunSessionSelect");
 if (!sel) return;
 const extra = [];
 if (
 selected &&
 selected !== SESSION_SPECIAL.NEW &&
 selected !== SESSION_SPECIAL.CURRENT
 ) {
 extra.push({ value: selected, label: "流程默认对话" });
 }
 await populateSessionSelect(sel, {
 special: wfRunSessionSpecials(),
 selected: selected || SESSION_SPECIAL.NEW,
 extra,
 force: true,
 });
 }

 function collectWfSession() {
 const picked = resolveSessionSelectValue($("wfDefaultSessionSelect")?.value);
 if (picked.mode === "current" && !picked.session_id) {
 setMsg("msgWfEdit", "请先在主界面打开一个对话，或改选其它对话", "error");
 return null;
 }
 return {
 default_session_id: picked.session_id || "",
 always_new_session: !!picked.always_new_session,
 };
 }

 function collectWfSchedule() {
 if (_wfSchedMode === "off") {
 return { mode: "off", enabled: false };
 }
 if (_wfSchedMode === "interval") {
 const mins = parseInt($("wfIntervalMin")?.value, 10) || 60;
 return {
 mode: "interval",
 enabled: true,
 interval_seconds: Math.max(60, mins * 60),
 run_once: false,
 cron: null,
 };
 }
 if (_wfSchedMode === "daily") {
 const h = Math.min(23, Math.max(0, parseInt($("wfDailyHour")?.value, 10) || 9));
 const m = Math.min(59, Math.max(0, parseInt($("wfDailyMin")?.value, 10) || 0));
 return {
 mode: "daily",
 enabled: true,
 cron: localDailyToUtcCron(h, m),
 interval_seconds: null,
 run_once: false,
 };
 }
 if (_wfSchedMode === "cron") {
 const c = ($("wfCron")?.value || "").trim();
 if (!c) {
 setMsg("msgWfEdit", "请填写 Cron 表达式，或不定时", "error");
 return null;
 }
 return {
 mode: "cron",
 enabled: true,
 cron: c,
 interval_seconds: null,
 run_once: false,
 };
 }
 return { mode: "once", enabled: true, run_once: true, cron: null, interval_seconds: null };
 }

 // ---- Editor ----
 async function openWorkflowEditor(wfId) {
 initWorkflowPanel();
 const modal = getWfPageModal();
 if (!modal) {
 setMsg("msgWorkflows", "编辑器还没加载好，请刷新页面", "error");
 showToast("请刷新页面后再试", "error");
 return;
 }
 await ensureWfTools(true);
 closeWfSkillPicker();
 _wfEditingId = wfId || "";
 _wfDirty = false;
 _wfTplFilter = "all";
 setMsg("msgWfEdit", "");
 const titleEl = $("wfEditorTitle");
 const leadEl = $("wfEditorLead");

 if (wfId) {
 _wfSelectedTplId = "";
 try {
 const w = await api(`/api/workflows/${encodeURIComponent(wfId)}`);
 if ($("wfId")) $("wfId").value = w.id || wfId;
 if ($("wfName")) $("wfName").value = w.name || "";
 if ($("wfDesc")) $("wfDesc").value = w.description || "";
 if ($("wfEnabled")) $("wfEnabled").checked = w.enabled !== false;
 applyWfScheduleToForm(w.schedule);
 await renderWfDefaultSessionSelect(wfSelectedValueFromDef(w));
 if ($("wfInputs"))
 $("wfInputs").value = JSON.stringify(w.inputs || {}, null, 2);
 if ($("wfSteps"))
 $("wfSteps").value = JSON.stringify(w.steps || [], null, 2);
 renderInputsBuilder(w.inputs || {});
 await renderStepsBuilder(w.steps || []);
 // open optional panels only when they have content
 const moreBasics = document.querySelector("#wfPhaseEdit .wf-more-basics");
 if (moreBasics) {
 moreBasics.open = !!(w.description || w.enabled === false);
 }
 const inSec = $("wfSectionInputs");
 if (inSec) {
 inSec.open = Object.keys(w.inputs || {}).length > 0;
 }
 if (titleEl) {
 titleEl.innerHTML = `<span data-ipk="branch-one" data-ipk-class="ipk-sm"></span> 改流程 · ${escapeHtml(
 w.name || w.id || wfId
 )}`;
 }
 if (leadEl) leadEl.textContent = "改名字、加减步骤，保存后立即生效";
 setWfCreatePhase("edit");
 } catch (e) {
 setMsg("msgWorkflows", e.message, "error");
 return;
 }
 } else {
 if ($("wfId")) $("wfId").value = "";
 if ($("wfName")) $("wfName").value = "";
 if ($("wfDesc")) $("wfDesc").value = "";
 if ($("wfEnabled")) $("wfEnabled").checked = true;
 applyWfScheduleToForm({ mode: "off", enabled: false });
 await renderWfDefaultSessionSelect(SESSION_SPECIAL.AUTO);
 if ($("wfInputs")) $("wfInputs").value = "{}";
 if ($("wfSteps")) $("wfSteps").value = "[]";
 renderInputsBuilder({});
 await renderStepsBuilder([]);
 _wfSelectedTplId = "";
 if (titleEl) {
 titleEl.innerHTML =
 '<span data-ipk="branch-one" data-ipk-class="ipk-sm"></span> 新建流程';
 }
 if (leadEl) leadEl.textContent = "先选一个起点，再改名字和步骤";
 setWfTplFilter("all");
 renderWfTemplates();
 setWfCreatePhase("pick");
 }

 modal.classList.remove("hidden");
 document.body.classList.add("wf-page-modal-open");
 if (typeof L.hydrateIconPark === "function") L.hydrateIconPark(modal);
 requestAnimationFrame(() => {
 if (_wfCreatePhase === "edit") $("wfName")?.focus();
 else document.querySelector("#wfTemplateGrid .wf-tpl-card")?.focus();
 });
 }

 function gatherWorkflowBody() {
 if (_wfCreatePhase === "pick") {
 setMsg("msgWfEdit", "请先选一个模板，或点「从空白开始」", "error");
 return null;
 }
 const name = ($("wfName")?.value || "").trim();
 if (!name) {
 setMsg("msgWfEdit", "请给流程起个名字", "error");
 $("wfName")?.classList.add("wf-section-invalid");
 $("wfName")?.focus();
 $("wfSectionBasics")?.scrollIntoView({ behavior: "smooth", block: "start" });
 return null;
 }
 $("wfName")?.classList.remove("wf-section-invalid");
 let inputs = collectInputsFromBuilder();
 let steps = collectStepsFromBuilder();
 if (!Object.keys(inputs).length && ($("wfInputs")?.value || "").trim()) {
 try {
 inputs = JSON.parse($("wfInputs").value || "{}");
 } catch (e) {
 setMsg("msgWfEdit", "高级参数格式有误: " + e.message, "error");
 return null;
 }
 }
 if (!steps.length && ($("wfSteps")?.value || "").trim()) {
 try {
 steps = JSON.parse($("wfSteps").value || "[]");
 if (!Array.isArray(steps)) throw new Error("步骤必须是列表");
 } catch (e) {
 setMsg("msgWfEdit", "高级步骤格式有误: " + e.message, "error");
 return null;
 }
 }
 if (!steps.length) {
 setMsg("msgWfEdit", "至少加一步要做的事（点下方常用按钮）", "error");
 $("wfSectionSteps")?.scrollIntoView({
 behavior: "smooth",
 block: "start",
 });
 return null;
 }
 if ($("wfInputs")) $("wfInputs").value = JSON.stringify(inputs, null, 2);
 if ($("wfSteps")) $("wfSteps").value = JSON.stringify(steps, null, 2);

 const schedule = collectWfSchedule();
 if (!schedule) return null;
 const session = collectWfSession();
 if (!session) return null;

 return {
 id: ($("wfId")?.value || "").trim() || undefined,
 name,
 description: $("wfDesc")?.value || "",
 enabled: !!$("wfEnabled")?.checked,
 inputs,
 steps,
 schedule,
 default_session_id: session.default_session_id,
 always_new_session: session.always_new_session,
 };
 }

 async function saveWorkflow(opts) {
 const andRun = !!(opts && opts.andRun);
 const body = gatherWorkflowBody();
 if (!body) return null;
 try {
 const saved = await api("/api/workflows", {
 method: "POST",
 body: JSON.stringify(body),
 });
 if ($("wfId")) $("wfId").value = saved.id || "";
 _wfEditingId = saved.id || "";
 _wfDirty = false;
 setMsg("msgWfEdit", "已保存", "ok");
 showToast("流程已保存", "success");
 await loadWorkflows();
 if (andRun && saved.id) {
 // skip dirty confirm on intentional close
 _wfDirty = false;
 const modal = getWfPageModal();
 if (modal) modal.classList.add("hidden");
 document.body.classList.remove("wf-page-modal-open");
 await openWfRunModal(saved.id);
 }
 return saved;
 } catch (e) {
 setMsg("msgWfEdit", e.message, "error");
 showToast("保存失败", "error");
 return null;
 }
 }

 // ---- Run UI ----
 function friendlyStepTitle(s) {
 if (!s) return "步骤";
 if (s.type === "note") return "说明";
 if (s.type === "human_gate") return "需要你确认";
 if (s.type === "agent") return "AI 思考 · " + (s.id || "agent");
 if (s.status === "skipped") return "已跳过 · " + (s.id || "步骤");
 if (s.tool === "workspace") {
 const a = (s.args || {}).action || "";
 if (a === "list") return "看文件夹";
 if (a === "write") return "写文件";
 if (a === "read") return "读文件";
 return "操作文件";
 }
 if (s.tool === "kb") return "查知识库";
 if (s.tool === "get_current_time") return "看时间";
 if (s.tool) {
 const t = wfToolByName(s.tool);
 return (t && t.label) || String(s.tool);
 }
 return s.id || "步骤";
 }

 function renderRunTimeline(run, result) {
 const host = $("wfRunTimeline");
 if (!host) return;
 const steps = (run && run.steps) || [];
 const status = (result && result.status) || (run && run.status) || "";
 if (!steps.length) {
 host.innerHTML =
 '<div class="wf-empty-hint">还没有结果。点「开始」后这里会显示进度。</div>';
 return;
 }
 const lines = steps
 .map((s, i) => {
 const title = friendlyStepTitle(s);
 const st = s.status || "";
 const out =
 s.output != null
 ? String(s.output)
 : s.error
 ? String(s.error)
 : s.prompt
 ? String(s.prompt)
 : "";
 const preview =
 out.length > 280 ? out.slice(0, 280) + "…" : out;
 return `<div class="wf-tl-item wf-tl-${escapeHtml(st)}">
 <div class="wf-tl-head">
 <span class="wf-step-idx">${i + 1}</span>
 <strong>${escapeHtml(title)}</strong>
 ${wfStatusPill(st)}
 </div>
 ${
 preview
 ? `<div class="wf-tl-body">${escapeHtml(preview)}</div>`
 : ""
 }
 </div>`;
 })
 .join("");
 let footer = "";
 if (status === "succeeded") {
 footer =
 '<div class="wf-tl-footer ok">全部做完了 ✅</div>';
 } else if (status === "waiting_human") {
 footer =
 '<div class="wf-tl-footer wait">流程停在「等你确认」——看下方按钮</div>';
 } else if (status === "failed") {
 footer = `<div class="wf-tl-footer fail">中断了：${escapeHtml(
 String((result && result.error) || (run && run.error) || "未知错误")
 )}</div>`;
 } else if (status === "cancelled") {
 footer = '<div class="wf-tl-footer">已按你的选择停下</div>';
 }
 host.innerHTML = lines + footer;
 }

 async function openWfRunModal(wfId) {
 initWorkflowPanel();
 const modal = $("wfRunModal");
 if (!modal || !wfId) {
 setMsg("msgWorkflows", "打不开运行窗口", "error");
 return;
 }
 setMsg("msgWfRun", "");
 _wfCurrentRunId = "";
 if ($("wfRunId")) $("wfRunId").value = wfId;
 if ($("wfRunResult")) $("wfRunResult").textContent = "";
 if ($("wfRunTimeline")) {
 $("wfRunTimeline").innerHTML =
 '<div class="wf-empty-hint">点「开始」后，这里会逐步显示做了什么。</div>';
 }
 $("wfRunGateBar")?.classList.add("hidden");
 $("btnDoWfRun")?.classList.remove("hidden");
 $("btnWfOpenRunSession")?.classList.add("hidden");
 $("btnWfOpenRunSession")?.removeAttribute("data-session-id");

 try {
 const w = await api(`/api/workflows/${encodeURIComponent(wfId)}`);
 const title = $("wfRunTitle");
 if (title) {
 title.innerHTML = `<span data-ipk="play" data-ipk-class="ipk-sm"></span> ${escapeHtml(
 w.name || "开始跑流程"
 )}`;
 }
 if ($("wfRunLead")) {
 $("wfRunLead").textContent =
 w.description || "填好下面内容（如果有），再点开始";
 }
 renderRunInputsForm(w.inputs || {});
 let preselect = SESSION_SPECIAL.NEW;
 if (w.always_new_session) preselect = SESSION_SPECIAL.NEW;
 else if (w.default_session_id) preselect = w.default_session_id;
 else if (state && state.sessionId) preselect = SESSION_SPECIAL.CURRENT;
 await renderWfRunSessionSelect(preselect);
 modal.classList.remove("hidden");
 document.body.classList.add("wf-run-modal-open");
 if (typeof L.hydrateIconPark === "function") L.hydrateIconPark(modal);
 } catch (e) {
 setMsg("msgWorkflows", e.message, "error");
 showToast(e.message, "error");
 }
 }

 function renderRunInputsForm(inputsSpec) {
 const host = $("wfRunInputsHost");
 if (!host) return;
 const spec = inputsSpec && typeof inputsSpec === "object" ? inputsSpec : {};
 const keys = Object.keys(spec);
 if (!keys.length) {
 host.innerHTML =
 '<div class="wf-empty-hint">这个流程不用额外填写，直接点「开始」就行。</div>';
 return;
 }
 host.innerHTML =
 '<p class="field-hint" style="margin:0 0 8px">运行前请确认 / 修改下面内容：</p>' +
 keys
 .map((key) => {
 const meta = spec[key];
 const type =
 typeof meta === "object" && meta
 ? meta.type || "string"
 : "string";
 const def =
 typeof meta === "object" && meta && "default" in meta
 ? meta.default
 : typeof meta !== "object"
 ? meta
 : "";
 const label =
 typeof meta === "object" && meta && meta.label
 ? meta.label
 : key;
 const defStr = def === undefined || def === null ? "" : String(def);
 if (type === "boolean") {
 const checked =
 def === true || def === "true" || def === 1 || def === "1";
 return `<label class="kb-check-line wf-run-field">
 <input type="checkbox" class="wf-run-in" data-key="${escapeHtml(
 key
 )}" data-type="boolean"${checked ? " checked" : ""} />
 <span>${escapeHtml(label)}</span>
 </label>`;
 }
 const inputType = type === "number" ? "number" : "text";
 return `<label class="kb-label wf-run-field">${escapeHtml(label)}
 <input class="wf-run-in task-field-input" type="${inputType}" data-key="${escapeHtml(
 key
 )}" data-type="${escapeHtml(
 type
 )}" value="${escapeHtml(defStr)}" placeholder="${escapeHtml(
 defStr || label
 )}" />
 </label>`;
 })
 .join("");
 }

 function collectRunInputs() {
 const host = $("wfRunInputsHost");
 const out = {};
 if (!host) return out;
 host.querySelectorAll(".wf-run-in").forEach((el) => {
 const key = el.dataset.key;
 if (!key) return;
 const type = el.dataset.type || "string";
 if (type === "boolean") out[key] = !!el.checked;
 else if (type === "number") {
 const n = Number(el.value);
 out[key] = el.value === "" || Number.isNaN(n) ? el.value : n;
 } else out[key] = el.value;
 });
 return out;
 }

 function applyRunResultToUi(result) {
 const pre = $("wfRunResult");
 const run = result.run || result;
 renderRunTimeline(run, result);
 if (pre) {
 const slim = {
 ok: result.ok,
 status: result.status || run.status,
 error: result.error || run.error,
 message: result.message,
 run_id: run.id,
 steps: (run.steps || []).map((s) => ({
 id: s.id,
 type: s.type,
 tool: s.tool,
 status: s.status,
 output: s.output
 ? String(s.output).slice(0, 500) +
 (String(s.output).length > 500 ? "…" : "")
 : s.output,
 error: s.error,
 })),
 };
 pre.textContent = JSON.stringify(slim, null, 2);
 }
 const status = result.status || run.status;
 const sid = run.session_id || result.session_id;
 const openBtn = $("btnWfOpenRunSession");
 if (openBtn) {
 if (sid) {
 openBtn.classList.remove("hidden");
 openBtn.setAttribute("data-session-id", sid);
 } else {
 openBtn.classList.add("hidden");
 }
 }
 const gateBar = $("wfRunGateBar");
 if (status === "waiting_human") {
 _wfCurrentRunId = run.id || "";
 gateBar?.classList.remove("hidden");
 if ($("wfRunGateMsg")) {
 $("wfRunGateMsg").textContent =
 result.message ||
 "流程想确认一下再继续。可以点「好的，继续」或「先停在这里」。";
 }
 $("btnDoWfRun")?.classList.add("hidden");
 } else {
 gateBar?.classList.add("hidden");
 $("btnDoWfRun")?.classList.remove("hidden");
 }
 return status;
 }

 async function pollWfRunUntilDone(runId, opts) {
 const maxMs = (opts && opts.maxMs) || 10 * 60 * 1000;
 const interval = (opts && opts.interval) || 1500;
 const started = Date.now();
 let last = null;
 while (Date.now() - started < maxMs) {
 await new Promise((r) => setTimeout(r, interval));
 try {
 const run = await api(
 `/api/workflows/runs/${encodeURIComponent(runId)}`
 );
 last = { ok: true, status: run.status, run, error: run.error };
 applyRunResultToUi(last);
 const st = run.status || "";
 if (WF_TERMINAL.has(st)) return last;
 setMsg(
 "msgWfRun",
 st === "running"
 ? `正在跑…${run.current_step ? " · " + run.current_step : ""}`
 : String(st),
 "ok"
 );
 } catch (e) {
 /* keep polling briefly */
 }
 }
 return (
 last || {
 ok: false,
 status: "running",
 error: "等待超时，可稍后在「最近跑过的记录」查看",
 }
 );
 }

 async function doDirectWfRun() {
 const id = ($("wfRunId")?.value || "").trim();
 if (!id) {
 setMsg("msgWfRun", "找不到要跑的流程", "error");
 return;
 }
 const inputs = collectRunInputs();
 const picked = resolveSessionSelectValue($("wfRunSessionSelect")?.value);
 if (picked.mode === "current" && !picked.session_id) {
 setMsg("msgWfRun", "请先在主界面打开一个对话，或改选其它对话", "error");
 return;
 }
 setMsg("msgWfRun", "正在跑…");
 const btn = $("btnDoWfRun");
 if (btn) btn.disabled = true;
 try {
 const result = await api(`/api/workflows/${encodeURIComponent(id)}/run`, {
 method: "POST",
 body: JSON.stringify({
 inputs,
 trigger: "ui",
 background: true,
 session_id: picked.session_id || "",
 always_new_session: !!picked.always_new_session,
 }),
 });
 let finalResult = result;
 applyRunResultToUi(result);
 let status = result.status || (result.run && result.run.status) || "";
 if (result.background && result.run && result.run.id) {
 _wfCurrentRunId = result.run.id;
 setMsg("msgWfRun", "后台执行中，进度会自动刷新…", "ok");
 finalResult = await pollWfRunUntilDone(result.run.id);
 status =
 finalResult.status ||
 (finalResult.run && finalResult.run.status) ||
 "";
 } else {
 status = applyRunResultToUi(result);
 }
 if (status === "succeeded") {
 setMsg("msgWfRun", "全部完成", "ok");
 showToast("流程跑完了", "success");
 } else if (status === "waiting_human") {
 setMsg("msgWfRun", "等你确认", "ok");
 showToast("需要你点一下确认", "info");
 } else if (status === "running") {
 setMsg(
 "msgWfRun",
 (finalResult && finalResult.error) || "仍在运行，请稍后查看记录",
 "error"
 );
 } else {
 setMsg(
 "msgWfRun",
 (finalResult && finalResult.error) ||
 (result && result.error) ||
 "没跑完",
 "error"
 );
 showToast(
 (finalResult && finalResult.error) || result.error || "出了点问题",
 "error"
 );
 }
 await loadWorkflows();
 } catch (e) {
 setMsg("msgWfRun", e.message, "error");
 showToast(e.message, "error");
 } finally {
 if (btn) btn.disabled = false;
 }
 }

 async function resumeCurrentRun(approved) {
 const runId = _wfCurrentRunId;
 if (!runId) {
 setMsg("msgWfRun", "没有等待确认的流程", "error");
 return;
 }
 const note = approved ? "用户确认继续" : "用户选择停下";
 setMsg("msgWfRun", approved ? "继续跑…" : "正在停下…");
 try {
 const result = await api(
 `/api/workflows/runs/${encodeURIComponent(runId)}/resume`,
 {
 method: "POST",
 body: JSON.stringify({
 approved: !!approved,
 note,
 background: !!approved,
 }),
 }
 );
 let finalResult = result;
 let status = applyRunResultToUi(result);
 if (approved && result.background) {
 setMsg("msgWfRun", "后台继续执行中…", "ok");
 finalResult = await pollWfRunUntilDone(runId);
 status =
 finalResult.status ||
 (finalResult.run && finalResult.run.status) ||
 status;
 }
 if (status === "succeeded") {
 setMsg("msgWfRun", "全部完成", "ok");
 showToast("流程跑完了", "success");
 } else if (status === "waiting_human") {
 setMsg("msgWfRun", "还要再确认一次", "ok");
 } else if (status === "cancelled") {
 setMsg("msgWfRun", "已停下", "ok");
 showToast("已停下", "info");
 } else if (finalResult && finalResult.ok === false) {
 setMsg("msgWfRun", finalResult.error || "失败", "error");
 } else if (status === "running") {
 setMsg("msgWfRun", "仍在运行，请稍后查看记录", "ok");
 } else {
 setMsg("msgWfRun", "好了", "ok");
 }
 await loadWorkflows();
 } catch (e) {
 setMsg("msgWfRun", e.message, "error");
 }
 }

 async function openWfRunDetail(runId) {
 if (!runId) return;
 initWorkflowPanel();
 const modal = $("wfRunDetailModal");
 if (!modal) return;
 try {
 const run = await api(`/api/workflows/runs/${encodeURIComponent(runId)}`);
 _wfCurrentRunId = run.status === "waiting_human" ? run.id : "";
 const name = run.workflow_name || run.workflow_id || "流程";
 if ($("wfRunDetailTitle")) {
 $("wfRunDetailTitle").innerHTML = `${escapeHtml(name)} ${wfStatusPill(
 run.status
 )}`;
 }
 if ($("wfRunDetailLead")) {
 const when = run.created_at
 ? String(run.created_at).replace("T", " ").slice(0, 16)
 : "";
 const sessRow = run.session_id
 ? findSessionRow(_sessionListCache.rows, run.session_id)
 : null;
 const sessBit = sessRow
 ? ` · 对话：${sessionDisplayName(sessRow)}`
 : run.session_id
 ? " · 已写入指定对话"
 : "";
 $("wfRunDetailLead").textContent = when
 ? `这次运行时间：${when}${sessBit}`
 : `逐步结果如下${sessBit}`;
 }
 const host = $("wfRunDetailSteps");
 if (host) {
 const steps = run.steps || [];
 if (!steps.length) {
 host.innerHTML = '<div class="wf-empty-hint">还没有任何步骤记录</div>';
 } else {
 host.innerHTML = steps
 .map((s, i) => {
 const title = friendlyStepTitle(s);
 const out =
 s.output != null ? String(s.output) : s.error || "";
 const preview =
 out.length > 400 ? out.slice(0, 400) + "…" : out;
 return `<div class="wf-detail-step">
 <div class="wf-detail-step-head">
 <span class="wf-step-idx">${i + 1}</span>
 <strong>${escapeHtml(title)}</strong>
 ${wfStatusPill(s.status)}
 </div>
 ${
 s.prompt
 ? `<div class="card-sub">问：${escapeHtml(s.prompt)}</div>`
 : ""
 }
 ${
 preview
 ? `<pre class="wf-detail-out">${escapeHtml(preview)}</pre>`
 : ""
 }
 </div>`;
 })
 .join("");
 if (run.status === "waiting_human") {
 host.innerHTML += `
 <div class="wf-gate-bar" style="margin-top:12px">
 <p class="field-hint" style="margin:0 0 8px">流程在等你拍板</p>
 <div class="row-actions" style="margin:0">
 <button type="button" class="btn primary" id="btnWfDetailResume">好的，继续</button>
 <button type="button" class="btn danger" id="btnWfDetailReject">先停在这里</button>
 </div>
 </div>`;
 }
 }
 }
 if ($("wfRunDetailRaw")) {
 $("wfRunDetailRaw").textContent = JSON.stringify(
 {
 id: run.id,
 status: run.status,
 inputs: run.inputs,
 error: run.error,
 finished_at: run.finished_at,
 },
 null,
 2
 );
 }
 modal.classList.remove("hidden");
 document.body.classList.add("wf-run-detail-open");
 if (typeof L.hydrateIconPark === "function") L.hydrateIconPark(modal);
 } catch (e) {
 showToast(e.message, "error");
 }
 }

 async function deleteWorkflow(id) {
 const wid = String(id || "").trim();
 if (!wid) {
 showToast("找不到要删除的流程 id", "error");
 setMsg("msgWorkflows", "删除失败：缺少流程 id", "error");
 return;
 }
 if (
 !confirm(
 "确定删掉这个流程？删了不能恢复（内置示例也不会再自动出现，除非重新创建）。"
 )
 ) {
 return;
 }
 try {
 const res = await api(`/api/workflows/${encodeURIComponent(wid)}`, {
 method: "DELETE",
 });
 const name = (res && res.name) || wid;
 setMsg("msgWorkflows", `已删除：${name}`, "ok");
 showToast("流程已删除", "success");
 await loadWorkflows();
 } catch (e) {
 setMsg("msgWorkflows", e.message || "删除失败", "error");
 showToast(e.message || "删除失败", "error");
 }
 }

 function getSelectedWfRunIds() {
 const runsEl = $("workflowRunList");
 if (!runsEl) return [];
 return Array.from(runsEl.querySelectorAll(".wf-run-cb:checked"))
 .map((el) => el.getAttribute("data-run-id") || "")
 .filter(Boolean);
 }

 function updateWfRunSelectionUi() {
 const ids = getSelectedWfRunIds();
 const btn = $("btnWfDeleteSelectedRuns");
 if (btn) {
 btn.disabled = !ids.length;
 btn.textContent = ids.length
 ? `删除所选 (${ids.length})`
 : "删除所选";
 }
 const runsEl = $("workflowRunList");
 const all = runsEl
 ? runsEl.querySelectorAll(".wf-run-cb")
 : [];
 const checked = runsEl
 ? runsEl.querySelectorAll(".wf-run-cb:checked")
 : [];
 const selectAll = $("wfRunSelectAll");
 if (selectAll && all.length) {
 selectAll.checked = checked.length === all.length;
 selectAll.indeterminate =
 checked.length > 0 && checked.length < all.length;
 } else if (selectAll) {
 selectAll.checked = false;
 selectAll.indeterminate = false;
 }
 runsEl?.querySelectorAll(".wf-run-card").forEach((card) => {
 const on = !!card.querySelector(".wf-run-cb:checked");
 card.classList.toggle("is-selected", on);
 });
 }

 async function deleteSelectedWfRuns() {
 const ids = getSelectedWfRunIds();
 if (!ids.length) {
 showToast("请先勾选要删除的记录", "info");
 return;
 }
 if (
 !confirm(
 `确定删除选中的 ${ids.length} 条运行记录？删除后不能恢复。`
 )
 ) {
 return;
 }
 try {
 const res = await api("/api/workflows/runs/bulk-delete", {
 method: "POST",
 body: JSON.stringify({ ids }),
 });
 const n = res.count ?? ids.length;
 setMsg("msgWorkflows", `已删除 ${n} 条记录`, "ok");
 showToast(`已删除 ${n} 条`, "success");
 await loadWorkflows();
 } catch (e) {
 setMsg("msgWorkflows", e.message, "error");
 showToast(e.message, "error");
 }
 }

 async function clearAllWfRuns() {
 if (
 !confirm(
 "确定清空全部运行记录？只删历史，不会删除流程定义。此操作不可恢复。"
 )
 ) {
 return;
 }
 try {
 const res = await api("/api/workflows/runs", { method: "DELETE" });
 const n = res.count ?? 0;
 setMsg("msgWorkflows", n ? `已清理 ${n} 条记录` : "没有可清理的记录", "ok");
 showToast(n ? `已清理 ${n} 条` : "已是空的", "success");
 await loadWorkflows();
 } catch (e) {
 setMsg("msgWorkflows", e.message, "error");
 showToast(e.message, "error");
 }
 }

 async function deleteOneWfRun(runId) {
 if (!runId || !confirm("确定删除这条运行记录？")) return;
 try {
 await api(`/api/workflows/runs/${encodeURIComponent(runId)}`, {
 method: "DELETE",
 });
 setMsg("msgWorkflows", "已删除该记录", "ok");
 showToast("已删除", "success");
 await loadWorkflows();
 } catch (e) {
 setMsg("msgWorkflows", e.message, "error");
 showToast(e.message, "error");
 }
 }

 async function runWorkflow(wfId) {
 await openWfRunModal(wfId);
 }

 function initWorkflowPanel() {
 if (initWorkflowPanel._done) return;
 if (!$("btnNewWorkflow") && !$("wfPageModal") && !$("workflowList")) return;
 initWorkflowPanel._done = true;
 $("wfPageModal")?.addEventListener("click", (e) => {
 if (e.target === $("wfPageModal")) closeWfPageModal();
 });
 $("wfRunModal")?.addEventListener("click", (e) => {
 if (e.target === $("wfRunModal")) closeWfRunModal();
 });
 $("wfRunDetailModal")?.addEventListener("click", (e) => {
 if (e.target === $("wfRunDetailModal")) closeWfRunDetailModal();
 });
 // run history selection
 $("workflowRunList")?.addEventListener("change", (e) => {
 const t = e.target;
 if (!(t instanceof Element)) return;
 if (t.classList.contains("wf-run-cb")) updateWfRunSelectionUi();
 });
 $("wfRunSelectAll")?.addEventListener("change", (e) => {
 const on = !!(e.target && e.target.checked);
 $("workflowRunList")
 ?.querySelectorAll(".wf-run-cb")
 .forEach((cb) => {
 cb.checked = on;
 });
 updateWfRunSelectionUi();
 });
 // live meta + dirty tracking in editor
 $("wfPageModal")?.addEventListener("input", (e) => {
 const t = e.target;
 if (!(t instanceof Element)) return;
 if (!t.closest("#wfPhaseEdit")) return;
 _wfDirty = true;
 if (t.id === "wfName" || t.id === "wfDesc") updateWfNameMeta();
 if (
 t.closest("#wfInputsBuilder") ||
 t.closest("#wfStepsBuilder") ||
 t.classList.contains("wf-fld") ||
 t.classList.contains("wf-st-action")
 ) {
 updateWfEditStats();
 }
 });
 $("wfPageModal")?.addEventListener("change", (e) => {
 const t = e.target;
 if (!(t instanceof Element)) return;
 if (!t.closest("#wfPhaseEdit")) return;
 _wfDirty = true;
 updateWfEditStats();
 updateWfNameMeta();
 });
 document.addEventListener("keydown", (e) => {
 if (e.key !== "Escape") return;
 const modal = getWfPageModal();
 if (!modal || modal.classList.contains("hidden")) return;
 e.preventDefault();
 if (_wfCreatePhase === "pick") {
 _wfDirty = false;
 closeWfPageModal();
 } else if (!_wfEditingId && _wfSelectedTplId) {
 // new flow: Esc back to template pick
 if (_wfDirty && !confirm("返回选模板？未保存修改可能丢失。")) return;
 setWfCreatePhase("pick");
 renderWfTemplates();
 } else {
 closeWfPageModal();
 }
 });
 }

 if (!window.__lilyWfFormDelegate) {
 window.__lilyWfFormDelegate = true;
 document.addEventListener(
 "click",
 (e) => {
 const t = e.target;
 if (!(t instanceof Element)) return;

 if (t.closest("#btnNewWorkflow")) {
 e.preventDefault();
 openWorkflowEditor("");
 return;
 }
 if (t.closest("#btnRefreshWorkflows")) {
 e.preventDefault();
 loadWorkflows();
 return;
 }
 if (t.closest("#btnWfClearRuns")) {
 e.preventDefault();
 clearAllWfRuns();
 return;
 }
 if (t.closest("#btnWfDeleteSelectedRuns")) {
 e.preventDefault();
 deleteSelectedWfRuns();
 return;
 }
 const delRun = t.closest(".del-run");
 if (delRun) {
 e.preventDefault();
 deleteOneWfRun(delRun.dataset.runId || "");
 return;
 }

 // Workspace path picker (folder / file)
 const pathBrowseBtn = t.closest(".wf-path-browse");
 if (pathBrowseBtn) {
 e.preventDefault();
 const field = pathBrowseBtn.closest(".wf-path-field");
 if (field) openWfPathBrowser(field);
 return;
 }
 const pathBrowser = t.closest(".wf-path-browser");
 if (pathBrowser) {
 const field = pathBrowser.closest(".wf-path-field");
 if (t.closest(".wf-browse-close")) {
 e.preventDefault();
 pathBrowser.classList.add("hidden");
 return;
 }
 const pickEl = t.closest("[data-browse-pick]");
 if (pickEl && !pickEl.hasAttribute("data-browse-enter")) {
 e.preventDefault();
 const p = pickEl.getAttribute("data-browse-pick") || ".";
 setWfPathFieldValue(field, p);
 setMsg(
 "msgWfEdit",
 (field?.dataset.pickMode || "dir") === "file"
 ? "已选择文件"
 : "已选择文件夹",
 "ok"
 );
 return;
 }
 // quick: root as both pick and show — handled above for data-browse-pick="."
 const enterEl =
 t.closest("[data-browse-enter]") ||
 t.closest(".wf-browse-up") ||
 t.closest("[data-browse-nav]");
 if (enterEl) {
 e.preventDefault();
 const nav =
 enterEl.getAttribute("data-browse-enter") ||
 enterEl.getAttribute("data-browse-nav") ||
 ".";
 openWfPathBrowser(field, nav);
 return;
 }
 // use here button has data-browse-pick only
 const useHere = t.closest(".wf-browse-use-here");
 if (useHere) {
 e.preventDefault();
 setWfPathFieldValue(
 field,
 useHere.getAttribute("data-browse-pick") || "."
 );
 setMsg("msgWfEdit", "已选择文件夹", "ok");
 return;
 }
 return;
 }

 const tplFilter = t.closest("#wfTplFilters [data-wf-tpl-group]");
 if (tplFilter) {
 e.preventDefault();
 setWfTplFilter(tplFilter.getAttribute("data-wf-tpl-group") || "all");
 return;
 }

 const tpl = t.closest("[data-wf-tpl]");
 if (tpl && tpl.closest("#wfTemplateGrid")) {
 e.preventDefault();
 applyWfTemplate(tpl.getAttribute("data-wf-tpl") || "", {
 force: _wfCreatePhase === "pick",
 goEdit: true,
 });
 return;
 }
 if (t.closest("#btnWfSkipToBlank")) {
 e.preventDefault();
 applyWfTemplate("blank", { force: true, goEdit: true });
 return;
 }
 if (t.closest("#btnWfChangeTemplate")) {
 e.preventDefault();
 if (
 _wfDirty &&
 !confirm("返回选模板可能覆盖当前编辑内容。要继续吗？")
 ) {
 return;
 }
 setWfCreatePhase("pick");
 renderWfTemplates();
 setMsg("msgWfEdit", "点一张卡片即可换起点", "ok");
 return;
 }
 if (t.closest("#btnCancelWorkflowPick")) {
 e.preventDefault();
 _wfDirty = false;
 closeWfPageModal();
 return;
 }

 const runBtn = t.closest(".run-wf");
 if (runBtn) {
 e.preventDefault();
 openWfRunModal(runBtn.dataset.wfId || "");
 return;
 }
 const editBtn = t.closest(".edit-wf");
 if (editBtn) {
 e.preventDefault();
 openWorkflowEditor(editBtn.dataset.wfId || "");
 return;
 }
 const delBtn = t.closest(".del-wf");
 if (delBtn) {
 e.preventDefault();
 e.stopPropagation();
 const wid =
 delBtn.getAttribute("data-wf-id") ||
 delBtn.dataset.wfId ||
 delBtn.closest(".wf-def-card")?.dataset.wfId ||
 "";
 deleteWorkflow(wid);
 return;
 }
 const viewRun = t.closest(".view-run");
 if (viewRun) {
 e.preventDefault();
 openWfRunDetail(viewRun.dataset.runId || "");
 return;
 }
 const openRunSess = t.closest(".open-run-session");
 if (openRunSess) {
 e.preventDefault();
 const sid = openRunSess.getAttribute("data-session-id") || "";
 if (sid && typeof L.openSession === "function") {
 L.openSession(sid, "工作流对话");
 showToast("已打开流程对话", "success");
 }
 return;
 }
 const resumeList = t.closest(".resume-run");
 if (resumeList) {
 e.preventDefault();
 openWfRunDetail(resumeList.dataset.runId || "");
 return;
 }

 if (t.closest("#btnCloseWfPage") || t.closest("#btnCancelWorkflow")) {
 e.preventDefault();
 closeWfPageModal();
 return;
 }
 if (t.closest("#btnRefreshWfSessions")) {
 e.preventDefault();
 renderWfDefaultSessionSelect($("wfDefaultSessionSelect")?.value);
 return;
 }
 if (t.closest("#btnRefreshWfRunSessions")) {
 e.preventDefault();
 renderWfRunSessionSelect($("wfRunSessionSelect")?.value);
 return;
 }
 if (t.closest("#btnWfOpenRunSession")) {
 e.preventDefault();
 const sid =
 $("btnWfOpenRunSession")?.getAttribute("data-session-id") || "";
 if (sid && typeof L.openSession === "function") {
 L.openSession(sid, "工作流对话");
 showToast("已打开流程对话", "success");
 } else {
 showToast("还没有可打开的对话", "error");
 }
 return;
 }
 if (t.closest("#btnSaveWorkflow")) {
 e.preventDefault();
 saveWorkflow();
 return;
 }
 if (t.closest("#btnRunWorkflowFromEdit")) {
 e.preventDefault();
 saveWorkflow({ andRun: true });
 return;
 }
 if (t.closest("#btnWfAddInput")) {
 e.preventDefault();
 addInputRow();
 return;
 }

 if (t.closest("#btnWfOpenSkillPicker")) {
 e.preventDefault();
 openWfSkillPicker();
 return;
 }
 if (t.closest("#btnCloseWfSkillPicker")) {
 e.preventDefault();
 closeWfSkillPicker();
 return;
 }
 const skillTab = t.closest("#wfSkillTabs [data-wf-src]");
 if (skillTab) {
 e.preventDefault();
 _wfSkillSrc = skillTab.getAttribute("data-wf-src") || "all";
 $("wfSkillTabs")
 ?.querySelectorAll("[data-wf-src]")
 .forEach((b) => b.classList.toggle("is-active", b === skillTab));
 renderWfSkillPickerList();
 return;
 }
 const skillItem = t.closest(".wf-skill-item[data-wf-tool]");
 if (skillItem) {
 e.preventDefault();
 addStepFromToolName(skillItem.getAttribute("data-wf-tool") || "");
 return;
 }

 const actBtn = t.closest("[data-wf-action]");
 if (
 actBtn &&
 (actBtn.closest("#wfAddActionBar") ||
 actBtn.id === "btnWfAddTool" ||
 actBtn.id === "btnWfAddCustom")
 ) {
 e.preventDefault();
 addStepByAction(actBtn.getAttribute("data-wf-action") || "custom");
 return;
 }
 // 旧 id 兼容
 if (t.closest("#btnWfAddNote")) {
 e.preventDefault();
 addStepByAction("note");
 return;
 }
 if (t.closest("#btnWfAddGate")) {
 e.preventDefault();
 addStepByAction("gate");
 return;
 }
 if (t.closest("#btnWfAddTool")) {
 e.preventDefault();
 addStepByAction("custom");
 return;
 }

 if (t.closest("#btnWfSyncFromJson")) {
 e.preventDefault();
 syncInputsBuilderFromJson();
 syncStepsBuilderFromJson();
 setMsg("msgWfEdit", "已同步到上方", "ok");
 return;
 }
 if (t.closest(".wf-in-remove")) {
 e.preventDefault();
 t.closest(".wf-input-row")?.remove();
 const host = $("wfInputsBuilder");
 if (host && !host.querySelector(".wf-input-row")) {
 host.innerHTML =
 '<div class="wf-empty-hint">大多数流程不用填。若某一步内容每次不同，可在这里加一项，运行时会问你。</div>';
 }
 syncInputsJsonFromBuilder();
 return;
 }
 if (t.closest(".wf-st-remove")) {
 e.preventDefault();
 t.closest(".wf-step-card")?.remove();
 reindexStepCards();
 const host = $("wfStepsBuilder");
 if (host && !host.querySelector(".wf-step-card")) {
 host.innerHTML =
 '<div class="wf-empty-hint">还没有步骤。点下面「添加一步」的按钮，像点菜一样选就行。</div>';
 }
 syncStepsJsonFromBuilder();
 return;
 }
 if (t.closest(".wf-st-up")) {
 e.preventDefault();
 moveStepCard(t.closest(".wf-step-card"), -1);
 return;
 }
 if (t.closest(".wf-st-down")) {
 e.preventDefault();
 moveStepCard(t.closest(".wf-step-card"), 1);
 return;
 }

 if (t.closest("#btnCloseWfRun") || t.closest("#btnCancelWfRun")) {
 e.preventDefault();
 closeWfRunModal();
 return;
 }
 if (t.closest("#btnDoWfRun")) {
 e.preventDefault();
 doDirectWfRun();
 return;
 }
 if (t.closest("#btnWfResume")) {
 e.preventDefault();
 resumeCurrentRun(true);
 return;
 }
 if (t.closest("#btnWfDetailResume")) {
 e.preventDefault();
 {
 const rid = _wfCurrentRunId;
 resumeCurrentRun(true).then(() => {
 if (rid) openWfRunDetail(rid);
 });
 }
 return;
 }
 if (t.closest("#btnWfReject")) {
 e.preventDefault();
 resumeCurrentRun(false);
 return;
 }
 if (t.closest("#btnWfDetailReject")) {
 e.preventDefault();
 resumeCurrentRun(false).then(() => closeWfRunDetailModal());
 return;
 }
 if (t.closest("#btnCloseWfRunDetail")) {
 e.preventDefault();
 closeWfRunDetailModal();
 return;
 }
 },
 true
 );

 document.addEventListener(
 "change",
 (e) => {
 const t = e.target;
 if (!(t instanceof Element)) return;
 if (t.classList.contains("wf-st-action")) {
 const card = t.closest(".wf-step-card");
 if (card) changeStepAction(card, t.value);
 return;
 }
 if (
 t.classList.contains("wf-in-label") ||
 t.classList.contains("wf-in-key") ||
 t.classList.contains("wf-in-type") ||
 t.classList.contains("wf-in-default")
 ) {
 // auto key from label if key empty
 if (t.classList.contains("wf-in-label")) {
 const row = t.closest(".wf-input-row");
 const keyEl = row?.querySelector(".wf-in-key");
 if (keyEl && !(keyEl.value || "").trim()) {
 keyEl.value = wfSlugFromLabel(t.value, "field");
 }
 }
 syncInputsJsonFromBuilder();
 return;
 }
 if (t.closest(".wf-step-card")) {
 syncStepsJsonFromBuilder();
 }
 },
 true
 );

 document.addEventListener(
 "input",
 (e) => {
 const t = e.target;
 if (!(t instanceof Element)) return;
 if (t.id === "wfSkillSearch") {
 renderWfSkillPickerList();
 return;
 }
 if (
 t.classList.contains("wf-in-label") ||
 t.classList.contains("wf-in-default") ||
 t.classList.contains("wf-in-key")
 ) {
 if (t.classList.contains("wf-in-label")) {
 const row = t.closest(".wf-input-row");
 const keyEl = row?.querySelector(".wf-in-key");
 if (keyEl && !(keyEl.dataset.touched === "1")) {
 keyEl.value = wfSlugFromLabel(t.value, "field");
 }
 }
 if (t.classList.contains("wf-in-key")) {
 t.dataset.touched = "1";
 }
 syncInputsJsonFromBuilder();
 return;
 }
 if (t.classList.contains("wf-fld") || t.classList.contains("wf-st-tool")) {
 syncStepsJsonFromBuilder();
 }
 },
 true
 );

 document.addEventListener(
 "blur",
 (e) => {
 const t = e.target;
 if (!(t instanceof Element)) return;
 if (t.classList.contains("wf-st-args") || t.classList.contains("wf-fld")) {
 syncStepsJsonFromBuilder();
 }
 if (t.id === "wfInputs") syncInputsBuilderFromJson();
 if (t.id === "wfSteps") syncStepsBuilderFromJson();
 },
 true
 );
 }
 initWorkflowPanel();

 // Workspace panel lives in app-workspace.js

 // ==================== Webhook multi-channel panel ====================
 let _whCache = [];
 let _whSessions = [];
 let _whTokenVisible = false;

 function whModeLabel(mode) {
   if (mode === "map") return "按外部 ID 映射";
   if (mode === "new") return "每次新建";
   return "固定会话";
 }

 function whPlatformLabel(p) {
   const m = {
     feishu: "飞书",
     wecom: "企微",
     dingtalk: "钉钉",
     telegram: "Telegram",
     discord: "Discord",
     slack: "Slack",
     custom: "自定义",
     other: "其它",
   };
   return m[p] || p || "自定义";
 }

 async function loadWhSessions() {
   _whSessions = await fetchSessionList(true);
   const sel = $("whSessionId");
   if (!sel) return;
   const cur = sel.value;
   sel.innerHTML =
     '<option value="">（不固定 / 新会话时由系统创建）</option>';
   for (const s of _whSessions) {
     const opt = document.createElement("option");
     opt.value = s.session_id || "";
     opt.textContent = sessionOptionLabel(s);
     sel.appendChild(opt);
   }
   // keep free-text session ids not in list
   if (cur && ![...sel.options].some((o) => o.value === cur)) {
     const opt = document.createElement("option");
     opt.value = cur;
     opt.textContent = `当前: ${cur}`;
     sel.appendChild(opt);
   }
   if (cur) sel.value = cur;
 }

 function whUrlFor(item) {
   const slug = item?.slug || item?.id || "";
   const path = slug
     ? `/api/webhook/${encodeURIComponent(slug)}/chat`
     : "/api/webhook/chat";
   try {
     return location.origin + path;
   } catch (_) {
     return path;
   }
 }

 async function loadWebhooks() {
   initWebhookPanel();
   const list = $("webhookList");
   if (!list) return;
   list.innerHTML = "";
   renderSkeleton(list, 3);
   setMsg("msgWebhooks", "载入中…");
   try {
     const data = await api("/api/webhooks");
     const items = Array.isArray(data?.items) ? data.items : [];
     _whCache = items;
     list.innerHTML = "";
     if (!items.length) {
       list.innerHTML =
         '<div class="card"><div class="card-body"><div class="card-sub">还没有通道。点「新建通道」对接飞书/企微等平台，每条可指向不同对话。</div></div></div>';
       setMsg("msgWebhooks", "0 个通道", "ok");
       return;
     }
     for (const it of items) {
       const card = document.createElement("div");
       const on = it.enabled !== false;
       card.className = "card" + (on ? "" : " card-disabled");
       const sess =
         it.session_mode === "fixed" && it.session_id
           ? (() => {
               const row = findSessionRow(_sessionListCache.rows, it.session_id);
               return row
                 ? "对话：" + sessionDisplayName(row)
                 : "已指定对话";
             })()
           : whModeLabel(it.session_mode);
       card.innerHTML = `
 <div class="card-body">
 <div class="card-title">${escapeHtml(it.name || it.slug || it.id)}
 <span class="pill integ-${on ? "ok" : "miss"}">${on ? "启用" : "停用"}</span>
 <span class="pill">${escapeHtml(whPlatformLabel(it.platform))}</span>
 </div>
 <div class="card-sub muted-line">slug: <code>${escapeHtml(
   it.slug || ""
 )}</code> · ${escapeHtml(sess)}</div>
 <div class="card-sub muted-line"><code class="wh-url-line">${escapeHtml(
   whUrlFor(it)
 )}</code></div>
 <div class="card-sub muted-line">Token ${
   it.token_set
     ? "已设置" + (it.token_hint ? " · " + escapeHtml(it.token_hint) : "")
     : "未设置"
 } · 工具 ${it.use_tools === false ? "关" : "开"} · 记忆 ${
         it.use_memory === false ? "关" : "开"
       }</div>
 ${
   it.note
     ? `<div class="card-sub muted-line">${escapeHtml(it.note)}</div>`
     : ""
 }
 </div>
 <div class="card-actions">
 <button type="button" class="btn edit-wh icon-btn" title="编辑">${_ipk(
   "edit",
   "ipk-sm"
 )}</button>
 <button type="button" class="btn copy-wh-url icon-btn" title="复制地址">${_ipk(
   "link",
   "ipk-sm"
 )}</button>
 <button type="button" class="btn danger del-wh icon-btn" title="删除">${_ipk(
   "delete",
   "ipk-sm"
 )}</button>
 </div>`;
       card.querySelector(".edit-wh")?.addEventListener("click", () =>
         openWebhookEditor(it.id)
       );
       card.querySelector(".copy-wh-url")?.addEventListener("click", async () => {
         const url = whUrlFor(it);
         try {
           await navigator.clipboard.writeText(url);
           showToast("已复制调用地址", "success");
         } catch (_) {
           prompt("复制地址", url);
         }
       });
       card.querySelector(".del-wh")?.addEventListener("click", () =>
         deleteWebhook(it.id, it.name)
       );
       list.appendChild(card);
     }
     setMsg(
       "msgWebhooks",
       `${items.length} 个通道 · 启用 ${items.filter((x) => x.enabled !== false).length}`,
       "ok"
     );
     if (typeof L.hydrateIconPark === "function") L.hydrateIconPark(list);
   } catch (e) {
     list.innerHTML = "";
     setMsg("msgWebhooks", e.message || String(e), "error");
   }
 }

 async function openWebhookEditor(id) {
   await loadWhSessions();
   const box = $("webhookEditorModal");
   if (!box) return;
   setMsg("msgWhEditor", "");
   _whTokenVisible = false;
   const tokInput = $("whToken");
   if (tokInput) {
     tokInput.type = "password";
     tokInput.value = "";
     tokInput.placeholder = "留空保存表示不修改；新建时自动生成";
   }
   const btnReveal = $("btnWhRevealToken");
   if (btnReveal) btnReveal.textContent = "显示";

   if (!id) {
     $("whId").value = "";
     $("whEditorTitle").innerHTML =
       '<span data-ipk="plus" data-ipk-class="ipk-sm"></span> 新建通道';
     $("whName").value = "";
     $("whSlug").value = "";
     $("whPlatform").value = "custom";
     $("whEnabled").value = "true";
     $("whSessionMode").value = "fixed";
     $("whSessionId").value = "";
     $("whUseTools").value = "true";
     $("whUseMemory").value = "true";
     $("whNote").value = "";
     $("whUrlPreview").value = location.origin + "/api/webhook/{slug}/chat";
     if (typeof L.openNestedEditor === "function") {
       L.openNestedEditor("webhookEditorModal");
     } else {
       box.classList.remove("hidden");
       document.body.classList.add("cfg-nested-open");
     }
     requestAnimationFrame(() => $("whName")?.focus());
     return;
   }

   const it = _whCache.find((x) => x.id === id) || { id };
   $("whId").value = it.id || id;
   $("whEditorTitle").innerHTML =
     '<span data-ipk="edit" data-ipk-class="ipk-sm"></span> 编辑 · ' +
     escapeHtml(it.name || it.slug || id);
   $("whName").value = it.name || "";
   $("whSlug").value = it.slug || "";
   $("whPlatform").value = it.platform || "custom";
   $("whEnabled").value = it.enabled === false ? "false" : "true";
   $("whSessionMode").value = it.session_mode || "fixed";
   // ensure session option
   if (it.session_id) {
     const sel = $("whSessionId");
     if (sel && ![...sel.options].some((o) => o.value === it.session_id)) {
       const opt = document.createElement("option");
       opt.value = it.session_id;
       opt.textContent = `已绑定: ${it.session_id}`;
       sel.appendChild(opt);
     }
     $("whSessionId").value = it.session_id;
   } else {
     $("whSessionId").value = "";
   }
   $("whUseTools").value = it.use_tools === false ? "false" : "true";
   $("whUseMemory").value = it.use_memory === false ? "false" : "true";
   $("whNote").value = it.note || "";
   $("whUrlPreview").value = whUrlFor(it);
   if (tokInput) {
     tokInput.placeholder = it.token_set
       ? "已设置 · 留空不修改 · 点「显示」查看"
       : "未设置 · 保存时自动生成";
   }
   if (typeof L.openNestedEditor === "function") {
     L.openNestedEditor("webhookEditorModal");
   } else {
     box.classList.remove("hidden");
     document.body.classList.add("cfg-nested-open");
   }
 }

 function closeWebhookEditor() {
   setMsg("msgWhEditor", "");
   if (typeof L.closeNestedEditor === "function") {
     L.closeNestedEditor("webhookEditorModal");
   } else {
     $("webhookEditorModal")?.classList.add("hidden");
   }
 }

 async function saveWebhook() {
   const id = ($("whId")?.value || "").trim();
   const name = ($("whName")?.value || "").trim();
   if (!name) {
     setMsg("msgWhEditor", "请填写名称", "error");
     return;
   }
   const body = {
     name,
     slug: ($("whSlug")?.value || "").trim() || undefined,
     platform: $("whPlatform")?.value || "custom",
     enabled: $("whEnabled")?.value !== "false",
     session_mode: $("whSessionMode")?.value || "fixed",
     session_id: ($("whSessionId")?.value || "").trim(),
     use_tools: $("whUseTools")?.value !== "false",
     use_memory: $("whUseMemory")?.value !== "false",
     note: ($("whNote")?.value || "").trim(),
   };
   const tok = ($("whToken")?.value || "").trim();
   if (tok) body.token = tok;

   try {
     setMsg("msgWhEditor", "保存中…");
     let res;
     if (id) {
       res = await api("/api/webhooks/" + encodeURIComponent(id), {
         method: "PUT",
         body: JSON.stringify(body),
       });
     } else {
       res = await api("/api/webhooks", {
         method: "POST",
         body: JSON.stringify(body),
       });
     }
     const item = res?.item;
     if (item?.token) {
       $("whToken").value = item.token;
       $("whToken").type = "text";
       _whTokenVisible = true;
       if ($("btnWhRevealToken")) $("btnWhRevealToken").textContent = "隐藏";
       setMsg(
         "msgWhEditor",
         "已保存 · Token 已显示，请复制保存",
         "ok"
       );
       showToast("通道已保存，请复制 Token", "success");
     } else {
       setMsg("msgWhEditor", "已保存", "ok");
       showToast("通道已保存", "success");
     }
     if (item?.id) {
       $("whId").value = item.id;
       $("whSlug").value = item.slug || "";
       $("whUrlPreview").value = whUrlFor(item);
     }
     await loadWebhooks();
   } catch (e) {
     setMsg("msgWhEditor", e.message || String(e), "error");
     showToast("保存失败", "error");
   }
 }

 async function deleteWebhook(id, name) {
   if (!id) return;
   if (!confirm(`确定删除 Webhook 通道「${name || id}」？外部调用将立即失效。`))
     return;
   try {
     await api("/api/webhooks/" + encodeURIComponent(id), { method: "DELETE" });
     showToast("已删除", "success");
     if ($("whId")?.value === id) closeWebhookEditor();
     await loadWebhooks();
   } catch (e) {
     setMsg("msgWebhooks", e.message || String(e), "error");
     showToast("删除失败", "error");
   }
 }

 async function revealWhToken() {
   const id = ($("whId")?.value || "").trim();
   const input = $("whToken");
   if (!input) return;
   if (_whTokenVisible) {
     input.type = "password";
     _whTokenVisible = false;
     if ($("btnWhRevealToken")) $("btnWhRevealToken").textContent = "显示";
     return;
   }
   if (!id) {
     // new: just toggle if has value
     if (input.value) {
       input.type = "text";
       _whTokenVisible = true;
       if ($("btnWhRevealToken")) $("btnWhRevealToken").textContent = "隐藏";
     }
     return;
   }
   try {
     const data = await api(
       "/api/webhooks/" + encodeURIComponent(id) + "/token"
     );
     input.value = data.token || "";
     input.type = "text";
     _whTokenVisible = true;
     if ($("btnWhRevealToken")) $("btnWhRevealToken").textContent = "隐藏";
   } catch (e) {
     setMsg("msgWhEditor", e.message || String(e), "error");
   }
 }

 async function regenWhToken() {
   const id = ($("whId")?.value || "").trim();
   if (!id) {
     setMsg("msgWhEditor", "请先保存通道再重置 Token", "error");
     return;
   }
   if (!confirm("重置后旧 Token 立即失效，确定？")) return;
   try {
     const data = await api(
       "/api/webhooks/" + encodeURIComponent(id) + "/regenerate-token",
       { method: "POST" }
     );
     const tok = data?.item?.token || "";
     $("whToken").value = tok;
     $("whToken").type = "text";
     _whTokenVisible = true;
     if ($("btnWhRevealToken")) $("btnWhRevealToken").textContent = "隐藏";
     setMsg("msgWhEditor", "Token 已重置，请复制保存", "ok");
     showToast("Token 已重置", "success");
     await loadWebhooks();
   } catch (e) {
     setMsg("msgWhEditor", e.message || String(e), "error");
   }
 }

 async function copyWhToken() {
   const input = $("whToken");
   let tok = (input?.value || "").trim();
   const id = ($("whId")?.value || "").trim();
   if (!tok && id) {
     try {
       const data = await api(
         "/api/webhooks/" + encodeURIComponent(id) + "/token"
       );
       tok = data.token || "";
       if (input) {
         input.value = tok;
         input.type = "text";
         _whTokenVisible = true;
       }
     } catch (e) {
       setMsg("msgWhEditor", e.message || String(e), "error");
       return;
     }
   }
   if (!tok) {
     setMsg("msgWhEditor", "暂无 Token 可复制", "error");
     return;
   }
   try {
     await navigator.clipboard.writeText(tok);
     showToast("Token 已复制", "success");
   } catch (_) {
     prompt("复制 Token", tok);
   }
 }

 function bindWebhookDelegatedUi() {
   // 与任务/集成相同：config-modal.html 晚于本脚本注入时，直接 addEventListener 会绑空且 _done 不再重试。
   if (bindWebhookDelegatedUi._done) return;
   bindWebhookDelegatedUi._done = true;
   document.addEventListener("click", (e) => {
     const t = e.target;
     if (!(t instanceof Element)) return;
     if (t.id === "webhookEditorModal") {
       closeWebhookEditor();
       return;
     }
     const btn = t.closest(
       "#btnNewWebhook, #btnRefreshWebhooks, #btnSaveWebhook, #btnCancelWebhook, #btnCloseWebhookEditor, #btnWhRevealToken, #btnWhRegenToken, #btnWhCopyToken"
     );
     if (!btn) return;
     e.preventDefault();
     switch (btn.id) {
       case "btnNewWebhook":
         openWebhookEditor("");
         break;
       case "btnRefreshWebhooks":
         loadWebhooks();
         break;
       case "btnSaveWebhook":
         saveWebhook();
         break;
       case "btnCancelWebhook":
       case "btnCloseWebhookEditor":
         closeWebhookEditor();
         break;
       case "btnWhRevealToken":
         revealWhToken();
         break;
       case "btnWhRegenToken":
         regenWhToken();
         break;
       case "btnWhCopyToken":
         copyWhToken();
         break;
       default:
         break;
     }
   });
 }

 function bindWebhookFieldUi() {
   if (bindWebhookFieldUi._done) return;
   const slugEl = $("whSlug");
   const nameEl = $("whName");
   if (!slugEl && !nameEl) return;
   bindWebhookFieldUi._done = true;
   slugEl?.addEventListener("input", () => {
     const slug = (slugEl.value || "").trim() || "{slug}";
     if ($("whUrlPreview")) {
       try {
         $("whUrlPreview").value =
           location.origin + "/api/webhook/" + encodeURIComponent(slug) + "/chat";
       } catch (_) {
         $("whUrlPreview").value = "/api/webhook/" + slug + "/chat";
       }
     }
   });
   nameEl?.addEventListener("blur", () => {
     if ((slugEl?.value || "").trim()) return;
     const n = (nameEl.value || "").trim();
     if (!n || !slugEl) return;
     let s = n
       .toLowerCase()
       .replace(/\s+/g, "-")
       .replace(/[^a-z0-9_-]+/g, "");
     if (!s) s = "hook";
     if (!/^[a-z]/.test(s)) s = "w-" + s;
     slugEl.value = s.slice(0, 48);
     slugEl.dispatchEvent(new Event("input"));
   });
 }

 function initWebhookPanel() {
   bindWebhookDelegatedUi();
   bindWebhookFieldUi();
 }
 initWebhookPanel();
 if (window.__configModalReady && typeof window.__configModalReady.then === "function") {
   window.__configModalReady.then(() => bindWebhookFieldUi());
 }

 // Export
 L.normalizeTask = normalizeTask;
 L.loadTasks = loadTasks;
 L.openTaskEditor = openTaskEditor;
 L.closeTaskEditor = closeTaskEditor;
 L.bindTaskFormUi = bindTaskFormUi;
 L.runTask = runTask;
 L.loadMemory = loadMemory;
 L.addMemory = addMemory;
 L.deleteMemory = deleteMemory;
 L.initMemoryForm = initMemoryForm;
 L.openMemoryAddModal = openMemoryAddModal;
 L.closeMemoryAddModal = closeMemoryAddModal;
 L.loadKb = loadKb;
 L.openKbEditor = openKbEditor;
 L.closeKbPageModal = closeKbPageModal;
 L.initKbPanel = initKbPanel;
 L.loadWorkflows = loadWorkflows;
 L.initWorkflowPanel = initWorkflowPanel;
 L.openWorkflowEditor = openWorkflowEditor;
 L.openWfRunModal = openWfRunModal;
 L.openWfRunDetail = openWfRunDetail;
 L.closeWfPageModal = closeWfPageModal;
 L.loadWebhooks = loadWebhooks;
 L.initWebhookPanel = initWebhookPanel;
 L.openWebhookEditor = openWebhookEditor;
 L.closeWebhookEditor = closeWebhookEditor;
 L.closeWfRunModal = closeWfRunModal;
 L.closeWfRunDetailModal = closeWfRunDetailModal;
})(window.Lily);
