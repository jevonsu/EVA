/**
 * Lily - Voice input (Web Speech API)
 * 识别语言默认跟随「人设 → 语言」：
 *   粤语 → zh-HK / yue-Hant-HK；简体中文 → zh-CN；英文 → en-US；
 *   跟随用户 / 中英混合 → 自动检测切换
 * 连续听写：静音/会话结束后自动重启，直到用户点停
 */
((L) => {
 "use strict";

 const { $, els, state, showToast } = L;

 const LANG_META = {
 auto: { label: "自动", space: false },
 "zh-CN": { label: "普通话", space: false },
 "zh-TW": { label: "繁体中文", space: false },
 "zh-HK": { label: "粤语", space: false },
 "yue-Hant-HK": { label: "粤语", space: false },
 "en-US": { label: "English", space: true },
 "en-GB": { label: "English", space: true },
 };

 /** 引擎实际使用的 BCP-47 */
 let effectiveLang = "zh-CN";
 /** 自动模式：连续命中同一语言才切换，防抖 */
 let pendingDetectLang = null;
 let pendingDetectHits = 0;
 const DETECT_SWITCH_HITS = 2;
 /** 粤语引擎候选（按优先级） */
 const YUE_LANG_CANDIDATES = ["zh-HK", "yue-Hant-HK", "zh-Yue", "yue"];

 let recognition = null;
 let listening = false;
 let interimActive = false;
 let baseBeforeInterim = "";
 let meetingHeaderWritten = false;
 let switchingLang = false;

 /** 连续听写：重启调度 */
 let restartTimer = null;
 let sessionGen = 0; // 递增，丢弃过期实例的回调
 let networkFailCount = 0;
 let lastSpeechAt = 0;
 let watchdogTimer = null;
 const RESTART_DELAY_MS = 280;
 const WATCHDOG_MS = 12000;
 const MAX_NETWORK_FAILS = 3;

 // 粤语特征字 / 词（简繁都覆盖一部分）
 const YUE_MARKERS =
 /[嘅咗喺唔係嚟咁嘢哋攞睇傾計搞掂冇係咪嚿喎噃喇嘞啱啲哋佢哋]/;

 function SpeechRecognitionCtor() {
 return window.SpeechRecognition || window.webkitSpeechRecognition || null;
 }

 function isSupported() {
 return !!SpeechRecognitionCtor();
 }

 /** 人设里的语言字段（设定 → 身份 → 语言） */
 function personaLanguage() {
 try {
 const a =
 (state.config && state.config.agent) ||
 (window.Lily &&
 window.Lily.state &&
 window.Lily.state.config &&
 window.Lily.state.config.agent) ||
 {};
 return String(a.language || "").trim() || "跟随用户";
 } catch (_) {
 return "跟随用户";
 }
 }

 /**
 * 人设语言 → 语音识别模式
 * @returns {{ mode: "auto"|"fixed", lang: string, label: string }}
 */
 function mapPersonaToSpeech() {
 const raw = personaLanguage();
 const t = raw.toLowerCase();

 if (
 !raw ||
 raw === "跟随用户" ||
 raw.includes("跟随") ||
 raw.includes("中英混合") ||
 /mixed|follow/i.test(raw)
 ) {
 return { mode: "auto", lang: "auto", label: "跟随用户·自动" };
 }
 if (
 raw.includes("粤") ||
 raw.includes("粵") ||
 /cantonese|yue/i.test(t)
 ) {
 return { mode: "fixed", lang: "zh-HK", label: "粤语" };
 }
 if (
 raw.includes("繁体") ||
 raw.includes("繁體") ||
 raw.includes("台湾") ||
 raw.includes("台灣") ||
 /zh-tw|traditional/i.test(t)
 ) {
 return { mode: "fixed", lang: "zh-TW", label: "繁体中文" };
 }
 if (
 raw.includes("英文") ||
 raw.includes("英语") ||
 raw.includes("English") ||
 /^en\b/i.test(t)
 ) {
 return { mode: "fixed", lang: "en-US", label: "English" };
 }
 // 简体中文 / 中文 / 普通话
 if (
 raw.includes("简体") ||
 raw.includes("簡體") ||
 raw.includes("普通话") ||
 raw.includes("普通話") ||
 raw.includes("国语") ||
 raw.includes("中文") ||
 /mandarin|zh-cn|simplified/i.test(t)
 ) {
 return { mode: "fixed", lang: "zh-CN", label: "普通话" };
 }
 return { mode: "auto", lang: "auto", label: raw || "自动" };
 }

 /** 跟随用户 / 中英混合 → 自动；粤语等固定语言 → 锁定引擎 */
 function isAutoMode() {
 return mapPersonaToSpeech().mode === "auto";
 }

 function isMeetingMode() {
 const el = $("voiceMeeting");
 if (el) return !!el.checked;
 return !!state.voiceMeeting;
 }

 function currentLangSetting() {
 const m = mapPersonaToSpeech();
 return m.mode === "auto" ? "auto" : m.lang;
 }

 function langLabel(code) {
 if (code === "auto") {
 const m = mapPersonaToSpeech();
 return m.mode === "auto" ? "自动" : m.label;
 }
 return (LANG_META[code] && LANG_META[code].label) || code;
 }

 /** 浏览器语言 → 初始引擎语言（仅 auto 模式） */
 function guessLangFromBrowser() {
 const nav = (navigator.language || navigator.userLanguage || "zh-CN").toLowerCase();
 if (nav.startsWith("yue") || nav === "zh-hk" || nav === "zh-mo") return "zh-HK";
 if (nav === "zh-tw") return "zh-TW";
 if (nav.startsWith("en")) return "en-US";
 if (nav.startsWith("zh")) return "zh-CN";
 return "zh-CN";
 }

 /** 固定模式下应使用的引擎语言 */
 function fixedEngineLang() {
 const m = mapPersonaToSpeech();
 if (m.mode !== "fixed") return guessLangFromBrowser();
 // 粤语：优先 zh-HK（Chrome 支持最好），可记用户上次成功的 yue tag
 if (m.lang === "zh-HK") {
 try {
 const saved = localStorage.getItem("lily_voice_yue_engine");
 if (saved && YUE_LANG_CANDIDATES.includes(saved)) return saved;
 } catch (_) {}
 return "zh-HK";
 }
 return m.lang;
 }

 /**
 * 从已识别文本猜测语言（启发式，非完美）
 * @returns {"zh-CN"|"zh-HK"|"en-US"|null}
 */
 function detectLangFromText(text) {
 const t = (text || "").trim();
 if (t.length < 2) return null;

 const cjk = (t.match(/[\u4e00-\u9fff]/g) || []).length;
 const latin = (t.match(/[A-Za-z]/g) || []).length;
 const totalLetters = cjk + latin;
 if (totalLetters < 2) return null;

 if (latin >= 4 && latin >= cjk * 1.2) return "en-US";

 if (cjk >= 2) {
 if (YUE_MARKERS.test(t)) return "zh-HK";
 return "zh-CN";
 }

 if (latin >= 3) return "en-US";
 return null;
 }

 function setVoiceHint(text, type) {
 const el = $("voiceHint");
 if (el) {
 const show = type === "live" || type === "error";
 el.textContent = text;
 el.title = text;
 el.classList.toggle("is-live", type === "live");
 el.classList.toggle("is-err", type === "error");
 el.classList.toggle("is-idle", !show);
 el.hidden = !show;
 }
 if (typeof L.setStatus === "function" && type === "error") {
 L.setStatus(text, "error");
 }
 }

 function setListeningUI(on) {
 listening = !!on;
 state.voiceListening = listening;
 document.body.classList.toggle("voice-listening", listening);
 document.body.classList.toggle("voice-meeting", listening && isMeetingMode());
 const btn = $("btnVoice");
 const plus = $("btnComposerPlus");
 const label = $("btnVoiceLabel");
 if (btn) {
 btn.classList.toggle("listening", listening);
 btn.setAttribute("aria-pressed", listening ? "true" : "false");
 const p = mapPersonaToSpeech();
 const langPart =
 p.mode === "fixed" ? p.label + "·随人设" : "自动·随人设";
 btn.title = listening
 ? `停止语音输入（${langPart}）`
 : isMeetingMode()
 ? `会议听写（连续 · ${langPart}）`
 : `语音输入（连续 · ${langPart} · 再点停止）`;
 }
 if (label) label.textContent = listening ? "停止语音" : "语音输入";
 if (plus) plus.classList.toggle("listening", listening);
 }

 function needsSpace(lang, left, right) {
 const code = lang === "auto" ? effectiveLang : lang;
 const meta = LANG_META[code] || LANG_META["zh-CN"];
 if (!meta.space) return false;
 if (!left || !right) return false;
 const l = left.slice(-1);
 const r = right[0];
 if (/\s/.test(l) || /\s/.test(r)) return false;
 if (/[([{（【「『]$/.test(l) || /^[)\]}）】」』,.!?;:，。！？；：]/.test(r)) {
 return false;
 }
 return /[A-Za-z0-9]$/.test(l) && /[A-Za-z0-9]/.test(r);
 }

 function engineLang() {
 if (isAutoMode()) return effectiveLang || guessLangFromBrowser();
 // 锁定人设语言（粤语等），不因识别文本漂回普通话
 return effectiveLang || fixedEngineLang();
 }

 function formatTime(d = new Date()) {
 const p = (n) => String(n).padStart(2, "0");
 return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
 }

 function ensureMeetingHeader() {
 if (!isMeetingMode() || meetingHeaderWritten || !els.input) return;
 const stamp = new Date().toLocaleString();
 const header = `【会议记录 · ${stamp}】\n`;
 if (!els.input.value.includes("【会议记录")) {
 const cur = els.input.value;
 els.input.value = cur ? cur.replace(/\s*$/, "") + "\n\n" + header : header;
 if (typeof L.autoResize === "function") L.autoResize();
 }
 meetingHeaderWritten = true;
 baseBeforeInterim = els.input.value;
 }

 function appendToInput(text, { replaceInterim = false, meetingLine = false } = {}) {
 if (!els.input || !text) return;
 const ta = els.input;
 let value = ta.value;
 const lang = engineLang();

 if (replaceInterim && interimActive) {
 value = baseBeforeInterim;
 interimActive = false;
 }

 if (replaceInterim) {
 if (!interimActive) {
 baseBeforeInterim = value;
 interimActive = true;
 }
 const sep = needsSpace(lang, baseBeforeInterim, text) ? " " : "";
 ta.value = baseBeforeInterim + sep + text;
 } else {
 if (interimActive) {
 value = baseBeforeInterim;
 interimActive = false;
 }
 let piece = text;
 if (meetingLine && isMeetingMode()) {
 ensureMeetingHeader();
 value = ta.value;
 if (interimActive) {
 value = baseBeforeInterim;
 interimActive = false;
 }
 const line = `[${formatTime()}] ${text.trim()}`;
 const needNl = value && !value.endsWith("\n");
 ta.value = value + (needNl ? "\n" : "") + line + "\n";
 baseBeforeInterim = ta.value;
 if (typeof L.autoResize === "function") L.autoResize();
 try {
 const len = ta.value.length;
 ta.setSelectionRange(len, len);
 ta.focus();
 } catch (_) {}
 return;
 }

 let join = "";
 if (value && !/\s$/.test(value) && !/^[，。！？、,.!?;:\s]/.test(piece)) {
 join = needsSpace(lang, value, piece) ? " " : "";
 }
 ta.value = value + join + piece;
 baseBeforeInterim = ta.value;
 }

 if (typeof L.autoResize === "function") L.autoResize();
 try {
 const len = ta.value.length;
 ta.setSelectionRange(len, len);
 ta.focus();
 } catch (_) {}
 }

 function commitFinal(text) {
 const t = (text || "").trim();
 if (!t) return;
 appendToInput(t, {
 replaceInterim: false,
 meetingLine: isMeetingMode(),
 });
 }

 function showInterim(text) {
 const t = text || "";
 if (!t) return;
 appendToInput(t, { replaceInterim: true });
 }

 function clearRestartTimer() {
 if (restartTimer) {
 clearTimeout(restartTimer);
 restartTimer = null;
 }
 }

 function clearWatchdog() {
 if (watchdogTimer) {
 clearInterval(watchdogTimer);
 watchdogTimer = null;
 }
 }

 function touchSpeech() {
 lastSpeechAt = Date.now();
 }

 /**
 * 连续听写核心：会话结束后延迟重启（Chrome 静音后会 onend，必须重建/重启）
 */
 function scheduleRestart(reason) {
 if (!state.voiceWantListen) return;
 clearRestartTimer();
 restartTimer = setTimeout(() => {
 restartTimer = null;
 if (!state.voiceWantListen) return;
 tryStartRecognition(reason || "restart");
 }, RESTART_DELAY_MS);
 }

 function startWatchdog() {
 clearWatchdog();
 lastSpeechAt = Date.now();
 watchdogTimer = setInterval(() => {
 if (!state.voiceWantListen) {
 clearWatchdog();
 return;
 }
 // 想听但 UI 不在听，或长时间无结果 → 强制重启
 const idle = Date.now() - lastSpeechAt;
 if (!listening || idle > WATCHDOG_MS) {
 setVoiceHint(
 listening
 ? "语音：静音过久，自动续听…"
 : "语音：会话中断，自动续听…",
 "live"
 );
 scheduleRestart("watchdog");
 }
 }, Math.floor(WATCHDOG_MS / 2));
 }

 /**
 * 仅「跟随用户 / 中英混合」自动模式：根据文本决定是否切换引擎语言
 * 人设锁定粤语/普通话/英语时不切换，避免粤语被漂成普通话
 */
 function maybeSwitchLangFromText(text) {
 if (!isAutoMode() || !state.voiceWantListen) return;

 const detected = detectLangFromText(text);
 if (!detected) return;

 const cur = effectiveLang === "yue-Hant-HK" ? "zh-HK" : effectiveLang;
 const det = detected === "yue-Hant-HK" ? "zh-HK" : detected;
 if (det === cur) {
 pendingDetectLang = null;
 pendingDetectHits = 0;
 return;
 }

 if (pendingDetectLang === det) {
 pendingDetectHits += 1;
 } else {
 pendingDetectLang = det;
 pendingDetectHits = 1;
 }

 if (pendingDetectHits < DETECT_SWITCH_HITS) {
 setVoiceHint(
 `语音：疑似${langLabel(det)}（${pendingDetectHits}/${DETECT_SWITCH_HITS}）· 当前${langLabel(effectiveLang)}`,
 "live"
 );
 return;
 }

 pendingDetectHits = 0;
 pendingDetectLang = null;
 switchEngineLang(detected, true);
 }

 function switchEngineLang(nextLang, fromAuto) {
 if (!nextLang || nextLang === effectiveLang) return;
 const prev = effectiveLang;
 effectiveLang = nextLang;
 try {
 localStorage.setItem("lily_voice_effective", nextLang);
 } catch (_) {}

 setVoiceHint(
 `语音：${fromAuto ? "自动切换 → " : ""}${langLabel(nextLang)}`,
 "live"
 );
 if (fromAuto) {
 showToast(`识别语言已切换：${langLabel(prev)} → ${langLabel(nextLang)}`, "info", 2200);
 }

 if (state.voiceWantListen) {
 switchingLang = true;
 disposeRecognition(false);
 scheduleRestart("lang-switch");
 setTimeout(() => {
 switchingLang = false;
 }, 400);
 }
 }

 /** 安全停掉当前实例；clearWant=false 时保留连续意图 */
 function disposeRecognition(clearHandlers) {
 const rec = recognition;
 recognition = null;
 if (!rec) return;
 try {
 if (clearHandlers) {
 rec.onstart = null;
 rec.onend = null;
 rec.onerror = null;
 rec.onresult = null;
 rec.onnomatch = null;
 rec.onsoundend = null;
 rec.onspeechend = null;
 }
 rec.stop();
 } catch (_) {
 try {
 rec.abort();
 } catch (_) {}
 }
 }

 function createRecognition(gen) {
 const Ctor = SpeechRecognitionCtor();
 if (!Ctor) return null;
 const rec = new Ctor();
 rec.continuous = true;
 rec.interimResults = true;
 rec.maxAlternatives = 1;
 rec.lang = engineLang();

 rec.onstart = () => {
 if (gen !== sessionGen || !state.voiceWantListen) return;
 setListeningUI(true);
 networkFailCount = 0;
 touchSpeech();
 const mode = isAutoMode() ? "自动" : langLabel(currentLangSetting());
 const eng = langLabel(engineLang());
 const meet = isMeetingMode() ? " · 会议" : "";
 setVoiceHint(
 `语音：连续聆听 · ${mode}${isAutoMode() ? `（${eng}）` : ""}${meet}`,
 "live"
 );
 interimActive = false;
 baseBeforeInterim = els.input ? els.input.value : "";
 if (isMeetingMode()) ensureMeetingHeader();
 };

 rec.onend = () => {
 if (gen !== sessionGen) return;
 // 仅当仍是当前实例时清 UI 的 listening；续听由 scheduleRestart 接上
 if (recognition === rec) {
 recognition = null;
 }
 setListeningUI(false);

 if (state.voiceWantListen) {
 // Chrome：静音 / 一段结束后会 onend，必须重启才能「连续」
 setVoiceHint("语音：续听中…", "live");
 scheduleRestart("onend");
 return;
 }

 interimActive = false;
 if (!switchingLang) setVoiceHint("语音：待机", "");
 clearWatchdog();
 };

 rec.onerror = (ev) => {
 if (gen !== sessionGen) return;
 const err = ev.error || "error";

 // 可恢复错误：保持 voiceWantListen，等 onend 或主动重启
 if (err === "no-speech" || err === "aborted" || err === "audio-capture") {
 if (err === "no-speech") {
 setVoiceHint(
 isMeetingMode() ? "语音：等待发言…" : "语音：未检测到说话，继续听…",
 "live"
 );
 }
 // aborted 常在 stop/切换时出现；若仍要听则续
 if (state.voiceWantListen && err !== "aborted") {
 // 部分浏览器 no-speech 后不立刻 onend，补一刀
 scheduleRestart(err);
 }
 return;
 }

 if (err === "not-allowed" || err === "service-not-allowed") {
 state.voiceWantListen = false;
 clearRestartTimer();
 clearWatchdog();
 setListeningUI(false);
 setVoiceHint("语音：麦克风权限被拒绝", "error");
 showToast("请允许浏览器使用麦克风后重试", "error");
 return;
 }

 if (err === "network") {
 networkFailCount += 1;
 setVoiceHint(
 `语音：网络错误（${networkFailCount}/${MAX_NETWORK_FAILS}），重试中…`,
 "error"
 );
 if (networkFailCount >= MAX_NETWORK_FAILS) {
 state.voiceWantListen = false;
 clearRestartTimer();
 clearWatchdog();
 setListeningUI(false);
 showToast("语音识别需要稳定网络（浏览器云端服务）", "warn");
 setVoiceHint("语音：网络失败，已停止", "error");
 return;
 }
 scheduleRestart("network");
 return;
 }

 if (err === "language-not-supported") {
 // 粤语：依次尝试候选标签，不要立刻掉回普通话
 if (
 !isAutoMode() &&
 mapPersonaToSpeech().lang === "zh-HK"
 ) {
 const cur = effectiveLang;
 const idx = YUE_LANG_CANDIDATES.indexOf(cur);
 const next =
 idx >= 0 && idx < YUE_LANG_CANDIDATES.length - 1
 ? YUE_LANG_CANDIDATES[idx + 1]
 : null;
 if (next) {
 showToast(`粤语引擎 ${cur} 不可用，尝试 ${next}`, "warn");
 try {
 localStorage.setItem("lily_voice_yue_engine", next);
 } catch (_) {}
 switchEngineLang(next, false);
 return;
 }
 showToast(
 "浏览器未提供粤语识别，请用 Chrome/Edge 并允许麦克风；将尽量使用 zh-HK",
 "warn"
 );
 }
 if (isAutoMode() && effectiveLang !== "zh-CN") {
 showToast("当前语言引擎不可用，回退普通话", "warn");
 switchEngineLang("zh-CN", true);
 return;
 }
 setVoiceHint("语音：当前语言不受支持", "error");
 showToast("此浏览器不支持所选语言", "warn");
 return;
 }

 // 其它错误：尝试续听，不直接杀掉连续模式
 setVoiceHint("语音：错误 " + err + "，尝试续听…", "error");
 if (state.voiceWantListen) scheduleRestart("error:" + err);
 };

 rec.onresult = (event) => {
 if (gen !== sessionGen || !state.voiceWantListen) return;
 touchSpeech();
 networkFailCount = 0;

 let interim = "";
 let finalChunk = "";
 for (let i = event.resultIndex; i < event.results.length; i++) {
 const res = event.results[i];
 const t = (res[0] && res[0].transcript) || "";
 if (res.isFinal) finalChunk += t;
 else interim += t;
 }
 if (finalChunk) {
 commitFinal(finalChunk);
 baseBeforeInterim = els.input ? els.input.value : "";
 interimActive = false;
 maybeSwitchLangFromText(finalChunk);
 const mode = isAutoMode()
 ? `自动→${langLabel(engineLang())}`
 : langLabel(engineLang());
 setVoiceHint(
 `语音：连续聆听 · 已写入 · ${mode}${isMeetingMode() ? " · 会议" : ""}`,
 "live"
 );
 } else if (interim) {
 showInterim(interim);
 if (isAutoMode()) {
 const d = detectLangFromText(interim);
 if (d && d !== (effectiveLang === "yue-Hant-HK" ? "zh-HK" : effectiveLang)) {
 setVoiceHint(`语音：…${interim.slice(-12)}（疑似${langLabel(d)}）`, "live");
 } else {
 setVoiceHint(`语音：…${interim.slice(-16)}`, "live");
 }
 } else {
 setVoiceHint(`语音：…${interim.slice(-16)}`, "live");
 }
 }
 };

 // 辅助信号：有声音也算活跃，避免 watchdog 误杀
 rec.onsoundstart = () => {
 if (gen === sessionGen) touchSpeech();
 };
 rec.onspeechstart = () => {
 if (gen === sessionGen) touchSpeech();
 };

 return rec;
 }

 function tryStartRecognition(reason) {
 if (!state.voiceWantListen) return;
 if (!isSupported()) return;

 clearRestartTimer();
 // 丢弃旧实例回调
 sessionGen += 1;
 const gen = sessionGen;
 disposeRecognition(true);

 try {
 recognition = createRecognition(gen);
 if (!recognition) {
 state.voiceWantListen = false;
 setListeningUI(false);
 setVoiceHint("语音：浏览器不支持", "error");
 return;
 }
 recognition.lang = engineLang();
 recognition.start();
 // 部分浏览器 start 异步，短暂保持 want
 if (reason && reason !== "start") {
 // 保持提示
 }
 } catch (e) {
 const name = e && (e.name || "");
 // already started：稍后再试
 if (String(name).includes("InvalidState") || /already/i.test(String(e))) {
 scheduleRestart("invalid-state");
 return;
 }
 // 启动失败：有限次重试
 if (state.voiceWantListen) {
 setVoiceHint("语音：启动失败，重试中…", "error");
 scheduleRestart("start-fail");
 return;
 }
 state.voiceWantListen = false;
 setListeningUI(false);
 showToast("无法启动语音: " + (e.message || e), "error");
 setVoiceHint("语音：启动失败", "error");
 }
 }

 function startVoice() {
 if (!isSupported()) {
 showToast("当前浏览器不支持语音输入，请用 Chrome 或 Edge", "error");
 setVoiceHint("语音：浏览器不支持", "error");
 return;
 }
 const secure =
 location.protocol === "https:" ||
 location.hostname === "localhost" ||
 location.hostname === "127.0.0.1";
 if (!secure) {
 showToast("语音输入需要 HTTPS 或 localhost", "warn");
 }

 const persona = mapPersonaToSpeech();
 if (persona.mode === "auto") {
 try {
 const saved = localStorage.getItem("lily_voice_effective");
 // 跟随用户：可用上次自动结果，否则浏览器语言
 effectiveLang = saved || guessLangFromBrowser();
 } catch (_) {
 effectiveLang = guessLangFromBrowser();
 }
 } else {
 // 锁定人设语言（粤语优先 zh-HK，不再默认普通话）
 effectiveLang = fixedEngineLang();
 try {
 localStorage.setItem("lily_voice_effective", effectiveLang);
 } catch (_) {}
 }
 pendingDetectHits = 0;
 pendingDetectLang = null;
 meetingHeaderWritten = false;
 networkFailCount = 0;
 switchingLang = false;

 state.voiceWantListen = true;
 startWatchdog();
 tryStartRecognition("start");
 const lockHint =
 persona.mode === "fixed"
 ? `锁定「${persona.label}」· 随人设`
 : `自动 · 人设「${personaLanguage()}」`;
 setVoiceHint(`语音：连续聆听 · ${lockHint}`, "live");
 showToast(
 persona.mode === "fixed"
 ? `语音识别：${persona.label}（跟随人设）`
 : "语音识别：自动切换（人设为跟随用户）",
 "info",
 2200
 );
 }

 function stopVoice() {
 state.voiceWantListen = false;
 interimActive = false;
 pendingDetectHits = 0;
 pendingDetectLang = null;
 switchingLang = false;
 networkFailCount = 0;
 clearRestartTimer();
 clearWatchdog();
 sessionGen += 1; // 作废进行中的回调
 disposeRecognition(true);
 setListeningUI(false);
 setVoiceHint("语音：待机", "");
 if (isMeetingMode() && els.input && meetingHeaderWritten) {
 const end = `\n【会议记录结束 · ${new Date().toLocaleString()}】\n`;
 if (!els.input.value.includes("会议记录结束")) {
 els.input.value = els.input.value.replace(/\s*$/, "") + end;
 if (typeof L.autoResize === "function") L.autoResize();
 }
 }
 }

 function toggleVoice() {
 if (listening || state.voiceWantListen) stopVoice();
 else startVoice();
 }

 function bindVoiceUI() {
 const btn = $("btnVoice");
 const meet = $("voiceMeeting");

 function idleHint() {
 const p = mapPersonaToSpeech();
 if (p.mode === "fixed") {
 return `语音：待机 · ${p.label}（跟随人设）`;
 }
 return "语音：待机 · 自动识别（人设：跟随用户）";
 }

 if (!isSupported()) {
 if (btn) {
 btn.disabled = true;
 btn.title = "浏览器不支持 Web Speech API（建议 Chrome / Edge）";
 }
 setVoiceHint("语音：不支持", "error");
 } else {
 setVoiceHint(idleHint(), "");
 if (btn) {
 const p = mapPersonaToSpeech();
 btn.title =
 p.mode === "fixed"
 ? `语音输入 · ${p.label}（随人设语言）· 再点停止`
 : "语音输入 · 自动识别 · 再点停止";
 }
 }

 try {
 const meetSaved = localStorage.getItem("lily_voice_meeting");
 if (meet && meetSaved != null) meet.checked = meetSaved === "1";
 // 旧版手动语言选择缓存作废，改跟从人设
 localStorage.removeItem("lily_voice_lang");
 } catch (_) {}

 meet?.addEventListener("change", () => {
 state.voiceMeeting = !!meet.checked;
 try {
 localStorage.setItem("lily_voice_meeting", meet.checked ? "1" : "0");
 } catch (_) {}
 const p = mapPersonaToSpeech();
 setVoiceHint(
 meet.checked
 ? `语音：会议模式 · ${p.mode === "fixed" ? p.label : "自动"} · 时间戳`
 : idleHint(),
 ""
 );
 });

 btn?.addEventListener("click", () => toggleVoice());

 // 人设语言保存后刷新待机提示
 L.refreshVoiceLangFromPersona = function refreshVoiceLangFromPersona() {
 if (listening || state.voiceWantListen) {
 // 听写中途：若人设改为固定语言，切换引擎
 const p = mapPersonaToSpeech();
 if (p.mode === "fixed") {
 const next = fixedEngineLang();
 if (next !== effectiveLang) switchEngineLang(next, false);
 }
 } else {
 setVoiceHint(idleHint(), "");
 if (btn) {
 const p = mapPersonaToSpeech();
 btn.title =
 p.mode === "fixed"
 ? `语音输入 · ${p.label}（随人设语言）· 再点停止`
 : "语音输入 · 自动识别 · 再点停止";
 }
 }
 };

 document.addEventListener("keydown", (e) => {
 if (e.key === "Escape" && (listening || state.voiceWantListen)) {
 stopVoice();
 }
 });

 // 页面隐藏时 Chrome 会掐识别；回来后若仍要听则续
 document.addEventListener("visibilitychange", () => {
 if (document.visibilityState === "visible" && state.voiceWantListen && !listening) {
 scheduleRestart("visible");
 }
 });
 }

 L.bindVoiceUI = bindVoiceUI;
 L.startVoice = startVoice;
 L.stopVoice = stopVoice;
 L.toggleVoice = toggleVoice;
 L.isVoiceSupported = isSupported;
 L.detectLangFromText = detectLangFromText;
 L.mapPersonaToSpeech = mapPersonaToSpeech;
 L.personaLanguage = personaLanguage;
})(window.Lily);
