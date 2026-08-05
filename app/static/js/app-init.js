/**
 * Lily - Init (Event Binding + Sidebar + Mobile + Startup)
 */
((L) => {
 "use strict";
 const { $, els, state, showToast, debounce } = L;

 // 通过 L 调用，避免加载顺序导致的陈旧闭包
 const api = (...a) => L.api(...a);
 const setMsg = (...a) => L.setMsg(...a);
 const setStatus = (...a) => L.setStatus(...a);
 const setSidebarOpen = (...a) => L.setSidebarOpen(...a);
 const nearBottom = (...a) => L.nearBottom(...a);
 const scrollMessages = (...a) => L.scrollMessages(...a);
 const autoResize = (...a) => L.autoResize(...a);
 const showEmpty = (...a) => L.showEmpty(...a);
 const openConfig = (...a) => L.openConfig(...a);
 const closeConfig = (...a) => L.closeConfig(...a);
 const switchTab = (...a) => L.switchTab(...a);
 const loadTasks = (...a) => L.loadTasks(...a);
 const loadMemory = (...a) => L.loadMemory(...a);
 const addMemory = (...a) => L.addMemory(...a);
 const loadHealth = (...a) => L.loadHealth(...a);
 const loadSessions = (...a) => L.loadSessions(...a);
 const openSession = (...a) => L.openSession(...a);
 const newChat = (...a) => L.newChat(...a);
 const filterSessions = (...a) => L.filterSessions(...a);
 const send = (...a) => L.send(...a);

 function updateModeHint() {
 const chip = $("modeHint");
 if (!chip) return;
 // 工具/记忆默认开启且界面不展示开关；仍按隐藏 checkbox 状态刷新文案
 const toolsOn = !els.useTools || els.useTools.checked;
 const narrow =
  typeof window.matchMedia === "function" &&
  window.matchMedia("(max-width: 640px)").matches;
 if (toolsOn) {
 chip.textContent = narrow ? "工具开" : "模式：工具开启 · 完整回复";
 chip.title = "默认可调用技能/工具；回复为完整模式（含进度日志）";
 } else {
 chip.textContent = narrow ? "流式" : "模式：工具关闭 · 流式回复";
 chip.title = "关闭工具时使用流式输出，响应更快";
 }
 }

 function updateScrollBottomBtn() {
 const btn = $("btnScrollBottom");
 if (!btn || !els.messages) return;
 const show = !nearBottom(els.messages, 120);
 btn.classList.toggle("hidden", !show);
 }

 // ==================== Tabs / memory / tasks 事件绑定 ====================
 // config-modal.html 是异步注入的：本机 LAN 快时常在 init 前就就绪，
 // 远程/跨机访问（如 10.11.11.x）时 fetch 更慢，querySelector 绑定时 DOM 还不存在。
 // 统一用 document 事件委托，注入后再点也能响应。
 const onMemSearch = debounce(() => {
  loadMemory($("memSearch")?.value?.trim() || "");
 }, 300);

 async function saveAgentFromForm() {
  const data =
   typeof L.collectAgentFormPayload === "function"
    ? L.collectAgentFormPayload()
    : {
       name: $("cfgAgentName")?.value || "",
       role: L.getMsSelection?.("role") || [],
       language: $("cfgLanguage")?.value || "跟随用户",
       language_style: L.getMsSelection?.("language_style") || [],
       background: $("cfgBackground")?.value || "",
       decision_tree: $("cfgDecisionTree")?.value || "",
       language_calibrator: $("cfgLanguageCalibrator")?.value || "",
       sop: $("cfgSop")?.value || "",
       hard_boundaries: $("cfgHardBoundaries")?.value || "",
       greeting: $("cfgGreeting")?.value || "",
       max_tool_rounds: parseInt($("cfgMaxRounds")?.value, 10) || 8,
       max_history_messages: parseInt($("cfgMaxHistory")?.value, 10) || 40,
       evolution_enabled: ($("cfgEvoEnabled")?.value || "1") !== "0",
       evolution_trigger_messages: parseInt($("cfgEvoTrigger")?.value, 10) || 24,
       evolution_keep_messages: parseInt($("cfgEvoKeep")?.value, 10) || 16,
       evolution_max_entries: parseInt($("cfgEvoMaxEntries")?.value, 10) || 12,
      };
  // 助手模式：建议填写角色背景；扮演模式：角色背景或扮演字段至少一项
  const roleplayOn = !!data.roleplay_enabled;
  const roleBg = String(data.background || "").trim();
  if (!roleplayOn) {
   if (!roleBg) {
    setMsg("msgAgent", "请填写「角色背景」（或开启角色扮演）", "error");
    return;
   }
  } else {
   const hasPersona = [
    data.name,
    roleBg,
    data.relationship,
    data.personality,
    data.speech_patterns,
    data.example_dialogue,
   ].some((x) => String(x || "").trim());
   if (!hasPersona) {
    setMsg(
     "msgAgent",
     "启用扮演时，请至少填写：名称、角色背景、关系、性格、说话方式或示例对话之一",
     "error"
    );
    return;
   }
  }
  try {
   await api("/api/config/agent", {
    method: "PATCH",
    body: JSON.stringify(data),
   });
   setMsg("msgAgent", "人设已保存", "ok");
   showToast("人设已保存（系统工具规则仍固定）", "success");
   try {
    const cfg = await api("/api/config");
    state.config = cfg;
    L.renderAgentForm?.(cfg);
    if (typeof L.refreshVoiceLangFromPersona === "function") {
     L.refreshVoiceLangFromPersona();
    }
   } catch (_) {}
   loadHealth();
  } catch (e) {
   setMsg("msgAgent", e.message, "error");
   showToast("保存失败", "error");
  }
 }

 document.addEventListener("click", (e) => {
  const t = e.target;
  if (!(t instanceof Element)) return;

  // 设定顶栏选项卡（#configTabs 内 .tab[data-tab]）
  const tabBtn = t.closest("#configTabs .tab[data-tab], #configModal .tabs .tab[data-tab]");
  if (tabBtn) {
   const name = tabBtn.dataset.tab;
   if (name) switchTab(name);
   return;
  }

  if (t.id === "btnRefreshTasks" || t.closest("#btnRefreshTasks")) {
   loadTasks();
   return;
  }
  if (t.id === "btnRefreshMemory" || t.closest("#btnRefreshMemory")) {
   loadMemory($("memSearch")?.value || "");
   return;
  }
  if (t.id === "btnSearchMemory" || t.closest("#btnSearchMemory")) {
   loadMemory($("memSearch")?.value || "");
   return;
  }
  if (t.id === "btnAddMemory" || t.closest("#btnAddMemory")) {
   addMemory();
   return;
  }
  if (t.id === "btnSaveAgent" || t.closest("#btnSaveAgent")) {
   saveAgentFromForm();
  }
 });

 document.addEventListener("input", (e) => {
  const t = e.target;
  if (!(t instanceof Element)) return;
  if (t.id === "memSearch") onMemSearch();
 });

 // ==================== Sidebar / quick / 移动端手势 ====================
 $("btnMenu")?.addEventListener("click", () => {
 setSidebarOpen(!document.body.classList.contains("sidebar-open"));
 });
 $("sidebarScrim")?.addEventListener("click", () => setSidebarOpen(false));

 $("btnQuickTasks")?.addEventListener("click", () => openConfig("tasks"));
 $("btnQuickMemory")?.addEventListener("click", () => openConfig("memory"));

 let touchStartX = 0;
 let touchStartY = 0;
 let edgeSwipe = false;

 document.addEventListener(
 "touchstart",
 (e) => {
 const t = e.changedTouches[0];
 touchStartX = t.clientX;
 touchStartY = t.clientY;
 edgeSwipe =
 touchStartX <= 24 || document.body.classList.contains("sidebar-open");
 },
 { passive: true }
 );

 document.addEventListener(
 "touchend",
 (e) => {
 if (!edgeSwipe) return;
 const t = e.changedTouches[0];
 const dx = t.clientX - touchStartX;
 const dy = t.clientY - touchStartY;
 if (Math.abs(dx) < 50 || Math.abs(dx) < Math.abs(dy)) return;
 if (dx > 0 && touchStartX <= 24) setSidebarOpen(true);
 else if (dx < 0 && document.body.classList.contains("sidebar-open")) {
 setSidebarOpen(false);
 }
 edgeSwipe = false;
 },
 { passive: true }
 );

 // 消息区：用户上滑阅读时不强制贴底 + 显示「回到底部」
 els.messages?.addEventListener(
 "scroll",
 () => {
 state.stickToBottom = nearBottom(els.messages, 100);
 updateScrollBottomBtn();
 },
 { passive: true }
 );

 $("btnScrollBottom")?.addEventListener("click", () => {
 state.stickToBottom = true;
 scrollMessages(true);
 updateScrollBottomBtn();
 });

 // ---- 移动端视口高度 + 键盘适配（iOS/Android 浏览器） ----
 function syncMobileViewport() {
 const root = document.documentElement;
 const vv = window.visualViewport;
 const height = vv && vv.height ? vv.height : window.innerHeight;
 // 用实际可见高度，避免 100vh 被地址栏/键盘撑破
 root.style.setProperty("--app-height", `${Math.round(height)}px`);
 if (vv) {
 root.style.setProperty("--vv-offset", `${Math.round(vv.offsetTop || 0)}px`);
 // 键盘弹出：可视高度明显小于布局高度
 const full = window.innerHeight || height;
 const open = height < full - 120;
 document.body.classList.toggle("kb-open", open);
 } else {
 document.body.classList.remove("kb-open");
 }
 }

 syncMobileViewport();
 window.addEventListener("resize", syncMobileViewport, { passive: true });
 window.addEventListener("orientationchange", () => {
 setTimeout(syncMobileViewport, 120);
 setTimeout(syncMobileViewport, 400);
 });

 if ("visualViewport" in window && window.visualViewport) {
 let lastHeight = window.visualViewport.height;
 const onVvChange = () => {
 const view = window.visualViewport;
 syncMobileViewport();
 const diff = lastHeight - view.height;
 if (diff > 80) {
 // 键盘升起：把输入区滚进可视区
 const composer = document.querySelector(".composer");
 if (composer) {
 setTimeout(() => {
 composer.scrollIntoView({ block: "end", behavior: "smooth" });
 if (state.stickToBottom) scrollMessages(true);
 }, 60);
 }
 } else if (diff < -40 && state.stickToBottom) {
 scrollMessages(false);
 }
 lastHeight = view.height;
 };
 window.visualViewport.addEventListener("resize", onVvChange);
 window.visualViewport.addEventListener("scroll", syncMobileViewport);
 }

 // 输入框聚焦时再同步一次（部分 WebView 只在 focus 后改高度）
 els.input?.addEventListener("focus", () => {
 setTimeout(syncMobileViewport, 50);
 setTimeout(syncMobileViewport, 300);
 });
 els.input?.addEventListener("blur", () => {
 setTimeout(syncMobileViewport, 50);
 setTimeout(() => document.body.classList.remove("kb-open"), 200);
 });

 // Enter 发送；Shift+Enter 换行
 els.input?.addEventListener("keydown", (e) => {
 if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
 e.preventDefault();
 send();
 }
 });

 if (els.sessionSearch) {
 els.sessionSearch.addEventListener(
 "input",
 debounce(() => filterSessions(els.sessionSearch.value), 180)
 );
 }

 els.useTools?.addEventListener("change", () => {
 try {
 localStorage.setItem("lily_use_tools", els.useTools.checked ? "1" : "0");
 } catch (_) {}
 updateModeHint();
 });
 els.useMemory?.addEventListener("change", () => {
 try {
 localStorage.setItem("lily_use_memory", els.useMemory.checked ? "1" : "0");
 } catch (_) {}
 });

 // ==================== 事件绑定 & 初始化 ====================
 els.btnNewChat?.addEventListener("click", newChat);
 els.btnSend?.addEventListener("click", send);
 els.input?.addEventListener("input", autoResize);

 // 文件上传（选择 / 拖拽 / 粘贴）
 if (typeof L.bindUploadUI === "function") L.bindUploadUI();
 // 语音输入（语言跟随人设）
 if (typeof L.bindVoiceUI === "function") L.bindVoiceUI();

 els.btnOpenConfig?.addEventListener("click", () => openConfig());

 // config modal 可能异步注入，统一用事件委托
 document.addEventListener("click", (e) => {
 const t = e.target;
 if (!(t instanceof Element)) return;
 if (t.id === "btnCloseConfig" || t.closest("#btnCloseConfig")) {
 closeConfig();
 return;
 }
 if (t.id === "configModal") {
 closeConfig();
 }
 });

 document.addEventListener("keydown", (e) => {
 if (e.key !== "Escape") return;
 // 知识页 / 任务新建 子弹优先关闭（叠在设定之上）
 const taskModal = $("taskPageModal");
 if (taskModal && !taskModal.classList.contains("hidden")) {
 if (typeof L.closeTaskEditor === "function") L.closeTaskEditor();
 else taskModal.classList.add("hidden");
 return;
 }
 const kbModal = $("kbPageModal");
 if (kbModal && !kbModal.classList.contains("hidden")) {
 if (typeof L.closeKbPageModal === "function") L.closeKbPageModal();
 else kbModal.classList.add("hidden");
 return;
 }
 const modal = $("configModal");
 if (modal && !modal.classList.contains("hidden")) {
 closeConfig();
 return;
 }
 if (document.body.classList.contains("sidebar-open")) {
 setSidebarOpen(false);
 }
 });

 // 仅保留后台 run 标记（侧栏绿点），不自动打开该会话
 try {
 const pending = sessionStorage.getItem("pending_chat");
 if (pending) {
 const p = JSON.parse(pending);
 if (p.run_id && p.session_id) {
  if (!state.chatRuns) state.chatRuns = {};
  state.chatRuns[p.session_id] = {
   runId: p.run_id,
   message: p.message || "",
   status: "running",
  };
  try {
   sessionStorage.setItem("chat_runs", JSON.stringify(state.chatRuns));
  } catch (_) {}
 }
 try {
  sessionStorage.removeItem("pending_chat");
 } catch (_) {}
 }
 } catch (_) {}

 // 生成已改为服务端后台任务：关页/刷新不再拦截。
 // 离开时只断开本页监听；任务继续，回来后可从会话里看到结果。
 window.addEventListener("pagehide", () => {
  if (typeof L.detachWatchOnly === "function" && (state.busy || state.abortController)) {
   try {
    L.detachWatchOnly();
   } catch (_) {}
  }
 });

 // 启动：轻量并行 — 健康检查 / 会话列表 / 人设（不预拉 tools/skills 重接口）
 updateModeHint();
 showEmpty();
 if (typeof L.hydrateIconPark === "function") {
 L.hydrateIconPark(document);
 }
 // config modal 注入完成后补一次图标（异步 HTML）
 if (window.__configModalReady && typeof window.__configModalReady.then === "function") {
  window.__configModalReady.then((ok) => {
   if (ok && typeof L.hydrateIconPark === "function") {
    L.hydrateIconPark(document.getElementById("configModalContainer") || document);
   }
  });
 }
 // 合并启动请求：health 内已拉 agent；此处只再拉一份完整 /api/config 做人设缓存
 loadHealth();
 (async () => {
  try {
   const cfg = await api("/api/config");
   state.config = cfg;
   if (typeof L.refreshVoiceLangFromPersona === "function") {
    L.refreshVoiceLangFromPersona();
   }
  } catch (_) {}
 })();
 // 打开站点地址：始终空白新对话，不自动恢复上次会话
 try {
  localStorage.removeItem("session_id");
 } catch (_) {}
 state.sessionId = null;
 if (typeof newChat === "function") {
  // newChat 会清会话并 showEmpty / 问候语
  try {
   newChat();
  } catch (_) {
   showEmpty();
  }
 } else {
  showEmpty();
 }
 // 仅刷新侧栏列表，不 openSession
 loadSessions().catch(() => {});
})(window.Lily);
