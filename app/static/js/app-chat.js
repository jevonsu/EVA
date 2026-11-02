/**
 * Lily - Chat (API + Sessions + Stream)
 * 体验修复：统一 abort、删除/重命名、工具进度、阶段计时
 */
((L) => {
 "use strict";

 const {
 $,
 els,
 state,
 showToast,
 escapeHtml,
 stripThinking,
 normalizeToolCalls,
 extractToolCalls,
 summarizeToolNames,
 timeAgo,
 } = L;

 // 延迟取用（避免模块加载顺序导致拿到旧闭包）
 const ui = () => L;
 const setStatus = (...a) => L.setStatus(...a);
 const setBusy = (...a) => L.setBusy(...a);
 const autoResize = (...a) => L.autoResize(...a);
 const formatUsage = (...a) => L.formatUsage(...a);
 const appendMessage = (...a) => L.appendMessage(...a);
 const appendTyping = (...a) => L.appendTyping(...a);
 const appendStreamBubble = (...a) => L.appendStreamBubble(...a);
 const updateStreamBubble = (...a) => L.updateStreamBubble(...a);
 const finalizeStreamBubble = (...a) => L.finalizeStreamBubble(...a);
 const removeTyping = (...a) => L.removeTyping(...a);
 const cancelRequest = (...a) => L.cancelRequest(...a);
 const detachWatchOnly = (...a) =>
  typeof L.detachWatchOnly === "function" ? L.detachWatchOnly(...a) : cancelRequest(...a);
 const closeMobileSidebar = (...a) => L.closeMobileSidebar(...a);
 const clearMessages = (...a) => L.clearMessages(...a);
 const showEmpty = (...a) => L.showEmpty(...a);
 const updateTypingPhase = (...a) => L.updateTypingPhase(...a);
 const appendTypingLog = (...a) => L.appendTypingLog(...a);
 const applyRunProgressEvent = (...a) =>
  typeof L.applyRunProgressEvent === "function"
   ? L.applyRunProgressEvent(...a)
   : null;

  const _ipk = (n, c) => (L.ipk ? L.ipk(n, c) : '');
  const _ipkLabel = (n, txt, c) => (L.ipkLabel ? L.ipkLabel(n, txt, c) : (txt || ''));

 function persistChatRuns() {
  try {
   sessionStorage.setItem("chat_runs", JSON.stringify(state.chatRuns || {}));
  } catch (_) {}
 }
 L.persistChatRuns = persistChatRuns;

 function rememberRun(sessionId, runId, message) {
  if (!sessionId || !runId) return;
  if (!state.chatRuns) state.chatRuns = {};
  state.chatRuns[sessionId] = {
   runId,
   message: message || "",
   status: "running",
  };
  persistChatRuns();
 }

 function forgetRun(sessionId) {
  if (!sessionId || !state.chatRuns) return;
  delete state.chatRuns[sessionId];
  persistChatRuns();
 }

 function sessionIsGenerating(sessionId) {
  const r = state.chatRuns && state.chatRuns[sessionId];
  return !!(r && r.status === "running" && r.runId);
 }

 /** 与服务端对齐：清掉已结束/不存在的「生成中」标记 */
 async function syncChatRunsWithServer() {
  if (!state.chatRuns || typeof state.chatRuns !== "object") return;
  const localIds = Object.keys(state.chatRuns);
  if (!localIds.length) return;
  let activeSet = new Set();
  try {
   const data = await api("/api/chat/runs");
   const list = data.active_sessions || [];
   activeSet = new Set(list);
  } catch (_) {
   // 网络失败时不误清本地
   return;
  }
  let changed = false;
  for (const sid of localIds) {
   const meta = state.chatRuns[sid];
   if (!meta || meta.status !== "running") {
    delete state.chatRuns[sid];
    changed = true;
    continue;
   }
   if (!activeSet.has(sid)) {
    // 服务端已无此会话的运行中任务 → 去掉绿点
    delete state.chatRuns[sid];
    changed = true;
   }
  }
  if (changed) persistChatRuns();
 }

 function getChatTitleTextEl() {
 return document.getElementById("chatTitleText") || els.chatTitle;
 }

 function getChatTitleText() {
 const el = getChatTitleTextEl();
 return (el && el.textContent) || "";
 }

 function setChatTitleText(text) {
 const el = getChatTitleTextEl();
 if (el) el.textContent = text || "新对话";
 }

 function isDefaultChatTitle() {
 const t = getChatTitleText().trim();
 return !t || t === "新对话" || t === "对话";
 }

 function suggestSessionTitle(message) {
  let t = String(message || "").trim();
  t = t.replace(/【表单回复】\s*/g, "").replace(/（已上传文件）/g, "");
  t = t.split(/\r?\n/)[0].trim();
  const dun = (t.match(/、/g) || []).length;
  const comma = (t.match(/，/g) || []).length;
  if (dun >= 2 || comma >= 2) t = t.split(/[、，]/)[0].trim();
  t = t.split(/[。！？!?]/)[0].trim();
  t = t.replace(/\s+/g, " ").replace(/^[ ·—-]+|[ ·—-]+$/g, "");
  if (!t) return "对话";
  if (t.length > 18) {
   t = t.slice(0, 18).replace(/[，、,.；;：:\-—…\s]+$/g, "") + "…";
  }
  return t;
 }

 function clearPhaseTimer() {
 if (state.phaseTimer) {
 clearInterval(state.phaseTimer);
 state.phaseTimer = null;
 }
 }

 function startPhaseTimer(startTime, mode) {
 clearPhaseTimer();
 const tick = () => {
 const elapsed = Math.floor((Date.now() - startTime) / 1000);
 if (mode === "stream") {
 setStatus(` 流式输出中…（${elapsed}s）`);
 } else {
 setStatus(`⏳ 处理中…（${elapsed}s）`);
 updateTypingPhase(elapsed);
 }
 };
 tick();
 state.phaseTimer = setInterval(tick, 1000);
 }

 // ==================== API 封装 ====================
 async function api(path, options = {}) {
 const { signal, headers: extraHeaders, body, ...rest } = options;
 const init = {
 headers: { "Content-Type": "application/json", ...(extraHeaders || {}) },
 signal,
 ...rest,
 };
 if (body !== undefined) {
 init.body = typeof body === "string" ? body : JSON.stringify(body);
 }
 const res = await fetch(path, init);
 let data = null;
 const text = await res.text();
 try {
 data = text ? JSON.parse(text) : null;
 } catch {
 data = { detail: text };
 }
 if (!res.ok) {
 if (
  res.status === 401 &&
  typeof path === "string" &&
  !path.startsWith("/api/auth/") &&
  !String(location.pathname || "").startsWith("/login")
 ) {
  const next = location.pathname + location.search;
  location.replace(
   "/login?next=" + encodeURIComponent(next.startsWith("/") ? next : "/")
  );
 }
 const detail = data?.detail || data?.error || res.statusText;
 throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
 }
 return data;
 }

 // ==================== 会话管理 ====================
 /** 账号状态摘要（卡密套餐文案已废弃） */
 function formatCardPlanMeta(me) {
  if (!me) return "";
  if (me.auth_enabled === false || me.mode === "open") return "开放访问";
  if (!me.authenticated) return "未登录";
  const name = String(me.display_name || me.username || "").trim() || "已登录";
  return name;
 }

 function applyAuthChrome(me) {
  const wrap = document.getElementById("topAuthWrap");
  const label = document.getElementById("topAuthLabel");
  const show = !!(me && me.authenticated && me.auth_enabled !== false);
  if (wrap) {
   wrap.hidden = !show;
   wrap.style.display = show ? "" : "none";
  }
  if (label && show) {
   label.textContent = String(me.display_name || me.username || "").trim() || "已登录";
  }
  // legacy ids (if any remain)
  const logoutBtn = document.getElementById("btnSidebarLogout");
  if (logoutBtn) logoutBtn.hidden = true;
  const userChip = document.getElementById("sidebarAuthUser");
  if (userChip) userChip.hidden = true;
 }

 async function refreshAuthChrome() {
  try {
   const me = await api("/api/auth/me");
   applyAuthChrome(me);
   if (els.agentMeta) els.agentMeta.textContent = formatCardPlanMeta(me) || "";
   return me;
  } catch (_) {
   return null;
  }
 }

 async function loadHealth() {
 try {
 // Parallel: health + card meta (was sequential and doubled first-paint wait)
 const healthP = api("/health");
 const meP = api("/api/auth/me").catch(() => null);
 const needAgent = !(state.config && state.config.agent);
 const agentP = needAgent
  ? api("/api/config/agent").catch(() => null)
  : Promise.resolve(null);

 const h = await healthP;
 const agentLabel = String(h.agent || "").trim() || "Eva";
 els.agentName.textContent = agentLabel;
 document.title = `${agentLabel} — AI 助手`;
 state.agentName = agentLabel;
 if (typeof h.llm_configured === "boolean") {
  state.llmConfigured = h.llm_configured;
 } else {
  state.llmConfigured = !!(h.llm_model || h.llm_provider);
 }

 const me = await meP;
 if (els.agentMeta) els.agentMeta.textContent = formatCardPlanMeta(me) || "";
 applyAuthChrome(me);

 if (needAgent) {
  const agent = await agentP;
  if (agent) {
   state.config = state.config || {};
   state.config.agent = agent;
  }
 }
 if (typeof L.refreshHomeHero === "function") L.refreshHomeHero();
 } catch (e) {
 els.agentMeta.textContent = "连接后端失败";
 setStatus(e.message, "error");
 showToast("健康检查失败: " + e.message, "error");
 }
 }

 async function restoreDeletedSession(snapshot) {
 if (!snapshot || !snapshot.session_id) return;
 try {
  await api("/api/sessions/restore", {
   method: "POST",
   body: { session: snapshot },
  });
  await loadSessions();
  await openSession(snapshot.session_id, snapshot.title || "对话");
  showToast("已撤销删除", "success");
 } catch (e) {
  showToast("撤销失败: " + (e.message || e), "error");
 }
 }

 async function deleteSession(sessionId, ev) {
 if (ev) {
 ev.preventDefault();
 ev.stopPropagation();
 }
 if (!confirm("确定删除这段对话？可在提示里撤销。")) return;
 let snapshot = null;
 try {
  snapshot = await api(`/api/sessions/${encodeURIComponent(sessionId)}`);
 } catch (_) {}
 try {
 await api(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
 if (state.sessionId === sessionId) {
 newChat();
 } else {
 await loadSessions();
 }
 setStatus("已删除对话", "ok");
 showToast("对话已删除", "success", 8000, snapshot
  ? { label: "撤销", onClick: () => restoreDeletedSession(snapshot) }
  : undefined);
 } catch (e) {
 setStatus("删除失败: " + e.message, "error");
 showToast("删除失败: " + e.message, "error");
 }
 }

 // ---- 未读提醒：localStorage 记每个会话已读到的消息数 ----
 const READ_KEY = "eva.sessionRead.v1";
 function _readMap() {
  try { return JSON.parse(localStorage.getItem(READ_KEY) || "null"); } catch { return null; }
 }
 function _saveReadMap(m) {
  try { localStorage.setItem(READ_KEY, JSON.stringify(m)); } catch (_) {}
 }
 function markSessionRead(sid, count) {
  if (!sid) return;
  const m = _readMap() || {};
  const n = Number(count);
  if (Number.isFinite(n)) m[sid] = Math.max(Number(m[sid] || 0), n);
  else {
   const row = (state.sessionsCache || []).find((r) => r.session_id === sid);
   m[sid] = Number(row?.message_count || m[sid] || 0);
  }
  _saveReadMap(m);
 }
 function sessionUnread(s, map) {
  if (!map || s.session_id === state.sessionId) return false;
  if (!(s.session_id in map)) return Number(s.message_count || 0) > 0 && map.__init_at && String(s.created_at || "") > map.__init_at;
  return Number(s.message_count || 0) > Number(map[s.session_id] || 0);
 }
 
 function syncUnreadAfterSessions(sid) {
  if (sid && sid === state.sessionId) {
   const row = (state.sessionsCache || []).find((x) => x.session_id === sid);
   markSessionRead(sid, row ? row.message_count : undefined);
  }
  filterSessions(els.sessionSearch?.value || "");
 }
 L.syncUnreadAfterSessions = syncUnreadAfterSessions;

L.markSessionRead = markSessionRead;

 function renderSessionList(rows) {
 els.sessionList.innerHTML = "";
 let readMap = _readMap();
 if (!readMap) {
  // 首次启用：现有会话全部视为已读，避免一片红点
  readMap = { __init_at: new Date().toISOString() };
  for (const r of state.sessionsCache || []) readMap[r.session_id] = Number(r.message_count || 0);
  _saveReadMap(readMap);
 }
 const activeRow = (rows || []).find((r) => r.session_id === state.sessionId);
 if (activeRow && !sessionIsGenerating(activeRow.session_id)) {
  readMap[activeRow.session_id] = Number(activeRow.message_count || 0);
  _saveReadMap(readMap);
 }
 if (!rows.length) {
 els.sessionList.innerHTML =
 '<div class="session-empty" role="status">'
 + '<div class="session-empty-title">还没有对话</div>'
 + '<div class="session-empty-sub">点上方「新对话」开始；对话会出现在这里。</div>'
 + '</div>';
 return;
 }
 for (const s of rows) {
 const row = document.createElement("div");
 const generating = sessionIsGenerating(s.session_id);
 row.className =
 "session-item" +
 (s.session_id === state.sessionId ? " active" : "") +
 (generating ? " is-generating" : "");
 const unread = !generating && sessionUnread(s, readMap);
 if (unread) row.classList.add("has-unread");
 const updated = s.updated_at || s.created_at;
 const timeBit = updated ? timeAgo(updated) : "";
 const genBit = generating ? " · 生成中" : "";
 row.innerHTML = `
 <div class="session-main">
 <div class="title">${unread ? '<span class="session-unread-dot" title="有新回复（未读）" aria-label="未读"></span>' : ""}${escapeHtml(s.title || "未命名对话")}${generating ? ' <span class="session-gen-dot" title="后台生成中"></span>' : ""}</div>
 <div class="meta">${s.message_count ?? "?"} 条${timeBit ? ` · ${escapeHtml(timeBit)}` : ""}${genBit}</div>
 </div>
 <button type="button" class="session-rename" title="重命名" aria-label="重命名">${_ipk("edit","ipk-sm")}</button>
 <button type="button" class="session-del" title="删除对话" aria-label="删除">${_ipk("delete","ipk-sm")}</button>`;
 row.querySelector(".session-main").addEventListener("click", () => {
 closeMobileSidebar();
 markSessionRead(s.session_id, s.message_count);
 openSession(s.session_id, s.title);
 });
 row.querySelector(".session-del").addEventListener("click", (e) =>
 deleteSession(s.session_id, e)
 );
 row.querySelector(".session-rename").addEventListener("click", async (e) => {
 e.stopPropagation();
 const nt = prompt("重命名对话：", s.title || "");
 if (nt && nt.trim()) {
 try {
 await api("/api/sessions/" + encodeURIComponent(s.session_id), {
 method: "PATCH",
 body: { title: nt.trim() },
 });
 await loadSessions();
 if (s.session_id === state.sessionId) {
 setChatTitleText(nt.trim());
 }
 showToast("已重命名", "success");
 } catch (err) {
 showToast("重命名失败: " + err.message, "error");
 }
 }
 });
 els.sessionList.appendChild(row);
 }
 }

 let sessionSearchGen = 0;

 async function filterSessions(q) {
 const query = (q || "").trim();
 if (!query) {
 renderSessionList(state.sessionsCache);
 return;
 }
 const gen = ++sessionSearchGen;
 const qLower = query.toLowerCase();
 const localHits = state.sessionsCache.filter((s) => {
  const title = (s.title || "").toLowerCase();
  const id = (s.session_id || "").toLowerCase();
  return title.includes(qLower) || id.includes(qLower);
 });
 if (localHits.length) renderSessionList(localHits);
 try {
  const rows = await api("/api/sessions?q=" + encodeURIComponent(query));
  if (gen !== sessionSearchGen) return;
  renderSessionList(Array.isArray(rows) ? rows : []);
 } catch (_) {
  if (gen !== sessionSearchGen) return;
  if (!localHits.length) renderSessionList([]);
 }
 }

 async function loadSessions() {
 try {
 await syncChatRunsWithServer();
 const rows = await api("/api/sessions");
 state.sessionsCache = Array.isArray(rows) ? rows : [];
 filterSessions(els.sessionSearch?.value || "");
 } catch (e) {
 setStatus("载入对话失败: " + e.message, "error");
 showToast("载入对话失败", "error");
 }
 }

 // ---- 侧栏未读实时刷新：轮询 + 回到前台/聚焦时立即刷新（无需 F5）----
 let _sessPollBusy = false;
 async function refreshSessionsQuiet() {
  if (_sessPollBusy || document.hidden) return;
  _sessPollBusy = true;
  try {
   const rows = await api("/api/sessions");
   if (Array.isArray(rows)) {
    const sig = (r) => r.map((x) => x.session_id + ":" + (x.message_count || 0) + ":" + (x.updated_at || "") + ":" + (sessionIsGenerating(x.session_id) ? 1 : 0)).join("|");
    const changed = sig(rows) !== sig(state.sessionsCache || []);
    state.sessionsCache = rows;
    if (changed) filterSessions(els.sessionSearch?.value || "");
   }
  } catch (_) {
  } finally {
   _sessPollBusy = false;
  }
 }
 L.refreshSessionsQuiet = refreshSessionsQuiet;
 // ---- IM 式推送：/api/sessions/events (SSE)；轮询仅作兜底 ----
 let _sessPushTimer = null;
 let _sessPushPending = false;
 function _applySessionEvent(ev) {
  const sid = ev && ev.session_id;
  if (!sid) return false;
  const rows = state.sessionsCache || [];
  if (ev.type === "session_deleted") {
   state.sessionsCache = rows.filter((r) => r.session_id !== sid);
   return true;
  }
  if (ev.type !== "session_updated") return false;
  const i = rows.findIndex((r) => r.session_id === sid);
  if (i < 0) return false; // 新会话：交给全量刷新
  const r = { ...rows[i], message_count: ev.message_count, updated_at: ev.updated_at || rows[i].updated_at };
  if (ev.title) r.title = ev.title;
  const next = rows.slice(); next.splice(i, 1); next.unshift(r);
  state.sessionsCache = next;
  return true;
 }
 async function _pushRefresh(full) {
  if (_sessPollBusy) { _sessPushPending = true; return; }
  try {
   if (full && typeof syncChatRunsWithServer === "function") await syncChatRunsWithServer();
  } catch (_) {}
  _sessPollBusy = false;
  const wasHidden = document.hidden;
  // 推送刷新即使页面隐藏也执行（标题/未读同步），轮询仍在隐藏时跳过
  _sessPollBusy = true;
  try {
   const rows = await api("/api/sessions");
   if (Array.isArray(rows)) state.sessionsCache = rows;
  } catch (_) {} finally { _sessPollBusy = false; }
  if (state.sessionId) {
   const row = (state.sessionsCache || []).find((x) => x.session_id === state.sessionId);
   if (row && !sessionIsGenerating(state.sessionId) && !wasHidden) markSessionRead(state.sessionId, row.message_count);
  }
  filterSessions(els.sessionSearch?.value || "");
  if (_sessPushPending) { _sessPushPending = false; _schedulePush(true); }
 }
 function _schedulePush(full) {
  clearTimeout(_sessPushTimer);
  _sessPushTimer = setTimeout(() => _pushRefresh(full), 120);
 }
 let _sessES = null, _sessESok = false, _sessFallback = null;
 function _setFallback(ms) {
  if (_sessFallback) clearInterval(_sessFallback);
  _sessFallback = setInterval(refreshSessionsQuiet, ms);
 }
 function connectSessionEvents() {
  if (typeof EventSource === "undefined") { _setFallback(4000); return; }
  try { _sessES && _sessES.close(); } catch (_) {}
  _sessES = new EventSource("/api/sessions/events", { withCredentials: true });
  _sessES.onopen = () => { _sessESok = true; _setFallback(30000); _schedulePush(true); };
  _sessES.onerror = () => { _sessESok = false; _setFallback(5000); };
  _sessES.onmessage = (m) => {
   let ev; try { ev = JSON.parse(m.data); } catch { return; }
   if (!ev || ev.type === "hello") return;
   // 先就地更新蓝点（0 延迟），再全量校准（带生成状态）
   if (_applySessionEvent(ev)) filterSessions(els.sessionSearch?.value || "");
   _schedulePush(ev.type !== "session_updated" || !(state.sessionsCache || []).some((r) => r.session_id === ev.session_id) || ev.last_role === "assistant");
  };
 }
 L.connectSessionEvents = connectSessionEvents;
 if (!window.__evaSessPoll) {
  window.__evaSessPoll = true;
  _setFallback(5000);
  connectSessionEvents();
  document.addEventListener("visibilitychange", () => {
   if (!document.hidden) {
    if (!_sessESok) connectSessionEvents();
    refreshSessionsQuiet();
   }
  });
  window.addEventListener("focus", () => refreshSessionsQuiet());
  window.addEventListener("online", () => connectSessionEvents());
 }

 async function openSession(sessionId, title) {
 // 切换会话：只断开本页监听，后台继续生成
 if (state.busy || state.abortController) {
  const stillBg = sessionIsGenerating(state.sessionId);
  detachWatchOnly();
  if (stillBg) {
   showToast("已切换；原对话仍在后台生成", "info", 2200);
  }
 }
 state.sessionId = sessionId;
 localStorage.setItem("session_id", sessionId);
 setChatTitleText(title || "对话");
 els.sessionHint.textContent = `会话 ${sessionId.slice(0, 8)}…`;
 clearMessages();
 setStatus("载入历史…");
 try {
 const data = await api(`/api/sessions/${sessionId}`);
 const messages = data.messages || [];
 if (!messages.length) showEmpty();
 const lastVis = [...messages]
  .reverse()
  .find((x) => x.role === "user" || x.role === "assistant");
 for (const m of messages) {
 const role =
 m.role === "user" || m.role === "assistant" ? m.role : "system";
 if (role === "system") continue;
 appendMessage(role, m.content || "", extrasFromStored(m, m === lastVis));
 }
 setStatus("");
 requestAnimationFrame(() => L.scrollMessages(true));
 // 若该会话仍有后台任务，重新附着进度；否则清掉残留绿点
 await reattachSessionRun(sessionId);
 await loadSessions();
 if (typeof L.loadEvolutionPanel === "function") L.loadEvolutionPanel();
 } catch (e) {
 showEmpty();
 setStatus(e.message, "error");
 showToast("打开会话失败", "error");
 }
 }

 function newChat() {
 // 不取消其它会话的后台生成；仅脱离当前页监听
 if (state.busy || state.abortController) {
  detachWatchOnly();
 }
 state.sessionId = null;
 localStorage.removeItem("session_id");
 setChatTitleText("新对话");
 els.sessionHint.textContent = "输入消息开始对话";
 clearMessages();
 showEmpty();
 setStatus("");
 closeMobileSidebar();
 loadSessions();
 if (typeof L.loadEvolutionPanel === "function") L.loadEvolutionPanel();
 els.input?.focus();
 }

 /** 打开会话时：若后台仍在生成，显示进度并继续收事件 */
 async function reattachSessionRun(sessionId) {
  if (!sessionId) return;
  let runId = state.chatRuns?.[sessionId]?.runId;
  let runMsg = state.chatRuns?.[sessionId]?.message || "";
  try {
   const data = await api(
    `/api/chat/runs?session_id=${encodeURIComponent(sessionId)}&active_only=true`
   );
   const rows = data.runs || [];
   if (rows[0]?.run_id) {
    runId = rows[0].run_id;
    runMsg = rows[0].message || runMsg;
    rememberRun(sessionId, runId, runMsg);
   } else if (runId) {
    // 本地有标记但服务端无进行中任务 → 清除绿点
    forgetRun(sessionId);
    runId = null;
    await loadSessions();
   }
  } catch (_) {}
  if (!runId) {
   // 可能已完成：清本地标记并刷新列表样式
   if (state.chatRuns?.[sessionId]) {
    forgetRun(sessionId);
    try {
     const data = await api(`/api/sessions/${sessionId}`);
     const messages = data.messages || [];
     clearMessages();
     if (!messages.length) showEmpty();
     const lastVis = [...messages]
      .reverse()
      .find((x) => x.role === "user" || x.role === "assistant");
     for (const m of messages) {
      const role =
       m.role === "user" || m.role === "assistant" ? m.role : "system";
      if (role === "system") continue;
      appendMessage(role, m.content || "", extrasFromStored(m, m === lastVis));
     }
    } catch (_) {}
    await loadSessions();
   }
   return;
  }

  // 检查状态
  try {
   const run = await api(`/api/chat/runs/${encodeURIComponent(runId)}`);
   if (run.status === "completed" && run.result) {
    forgetRun(sessionId);
    // 重载会话消息
    const data = await api(`/api/sessions/${sessionId}`);
    clearMessages();
    const msgs = data.messages || [];
    const lastVis = [...msgs]
     .reverse()
     .find((x) => x.role === "user" || x.role === "assistant");
    for (const m of msgs) {
     const role =
      m.role === "user" || m.role === "assistant" ? m.role : "system";
     if (role === "system") continue;
     appendMessage(role, m.content || "", extrasFromStored(m, m === lastVis));
    }
    setStatus("后台生成已完成", "ok");
    await loadSessions();
    return;
   }
   if (run.status !== "running") {
    forgetRun(sessionId);
    await loadSessions();
    return;
   }
   runMsg = run.message || runMsg;
  } catch (_) {
   // run 已过期/不存在：清掉列表绿字
   forgetRun(sessionId);
   await loadSessions();
   return;
  }

  // 历史里可能还没有本轮 user（agent 完成后才写入）——补一条乐观展示
  if (runMsg) {
   const lastUser = [...(els.messages?.querySelectorAll(".msg.user") || [])]
    .pop();
   const lastText = lastUser?.querySelector(".bubble")?.textContent || "";
   if (!lastText || !String(lastText).includes(String(runMsg).slice(0, 40))) {
    appendMessage("user", runMsg, {
     timestamp: new Date().toISOString(),
     ephemeral: true,
    });
   }
  }
  appendTyping();
  setBusy(true);
  setStatus("后台生成中…", "ok");
  const controller = new AbortController();
  const watchToken = Symbol("reattach");
  state.abortController = controller;
  state._watchToken = watchToken;
  state.activeRunId = runId;
  state.detachWatch = false;
  const startTime = Date.now();
  startPhaseTimer(startTime, "block");
  try {
   await watchRunEvents(runId, controller, startTime, runMsg);
  } catch (e) {
   if (state.detachWatch || isAbortError(e)) {
    setStatus("已离开此对话；生成仍在后台继续", "");
    return;
   }
   if (state._watchToken === watchToken) {
    removeTyping();
    setStatus(e.message || "附着失败", "error");
   }
  } finally {
   if (state._watchToken === watchToken) {
    setBusy(false);
    clearPhaseTimer();
    state.abortController = null;
    state.detachWatch = false;
   }
  }
 }

 // ==================== 发送消息 ====================
 function isAbortError(e) {
 return (
 e?.name === "AbortError" ||
 e?.cause?.name === "AbortError" ||
 /abort|The user aborted/i.test(e?.message || "")
 );
 }

 async function sendStream(message, controller, startTime) {
 const streamWrap = appendStreamBubble();
 let full = "";
 let sessionFromMeta = null;
 let lastPaint = 0;

 startPhaseTimer(startTime, "stream");

 const res = await fetch("/api/chat/stream", {
 method: "POST",
 headers: { "Content-Type": "application/json" },
 body: JSON.stringify({
 message,
 session_id: state.sessionId,
 use_tools: false,
 use_memory: els.useMemory.checked,
 stream: true,
 }),
 signal: controller.signal,
 });

 if (!res.ok) {
 const text = await res.text();
 let detail = text;
 try {
 const j = JSON.parse(text);
 detail = j.detail || j.error || text;
 } catch (_) {}
 throw new Error(
 typeof detail === "string" ? detail : JSON.stringify(detail)
 );
 }

 const reader = res.body.getReader();
 const decoder = new TextDecoder();
 let buffer = "";
 let eventLines = [];

 const consumeEvent = () => {
 if (!eventLines.length) return;
 const payload = eventLines.join("\n");
 eventLines = [];
 if (!payload || payload === "[DONE]") return;
 if (payload.startsWith("[ERROR]")) {
 throw new Error(payload.replace(/^\[ERROR\]\s*/, "") || "流式错误");
 }
 const sidMatch = payload.match(/\[\[session_id:([^\]]+)\]\]/);
 if (sidMatch) {
 sessionFromMeta = sidMatch[1];
 const cleaned = payload.replace(/\n*\[\[session_id:[^\]]+\]\]\s*/g, "");
 if (cleaned) full += cleaned;
 return;
 }
 full += payload;
 const now = Date.now();
 if (now - lastPaint > 40) {
 lastPaint = now;
 updateStreamBubble(streamWrap, full);
 }
 };

 while (true) {
 const { done, value } = await reader.read();
 if (done) break;
 buffer += decoder.decode(value, { stream: true });
 const parts = buffer.split("\n");
 buffer = parts.pop() || "";
 for (const rawLine of parts) {
 const line = rawLine.replace(/\r$/, "");
 if (line === "") {
 consumeEvent();
 continue;
 }
 if (line.startsWith("data:")) {
 eventLines.push(
 line.slice(5).startsWith(" ") ? line.slice(6) : line.slice(5)
 );
 }
 }
 }
 if (buffer) {
 const line = buffer.replace(/\r$/, "");
 if (line.startsWith("data:")) {
 eventLines.push(
 line.slice(5).startsWith(" ") ? line.slice(6) : line.slice(5)
 );
 }
 }
 consumeEvent();
 updateStreamBubble(streamWrap, full);

 let reply = stripThinking(
 full.replace(/\n*\[\[session_id:[^\]]+\]\]\s*/g, "").trim()
 );

 if (sessionFromMeta) {
 state.sessionId = sessionFromMeta;
 localStorage.setItem("session_id", sessionFromMeta);
 els.sessionHint.textContent = `会话 ${sessionFromMeta.slice(0, 8)}… · 流式`;
 }

 if (isDefaultChatTitle()) {
 setChatTitleText(suggestSessionTitle(message));
 }

 if (!reply) {
 streamWrap.remove();
 appendMessage(
 "system",
 "流式返回空内容，可重试或打开「工具」使用完整模式",
 {
 retry: true,
 retryMessage: message,
 }
 );
 setStatus("模型未输出可见内容", "warn");
 return;
 }

 finalizeStreamBubble(streamWrap, reply, {});
 const elapsed = Math.floor((Date.now() - startTime) / 1000);
 setStatus(`完成（${elapsed}s · 流式）`, "ok");
 await loadSessions();
 }

 async function applyChatResult(finalData, message, startTime) {
 if (!finalData) {
  setStatus("无响应数据", "error");
  appendMessage("system", "服务器未返回结果，请重试", {
   retry: true,
   retryMessage: message,
  });
  return;
 }

 const sid = finalData.session_id || state.sessionId;
 if (sid) {
  forgetRun(sid);
  // 若用户已切到别的会话，只更新列表，不往当前屏塞消息
  if (state.sessionId && state.sessionId !== sid) {
   setStatus("后台生成已完成（另一会话）", "ok");
   await loadSessions();
   syncUnreadAfterSessions(sid);
   return;
  }
  state.sessionId = sid;
  localStorage.setItem("session_id", sid);
  if (typeof L.loadEvolutionPanel === "function") L.loadEvolutionPanel();
 }

 els.sessionHint.textContent = `会话 ${
  sid ? sid.slice(0, 8) : "?"
 }… · ${finalData.model || "?"}`;

 if (isDefaultChatTitle()) {
  setChatTitleText(suggestSessionTitle(message));
 }

 const rawCalls = finalData.tool_calls || [];
 const toolCalls = normalizeToolCalls(rawCalls);
 const raw = finalData.reply || finalData.content || "";
 const reply = stripThinking(raw);
 if (!reply) {
  if (toolCalls.length) {
   appendMessage("assistant", "（工具已执行，可见正文为空）", {
    tool_calls: toolCalls,
    usage: finalData.usage || null,
    timestamp: new Date().toISOString(),
   });
   setStatus("无可见正文 · " + toolCalls.length + " 工具", "warn");
   await loadSessions();
   syncUnreadAfterSessions(sid);
   return;
  }
  const hint =
   raw === ""
    ? "模型返回空内容（可能只包含思考过程，已被过滤）"
    : "模型思考了一轮但没有输出可见内容，请再试一次？";
  appendMessage("system", hint, { retry: true, retryMessage: message });
  setStatus("模型未输出可见内容", "warn");
  await loadSessions();
   syncUnreadAfterSessions(sid);
  return;
 }

 appendMessage("assistant", reply, {
  tool_calls: toolCalls,
  usage: finalData.usage || null,
  timestamp: new Date().toISOString(),
  media_paths: finalData.media_paths || [],
  ask_deputy: !!finalData.ask_deputy,
  used_deputy: !!finalData.used_deputy,
  llm_name: finalData.llm_name || "",
  form: finalData.form || null,
  metadata: {
   ask_deputy: !!finalData.ask_deputy,
   used_deputy: !!finalData.used_deputy,
   llm_name: finalData.llm_name || "",
   deputy_reason: finalData.deputy_reason || "",
   form: finalData.form || null,
  },
 });

 const usage = finalData.usage || {};
 const nameBit =
  toolCalls.length > 0
   ? " · " +
     toolCalls.length +
     " 工具（" +
     summarizeToolNames(toolCalls).join(" · ") +
     "）"
   : "";
 const elapsed = Math.floor((Date.now() - startTime) / 1000);
 setStatus("完成（" + elapsed + "s）" + nameBit + formatUsage(usage), "ok");
 await loadSessions();
   syncUnreadAfterSessions(sid);
 }

 /** 订阅后台 run 的 SSE（断开只停监听，服务端继续） */
 async function watchRunEvents(runId, controller, startTime, message) {
  const res = await fetch(
   `/api/chat/runs/${encodeURIComponent(runId)}/events`,
   { signal: controller?.signal }
  );
  if (!res.ok) {
   const text = await res.text();
   throw new Error(text || "无法订阅生成进度");
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalData = null;
  let toolLogCount = 0;

  while (true) {
   const { done, value } = await reader.read();
   if (done) break;
   buffer += decoder.decode(value, { stream: true });
   const parts = buffer.split("\n\n");
   buffer = parts.pop();
   for (const part of parts) {
    for (const raw of part.split("\n")) {
     if (!raw.startsWith("data:")) continue;
     const payload = raw.slice(5).startsWith(" ")
      ? raw.slice(6)
      : raw.slice(5);
     if (payload === "[DONE]") continue;
     try {
      const evt = JSON.parse(payload);
      if (evt.type === "ping") continue;
      if (evt.type === "log") {
       toolLogCount += 1;
       appendTypingLog(evt.line);
      } else if (
       evt.type === "phase" ||
       evt.type === "tool_start" ||
       evt.type === "tool_end" ||
       evt.type === "status"
      ) {
       applyRunProgressEvent(evt);
      } else if (evt.type === "result") {
       finalData = evt;
      } else if (evt.type === "error") {
       if (evt.detail === "cancelled") {
        throw new DOMException("The user aborted a request.", "AbortError");
       }
       throw new Error(evt.detail || "请求失败");
      }
     } catch (parseErr) {
      if (parseErr instanceof SyntaxError) continue;
      throw parseErr;
     }
    }
   }
  }

  clearPhaseTimer();
  removeTyping();
  if (!finalData) {
   if (state.detachWatch) return;
   setStatus("无响应数据", "error");
   appendMessage("system", "服务器未返回结果，请重试", {
    retry: true,
    retryMessage: message,
   });
   return;
  }
  await applyChatResult(finalData, message, startTime);
 }

 async function sendBlocking(message, controller, startTime, metadata) {
 appendTyping();
 startPhaseTimer(startTime, "block");

 const body = {
 message,
 session_id: state.sessionId,
 use_tools: els.useTools.checked,
 use_memory: els.useMemory.checked,
 stream: false,
 };
 if (metadata && typeof metadata === "object" && Object.keys(metadata).length) {
  body.metadata = metadata;
 }
 const res = await fetch("/api/chat", {
 method: "POST",
 headers: { "Content-Type": "application/json" },
 body: JSON.stringify(body),
 signal: controller?.signal,
 });

 if (!res.ok) {
 const text = await res.text();
 let detail = text;
 try {
 const j = JSON.parse(text);
 detail = j.detail || j.error || text;
 } catch (_) {}
 throw new Error(
 typeof detail === "string" ? detail : JSON.stringify(detail)
 );
 }

 const reader = res.body.getReader();
 const decoder = new TextDecoder();
 let buffer = "";
 let finalData = null;
 let toolLogCount = 0;
 let runId = null;

 while (true) {
 const { done, value } = await reader.read();
 if (done) break;
 buffer += decoder.decode(value, { stream: true });

 const parts = buffer.split("\n\n");
 buffer = parts.pop();

 for (const part of parts) {
 const lines = part.split("\n");
 for (const raw of lines) {
 if (!raw.startsWith("data:")) continue;
 const payload = raw.slice(5).startsWith(" ")
 ? raw.slice(6)
 : raw.slice(5);
 if (payload === "[DONE]") continue;
 try {
 const evt = JSON.parse(payload);
 if (evt.type === "ping") continue;
 if (evt.type === "started") {
  runId = evt.run_id;
  state.activeRunId = runId;
  if (evt.session_id) {
   state.sessionId = evt.session_id;
   localStorage.setItem("session_id", evt.session_id);
   rememberRun(evt.session_id, runId, message);
   await loadSessions();
  }
  try {
   sessionStorage.setItem(
    "pending_chat",
    JSON.stringify({
     message,
     session_id: evt.session_id || state.sessionId,
     run_id: runId,
     time: startTime,
    })
   );
  } catch (_) {}
 } else if (evt.type === "log") {
 toolLogCount += 1;
 appendTypingLog(evt.line);
 } else if (
  evt.type === "phase" ||
  evt.type === "tool_start" ||
  evt.type === "tool_end" ||
  evt.type === "status"
 ) {
  applyRunProgressEvent(evt);
 } else if (evt.type === "result") {
 finalData = evt;
 } else if (evt.type === "error") {
  if (evt.detail === "cancelled") {
   throw new DOMException("The user aborted a request.", "AbortError");
  }
  throw new Error(evt.detail || "请求失败");
 }
 } catch (parseErr) {
 if (parseErr instanceof SyntaxError) continue;
 throw parseErr;
 }
 }
 }
 }

 clearPhaseTimer();
 removeTyping();

 if (!finalData) {
  if (state.detachWatch) return; // 切换/离开：后台仍在跑
 setStatus("无响应数据", "error");
 appendMessage("system", "服务器未返回结果，请重试", {
 retry: true,
 retryMessage: message,
 });
 return;
 }

 await applyChatResult(finalData, message, startTime);
 }

 function extrasFromStored(m, isTail) {
  const meta = m.metadata || {};
  return {
   tool_calls: extractToolCalls(m),
   usage: m.usage || null,
   timestamp: m.created_at || m.timestamp || null,
   fromStore: true,
   media_paths: meta.media_paths || m.media_paths || [],
   metadata: meta,
   msgId: m.id || "",
   used_deputy: !!meta.used_deputy,
   llm_name: meta.llm_name || "",
   ask_deputy: !!(isTail && meta.ask_deputy),
   form: isTail ? meta.form || null : null,
  };
 }

 function lastDomUserText() {
 const nodes = document.querySelectorAll("#messages .msg.user .bubble");
 if (!nodes.length) return "";
 return (nodes[nodes.length - 1].textContent || "").trim();
 }

 function trimDomFromLastUser() {
 const root = els.messages;
 if (!root) return;
 const users = [...root.querySelectorAll(".msg.user")];
 const last = users[users.length - 1];
 if (!last) return;
 let node = last;
 while (node) {
 const next = node.nextElementSibling;
 node.remove();
 node = next;
 }
 if (typeof L.refreshTurnActions === "function") L.refreshTurnActions();
 }

 function trimDomAfterLastUser() {
 const root = els.messages;
 if (!root) return;
 const users = [...root.querySelectorAll(".msg.user")];
 const last = users[users.length - 1];
 if (!last) return;
 let node = last.nextElementSibling;
 while (node) {
 const next = node.nextElementSibling;
 node.remove();
 node = next;
 }
 if (typeof L.refreshTurnActions === "function") L.refreshTurnActions();
 }

 async function rewindSessionKeep(keep) {
 if (!state.sessionId) return;
 await api(`/api/sessions/${encodeURIComponent(state.sessionId)}/rewind`, {
 method: "POST",
 body: { keep },
 });
 }

 async function lastStoredUserIndex() {
 if (!state.sessionId) return { idx: -1, text: "", total: 0 };
 try {
 const data = await api(`/api/sessions/${encodeURIComponent(state.sessionId)}`);
 const msgs = Array.isArray(data?.messages) ? data.messages : [];
 let idx = -1;
 for (let i = msgs.length - 1; i >= 0; i--) {
 if (msgs[i]?.role === "user") {
 idx = i;
 break;
 }
 }
 return {
 idx,
 text: idx >= 0 ? String(msgs[idx].content || "") : "",
 total: msgs.length,
 };
 } catch (_) {
 return { idx: -1, text: "", total: 0 };
 }
 }

 async function editLastUser(preset) {
 if (state.busy) {
 showToast("请先停止当前生成", "warn");
 return;
 }
 const stored = await lastStoredUserIndex();
 let text = String(preset || "").trim() || stored.text || lastDomUserText();
 if (!text) {
 showToast("没有可改写的上一句", "warn");
 return;
 }
 if (stored.idx >= 0) {
 try {
 await rewindSessionKeep(stored.idx);
 } catch (e) {
 showToast("撤回上一轮失败: " + (e.message || e), "error");
 return;
 }
 }
 trimDomFromLastUser();
 els.input.value = text;
 autoResize();
 els.input.focus();
 showToast("已放回输入框，改完再发送", "info");
 }

 async function retryLastTurn() {
 if (state.busy) return;
 const stored = await lastStoredUserIndex();
 const text = stored.text || lastDomUserText();
 if (!text) {
 showToast("没有可重试的上一句", "warn");
 return;
 }
 if (stored.idx >= 0) {
 try {
 await rewindSessionKeep(stored.idx + 1);
 } catch (e) {
 showToast("撤回失败: " + (e.message || e), "error");
 return;
 }
 }
 trimDomAfterLastUser();
 await send({ message: text, skipUserAppend: true });
 }

 async function send(opts = {}) {
 if (state.busy) {
 cancelRequest();
 return;
 }
 if (typeof L.hasChatLlm === "function" ? !L.hasChatLlm() : !state.llmConfigured) {
  showToast("先添加一个对话模型", "warn");
  if (typeof L.goAddLlm === "function") L.goAddLlm();
  return;
 }

 const skipUserAppend = !!(opts && opts.skipUserAppend);
 const metadata =
  opts && opts.metadata && typeof opts.metadata === "object"
   ? opts.metadata
   : null;
 const forced = opts && typeof opts.message === "string" ? opts.message : "";
 const typed = forced ? "" : els.input.value.trim();
 const consume = forced
 ? { textSuffix: "", attachments: [] }
 : typeof L.consumeAttachmentsForSend === "function"
 ? L.consumeAttachmentsForSend()
 : { textSuffix: "", attachments: [] };
 const attachments = consume.attachments || [];
 if (!forced && !typed && !attachments.length) return;

 const message = (forced || (typed + (consume.textSuffix || ""))).trim();
 if (!message) return;

 const controller = new AbortController();
 const watchToken = Symbol("watch");
 state.abortController = controller;
 state._watchToken = watchToken;
 state.detachWatch = false;
 state.activeRunId = null;
 const startTime = Date.now();

 // 默认走后台可脱离的完整模式（关页/切会话仍继续）
 // 仅「无附件 + 明确关工具」时用流式（流式仍绑定当前页）
 const preferStream = !els.useTools.checked && !attachments.length;
 if (preferStream) {
  setStatus("纯文本流式（不调技能/工具）");
 }

 setBusy(true);
 els.input.value = "";
 autoResize();

 const empty = els.messages.querySelector(".empty");
 if (empty) empty.remove();
 // 发送即退出居中主页，输入框回底部（appendMessage 也会再确保一次）
 if (typeof L.setHomeHeroMode === "function") L.setHomeHeroMode(false);
 // 手机：发送后保持键盘（多轮对话），并确保滚到最新
 try {
  if (window.matchMedia("(max-width: 900px)").matches) {
   state.stickToBottom = true;
   requestAnimationFrame(() => {
    if (typeof L.scrollMessages === "function") L.scrollMessages(true);
   });
  }
 } catch (_) {}

 if (!skipUserAppend) {
 const displayText =
  (typed || forced || "").trim() ||
  (attachments.length ? "（已上传文件）" : message);
 appendMessage("user", displayText, {
 timestamp: new Date().toISOString(),
 attachments,
 media_paths: attachments.map((a) => a.path),
 });
 }

 try {
 sessionStorage.setItem(
 "pending_chat",
 JSON.stringify({
 message,
 session_id: state.sessionId,
 time: startTime,
 })
 );
 } catch (_) {}

 try {
 if (preferStream) {
 try {
 await sendStream(message, controller, startTime);
 } catch (streamErr) {
 if (isAbortError(streamErr)) throw streamErr;
 removeTyping();
 const sm = document.getElementById("streamMsg");
 if (sm) sm.remove();
 setStatus("流式失败，改用完整模式…", "warn");
 showToast("流式失败，已切换完整模式", "warn");
 await sendBlocking(message, controller, startTime, metadata);
 }
 } else {
 await sendBlocking(message, controller, startTime, metadata);
 }
 } catch (e) {
 if (state._watchToken === watchToken) removeTyping();
 const sm = document.getElementById("streamMsg");
 if (sm) sm.remove();
 if (state.detachWatch || (isAbortError(e) && state.detachWatch)) {
  setStatus("已切换；生成在后台继续", "");
 } else if (isAbortError(e)) {
  // 用户点停止
  setStatus("已停止", "");
 } else if (state._watchToken === watchToken) {
 appendMessage("system", `请求失败: ${e.message}`, {
 retry: true,
 retryMessage: message,
 });
 setStatus(e.message, "error");
 showToast("请求失败: " + e.message, "error");
 }
 } finally {
 // 若已切换会话并开启新的监听，不要清掉新 controller / busy
 if (state._watchToken === watchToken) {
  const wasDetach = state.detachWatch;
  setBusy(false);
  try {
   if (!wasDetach) sessionStorage.removeItem("pending_chat");
  } catch (_) {}
  clearPhaseTimer();
  state.abortController = null;
  state.detachWatch = false;
  if (!wasDetach) {
   const asking = els.messages?.querySelector(
    ".msg.assistant:last-child .ask-form:not(.is-done)"
   );
   if (!asking) els.input?.focus();
  }
 }
 await loadSessions();
 if (state._watchToken === watchToken && !state.detachWatch) {
  if (typeof L.syncDomMessageIds === "function") await L.syncDomMessageIds();
 }
 }
 }

 async function syncDomMessageIds() {
 if (!state.sessionId || !els.messages) return;
 try {
  const data = await api(`/api/sessions/${encodeURIComponent(state.sessionId)}`);
  const stored = (data.messages || []).filter(
   (m) => m && (m.role === "user" || m.role === "assistant")
  );
  const vis = [...els.messages.querySelectorAll(".msg.user, .msg.assistant")]
   .filter((el) => !el.classList.contains("typing-msg") && el.dataset.ephemeral !== "1");
  const n = Math.min(stored.length, vis.length);
  for (let i = 1; i <= n; i++) {
   const id = stored[stored.length - i]?.id;
   if (id) vis[vis.length - i].dataset.msgId = id;
  }
 } catch (_) {}
 }

 function visibleChatMsgs() {
 if (!els.messages) return [];
 return [...els.messages.querySelectorAll(".msg.user, .msg.assistant")].filter(
  (el) => !el.classList.contains("typing-msg") && el.dataset.ephemeral !== "1"
 );
 }

 async function deleteChatMessage(wrap) {
 if (!(wrap instanceof HTMLElement)) return;
 if (state.busy) {
  showToast("生成中，请稍后再删", "warn");
  return;
 }
 if (!window.confirm("删除这条消息？可在提示里撤销。")) return;
 if (wrap.dataset.ephemeral === "1" || !state.sessionId) {
  wrap.remove();
  if (!els.messages.querySelector(".msg.user, .msg.assistant")) showEmpty();
  if (typeof L.refreshTurnActions === "function") L.refreshTurnActions();
  return;
 }
 try {
  await syncDomMessageIds();
  const vis = visibleChatMsgs();
  const index = vis.indexOf(wrap);
  const msgId = wrap.dataset.msgId || "";
  if (index < 0 && !msgId) {
   wrap.remove();
   if (typeof L.refreshTurnActions === "function") L.refreshTurnActions();
   return;
  }
  const sid = state.sessionId;
  const title = getChatTitleText();
  const res = await api(
   `/api/sessions/${encodeURIComponent(sid)}/messages/delete`,
   { method: "POST", body: { id: msgId || null, index: index < 0 ? null : index } }
  );
  wrap.remove();
  if (!els.messages.querySelector(".msg.user, .msg.assistant")) showEmpty();
  if (typeof L.refreshTurnActions === "function") L.refreshTurnActions();
  await loadSessions();
  const removed = res && res.removed;
  const dropAt = res && typeof res.index === "number" ? res.index : null;
  if (removed && dropAt != null) {
   showToast("消息已删除", "success", 8000, {
    label: "撤销",
    onClick: async () => {
     try {
      await api(
       `/api/sessions/${encodeURIComponent(sid)}/messages/restore`,
       { method: "POST", body: { message: removed, index: dropAt } }
      );
      if (state.sessionId === sid) {
       await openSession(sid, title);
      } else {
       await loadSessions();
      }
      showToast("已撤销删除", "success");
     } catch (err) {
      showToast("撤销失败: " + (err.message || err), "error");
     }
    },
   });
  }
 } catch (e) {
  showToast("删除失败: " + (e.message || e), "error");
 }
 }

 // Export
 L.api = api;
 L.loadHealth = loadHealth;
 L.deleteSession = deleteSession;
 L.renderSessionList = renderSessionList;
 L.filterSessions = filterSessions;
 L.loadSessions = loadSessions;
 L.openSession = openSession;
 L.newChat = newChat;
 L.isAbortError = isAbortError;
 L.sendStream = sendStream;
 L.sendBlocking = sendBlocking;
 L.send = send;
 L.editLastUser = editLastUser;
 L.retryLastTurn = retryLastTurn;
 L.syncDomMessageIds = syncDomMessageIds;
 L.deleteChatMessage = deleteChatMessage;
 L.refreshAuthChrome = refreshAuthChrome;
 L.applyAuthChrome = applyAuthChrome;
 // cancelRequest 以 app-render 的为准（操作 state.abortController）
})(window.Lily);

