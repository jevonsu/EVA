window.Lily = (() => {
 "use strict";

/**
 * Lily — 桜のAI助手 (优化版 v2.3)
 * 玻璃拟态基线 + Markdown / 流式 / 任务API / 体验补丁
 */

 const $ = (id) => document.getElementById(id);

 /** IconPark API (official icons) */
 function iconApi() {
 return window.IconParkUI || (window.L && window.L.icons) || null;
 }

 function ipk(name, cls) {
 const api = iconApi();
 if (!api || typeof api.iconHtml !== "function") return "";
 try {
 return api.iconHtml(name, cls || "ipk-xs") || "";
 } catch (_) {
 return "";
 }
 }

 /** Icon + escaped text (safe HTML) */
 function ipkLabel(name, text, cls) {
 const i = ipk(name, cls || "ipk-xs");
 const t = escapeHtml(text == null ? "" : String(text));
 return (i ? i + " " : "") + t;
 }

 /** Hydrate [data-ipk] placeholders with IconPark official SVGs */
 function hydrateIconPark(root) {
 const scope = root || document;
 const api = iconApi();
 if (!api || typeof api.iconHtml !== "function") return;
 scope.querySelectorAll("[data-ipk]").forEach((el) => {
 const name = el.getAttribute("data-ipk");
 if (!name) return;
 const cls = el.getAttribute("data-ipk-class") || "ipk-sm";
 const svg = api.iconHtml(name, cls);
 if (svg) el.innerHTML = svg;
 });
 }

 const els = {
 agentName: $("agentName"),
 agentMeta: $("agentMeta"),
 sessionList: $("sessionList"),
 sessionSearch: $("sessionSearch"),
 messages: $("messages"),
 input: $("input"),
 status: $("status"),
 chatTitle: $("chatTitle"),
 sessionHint: $("sessionHint"),
 btnSend: $("btnSend"),
 btnNewChat: $("btnNewChat"),
 useTools: $("useTools"),
 useMemory: $("useMemory"),
 btnOpenConfig: $("btnOpenConfig"),
 btnCloseConfig: $("btnCloseConfig"),
 configModal: $("configModal"),
 };

 // 打开站点默认空白对话：不从 localStorage 恢复上次会话进主界面
 // （用户可从侧栏手动点开历史；私密模式无 localStorage 也不应抛错）
 const state = {
 sessionId: null,
 busy: false,
 config: null,
 sessionsCache: [],
 stickToBottom: true,
 /** 仅用于「当前页面的 SSE 监听」—— abort 不会停掉服务端生成 */
 abortController: null,
 /** true：切换会话/关页时主动断开监听，不算用户取消 */
 detachWatch: false,
 /** 当前正在看的后台 run_id */
 activeRunId: null,
 /**
  * 各会话后台生成状态（服务端继续跑）
  * { [sessionId]: { runId, message, status } }
  */
 chatRuns: {},
 /** 阶段计时器 handle */
 phaseTimer: null,
 /** 待发送附件（workspace 相对路径） */
 attachments: [],
 };

 // 恢复本地记录的进行中 run（刷新后可再附着）
 try {
 const raw = sessionStorage.getItem("chat_runs");
 if (raw) {
 const obj = JSON.parse(raw);
 if (obj && typeof obj === "object") state.chatRuns = obj;
 }
 } catch (_) {}

 // 工具 / 记忆：界面不再展示开关，固定默认开启（完整能力）
 if (els.useTools) els.useTools.checked = true;
 if (els.useMemory) els.useMemory.checked = true;
 try {
 localStorage.setItem("lily_use_tools", "1");
 localStorage.setItem("lily_use_memory", "1");
 } catch (_) {}

 // ==================== 工具函数 ====================
 function showToast(message, type = "info", duration = 3000) {
 const container = document.getElementById("toastContainer");
 if (!container) return;
 const toast = document.createElement("div");
 toast.className = `toast ${type}`;
 const span = document.createElement("span");
 span.textContent = message || "";
 const close = document.createElement("button");
 close.type = "button";
 close.className = "toast-close";
 close.setAttribute("aria-label", "关闭");
 close.textContent = "×";
 close.addEventListener("click", () => toast.remove());
 toast.appendChild(span);
 toast.appendChild(close);
 container.appendChild(toast);
 setTimeout(() => {
 if (toast.isConnected) toast.remove();
 }, duration);
 }

 function debounce(fn, delay = 300) {
 let timer = null;
 return (...args) => {
 clearTimeout(timer);
 timer = setTimeout(() => fn(...args), delay);
 };
 }

 function timeAgo(iso) {
 if (!iso) return "";
 try {
 const diff = Date.now() - new Date(iso).getTime();
 if (diff < 60000) return "刚刚";
 if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`;
 if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`;
 return new Date(iso).toLocaleDateString();
 } catch {
 return "";
 }
 }

 function renderSkeleton(container, count = 3) {
 const template = document.getElementById("skeletonTask");
 if (!template) return;
 for (let i = 0; i < count; i++) {
 const clone = template.content.cloneNode(true);
 container.appendChild(clone);
 }
 }

 function escapeHtml(s) {
 return String(s)
 .replaceAll("&", "&amp;")
 .replaceAll("<", "&lt;")
 .replaceAll(">", "&gt;")
 .replaceAll('"', "&quot;");
 }

 function stripThinking(text) {
 if (text == null) return "";
 let t = String(text);
 // 标签式思考块
 t = t.replace(/<think\b[^>]*>[\s\S]*?<\/think>/gi, "");
 t = t.replace(/<thinking\b[^>]*>[\s\S]*?<\/thinking>/gi, "");
 t = t.replace(/<reasoning\b[^>]*>[\s\S]*?<\/reasoning>/gi, "");
 t = t.replace(/```(?:thinking|reasoning|thought)[\s\S]*?```/gi, "");
 // 未闭合 think 块（流式中途）
 t = t.replace(/<think\b[^>]*>[\s\S]*$/gi, "");
 t = t.replace(/<thinking\b[^>]*>[\s\S]*$/gi, "");
 // 常见「思考过程」段落标题（不展示完整推理）
 t = t.replace(
 /(?:^|\n)\s*(?:思考过程|思考|推理|Reasoning|Thinking)\s*[:：][\s\S]*?(?=\n\s*(?:#{1,3}\s||最终|答[案复]|回复)|$)/gi,
 "\n"
 );
 return t.replace(/\n{3,}/g, "\n\n").trim();
 }

 /** 把工具记录规范成 { name, arguments?, result? }[] */
 function normalizeToolCalls(list) {
 if (!Array.isArray(list) || !list.length) return [];
 return list
 .map((t) => {
 if (!t) return null;
 if (typeof t === "string") {
 const name = t.replace(/\(\)\s*$/, "").trim();
 return name ? { name } : null;
 }
 const name =
 t.name ||
 t.tool ||
 t.function?.name ||
 (typeof t.function === "string" ? t.function : "") ||
 "";
 if (!name) return null;
 let args = t.arguments ?? t.args ?? t.function?.arguments;
 if (typeof args === "string") {
 try {
 args = JSON.parse(args);
 } catch {
 args = { raw: args };
 }
 }
 return {
 name: String(name),
 arguments: args && typeof args === "object" ? args : {},
 result: t.result ?? t.output ?? null,
 media_paths: Array.isArray(t.media_paths) ? t.media_paths : [],
 };
 })
 .filter(Boolean);
 }

 /**
 * 从消息 / API 提取工具调用：
 * - tool_calls 数组（API 即时回复）
 * - metadata.tool_calls
 * - metadata.tools_used: "a(); b(); a()"（历史会话）
 */
 function extractToolCalls(m) {
 if (!m) return [];
 if (Array.isArray(m.tool_calls) && m.tool_calls.length) {
 return normalizeToolCalls(m.tool_calls);
 }
 if (Array.isArray(m.tools) && m.tools.length) {
 return normalizeToolCalls(m.tools);
 }
 const meta = m.metadata || {};
 if (Array.isArray(meta.tool_calls) && meta.tool_calls.length) {
 return normalizeToolCalls(meta.tool_calls);
 }
 if (typeof meta.tools_used === "string" && meta.tools_used.trim()) {
 // "daphile(); list_workspace(); daphile()"
 const names = meta.tools_used
 .split(/[;；]/)
 .map((s) => s.trim().replace(/\(\)\s*$/, "").trim())
 .filter(Boolean);
 return normalizeToolCalls(names);
 }
 return [];
 }

 /** 调用名 → 中文展示名（可由 /api/config/tools 刷新） */
 const TOOL_DISPLAY_NAMES = {
 analyze_image_auto: "产品识图",
 grok_media: "生图 / 视频",
 memory: "长期记忆",
 product_multi_platform_publisher: "多平台文案",
 workspace: "本地工作区",
 http: "网络请求",
 office: "办公文档",
 scheduled_task: "定时任务",
 reminders: "提醒",
 search_ai_news: "AI / 科技资讯",
 nas: "NAS / 共享盘",
 nocodb: "NocoDB 数据库",
 qb_manager: "qBittorrent 下载",
 get_current_time: "当前时间",
 calculator: "计算器",
 system_info: "系统信息",
 create_tool: "创建工具",
 read_skill: "查看 Skill 源码",
 delete_tool: "删除工具",
 kb: "知识库 Wiki",
 workflow: "工作流",
 memory: "长期记忆",
 reload_runtime: "热重载运行时",
 run_py: "运行 Python / 装包",
 list_api_models: "列出 API 模型",
 server_health_check: "服务器健康检查",
 };

 function setToolDisplayLabels(catalog) {
 if (!Array.isArray(catalog)) return;
 for (const t of catalog) {
 const n = t && t.name;
 if (!n) continue;
 const label = t.display_name || t.label;
 if (label) TOOL_DISPLAY_NAMES[n] = label;
 }
 }

 function toolDisplayName(name) {
 const n = name == null ? "" : String(name);
 if (!n) return "?";
 if (TOOL_DISPLAY_NAMES[n]) return TOOL_DISPLAY_NAMES[n];
 return n.replace(/_/g, " ");
 }

 /** 工具名一行摘要（去重保序，重复次数标 xN）— 展示中文名 */
 function summarizeToolNames(toolCalls) {
 const order = [];
 const count = new Map();
 for (const t of toolCalls) {
 const n = t.name || "?";
 if (!count.has(n)) {
 order.push(n);
 count.set(n, 1);
 } else {
 count.set(n, count.get(n) + 1);
 }
 }
 return order.map((n) => {
 const c = count.get(n);
 const label = toolDisplayName(n);
 return c > 1 ? `${label}×${c}` : label;
 });
 }

 const MEDIA_PATH_RE =
 /(?:workspace[\\/])?([\w./\\-]+\.(?:png|jpe?g|gif|webp|bmp|svg|mp4|webm|mov|m4v))/gi;

 const LIST_LIKE_TOOLS = new Set([
 "workspace",
 "find_web_project",
 ]);
 const INPUT_ONLY_TOOLS = new Set([
 "analyze_image_auto",
 ]);

 function normalizeMediaPath(p) {
 if (!p || typeof p !== "string") return "";
 let s = p.trim().replace(/\\/g, "/");
 while (s.includes("//")) s = s.replace(/\/\//g, "/");
 while (s.startsWith("./")) s = s.slice(2);
 if (s.toLowerCase().startsWith("workspace/")) s = s.slice("workspace/".length);
 s = s.replace(/^\/+/, "");
 return s;
 }

 function isUploadPath(p) {
 const s = normalizeMediaPath(p).toLowerCase();
 return s.startsWith("uploads/") || s.includes("/uploads/");
 }

 /** 从工具结果 / metadata 提取本地媒体路径（排除 uploads 用户上传） */
 function extractMediaPaths(toolCalls, extra) {
 const out = [];
 const add = (p) => {
 if (!p || typeof p !== "string") return;
 let s = normalizeMediaPath(p);
 if (!s || s.includes("..")) return;
 if (!/\.(png|jpe?g|gif|webp|bmp|svg|mp4|webm|mov|m4v)$/i.test(s)) return;
 // 用户上传只在用户气泡展示，不进助手「生成的文件」
 if (isUploadPath(s)) return;
 if (!out.includes(s)) out.push(s);
 };

 if (Array.isArray(extra?.media_paths)) {
 extra.media_paths.forEach(add);
 }
 if (Array.isArray(extra?.metadata?.media_paths)) {
 extra.metadata.media_paths.forEach(add);
 }

 const list = normalizeToolCalls(toolCalls);
 for (const t of list) {
 const tName = t.name || "";
 // 列表/分析工具：不把输入图或目录枚举当生成媒体
 if (LIST_LIKE_TOOLS.has(tName) || INPUT_ONLY_TOOLS.has(tName)) continue;

 if (Array.isArray(t.media_paths)) t.media_paths.forEach(add);
 if (Array.isArray(t.arguments?.saved_paths)) t.arguments.saved_paths.forEach(add);
 const raw = t.result != null ? String(t.result) : "";
 if (!raw) continue;
 try {
 const j = JSON.parse(raw);
 if (j && typeof j === "object") {
 // 仅结构化输出字段；不扫 files/paths 列表
 ["saved_paths", "media_paths", "output_paths"].forEach((k) => {
 if (Array.isArray(j[k])) j[k].forEach(add);
 else if (typeof j[k] === "string") add(j[k]);
 });
 ["path", "file", "output_path", "saved_path", "video_path"].forEach((k) => {
 if (typeof j[k] === "string") add(j[k]);
 });
 if (typeof j.preview_markdown === "string") {
 const md = j.preview_markdown.matchAll(/!\[[^\]]*\]\(([^)\s]+)\)/g);
 for (const m of md) add(m[1]);
 }
 }
 } catch (_) {
 /* not json */
 }
 }
 return out;
 }

 /**
 * 工具调用条 + 可选媒体画廊（从工具结果自动出图，不依赖模型是否写 markdown）
 */
 function renderToolsBar(toolCalls) {
 const list = normalizeToolCalls(toolCalls);
 if (!list.length) return null;

 const names = summarizeToolNames(list);
 const wrap = document.createElement("details");
 wrap.className = "tools tools-compact";

 const summary = document.createElement("summary");
 summary.className = "tools-summary";
 summary.innerHTML = `<span class="tools-count icon-inline">${ipk("tool", "ipk-xs")} 调用了 ${list.length} 个工具</span>`;

 const chips = document.createElement("span");
 chips.className = "tools-chips";
 for (const label of names) {
 const chip = document.createElement("span");
 chip.className = "tool-chip";
 chip.textContent = label;
 chips.appendChild(chip);
 }
 summary.appendChild(chips);
 wrap.appendChild(summary);

 const detail = document.createElement("div");
 detail.className = "tools-detail";
 for (const t of list) {
 const row = document.createElement("div");
 row.className = "tool-row";

 const title = document.createElement("div");
 title.className = "tool-row-name";
 const callName = t.name || "";
 const nice = toolDisplayName(callName);
 const nameHtml =
 nice && nice !== callName
 ? `${escapeHtml(nice)} <span class="muted-line" style="font-weight:400;opacity:.75">(${escapeHtml(
 callName
 )})</span>`
 : escapeHtml(callName);
 title.innerHTML = `${ipk("tool", "ipk-xs")} ${nameHtml}`;
 row.appendChild(title);

 const args = t.arguments && typeof t.arguments === "object" ? t.arguments : {};
 const keys = Object.keys(args);
 if (keys.length) {
 const argLine = document.createElement("div");
 argLine.className = "tool-row-args";
 const parts = keys.slice(0, 6).map((k) => {
 let v = args[k];
 if (v == null) return `${k}=—`;
 if (typeof v === "object") v = JSON.stringify(v);
 v = String(v).replace(/\s+/g, " ").trim();
 if (v.length > 48) v = v.slice(0, 48) + "…";
 return `${k}=${v}`;
 });
 if (keys.length > 6) parts.push(`…+${keys.length - 6}`);
 argLine.textContent = parts.join(" · ");
 row.appendChild(argLine);
 }

 if (t.result != null && String(t.result).trim()) {
 let r = stripThinking(String(t.result));
 r = r.replace(/\s+/g, " ").trim();
 if (r.length > 120) r = r.slice(0, 120) + "…";
 if (r) {
 const resLine = document.createElement("div");
 resLine.className = "tool-row-result";
 resLine.textContent = `→ ${r}`;
 row.appendChild(resLine);
 }
 }

 detail.appendChild(row);
 }
 wrap.appendChild(detail);
 return wrap;
 }


 // Utility: set message in a form feedback element
 // type: ok | error | warn | "" ; when icon provided, renders IconPark + text as HTML
 function setMsg(id, text, type = "", iconName = "") {
 const el = document.getElementById(id);
 if (!el) return;
 const map = { ok: "check-one", error: "close-one", warn: "attention", "": "" };
 const icon = iconName || map[type] || "";
 if (icon) {
 el.innerHTML = ipkLabel(icon, text, "ipk-xs");
 } else {
 el.textContent = text;
 }
 if (type) {
 el.className = "form-msg " + type;
 } else {
 el.className = "form-msg";
 }
 }

 return {
 $, els, state,
 showToast, debounce, timeAgo, renderSkeleton,
 escapeHtml, stripThinking, normalizeToolCalls,
 extractToolCalls, summarizeToolNames, extractMediaPaths,
 setToolDisplayLabels, toolDisplayName,
 setMsg, renderToolsBar, hydrateIconPark, ipk, ipkLabel,
 };
})();

// Fallback: async load if sync XHR didn"t work
(function() {
 function afterModal(html, c) {
 if (c) c.innerHTML = html;
 if (window.Lily && typeof window.Lily.hydrateIconPark === "function") {
 window.Lily.hydrateIconPark(document.getElementById("configModalContainer") || document);
 }
 // 配置 HTML 注入后再绑任务/集成等表单（避免按钮尚不存在）
 if (window.Lily && typeof window.Lily.bindTaskFormUi === "function") {
 try { window.Lily.bindTaskFormUi(); } catch (_) {}
 }
 if (window.Lily && typeof window.Lily.bindIntegrationUi === "function") {
 try { window.Lily.bindIntegrationUi(); } catch (_) {}
 }
 if (window.Lily && typeof window.Lily.bindConfigDelegatedUi === "function") {
 try { window.Lily.bindConfigDelegatedUi(); } catch (_) {}
 }
 }
 if (!document.getElementById('configModal')) {
 fetch('/static/html/config-modal.html')
 .then(function(r) { return r.text(); })
 .then(function(html) {
 var c = document.getElementById('configModalContainer');
 afterModal(html, c);
 })
 .catch(function(e) { console.warn('Config modal fallback failed:', e); });
 }
})();
