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
 const setSidebarOpen = (...a) => L.setSidebarOpen(...a);
 const clearMessages = (...a) => L.clearMessages(...a);
 const showEmpty = (...a) => L.showEmpty(...a);
 const updateTypingPhase = (...a) => L.updateTypingPhase(...a);
 const appendTypingLog = (...a) => L.appendTypingLog(...a);
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
 return !t || t === "新对话" || t === "新对话";
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
 const detail = data?.detail || data?.error || res.statusText;
 throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
 }
 return data;
 }

 // ==================== 会话管理 ====================
 async function loadHealth() {
 try {
 const h = await api("/health");
 els.agentName.textContent = h.agent || "Lily ";
 const tasksBit =
 h.scheduled_tasks != null ? ` · tasks ${h.scheduled_tasks}` : "";
 els.agentMeta.textContent = `${h.llm_provider || "?"}/${h.llm_model || "?"} · tools ${h.tools || 0}${tasksBit}`;
 document.title = h.agent ? `${h.agent}` : "Lily — AI 助手";
 } catch (e) {
 els.agentMeta.textContent = "连接后端失败";
 setStatus(e.message, "error");
 showToast("健康检查失败: " + e.message, "error");
 }
 // 仅当尚未缓存人设时再拉（启动路径会并行拉 /api/config）
 if (!(state.config && state.config.agent)) {
  try {
   const agent = await api("/api/config/agent");
   state.config = state.config || {};
   state.config.agent = agent;
  } catch (_) {}
 }
 }

 async function deleteSession(sessionId, ev) {
 if (ev) {
 ev.preventDefault();
 ev.stopPropagation();
 }
 if (!confirm("确定删除这段对话？删除后无法恢复。")) return;
 try {
 await api(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
 if (state.sessionId === sessionId) {
 newChat();
 } else {
 await loadSessions();
 }
 setStatus("已删除对话", "ok");
 showToast("对话已删除", "success");
 } catch (e) {
 setStatus("删除失败: " + e.message, "error");
 showToast("删除失败: " + e.message, "error");
 }
 }

 function renderSessionList(rows) {
 els.sessionList.innerHTML = "";
 if (!rows.length) {
 els.sessionList.innerHTML =
 '<div class="session-item"><div class="meta">暂无对话</div></div>';
 return;
 }
 for (const s of rows) {
 const row = document.createElement("div");
 const generating = sessionIsGenerating(s.session_id);
 row.className =
 "session-item" +
 (s.session_id === state.sessionId ? " active" : "") +
 (generating ? " is-generating" : "");
 const updated = s.updated_at || s.created_at;
 const timeBit = updated ? timeAgo(updated) : "";
 const genBit = generating ? " · 生成中" : "";
 row.innerHTML = `
 <div class="session-main">
 <div class="title">${escapeHtml(s.title || "未命名对话")}${generating ? ' <span class="session-gen-dot" title="后台生成中"></span>' : ""}</div>
 <div class="meta">${s.message_count ?? "?"} 条${timeBit ? ` · ${escapeHtml(timeBit)}` : ""}${genBit}</div>
 </div>
 <button type="button" class="session-rename" title="重命名" aria-label="重命名">${_ipk("edit","ipk-sm")}</button>
 <button type="button" class="session-del" title="删除对话" aria-label="删除">${_ipk("delete","ipk-sm")}</button>`;
 row.querySelector(".session-main").addEventListener("click", () => {
 setSidebarOpen(false);
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

 function filterSessions(q) {
 const query = (q || "").trim().toLowerCase();
 if (!query) {
 renderSessionList(state.sessionsCache);
 return;
 }
 const filtered = state.sessionsCache.filter((s) => {
 const title = (s.title || "").toLowerCase();
 const id = (s.session_id || "").toLowerCase();
 return title.includes(query) || id.includes(query);
 });
 renderSessionList(filtered);
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
 for (const m of messages) {
 const role =
 m.role === "user" || m.role === "assistant" ? m.role : "system";
 if (role === "system") continue;
 const tools = extractToolCalls(m);
 appendMessage(role, m.content || "", {
 tool_calls: tools,
 usage: m.usage || null,
 timestamp: m.created_at || m.timestamp,
 media_paths: m.metadata?.media_paths || m.media_paths || [],
 metadata: m.metadata || null,
 });
 }
 setStatus("");
 requestAnimationFrame(() => L.scrollMessages(true));
 // 若该会话仍有后台任务，重新附着进度；否则清掉残留绿点
 await reattachSessionRun(sessionId);
 await loadSessions();
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
 const greeting = String(
  (state.config && state.config.agent && state.config.agent.greeting) || ""
 ).trim();
 if (greeting) {
  appendMessage("assistant", greeting, { ephemeral: true, greeting: true });
 } else {
  showEmpty();
 }
 setStatus("");
 setSidebarOpen(false);
 loadSessions();
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
     for (const m of messages) {
      const role =
       m.role === "user" || m.role === "assistant" ? m.role : "system";
      if (role === "system") continue;
      appendMessage(role, m.content || "", {
       tool_calls: extractToolCalls(m),
       usage: m.usage || null,
       timestamp: m.created_at || m.timestamp,
       media_paths: m.metadata?.media_paths || m.media_paths || [],
       metadata: m.metadata || null,
      });
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
    for (const m of data.messages || []) {
     const role =
      m.role === "user" || m.role === "assistant" ? m.role : "system";
     if (role === "system") continue;
     appendMessage(role, m.content || "", {
      tool_calls: extractToolCalls(m),
      usage: m.usage || null,
      timestamp: m.created_at || m.timestamp,
      media_paths: m.metadata?.media_paths || m.media_paths || [],
      metadata: m.metadata || null,
     });
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
 setChatTitleText(message.slice(0, 40));
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
   return;
  }
  state.sessionId = sid;
  localStorage.setItem("session_id", sid);
 }

 els.sessionHint.textContent = `会话 ${
  sid ? sid.slice(0, 8) : "?"
 }… · ${finalData.model || "?"}`;

 if (isDefaultChatTitle()) {
  setChatTitleText(message.slice(0, 40));
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
   return;
  }
  const hint =
   raw === ""
    ? "模型返回空内容（可能只包含思考过程，已被过滤）"
    : "模型思考了一轮但没有输出可见内容，请再试一次？";
  appendMessage("system", hint, { retry: true, retryMessage: message });
  setStatus("模型未输出可见内容", "warn");
  await loadSessions();
  return;
 }

 appendMessage("assistant", reply, {
  tool_calls: toolCalls,
  usage: finalData.usage || null,
  timestamp: new Date().toISOString(),
  media_paths: finalData.media_paths || [],
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
       if (toolLogCount === 1 || toolLogCount % 3 === 0) {
        const elapsed = Math.floor((Date.now() - startTime) / 1000);
        updateTypingPhase(
         elapsed,
         `运行中…（${elapsed}s · ${toolLogCount} 条日志）`
        );
       }
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

 async function sendBlocking(message, controller, startTime) {
 appendTyping();
 startPhaseTimer(startTime, "block");

 const body = {
 message,
 session_id: state.sessionId,
 use_tools: els.useTools.checked,
 use_memory: els.useMemory.checked,
 stream: false,
 };
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
 if (toolLogCount === 1 || toolLogCount % 3 === 0) {
 const elapsed = Math.floor((Date.now() - startTime) / 1000);
 updateTypingPhase(
 elapsed,
 `运行中…（${elapsed}s · ${toolLogCount} 条日志）`
 );
 }
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

 async function send() {
 if (state.busy) {
 cancelRequest();
 return;
 }

 const typed = els.input.value.trim();
 const consume =
 typeof L.consumeAttachmentsForSend === "function"
 ? L.consumeAttachmentsForSend()
 : { textSuffix: "", attachments: [] };
 const attachments = consume.attachments || [];
 // 有附件时可只发附件不打字
 if (!typed && !attachments.length) return;

 const message = (typed + (consume.textSuffix || "")).trim();
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

 setBusy(true);
 els.input.value = "";
 autoResize();

 const empty = els.messages.querySelector(".empty");
 if (empty) empty.remove();

 appendMessage("user", typed || "（已上传文件）", {
 timestamp: new Date().toISOString(),
 attachments,
 media_paths: attachments.map((a) => a.path),
 });

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
 await sendBlocking(message, controller, startTime);
 }
 } else {
 await sendBlocking(message, controller, startTime);
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
  if (!wasDetach) els.input?.focus();
 }
 await loadSessions();
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
 // cancelRequest 以 app-render 的为准（操作 state.abortController）
})(window.Lily);
