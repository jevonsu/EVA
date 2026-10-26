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
 const isSidebarOpen = (...a) => L.isSidebarOpen(...a);
 const closeMobileSidebar = (...a) => L.closeMobileSidebar(...a);
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
 const toolsOn = !els.useTools || els.useTools.checked;
 const narrow =
  typeof window.matchMedia === "function" &&
  window.matchMedia("(max-width: 640px)").matches;
 chip.setAttribute("aria-pressed", toolsOn ? "true" : "false");
 if (toolsOn) {
 chip.textContent = narrow ? "工具开" : "模式：工具开启 · 完整回复";
 chip.title = "点一下关闭工具，改为流式回复";
 } else {
 chip.textContent = narrow ? "流式" : "模式：工具关闭 · 流式回复";
 chip.title = "点一下开启工具，可调用技能（完整回复）";
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
 // 远程/跨机访问时 fetch 更慢，querySelector 绑定时 DOM 还不存在。
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
    if (typeof L.refreshHomeHero === "function") L.refreshHomeHero();
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

  const groupBtn = t.closest("#configGroups .cfg-group[data-group]");
  if (groupBtn) {
   const g = groupBtn.dataset.group;
   if (g && typeof L.switchConfigGroup === "function") L.switchConfigGroup(g);
   else if (g) switchTab(g === "capability" ? "skills" : g === "system" ? "mcp" : "agent");
   return;
  }

  // 设定顶栏选项卡（#configTabs 内 .tab[data-tab]）
  const tabBtn = t.closest("#configTabs .tab[data-tab], #configModal .tabs .tab[data-tab]");
  if (tabBtn) {
   const name = tabBtn.dataset.tab;
   if (name) switchTab(name);
   return;
  }

  if (t.id === "btnHomeAddLlm" || t.closest("#btnHomeAddLlm")) {
   e.preventDefault();
   if (typeof L.goAddLlm === "function") L.goAddLlm();
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
 if (typeof L.initSidebarLayout === "function") L.initSidebarLayout();
 $("btnMenu")?.addEventListener("click", () => {
  setSidebarOpen(!isSidebarOpen());
 });
 $("sidebarScrim")?.addEventListener("click", () => setSidebarOpen(false));

 $("btnQuickTasks")?.addEventListener("click", () => {
  openConfig("tasks");
  closeMobileSidebar();
 });
 $("btnQuickMemory")?.addEventListener("click", () => {
  openConfig("memory");
  closeMobileSidebar();
 });
 $("btnQuickKb")?.addEventListener("click", () => {
  openConfig("kb");
  closeMobileSidebar();
 });
 $("btnQuickWorkspace")?.addEventListener("click", () => {
  openConfig("workspace");
  closeMobileSidebar();
 });
 $("modeHint")?.addEventListener("click", () => {
  if (!els.useTools) return;
  els.useTools.checked = !els.useTools.checked;
  els.useTools.dispatchEvent(new Event("change", { bubbles: true }));
 });


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
 root.style.setProperty("--vv-top", `${Math.round(vv.offsetTop || 0)}px`);
 // 键盘弹出：可视高度明显小于布局高度（短屏阈值更低）
 const full = Math.max(window.innerHeight || 0, screen?.height || 0, height);
 const threshold = full < 700 ? 80 : 120;
 const open = height < full - threshold;
 document.body.classList.toggle("kb-open", open);
 } else {
 document.body.classList.remove("kb-open");
 }
 }

 function ensureComposerVisible() {
  const composer = document.querySelector(".composer");
  if (!composer) return;
  // 主页键盘模式已用 CSS 贴底，不必 scrollIntoView（会抖）
  if (document.body.classList.contains("home-hero")) return;
  try {
   composer.scrollIntoView({ block: "end", behavior: "smooth" });
  } catch (_) {
   try {
    composer.scrollIntoView(false);
   } catch (__) {}
  }
  if (state.stickToBottom && typeof scrollMessages === "function") {
   scrollMessages(true);
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
 const diff = lastHeight - (view?.height || lastHeight);
 if (diff > 60) {
 // 键盘升起
 setTimeout(ensureComposerVisible, 40);
 setTimeout(ensureComposerVisible, 220);
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
 document.body.classList.add("input-focused");
 setTimeout(syncMobileViewport, 50);
 setTimeout(syncMobileViewport, 280);
 setTimeout(ensureComposerVisible, 300);
 });
 els.input?.addEventListener("blur", () => {
 document.body.classList.remove("input-focused");
 setTimeout(syncMobileViewport, 50);
 setTimeout(() => {
  // 失焦后若高度已恢复，清键盘态
  const vv = window.visualViewport;
  if (!vv || vv.height >= (window.innerHeight || vv.height) - 80) {
   document.body.classList.remove("kb-open");
  }
 }, 200);
 });

 // Enter 发送；Shift+Enter 换行（桌面 / 手机一致）
 // keyCode 229：中文等 IME 组字中，避免误发
 els.input?.addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  if (e.shiftKey) return; // 换行
  if (e.isComposing || e.keyCode === 229) return;
  e.preventDefault();
  send();
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
 els.input?.addEventListener("keyup", (e) => {
  if (
   e.key === "ArrowUp" ||
   e.key === "ArrowDown" ||
   e.key === "ArrowLeft" ||
   e.key === "ArrowRight" ||
   e.key === "Home" ||
   e.key === "End" ||
   e.key === "PageUp" ||
   e.key === "PageDown"
  ) {
   L.scrollInputCaretIntoView?.(els.input);
  }
 });
 els.input?.addEventListener("click", () => {
  L.scrollInputCaretIntoView?.(els.input);
 });
 // 初始同步发送按钮空/有内容态
 if (typeof L.syncSendButtonState === "function") L.syncSendButtonState();

 function bindComposerPlus() {
  const wrap = $("composerPlusWrap");
  const btn = $("btnComposerPlus");
  const menu = $("composerPlusMenu");
  if (!wrap || !btn || !menu) return;

  const setOpen = (open) => {
   menu.classList.toggle("hidden", !open);
   wrap.classList.toggle("is-open", !!open);
   btn.setAttribute("aria-expanded", open ? "true" : "false");
  };
  const isOpen = () => !menu.classList.contains("hidden");
  L.closeComposerPlusMenu = () => setOpen(false);

  btn.addEventListener("click", (e) => {
   e.preventDefault();
   e.stopPropagation();
   if (btn.disabled) return;
   const next = !isOpen();
   if (next && typeof L.closeUploadPicker === "function") L.closeUploadPicker();
   setOpen(next);
  });
  menu.addEventListener("click", (e) => {
   if (e.target.closest("#btnAttach, #btnVoice")) setOpen(false);
  });
  document.addEventListener("click", (e) => {
   if (!isOpen()) return;
   if (wrap.contains(e.target)) return;
   setOpen(false);
  });
  document.addEventListener("keydown", (e) => {
   if (e.key === "Escape" && isOpen()) setOpen(false);
  });
 }

 // 文件上传（选择 / 拖拽 / 粘贴）
 if (typeof L.bindUploadUI === "function") L.bindUploadUI();
 // 语音输入（语言跟随人设）
 if (typeof L.bindVoiceUI === "function") L.bindVoiceUI();
 bindComposerPlus();

 els.btnOpenConfig?.addEventListener("click", () => {
  closeMobileSidebar();
  openConfig();
 });

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

 function nestedEditorOpen(id) {
  const el = $(id);
  return !!(el && !el.classList.contains("hidden"));
 }

 function closeTopNestedEditor() {
  const steps = [
   ["promptEditorModal", () => L.closePromptEditor?.()],
   ["llmEditorModal", () => L.closeLlmEditor?.()],
   ["customToolEditorModal", () => L.closeCustomToolEditor?.()],
   ["mcpEditorModal", () => L.closeMcpEditor?.()],
   ["integrationEditorModal", () => L.closeIntegrationEditor?.()],
   ["webhookEditorModal", () => L.closeWebhookEditor?.()],
   ["memoryAddModal", () => L.closeMemoryAddModal?.()],
   ["wsNameDialog", () => L.closeWsNameDialog?.()],
   ["wsFileModal", () => L.closeWsFileModal?.()],
   ["kbPageModal", () => L.closeKbPageModal?.()],
   ["taskPageModal", () => L.closeTaskEditor?.()],
   ["wfRunDetailModal", () => L.closeWfRunDetailModal?.()],
   ["wfRunModal", () => L.closeWfRunModal?.()],
  ];
  for (const [id, fn] of steps) {
   if (!nestedEditorOpen(id)) continue;
   if (typeof fn === "function") fn();
   else $(id)?.classList.add("hidden");
   return true;
  }
  // 工作流编辑器有「返回选模板」的 Esc，交给它自己处理
  if (nestedEditorOpen("wfPageModal")) return "wf";
  return false;
 }

 // capture：先关叠在设定上的编辑窗，不要把整页设定一起关掉
 document.addEventListener(
  "keydown",
  (e) => {
   if (e.key !== "Escape") return;
   const which = closeTopNestedEditor();
   if (which === true) {
    e.preventDefault();
    e.stopImmediatePropagation();
   } else if (which === "wf") {
    e._evaWfEsc = true;
   }
  },
  true
 );

 document.addEventListener("keydown", (e) => {
 if (e.key !== "Escape") return;
 if (e._evaWfEsc) return;
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
   if (typeof L.refreshHomeHero === "function") L.refreshHomeHero();
  } catch (_) {}
 })();
 // 恢复上次会话；没有或已删除则空白新对话
 (async () => {
  let last = "";
  try {
   last = localStorage.getItem("session_id") || "";
  } catch (_) {}
  try {
   if (last && typeof openSession === "function") {
    await openSession(last);
   } else if (typeof newChat === "function") {
    newChat();
   } else {
    showEmpty();
   }
  } catch (_) {
   try {
    localStorage.removeItem("session_id");
   } catch (__) {}
   if (typeof newChat === "function") {
    try { newChat(); } catch (__) { showEmpty(); }
   } else {
    showEmpty();
   }
  }
  loadSessions().catch(() => {});
 })();
})(window.Lily);
