/**
 * EVA - 对话体验 P1：连续头像合并 / 未读计数 / 扮演徽标 / 头像热加载 / 人设头像上传
 */
((L) => {
 "use strict";
 const { $, els, state } = L;
 const AVATAR_MAX_BYTES = 200 * 1024;

 function msgsEl() { return els.messages || document.getElementById("messages"); }
 function nearBottom(el, th = 100) {
  if (!el) return true;
  return el.scrollHeight - el.scrollTop - el.clientHeight < th;
 }
 function roleOf(node) {
  if (!node || !node.classList || !node.classList.contains("msg")) return "";
  if (node.classList.contains("assistant")) return "assistant";
  if (node.classList.contains("user")) return "user";
  return "other";
 }

 // ---------- 1. 连续同角色只留第一条头像 ----------
 function regroupAvatars() {
  const root = msgsEl();
  if (!root) return;
  let prev = "";
  for (const node of root.children) {
   const r = roleOf(node);
   if (!r) { prev = ""; continue; }  // 非消息节点（分隔/日期等）打断分组
   const cont = (r === "assistant" || r === "user") && r === prev;
   node.classList.toggle("msg-cont", cont);
   prev = r === "other" ? "" : r;
  }
 }

 // ---------- 3. 未读计数 ----------
 state.readingHistory = false;
 let unread = 0;
 function renderUnread() {
  const btn = document.getElementById("btnScrollBottom");
  if (!btn) return;
  let badge = btn.querySelector(".scroll-unread");
  if (!badge) {
   badge = document.createElement("span");
   badge.className = "scroll-unread";
   btn.appendChild(badge);
  }
  badge.textContent = unread > 99 ? "99+" : String(unread);
  badge.hidden = unread <= 0;
  btn.classList.toggle("has-unread", unread > 0);
  btn.title = unread > 0 ? `${unread} 条新消息 · 回到底部` : "回到底部";
  if (unread > 0) btn.classList.remove("hidden");
 }
 function clearUnread() { unread = 0; renderUnread(); }
 function jumpBottom() {
  const root = msgsEl();
  state.readingHistory = false;
  state.stickToBottom = true;
  clearUnread();
  if (root) root.scrollTop = root.scrollHeight;
 }
 L.chatUxJumpBottom = jumpBottom;

 // ---------- 2. 头像热加载 ----------
 function agentAvatarUrl() {
  const a = state.config?.agent || {};
  return String(a.avatar || a.avatar_url || "").trim();
 }
 function agentLetter() {
  const n = String(state.config?.agent?.name || "").trim() || "E";
  const ch = Array.from(n)[0] || "E";
  return /[a-z]/i.test(ch) ? ch.toUpperCase() : ch;
 }
 function paintAssistantAvatars() {
  const root = msgsEl();
  if (!root) return;
  const url = agentAvatarUrl();
  const letter = agentLetter();
  root.querySelectorAll(".msg.assistant > .msg-main > .msg-avatar").forEach((av) => {
   const img = av.querySelector("img");
   if (url) {
    if (img && img.getAttribute("src") === url) return;
    av.textContent = "";
    const im = document.createElement("img");
    im.src = url; im.alt = ""; im.loading = "lazy";
    im.onerror = () => { im.remove(); av.textContent = letter; };
    av.appendChild(im);
   } else if (img || av.textContent !== letter) {
    av.textContent = letter;
   }
  });
 }

 // 左上角侧栏/顶栏头像同步 agent.avatar，无则回退默认 logo
 const DEFAULT_LOGO = "/static/logo.png";
 function paintLogoAvatars() {
  const url = agentAvatarUrl() || DEFAULT_LOGO;
  document.querySelectorAll("#btnLogoMenu img, #btnMenu img").forEach((im) => {
   if (im.getAttribute("src") === url) return;
   im.onerror = () => { im.onerror = null; im.src = DEFAULT_LOGO; };
   im.src = url;
  });
 }
 L.refreshLogoAvatar = function () { lastSig = null; checkConfig(); };

 // ---------- 5. 扮演徽标 ----------
 function ensureRpBadge() {
  let b = document.getElementById("roleplayBadge");
  if (b) return b;
  const composer = document.getElementById("composer");
  const shell = composer?.querySelector(".composer-shell");
  if (!composer) return null;
  b = document.createElement("div");
  b.id = "roleplayBadge";
  b.className = "roleplay-badge";
  b.hidden = true;
  b.setAttribute("role", "status");
  if (shell) shell.parentNode.insertBefore(b, shell); else composer.prepend(b);
  return b;
 }
 function isOn(v) { return v === true || v === 1 || v === "1" || v === "true"; }
 function renderRpBadge() {
  const b = ensureRpBadge();
  if (!b) return;
  const a = state.config?.agent || {};
  const on = isOn(a.roleplay_enabled);
  b.hidden = true; // 文字徽标已停用，改为头像角标
  document.body.classList.toggle("roleplay-on", on);
  if (on) {
   const name = String(a.name || "").trim() || "角色";
   b.textContent = "";
   const dot = document.createElement("span"); dot.className = "rp-dot";
   const t = document.createElement("span"); t.textContent = `扮演中 · ${name}`;
   b.append(dot, t);
   b.title = "已开启角色扮演（设定→人设可关闭）";
  }
 }

 function paintRpAvatarTitles() {
  const on = isOn(state.config?.agent?.roleplay_enabled);
  document.querySelectorAll(".msg.assistant > .msg-main > .msg-avatar").forEach((av) => {
   if (on) av.title = "扮演中"; else if (av.title === "扮演中") av.removeAttribute("title");
  });
 }
 // 配置热加载：轮询 state.config 的相关字段变化（轻量）
 let lastSig = null;
 function checkConfig() {
  const a = state.config?.agent || {};
  const sig = [a.name, isOn(a.roleplay_enabled), agentAvatarUrl().length, agentAvatarUrl().slice(-32)].join("|");
  if (sig === lastSig) return;
  lastSig = sig;
  renderRpBadge();
  paintLogoAvatars();
  paintAssistantAvatars();
  paintRpAvatarTitles();
 }

 // ---------- 4. 输入区高度变化时保持底部不被遮挡 ----------
 function watchComposer() {
  const composer = document.getElementById("composer");
  if (!composer || typeof ResizeObserver !== "function") return;
  const ro = new ResizeObserver(() => {
   const h = composer.getBoundingClientRect().height;
   document.documentElement.style.setProperty("--composer-h", Math.round(h) + "px");
   const root = msgsEl();
   if (root && !state.readingHistory && state.stickToBottom !== false) root.scrollTop = root.scrollHeight;
  });
  ro.observe(composer);
 }

 // ---------- 2. 人设头像上传（config-modal 异步注入，用委托） ----------
 function setAvatarPreview(url) {
  const pv = document.getElementById("cfgAvatarPreview");
  const clr = document.getElementById("btnAvatarClear");
  if (!pv) return;
  pv.textContent = "";
  if (url) {
   const im = document.createElement("img"); im.src = url; im.alt = "助手头像"; pv.appendChild(im);
  } else {
   pv.textContent = agentLetterFromForm();
  }
  if (clr) clr.hidden = !url;
 }
 function agentLetterFromForm() {
  const n = (document.getElementById("cfgAgentName")?.value || state.config?.agent?.name || "E").trim() || "E";
  const ch = Array.from(n)[0] || "E";
  return /[a-z]/i.test(ch) ? ch.toUpperCase() : ch;
 }
 L.syncAvatarField = function (agent) {
  const inp = document.getElementById("cfgAgentAvatar");
  if (!inp) return;
  inp.value = String(agent?.avatar || "");
  setAvatarPreview(inp.value);
 };
 function dataUrlBytes(u) { const i = u.indexOf(","); return Math.floor((u.length - i - 1) * 3 / 4); }
 function compressImage(file) {
  return new Promise((resolve, reject) => {
   if (file.size > 30 * 1024 * 1024) return reject(new Error("图片超过 30MB"));
   const fr = new FileReader();
   fr.onerror = () => reject(new Error("读取文件失败"));
   fr.onload = () => {
    const img = new Image();
    img.onerror = () => reject(new Error("浏览器无法解码该图片（建议 PNG/JPG/WebP）"));
    img.onload = () => {
     const S = 256;
     const side = Math.min(img.naturalWidth, img.naturalHeight);
     const sx = (img.naturalWidth - side) / 2, sy = (img.naturalHeight - side) / 2;
     const cv = document.createElement("canvas"); cv.width = S; cv.height = S;
     const ctx = cv.getContext("2d");
     ctx.drawImage(img, sx, sy, side, side, 0, 0, S, S);
     let out = "";
     for (const [type, q] of [["image/webp", 0.85], ["image/jpeg", 0.85], ["image/jpeg", 0.7], ["image/jpeg", 0.5]]) {
      out = cv.toDataURL(type, q);
      if (!out.startsWith("data:" + type)) continue;
      if (dataUrlBytes(out) <= AVATAR_MAX_BYTES) return resolve(out);
     }
     reject(new Error("压缩后仍超过 200KB"));
    };
    img.src = fr.result;
   };
   fr.readAsDataURL(file);
  });
 }
 document.addEventListener("click", (e) => {
  const t = e.target;
  if (!(t instanceof Element)) return;
  if (t.closest("#btnAvatarPick") || t.closest("#cfgAvatarPreview")) {
   document.getElementById("cfgAvatarFile")?.click();
  } else if (t.closest("#btnAvatarClear")) {
   const inp = document.getElementById("cfgAgentAvatar");
   if (inp) inp.value = "";
   setAvatarPreview("");
   L.showToast?.("头像已清除，保存人设后生效", "info");
  }
 });
 async function handleAvatarFile(file) {
  if (!file) return;
  if (file.type && !/^image\//.test(file.type)) { L.showToast?.("请选择图片文件", "error"); return; }
  try {
   const url = await compressImage(file);
   const inp = document.getElementById("cfgAgentAvatar");
   if (inp) inp.value = url;
   setAvatarPreview(url);
   L.showToast?.("头像已就绪，保存人设后生效", "success");
  } catch (err) {
   L.showToast?.("头像处理失败：" + (err?.message || err), "error");
  }
 }
 document.addEventListener("change", (e) => {
  const t = e.target;
  if (!(t instanceof HTMLInputElement) || t.id !== "cfgAvatarFile") return;
  const file = t.files && t.files[0];
  t.value = "";
  handleAvatarFile(file);
 });
 // 人设页打开时支持直接 Ctrl+V 粘贴截图作为头像
 document.addEventListener("paste", (e) => {
  const pv = document.getElementById("cfgAvatarPreview");
  if (!pv || !pv.offsetParent) return;
  const tg = e.target;
  if (tg instanceof Element && tg.closest("input:not([type=hidden]),textarea,[contenteditable=true]") && !tg.closest(".agent-avatar-row")) return;
  const it = Array.from(e.clipboardData?.items || []).find((x) => x.kind === "file" && /^image\//.test(x.type));
  if (!it) return;
  e.preventDefault();
  handleAvatarFile(it.getAsFile());
 });
 document.addEventListener("input", (e) => {
  if (e.target?.id === "cfgAgentName" && !document.getElementById("cfgAgentAvatar")?.value) setAvatarPreview("");
 });

 // ---------- 观察消息区 ----------
 function boot() {
  const root = msgsEl();
  if (!root) return;
  let lastCount = root.children.length;
  const mo = new MutationObserver((muts) => {
   let newAssistant = 0, userSent = false;
   for (const m of muts) {
    for (const n of m.addedNodes) {
     const r = roleOf(n);
     if (r === "assistant" && !n.classList.contains("typing-msg")) newAssistant++;
     if (r === "user") userSent = true;
    }
   }
   const cnt = root.children.length;
   if (cnt < lastCount && cnt <= 1) { state.readingHistory = false; clearUnread(); } // 切换会话/清空
   lastCount = cnt;
   regroupAvatars();
   if (newAssistant) { paintAssistantAvatars(); paintRpAvatarTitles(); }
   if (userSent) { jumpBottom(); return; }
   if (newAssistant && state.readingHistory) { unread += newAssistant; renderUnread(); }
  });
  mo.observe(root, { childList: true });
  root.addEventListener("scroll", () => {
   const nb = nearBottom(root, 100);
   state.readingHistory = !nb;
   if (nb && unread) clearUnread();
  }, { passive: true });
  // 捕获阶段接管回到底部，确保清零
  document.getElementById("btnScrollBottom")?.addEventListener("click", jumpBottom, true);
  regroupAvatars();
  renderUnread();
  watchComposer();
  checkConfig();
  setInterval(checkConfig, 1200);
 }
 if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
 else boot();
})(window.Lily);
