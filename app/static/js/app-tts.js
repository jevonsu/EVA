/**
 * Lily - Text-to-Speech（分语言朗读）
 * 普通话 zh-CN / 粤语 zh-HK / English en-US
 * 自动：按文段脚本切分，多语言依次朗读
 */
((L) => {
 "use strict";

 const { $, showToast } = L;

 const YUE_MARKERS =
 /[嘅咗喺唔係嚟咁嘢哋攞睇傾計搞掂冇係咪嚿喎噃喇嘞啱啲]/;

 const LANG_LABEL = {
 "zh-CN": "普通话",
 "zh-HK": "粤语",
 "en-US": "English",
 auto: "自动分语言",
 };

 let voicesReady = false;
 let speaking = false;
 let queue = [];
 let currentUtter = null;
 /** @type {HTMLElement|null} */
 let activeBtn = null;

 function isSupported() {
 return typeof window !== "undefined" && "speechSynthesis" in window;
 }

 function ensureVoices() {
 if (!isSupported()) return [];
 const list = speechSynthesis.getVoices() || [];
 if (list.length) voicesReady = true;
 return list;
 }

 if (isSupported()) {
 speechSynthesis.addEventListener("voiceschanged", () => {
 ensureVoices();
 voicesReady = true;
 });
 // 预热
 setTimeout(() => ensureVoices(), 200);
 }

 function detectLang(text) {
 if (typeof L.detectLangFromText === "function") {
 const d = L.detectLangFromText(text);
 if (d) return d === "yue-Hant-HK" ? "zh-HK" : d;
 }
 const t = (text || "").trim();
 if (!t) return "zh-CN";
 const cjk = (t.match(/[\u4e00-\u9fff]/g) || []).length;
 const latin = (t.match(/[A-Za-z]/g) || []).length;
 if (latin >= 4 && latin >= cjk * 1.2) return "en-US";
 if (cjk >= 2) {
 if (YUE_MARKERS.test(t)) return "zh-HK";
 return "zh-CN";
 }
 if (latin >= 3) return "en-US";
 return "zh-CN";
 }

 /** 去掉 Markdown / 路径噪音，便于朗读 */
 function stripForSpeech(raw) {
 let t = String(raw || "");
 t = t.replace(/```[\s\S]*?```/g, " ");
 t = t.replace(/`([^`]+)`/g, "$1");
 t = t.replace(/!\[[^\]]*\]\([^)]+\)/g, " ");
 t = t.replace(/\[[^\]]*\]\((https?:\/\/[^)]+)\)/g, " $1 ");
 t = t.replace(/https?:\/\/\S+/g, " ");
 t = t.replace(/^#{1,6}\s+/gm, "");
 t = t.replace(/^\s*[-*+]\s+/gm, "");
 t = t.replace(/^\s*\d+[.)]\s+/gm, "");
 t = t.replace(/[*_~]{1,3}/g, "");
 t = t.replace(/\|/g, " ");
 t = t.replace(/[ \t]+\n/g, "\n");
 t = t.replace(/\n{3,}/g, "\n\n");
 t = t.replace(/[ \t]{2,}/g, " ");
 return t.trim();
 }

 /**
 * 按「文种」切段，便于中英粤分别用对应引擎
 * 例："你好 Hello 世界" → [中文, English, 中文]
 */
 function segmentByScript(text) {
 const src = stripForSpeech(text);
 if (!src) return [];

 const parts = [];
 let buf = "";
 let kind = null; // "cjk" | "latin" | "other"

 const charKind = (ch) => {
 if (/[\u4e00-\u9fff]/.test(ch)) return "cjk";
 if (/[A-Za-z]/.test(ch)) return "latin";
 return "other";
 };

 const flush = () => {
 const s = buf.trim();
 if (s) parts.push(s);
 buf = "";
 };

 for (const ch of src) {
 const k = charKind(ch);
 if (k === "other") {
 buf += ch;
 continue;
 }
 if (kind == null) kind = k;
 if (k !== kind && buf.trim()) {
 // 切换文种：其他标点归前段
 flush();
 kind = k;
 buf = ch;
 } else {
 if (kind == null) kind = k;
 // 若 other 后接新文种
 if (k !== kind && !buf.trim()) kind = k;
 else if (k !== kind) {
 flush();
 kind = k;
 buf = ch;
 continue;
 }
 buf += ch;
 }
 }
 flush();

 // 合并过短片段到前一段（避免「OK」单独一段过于碎）
 const merged = [];
 for (const p of parts) {
 if (
 merged.length &&
 p.length <= 2 &&
 detectLang(p) === "en-US" &&
 detectLang(merged[merged.length - 1]) !== "en-US"
 ) {
 // 很短英文保留独立（专业名词）
 merged.push(p);
 } else if (merged.length && p.length === 1) {
 merged[merged.length - 1] += p;
 } else {
 merged.push(p);
 }
 }

 return merged
 .map((t) => ({ text: t.trim(), lang: detectLang(t) }))
 .filter((x) => x.text);
 }

 function pickVoice(lang) {
 const voices = ensureVoices();
 if (!voices.length) return null;

 const score = (v) => {
 const name = `${v.name} ${v.lang}`.toLowerCase();
 const vlang = (v.lang || "").toLowerCase();
 let s = 0;
 if (lang === "zh-CN") {
 if (/zh(-|_)?cn|cmn-hans|zh-hans/.test(vlang)) s += 50;
 if (/chinese/.test(name) && /china|simplified|mandarin|普通话/.test(name))
 s += 30;
 if (/xiaoxiao|xiaoyi|huihui|yaoyao|kangkang|cloud/.test(name)) s += 20;
 if (/zh(-|_)?tw|zh(-|_)?hk|yue|cantonese/.test(vlang)) s -= 20;
 } else if (lang === "zh-HK") {
 if (/zh(-|_)?hk|yue|zh(-|_)?yue/.test(vlang)) s += 55;
 if (/cantonese|粵|粤|hong\s*kong|hk/.test(name)) s += 35;
 if (/zh(-|_)?cn/.test(vlang) && !/hk|yue/.test(vlang)) s -= 10;
 } else if (lang === "en-US") {
 if (/^en(-|_)?us/.test(vlang)) s += 50;
 if (/^en(-|_)?gb/.test(vlang)) s += 35;
 if (/^en\b/.test(vlang)) s += 25;
 if (/zira|aria|guy|jenny|sara|david|mark|google us english/.test(name))
 s += 15;
 }
 if (v.default) s += 3;
 if (v.localService) s += 2;
 return s;
 };

 let best = null;
 let bestScore = -1;
 for (const v of voices) {
 const sc = score(v);
 if (sc > bestScore) {
 bestScore = sc;
 best = v;
 }
 }
 // 若粤语找不到专用声，退回中文
 if (lang === "zh-HK" && bestScore < 20) {
 return pickVoice("zh-CN");
 }
 return bestScore > 0 ? best : voices[0] || null;
 }

 function setSpeakingUI(on, btn) {
 speaking = !!on;
 document.body.classList.toggle("tts-speaking", speaking);
 if (activeBtn && activeBtn !== btn) {
 activeBtn.classList.remove("speaking");
 activeBtn.textContent = activeBtn.dataset.labelIdle || "朗读";
 }
 activeBtn = on ? btn || activeBtn : null;
 if (btn) {
 btn.classList.toggle("speaking", on);
 btn.textContent = on
 ? btn.dataset.labelStop || "⏹ 停止"
 : btn.dataset.labelIdle || "朗读";
 btn.setAttribute("aria-pressed", on ? "true" : "false");
 }
 // 同步其它朗读按钮
 document.querySelectorAll(".btn-speak").forEach((b) => {
 if (b === btn) return;
 if (!on) {
 b.classList.remove("speaking");
 b.textContent = b.dataset.labelIdle || "朗读";
 b.setAttribute("aria-pressed", "false");
 }
 });
 }

 function stopSpeak() {
 queue = [];
 currentUtter = null;
 try {
 speechSynthesis.cancel();
 } catch (_) {}
 setSpeakingUI(false, activeBtn);
 }

 function speakNext() {
 if (!queue.length) {
 setSpeakingUI(false, activeBtn);
 return;
 }
 const item = queue.shift();
 const u = new SpeechSynthesisUtterance(item.text);
 u.lang = item.lang || "zh-CN";
 u.rate = item.rate != null ? item.rate : 1;
 u.pitch = 1;
 const voice = pickVoice(item.lang);
 if (voice) {
 u.voice = voice;
 // 部分浏览器需与 voice.lang 一致
 if (voice.lang) u.lang = voice.lang;
 }
 currentUtter = u;
 u.onend = () => {
 currentUtter = null;
 speakNext();
 };
 u.onerror = () => {
 currentUtter = null;
 speakNext();
 };
 try {
 speechSynthesis.speak(u);
 } catch (e) {
 showToast("朗读失败: " + (e.message || e), "error");
 stopSpeak();
 }
 }

 /**
 * @param {string} text
 * @param {{ forceLang?: string, button?: HTMLElement, rate?: number }} opts
 * forceLang: auto | zh-CN | zh-HK | en-US
 */
 function speakText(text, opts = {}) {
 if (!isSupported()) {
 showToast("当前浏览器不支持朗读（Speech Synthesis）", "error");
 return;
 }
 const plain = stripForSpeech(text);
 if (!plain) {
 showToast("没有可朗读的文字", "warn");
 return;
 }

 // 再次点击同一按钮 → 停止
 if (speaking && opts.button && activeBtn === opts.button) {
 stopSpeak();
 return;
 }

 stopSpeak();
 ensureVoices();

 const force = opts.forceLang || "auto";
 let segments;
 if (force && force !== "auto") {
 segments = [{ text: plain, lang: force }];
 } else {
 segments = segmentByScript(plain);
 if (!segments.length) segments = [{ text: plain, lang: detectLang(plain) }];
 }

 // 过长单段再按句号切开，避免被截断
 const expanded = [];
 for (const seg of segments) {
 if (seg.text.length <= 180) {
 expanded.push(seg);
 continue;
 }
 const chunks = seg.text.split(/(?<=[。！？.!?；;\n])/);
 for (const c of chunks) {
 const t = c.trim();
 if (t) expanded.push({ text: t, lang: seg.lang });
 }
 }

 queue = expanded.map((s) => ({
 text: s.text,
 lang: s.lang,
 rate: opts.rate,
 }));

 const langs = [...new Set(expanded.map((s) => LANG_LABEL[s.lang] || s.lang))];
 if (typeof L.setStatus === "function") {
 L.setStatus(`朗读中（${langs.join(" + ")}）`, "ok");
 }
 setSpeakingUI(true, opts.button || null);
 // Chrome bug：cancel 后立即 speak 可能静音
 setTimeout(() => speakNext(), 40);
 }

 function toggleSpeak(text, opts = {}) {
 if (speaking) stopSpeak();
 else speakText(text, opts);
 }

 /**
 * 给消息操作区挂「语言 + 朗读」控件
 * @param {HTMLElement} actionsEl
 * @param {() => string} getText
 */
 function mountSpeakControls(actionsEl, getText) {
 if (!actionsEl || !isSupported()) return null;

 const wrap = document.createElement("span");
 wrap.className = "speak-wrap";

 const sel = document.createElement("select");
 sel.className = "speak-lang";
 sel.title = "朗读语言";
 sel.setAttribute("aria-label", "朗读语言");
 [
 ["auto", "自动"],
 ["zh-CN", "普通话"],
 ["zh-HK", "粤语"],
 ["en-US", "English"],
 ].forEach(([v, label]) => {
 const o = document.createElement("option");
 o.value = v;
 o.textContent = label;
 sel.appendChild(o);
 });
 try {
 const saved = localStorage.getItem("lily_tts_lang");
 if (saved && [...sel.options].some((o) => o.value === saved)) {
 sel.value = saved;
 }
 } catch (_) {}
 sel.addEventListener("change", () => {
 try {
 localStorage.setItem("lily_tts_lang", sel.value);
 } catch (_) {}
 });
 // 点击 select 不触发放开冒泡到消息
 sel.addEventListener("click", (e) => e.stopPropagation());

 const btn = document.createElement("button");
 btn.type = "button";
 btn.className = "btn-speak btn-copy";
 btn.dataset.labelIdle = "朗读";
 btn.dataset.labelStop = "⏹ 停止";
 btn.textContent = "朗读";
 btn.title = "朗读（可按语言分段）";
 btn.setAttribute("aria-pressed", "false");
 btn.addEventListener("click", (e) => {
 e.stopPropagation();
 const text = typeof getText === "function" ? getText() : "";
 speakText(text, { forceLang: sel.value || "auto", button: btn });
 });

 wrap.appendChild(sel);
 wrap.appendChild(btn);
 actionsEl.appendChild(wrap);
 return wrap;
 }

 // Esc 停止朗读
 document.addEventListener("keydown", (e) => {
 if (e.key === "Escape" && speaking) stopSpeak();
 });

 // 页面隐藏时停止，避免后台一直念
 document.addEventListener("visibilitychange", () => {
 if (document.hidden && speaking) stopSpeak();
 });

 L.speakText = speakText;
 L.stopSpeak = stopSpeak;
 L.toggleSpeak = toggleSpeak;
 L.mountSpeakControls = mountSpeakControls;
 L.isTtsSupported = isSupported;
 L.stripForSpeech = stripForSpeech;
 L.segmentByScript = segmentByScript;
})(window.Lily);
