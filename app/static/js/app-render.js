/**
 * Lily - Render (Markdown + Messages)
 */
((L) => {
 "use strict";
 const { $, els, state, showToast, debounce, timeAgo, formatMsgTime, renderSkeleton, escapeHtml, stripThinking, normalizeToolCalls, extractToolCalls, summarizeToolNames, extractMediaPaths, renderToolsBar, ipk, ipkLabel } = L;
 const _ipk = (n, c) => (typeof ipk === "function" ? ipk(n, c) : (L.ipk ? L.ipk(n, c) : ""));
 const _ipkLabel = (n, t, c) =>
   typeof ipkLabel === "function" ? ipkLabel(n, t, c) : (L.ipkLabel ? L.ipkLabel(n, t, c) : t || "");

 // ======== 本地 + 远程媒体 ========
 const IMAGE_EXT = /\.(png|jpe?g|gif|webp|bmp|svg|ico|avif|jfif)(?:\?|#|$)/i;
 const VIDEO_EXT = /\.(mp4|webm|mov|m4v|ogv)(?:\?|#|$)/i;
 const AUDIO_EXT = /\.(mp3|wav|m4a|aac|flac|ogg)(?:\?|#|$)/i;
 // 常见图床 / CDN（路径无扩展名也能当图片）
 const REMOTE_IMAGE_HOST =
 /(^|\.)((i\.)?imgur\.com|pbs\.twimg\.com|media\.discordapp\.(net|com)|cdn\.discordapp\.com|images\.unsplash\.com|plus\.unsplash\.com|lh3\.googleusercontent\.com|drive\.google\.com|raw\.githubusercontent\.com|user-images\.githubusercontent\.com|pic[0-9]*\.zhimg\.com|sinaimg\.cn|qpic\.cn|gtimg\.cn|byteimg\.com|pstatp\.com|bdstatic\.com|alicdn\.com|aliyuncs\.com|qcloud\.com|myqcloud\.com|cloudfront\.net|imgix\.net|cloudinary\.com|pinimg\.com|flickr\.com|staticflickr\.com|wp\.com|googleusercontent\.com|ggpht\.com|ytimg\.com|fbcdn\.net|cdninstagram\.com|sspai\.com|hdslb\.com|biliimg\.com)/i;

 function isHttpUrl(s) {
 return /^https?:\/\//i.test(s || "");
 }

 function isMediaApiUrl(s) {
 return (
 /^\/api\/workspace\/media\//i.test(s || "") ||
 /^\/api\/workspace\/smb-media\b/i.test(s || "")
 );
 }

 /** 还原路径/URL 中的 HTML 实体与尖括号包裹 */
 function decodeMediaRef(raw) {
 let p = String(raw || "").trim();
 p = p.replace(/^<|>$/g, "");
 p = p.replace(/^['"`]|['"`]$/g, "");
 p = p
 .replace(/&amp;/g, "&")
 .replace(/&lt;/g, "<")
 .replace(/&gt;/g, ">")
 .replace(/&quot;/g, '"')
 .replace(/&#39;/g, "'");
 return p.trim();
 }

 /** 是否像内网/文件服务器主机（避免把 //cdn.com 误判成 SMB） */
 function isLikelySmbHost(host) {
 const h = String(host || "").toLowerCase();
 if (!h) return false;
 if (/^\d{1,3}(\.\d{1,3}){3}$/.test(h)) return true; // IPv4
 if (h.endsWith(".local") || h.endsWith(".lan") || h.endsWith(".home")) return true;
 if (/^(nas|smb|fileserver|storage)/i.test(h)) return true;
 return false;
 }

 /**
 * 解析 SMB/UNC 引用 → { host, share, path } 或 null
 * 支持:
 *   \\10.0.0.10\share\folder\a.jpg
 *   //10.0.0.10/share/folder/a.jpg
 *   smb://10.0.0.10/share/folder/a.jpg
 *   /api/workspace/smb-media?share=…&path=…
 */
 function parseSmbRef(raw) {
 let s = decodeMediaRef(raw);
 if (!s) return null;

 // 已是代理 URL
 if (/^\/api\/workspace\/smb-media\b/i.test(s)) {
 try {
 const u = new URL(s, window.location.origin);
 const share = u.searchParams.get("share") || "";
 const path = u.searchParams.get("path") || "";
 const host = u.searchParams.get("host") || "";
 if (share && path) return { host, share, path };
 } catch (_) {}
 return null;
 }

 // 统一斜杠，保留前导 // 语义
 const hadUnc = /^[\\/]{2}/.test(s) || /^smb:\/\//i.test(s);
 s = s.replace(/\\/g, "/");

 // smb://host/share/path
 let m = s.match(/^smb:\/\/([^/]+)\/([^/]+)\/(.+)$/i);
 if (m) {
 return {
 host: m[1],
 share: m[2],
 path: m[3].replace(/^\/+/, ""),
 };
 }

 // //host/share/path 或 已转换的 UNC
 m = s.match(/^\/\/([^/]+)\/([^/]+)\/(.+)$/);
 if (m && (hadUnc || isLikelySmbHost(m[1]))) {
 return {
 host: m[1],
 share: m[2],
 path: m[3].replace(/^\/+/, ""),
 };
 }

 // host/share/path.jpg （显式 IP 开头）
 m = s.match(/^(\d{1,3}(?:\.\d{1,3}){3})\/([^/]+)\/(.+)$/);
 if (m) {
 return { host: m[1], share: m[2], path: m[3].replace(/^\/+/, "") };
 }

 return null;
 }

 function toSmbMediaUrl(ref) {
 if (!ref || !ref.share || !ref.path) return "";
 // 优先 path 形式，避免 query 里 + 被当成空格（如文件夹 18+）
 const share = encodeURIComponent(String(ref.share).replace(/\\/g, "/"));
 const segs = String(ref.path)
 .replace(/\\/g, "/")
 .replace(/^\/+/, "")
 .split("/")
 .filter(Boolean)
 .map((s) => encodeURIComponent(s));
 let url = `/api/workspace/smb-media/${share}/${segs.join("/")}`;
 if (ref.host) {
 url += `?host=${encodeURIComponent(ref.host)}`;
 }
 return url;
 }

 function isSmbRef(raw) {
 return !!parseSmbRef(raw);
 }

 /** 规范化成 workspace 相对路径（仅本地） */
 function normalizeLocalPath(raw) {
 if (!raw) return "";
 let p = decodeMediaRef(raw);
 if (isHttpUrl(p) || p.startsWith("data:") || isMediaApiUrl(p)) return "";
 if (parseSmbRef(p)) return ""; // SMB 不走 workspace
 p = p.replace(/\\/g, "/");
 // 去掉 file://
 p = p.replace(/^file:\/\//i, "");
 // 去掉盘符绝对路径里截取 workspace 之后
 const wsIdx = p.toLowerCase().lastIndexOf("/workspace/");
 if (wsIdx >= 0) {
 p = p.slice(wsIdx + "/workspace/".length);
 } else if (/^[a-z]:\//i.test(p)) {
 // 其它绝对路径：只取文件名（避免越权拼路径）
 p = p.split("/").pop() || p;
 }
 while (p.startsWith("./")) p = p.slice(2);
 if (p.toLowerCase().startsWith("workspace/")) p = p.slice("workspace/".length);
 p = p.replace(/^\/+/, "");
 return p;
 }

 /** 生成可预览 URL：本地 / SMB 代理 / 远程原样 */
 function toMediaSrc(raw) {
 const s = decodeMediaRef(raw);
 if (!s) return "";
 if (isMediaApiUrl(s) || s.startsWith("data:")) return s;
 if (isHttpUrl(s)) return s;

 // SMB / UNC 优先（避免 //10.x.x.x 被当成 https）
 const smb = parseSmbRef(s);
 if (smb) return toSmbMediaUrl(smb);

 // 协议相对 https（公网 CDN）
 if (/^\/\//.test(s) && !isLikelySmbHost(s.replace(/^\/\//, "").split("/")[0])) {
 return "https:" + s;
 }

 const rel = normalizeLocalPath(s);
 if (!rel || rel.includes("..")) return "";
 return (
 "/api/workspace/media/" +
 rel
 .split("/")
 .map((seg) => encodeURIComponent(seg))
 .join("/")
 );
 }

 function pathForExtTest(path) {
 // 去掉 query/hash 再测扩展名
 return String(path || "")
 .split("?")[0]
 .split("#")[0];
 }

 function hostOf(url) {
 try {
 return new URL(url).hostname || "";
 } catch {
 return "";
 }
 }

 /**
 * 推断媒体类型。
 * opts.forceImage：来自 ![alt](url) 语法时，远程无扩展名也当图片。
 */
 function mediaKind(path, opts = {}) {
 const raw = decodeMediaRef(path);
 if (!raw) return null;
 if (raw.startsWith("data:image/")) return "image";
 if (raw.startsWith("data:video/")) return "video";
 if (raw.startsWith("data:audio/")) return "audio";

 // SMB：看扩展名（path 段）
 const smb = parseSmbRef(raw);
 const extProbe = smb ? smb.path : raw;

 const base = pathForExtTest(extProbe);
 if (IMAGE_EXT.test(base) || IMAGE_EXT.test(extProbe)) return "image";
 if (VIDEO_EXT.test(base) || VIDEO_EXT.test(extProbe)) return "video";
 if (AUDIO_EXT.test(base) || AUDIO_EXT.test(extProbe)) return "audio";

 if (smb && opts.forceImage) return "image";

 if (isHttpUrl(raw) || (/^\/\//.test(raw) && !smb)) {
 const href = isHttpUrl(raw) ? raw : "https:" + raw;
 const host = hostOf(href);
 // 查询参数里带 format=jpg / fm=png 等
 if (/[?&](format|fm|type|ext)=(jpe?g|png|gif|webp|bmp|svg|avif)/i.test(href))
 return "image";
 if (REMOTE_IMAGE_HOST.test(host)) return "image";
 // Markdown 图片语法 / 明确要求当图
 if (opts.forceImage) return "image";
 // 路径段像图片资源
 if (/\/(image|images|img|photo|photos|media|static|upload|uploads)\//i.test(href))
 return "image";
 }
 return null;
 }

 /** 是否像可预览的远程图片 URL（含无扩展名图床） */
 function looksLikeRemoteImageUrl(path) {
 return mediaKind(path, { forceImage: false }) === "image" ||
 (isHttpUrl(decodeMediaRef(path)) && mediaKind(path, { forceImage: true }) === "image" &&
 (IMAGE_EXT.test(pathForExtTest(path)) ||
 REMOTE_IMAGE_HOST.test(hostOf(decodeMediaRef(path))) ||
 /[?&](format|fm|type|ext)=/i.test(path) ||
 /\/(image|images|img|photo|media|upload)/i.test(path)));
 }

 function renderMediaHtml(srcRaw, alt, opts = {}) {
 const raw = decodeMediaRef(srcRaw);
 const src = toMediaSrc(raw);
 if (!src) return null;
 const kind = mediaKind(raw, opts);
 if (!kind) return null;

 const safeAlt = escapeHtml(alt || raw);
 const safeSrc = escapeHtml(src);
 const smbRef = parseSmbRef(raw);
 const isRemote = isHttpUrl(src) || src.startsWith("data:");
 const isSmb = !!smbRef || /smb-media\b/i.test(src);
 // 远程/SMB：优先显示链接文字，否则显示路径
 const captionText =
 alt && String(alt).trim() && String(alt).trim() !== raw
   ? String(alt).trim()
   : isSmb && smbRef
     ? `SMB · ${smbRef.share}/${smbRef.path}`
     : isRemote
       ? raw
       : normalizeLocalPath(raw) || raw;
 const caption = escapeHtml(captionText);
 // 远程图：no-referrer 降低防盗链拦截（勿加 crossorigin，否则无 CORS 的 CDN 会直接失败）
 const remoteAttrs = isRemote ? ` referrerpolicy="no-referrer"` : "";
 const onErr =
 kind === "image"
 ? ` onerror="this.classList.add('md-img-broken');var c=this.closest('figure');if(c)c.classList.add('is-broken');"`
 : "";

 if (kind === "image") {
 return (
 `<figure class="md-media md-image${isRemote ? " md-remote" : ""}${isSmb ? " md-smb" : ""}">` +
 `<a href="${safeSrc}" target="_blank" rel="noopener noreferrer" title="打开原图">` +
 `<img src="${safeSrc}" alt="${safeAlt}" loading="lazy" decoding="async"${remoteAttrs}${onErr} />` +
 `</a>` +
 `<figcaption>${caption}</figcaption>` +
 `</figure>`
 );
 }
 if (kind === "video") {
 return (
 `<figure class="md-media md-video">` +
 `<video src="${safeSrc}" controls preload="metadata" playsinline${isRemote ? ' referrerpolicy="no-referrer"' : ""}></video>` +
 `<figcaption>${caption}</figcaption>` +
 `</figure>`
 );
 }
 if (kind === "audio") {
 return (
 `<figure class="md-media md-audio">` +
 `<audio src="${safeSrc}" controls preload="metadata"></audio>` +
 `<figcaption>${caption}</figcaption>` +
 `</figure>`
 );
 }
 return null;
 }

 /** 围栏代码/提示词语言标签（展示用） */
 function fenceKindLabel(lang) {
 const l = String(lang || "")
 .toLowerCase()
 .trim();
 if (!l || l === "text" || l === "txt" || l === "plain" || l === "plaintext")
 return "文本";
 if (
 l === "prompt" ||
 l === "prompts" ||
 l === "system" ||
 l === "user" ||
 l === "assistant"
 )
 return "提示词";
 if (l === "md" || l === "markdown") return "Markdown";
 if (l === "json") return "JSON";
 if (l === "bash" || l === "sh" || l === "shell" || l === "zsh" || l === "powershell" || l === "ps1")
 return "Shell";
 if (l === "py" || l === "python") return "Python";
 if (l === "js" || l === "javascript") return "JavaScript";
 if (l === "ts" || l === "typescript") return "TypeScript";
 if (l === "html") return "HTML";
 if (l === "css" || l === "scss") return "CSS";
 if (l === "sql") return "SQL";
 if (l === "yaml" || l === "yml") return "YAML";
 if (l === "xml") return "XML";
 if (l === "toml" || l === "ini" || l === "conf" || l === "env") return "配置";
 return l;
 }

 /** 可单独复制的代码/提示词围栏 */
 function renderCodeFence(lang, code) {
 const rawLang = String(lang || "").trim() || "text";
 const label = fenceKindLabel(rawLang);
 const body = escapeHtml(String(code || "").replace(/\n$/, ""));
 return (
 `<div class="md-code-block" data-lang="${escapeHtml(rawLang)}">` +
 `<div class="md-code-toolbar">` +
 `<span class="md-code-lang">${escapeHtml(label)}</span>` +
 `<button type="button" class="btn-copy-block" title="仅复制此代码块内容">复制</button>` +
 `</div>` +
 `<pre><code class="lang-${escapeHtml(rawLang)}">${body}</code></pre>` +
 `</div>`
 );
 }

 // ======== Markdown 渲染（安全：先 escape，再结构化） ========
 function renderMarkdown(text) {
 if (!text) return "";
 const raw = String(text).replace(/\r\n/g, "\n");
 const blocks = [];
 // 代码块占位，避免内部被二次处理（含独立复制按钮）
 let src = raw.replace(/```([\w+-]*)\n?([\s\S]*?)```/g, (_, lang, code) => {
 const i = blocks.length;
 blocks.push(renderCodeFence(lang, code));
 return `\u0000B${i}\u0000`;
 });

 // Markdown 图片：![alt](url|path|smb) —— 支持远程 / 本地 / SMB / <url> 包裹
 // 路径里可能含反斜杠，用 [^)] 更宽松
 src = src.replace(
 /!\[([^\]]*)\]\(\s*<?([^)\n]+?)>?(?:\s+(?:"[^"]*"|'[^']*'))?\s*\)/g,
 (_, alt, path) => {
 const raw = decodeMediaRef(path.trim());
 const html = renderMediaHtml(raw, alt, {
 forceImage:
 isHttpUrl(raw) ||
 isSmbRef(raw) ||
 /^\/\//.test(raw) ||
 raw.startsWith("data:image/"),
 });
 if (!html) {
 const href = isHttpUrl(raw) ? raw : toMediaSrc(raw) || raw;
 return `[${alt || path}](${href})`;
 }
 const i = blocks.length;
 blocks.push(html);
 return `\n\u0000B${i}\u0000\n`;
 }
 );

 // 普通链接指向图片/媒体（含 SMB）：[寫真1](url) / [封面](smb://host/share/a.jpg)
 src = src.replace(
 /\[([^\]]*)\]\(\s*<?((?:https?:\/\/|\/\/|smb:\/\/|\\\\|\\)[^)\n]+?|\/api\/workspace\/smb-media\?[^)\s]+)>?(?:\s+(?:"[^"]*"|'[^']*'))?\s*\)/gi,
 (m, label, path) => {
 const raw = decodeMediaRef(path.trim());
 const kind = mediaKind(raw);
 const smb = parseSmbRef(raw);
 const probe = smb ? smb.path : raw;
 const isImg =
 kind === "image" ||
 kind === "video" ||
 IMAGE_EXT.test(pathForExtTest(probe)) ||
 VIDEO_EXT.test(pathForExtTest(probe)) ||
 looksLikeRemoteImageUrl(raw);
 if (!isImg) return m;
 const html = renderMediaHtml(raw, label || raw, {
 forceImage: kind !== "video" && kind !== "audio",
 });
 if (!html) return m;
 const i = blocks.length;
 blocks.push(html);
 return `\n\u0000B${i}\u0000\n`;
 }
 );

 // 单独一行的媒体：本地 / 远程 / SMB UNC / smb://
 src = src.replace(
 /(?:^|\n)[ \t]*((?:smb:\/\/|\\\\|\/\/)[^\s<>"'|]+|(?:https?:\/\/)[^\s<>"'|]+|(?:\.\/)?(?:workspace[\\/])?[^\s<>"'|]+\.(?:png|jpe?g|gif|webp|bmp|svg|avif|mp4|webm|mov|m4v|ogv|mp3|wav)|\/api\/workspace\/smb-media\?[^\s<>"']+)[ \t]*(?=\n|$)/gi,
 (m, path) => {
 const raw = decodeMediaRef(path);
 const force =
 isHttpUrl(raw) || isSmbRef(raw) || /^\/\//.test(raw) || /^\\\\/.test(path);
 const kind = mediaKind(raw, { forceImage: false });
 if (force && kind !== "image" && kind !== "video" && kind !== "audio") {
 const smb = parseSmbRef(raw);
 const probe = smb ? smb.path : raw;
 if (
 !looksLikeRemoteImageUrl(raw) &&
 !IMAGE_EXT.test(pathForExtTest(probe)) &&
 !VIDEO_EXT.test(pathForExtTest(probe))
 ) {
 return m;
 }
 }
 const smb0 = parseSmbRef(raw);
 const html = renderMediaHtml(raw, raw, {
 forceImage:
 force &&
 (kind === "image" ||
 looksLikeRemoteImageUrl(raw) ||
 IMAGE_EXT.test(pathForExtTest(smb0 ? smb0.path : raw))),
 });
 if (!html) return m;
 const i = blocks.length;
 blocks.push(html);
 return `\n\u0000B${i}\u0000\n`;
 }
 );

 // 表格（简单 GFM）
 src = src.replace(/(?:^|\n)((?:\|.+\|\n)+)/g, (m, table) => {
 const rows = table.trim().split("\n").filter(Boolean);
 if (rows.length < 2) return m;
 const isSep = (r) => /^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?$/.test(r.trim());
 if (!isSep(rows[1])) return m;
 const parseRow = (r) =>
 r
 .replace(/^\|/, "")
 .replace(/\|$/, "")
 .split("|")
 .map((c) => c.trim());
 const head = parseRow(rows[0]);
 const body = rows.slice(2).map(parseRow);
 let html = "<table><thead><tr>";
 head.forEach((c) => {
 html += `<th>${inlineMd(escapeHtml(c))}</th>`;
 });
 html += "</tr></thead><tbody>";
 body.forEach((row) => {
 html += "<tr>";
 row.forEach((c) => {
 html += `<td>${inlineMd(escapeHtml(c))}</td>`;
 });
 html += "</tr>";
 });
 html += "</tbody></table>";
 const i = blocks.length;
 blocks.push(html);
 return `\n\u0000B${i}\u0000\n`;
 });

 const lines = src.split("\n");
 const out = [];
 let para = [];

 const flushPara = () => {
 if (!para.length) return;
 const t = para.join("\n").trim();
 if (t) out.push(`<p>${inlineMd(escapeHtml(t)).replace(/\n/g, "<br>")}</p>`);
 para = [];
 };

 let listOpen = null;
 const closeList = () => {
 if (listOpen) {
 out.push(listOpen === "ol" ? "</ol>" : "</ul>");
 listOpen = null;
 }
 };

 for (const line of lines) {
 if (/^\u0000B\d+\u0000$/.test(line.trim())) {
 closeList();
 flushPara();
 out.push(line.trim());
 continue;
 }
 if (/^---+$/.test(line.trim()) || /^\*\*\*+$/.test(line.trim())) {
 closeList();
 flushPara();
 out.push("<hr>");
 continue;
 }
 const h = line.match(/^(#{1,3})\s+(.+)$/);
 if (h) {
 closeList();
 flushPara();
 const level = h[1].length;
 out.push(`<h${level}>${inlineMd(escapeHtml(h[2]))}</h${level}>`);
 continue;
 }
 const bq = line.match(/^>\s?(.*)$/);
 if (bq) {
 closeList();
 flushPara();
 out.push(`<blockquote><p>${inlineMd(escapeHtml(bq[1]))}</p></blockquote>`);
 continue;
 }
 const ul = line.match(/^[-*+]\s+(.+)$/);
 if (ul) {
 flushPara();
 if (listOpen !== "ul") {
 closeList();
 out.push("<ul>");
 listOpen = "ul";
 }
 out.push(`<li>${inlineMd(escapeHtml(ul[1]))}</li>`);
 continue;
 }
 const ol = line.match(/^\d+[.)]\s+(.+)$/);
 if (ol) {
 flushPara();
 if (listOpen !== "ol") {
 closeList();
 out.push("<ol>");
 listOpen = "ol";
 }
 out.push(`<li>${inlineMd(escapeHtml(ol[1]))}</li>`);
 continue;
 }
 if (!line.trim()) {
 closeList();
 flushPara();
 continue;
 }
 closeList();
 para.push(line);
 }
 closeList();
 flushPara();

 let html = out.join("\n");
 html = html.replace(/\u0000B(\d+)\u0000/g, (_, i) => blocks[Number(i)] || "");
 // 合并相邻 blockquote
 html = html.replace(/<\/blockquote>\n<blockquote>/g, "\n");
 return html;
 }

 function isImageHref(url) {
 const raw = decodeMediaRef(url).replace(/&amp;/g, "&");
 if (!raw) return false;
 const smb = parseSmbRef(raw);
 const probe = smb ? smb.path : raw;
 return (
 mediaKind(raw) === "image" ||
 IMAGE_EXT.test(pathForExtTest(probe)) ||
 looksLikeRemoteImageUrl(raw)
 );
 }

 function inlineMd(s) {
 // 输入已 escape；先粗体再斜体，避免 ** 被拆
 // 注意：URL 内的下划线可能被斜体误伤，链接处理放在强调之后、但要先于裸 URL
 let out = s
 .replace(/`([^`]+)`/g, "<code>$1</code>")
 .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
 .replace(/__(.+?)__/g, "<strong>$1</strong>")
 .replace(/\*([^*\n]+)\*/g, "<em>$1</em>")
 // 跳过疑似 URL 内的单个 _word_（两侧像路径字符时不处理）
 .replace(/(^|[^A-Za-z0-9/])_([^_\n]+)_(?![A-Za-z0-9./-])/g, "$1<em>$2</em>");

 // 1) 先处理 Markdown 链接 [文字](url) —— 图片/视频链出预览，普通链出 a
 //    必须在裸 URL 之前，否则 (https://...jpg) 会被先抽走，再被通用链接规则拆坏
 out = out.replace(
 /\[([^\]]*)\]\(\s*<?((?:https?:\/\/|\/\/|smb:\/\/|\\\\)[^)\n]+?|\/api\/workspace\/smb-media\?[^)\s]+)>?(?:\s+(?:"[^"]*"|'[^']*'))?\s*\)/gi,
 (_, label, url) => {
 const raw = decodeMediaRef(url).replace(/&amp;/g, "&").trim();
 const kind = mediaKind(raw);
 if (kind === "image" || isImageHref(raw)) {
 const src = toMediaSrc(raw);
 if (src) {
 return (
 `<a class="md-inline-media" href="${escapeHtml(src)}" target="_blank" rel="noopener noreferrer" title="${label || ""}">` +
 `<img src="${escapeHtml(src)}" alt="${label || "image"}" loading="lazy" decoding="async" referrerpolicy="no-referrer" />` +
 `</a>`
 );
 }
 }
 if (kind === "video") {
 const src = toMediaSrc(raw);
 if (src) {
 return (
 `<figure class="md-media md-video md-inline-video">` +
 `<video src="${escapeHtml(src)}" controls preload="metadata" playsinline></video>` +
 `<figcaption>${escapeHtml(label || raw)}</figcaption></figure>`
 );
 }
 }
 return `<a href="${escapeHtml(toMediaSrc(raw) || raw)}" target="_blank" rel="noopener noreferrer">${label || raw}</a>`;
 }
 );

 // 本地路径链接 [文字](path/to.jpg)
 out = out.replace(
 /\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+(?:"[^"]*"|'[^']*'))?\s*\)/g,
 (m, label, path) => {
 // 已是 HTML 则跳过
 if (path.startsWith("<") || label.includes("<")) return m;
 const raw = decodeMediaRef(path).replace(/&amp;/g, "&");
 if (isImageHref(raw) || mediaKind(raw) === "image") {
 const src = toMediaSrc(raw);
 if (src) {
 return (
 `<a class="md-inline-media" href="${escapeHtml(src)}" target="_blank" rel="noopener noreferrer">` +
 `<img src="${escapeHtml(src)}" alt="${label || raw}" loading="lazy" decoding="async" />` +
 `</a>`
 );
 }
 }
 if (mediaKind(raw) === "video") {
 const src = toMediaSrc(raw);
 if (src) {
 return (
 `<figure class="md-media md-video md-inline-video">` +
 `<video src="${escapeHtml(src)}" controls preload="metadata" playsinline></video>` +
 `<figcaption>${escapeHtml(label || raw)}</figcaption></figure>`
 );
 }
 }
 const href = isHttpUrl(raw) ? raw : toMediaSrc(raw) || raw;
 return `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${label || href}</a>`;
 }
 );

 // 2) 裸图片 URL / 本地媒体路径（不在 markdown 链接里的）
 out = out.replace(
 /(?:^|[\s>，。；、])((?:https?:\/\/|\/\/)[^\s<>"')]+|(?:\.\/)?(?:workspace[\\/])?[^\s<>"'|]+\.(?:png|jpe?g|gif|webp|bmp|svg|avif|mp4|webm|mov|m4v))(?=$|[\s)）<,.;:，。；])/gi,
 (m, path, offset, full) => {
 const before = full.slice(0, offset);
 if (/<[^>]*$/.test(before)) return m;
 // 已在 markdown 链接括号内（理论上已被上面吃掉，双保险）
 if (/\]\(\s*$/.test(before) || /\]\($/.test(before)) return m;
 const raw2 = decodeMediaRef(path).replace(/&amp;/g, "&");
 let kind = mediaKind(raw2);
 if (!kind && (isHttpUrl(raw2) || /^\/\//.test(raw2)) && isImageHref(raw2))
 kind = "image";
 const src = toMediaSrc(raw2);
 if (!src || !kind) return m;
 const prefix = m.slice(0, m.indexOf(path));
 const remoteAttr = isHttpUrl(src) ? ` referrerpolicy="no-referrer"` : "";
 if (kind === "image") {
 return (
 `${prefix}<a class="md-inline-media" href="${escapeHtml(src)}" target="_blank" rel="noopener noreferrer">` +
 `<img src="${escapeHtml(src)}" alt="${escapeHtml(raw2)}" loading="lazy" decoding="async"${remoteAttr} /></a>`
 );
 }
 if (kind === "video") {
 return (
 `${prefix}<figure class="md-media md-video md-inline-video">` +
 `<video src="${escapeHtml(src)}" controls preload="metadata" playsinline></video>` +
 `<figcaption>${escapeHtml(raw2)}</figcaption></figure>`
 );
 }
 return `${prefix}<a href="${escapeHtml(src)}" target="_blank" rel="noopener noreferrer">${escapeHtml(path)}</a>`;
 }
 );

 // 3) 其它裸 http 链接（非图片）
 out = out.replace(/(^|[\s>])(https?:\/\/[^\s<]+)/g, (m, pre, url) => {
 // 已在标签内
 if (pre === ">" && false) return m;
 const raw = decodeMediaRef(url).replace(/&amp;/g, "&");
 if (isImageHref(raw)) {
 const src = toMediaSrc(raw);
 if (src) {
 return (
 `${pre}<a class="md-inline-media" href="${escapeHtml(src)}" target="_blank" rel="noopener noreferrer">` +
 `<img src="${escapeHtml(src)}" alt="image" loading="lazy" decoding="async" referrerpolicy="no-referrer" /></a>`
 );
 }
 }
 return `${pre}<a href="${escapeHtml(raw)}" target="_blank" rel="noopener noreferrer">${escapeHtml(url)}</a>`;
 });

 return out;
 }

 function nearBottom(el, threshold = 80) {
 if (!el) return true;
 return el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
 }

 function scrollMessages(force = false) {
 if (!els.messages) return;
 if (force || state.stickToBottom || nearBottom(els.messages)) {
 els.messages.scrollTop = els.messages.scrollHeight;
 state.stickToBottom = true;
 }
 const btn = document.getElementById("btnScrollBottom");
 if (btn) {
 btn.classList.toggle("hidden", nearBottom(els.messages, 120));
 }
 }

 function formatUsage(usage) {
 if (!usage || typeof usage !== "object") return "";
 const tin = usage.prompt_tokens ?? usage.input_tokens;
 const tout = usage.completion_tokens ?? usage.output_tokens;
 const tot = usage.total_tokens;
 if (tin != null && tout != null) {
 return ` · ${tin}→${tout}` + (tot != null ? `（共${tot}）` : "");
 }
 if (tot != null) return ` · ${tot} tokens`;
 return "";
 }

 function humanCron(cron) {
 if (!cron || typeof cron !== "string") return null;
 const p = cron.trim().split(/\s+/);
 if (p.length < 5) return cron;
 const [min, hour, dom, mon, dow] = p;
 if (dom === "*" && mon === "*" && dow === "*" && /^\d+$/.test(min) && /^\d+$/.test(hour)) {
 return `每天 ${String(hour).padStart(2, "0")}:${String(min).padStart(2, "0")}`;
 }
 if (dom === "*" && mon === "*" && dow === "*" && min.startsWith("*/") && hour === "*") {
 return `每 ${min.slice(2)} 分钟`;
 }
 if (dom === "*" && mon === "*" && dow === "*" && hour.startsWith("*/") && min === "0") {
 return `每 ${hour.slice(2)} 小时`;
 }
 return cron;
 }

 function formatSchedule(t) {
 if (t._schedule_desc) return t._schedule_desc;
 if (t.cron) {
 if (typeof t.cron === "object" && t.cron.description) return t.cron.description;
 if (typeof t.cron === "object" && t.cron.raw) return t.cron.raw;
 const h = humanCron(t.cron);
 return h && h !== t.cron ? `${h}（${t.cron}）` : `cron: ${t.cron}`;
 }
 if (t.interval_seconds) {
 const s = Number(t.interval_seconds);
 if (s % 3600 === 0) return `每 ${s / 3600} 小时`;
 if (s % 60 === 0) return `每 ${s / 60} 分钟`;
 return `每 ${s} 秒`;
 }
 if (t.run_once) return "只跑一次";
 return "—";
 }

 function formatTime(iso) {
 if (!iso) return "未跑过";
 try {
 const d = new Date(iso);
 if (Number.isNaN(d.getTime())) return String(iso);
 return d.toLocaleString();
 } catch {
 return String(iso);
 }
 }

 function setStatus(text, type = "") {
 if (!els.status) return;
 const map = { ok: "check-one", error: "close-one", warn: "attention" };
 const icon = map[type] || "";
 if (icon && text) {
   els.status.innerHTML = _ipkLabel(icon, text, "ipk-xs");
 } else {
   els.status.textContent = text || "";
 }
 els.status.className = "status" + (type ? ` ${type}` : "");
 }

 function syncSendButtonState() {
 if (!els.btnSend || els.btnSend.classList.contains("busy-stop")) return;
 const hasText = !!(els.input && String(els.input.value || "").trim());
 const hasAttach = !!(state.attachments && state.attachments.length);
 els.btnSend.classList.toggle("is-empty", !hasText && !hasAttach);
 }

 let _caretMirror = null;

 function _inputLineHeight(ta) {
  const cs = getComputedStyle(ta);
  const lh = parseFloat(cs.lineHeight);
  if (Number.isFinite(lh) && lh > 0) return lh;
  const fs = parseFloat(cs.fontSize);
  return Number.isFinite(fs) && fs > 0 ? fs * 1.5 : 22;
 }

 function scrollInputCaretIntoView(ta) {
  if (!ta) return;
  const value = ta.value || "";
  const pos = typeof ta.selectionEnd === "number" ? ta.selectionEnd : value.length;
  if (ta.scrollHeight <= ta.clientHeight + 1) {
   ta.scrollTop = 0;
   return;
  }
  if (pos >= value.length) {
   ta.scrollTop = ta.scrollHeight;
   return;
  }
  const cs = getComputedStyle(ta);
  if (!_caretMirror) {
   _caretMirror = document.createElement("div");
   _caretMirror.setAttribute("aria-hidden", "true");
   _caretMirror.style.cssText =
    "position:absolute;left:-9999px;top:0;visibility:hidden;pointer-events:none;" +
    "white-space:pre-wrap;word-wrap:break-word;overflow:hidden;";
   document.body.appendChild(_caretMirror);
  }
  const m = _caretMirror;
  const copy = [
   "boxSizing",
   "width",
   "font",
   "fontSize",
   "fontFamily",
   "fontWeight",
   "fontStyle",
   "letterSpacing",
   "textTransform",
   "textIndent",
   "paddingTop",
   "paddingRight",
   "paddingBottom",
   "paddingLeft",
   "borderTopWidth",
   "borderRightWidth",
   "borderBottomWidth",
   "borderLeftWidth",
   "borderStyle",
   "lineHeight",
   "wordSpacing",
  ];
  for (const p of copy) m.style[p] = cs[p];
  m.style.width = `${ta.clientWidth}px`;
  m.textContent = "";
  m.appendChild(document.createTextNode(value.slice(0, pos)));
  const marker = document.createElement("span");
  marker.textContent = value.charAt(pos) || "\u200b";
  m.appendChild(marker);
  const caretTop = marker.offsetTop;
  const caretH = marker.offsetHeight || _inputLineHeight(ta);
  const caretBottom = caretTop + caretH;
  const viewTop = ta.scrollTop;
  const viewBottom = viewTop + ta.clientHeight;
  if (caretTop < viewTop) {
   ta.scrollTop = Math.max(0, caretTop);
  } else if (caretBottom > viewBottom) {
   ta.scrollTop = caretBottom - ta.clientHeight;
  }
 }

 function autoResize() {
 if (!els.input) return;
 const ta = els.input;
 const atEnd = (ta.selectionEnd ?? 0) >= (ta.value || "").length;
 ta.style.height = "auto";
 // 主流 AI 输入：默认单行高度，随内容增高（手机略矮，避免占满屏）
 let maxH = 200;
 try {
  if (window.matchMedia("(max-width: 640px)").matches) maxH = 120;
  else if (window.matchMedia("(max-width: 900px)").matches) maxH = 160;
  if (document.body.classList.contains("kb-open")) maxH = Math.min(maxH, 100);
 } catch (_) {}
 const minH = 24;
 const next = Math.min(Math.max(ta.scrollHeight, minH), maxH);
 ta.style.height = next + "px";
 // height:"auto" 会把 scrollTop 打回 0；超高后要把光标所在行滚进视口
 const pinCaret = () => {
  if (atEnd || (ta.selectionEnd ?? 0) >= (ta.value || "").length) {
   ta.scrollTop = ta.scrollHeight;
  } else {
   scrollInputCaretIntoView(ta);
  }
 };
 pinCaret();
 requestAnimationFrame(pinCaret);
 syncSendButtonState();
 }

 function setBusy(busy) {
 state.busy = busy;
 if (busy) state._busySince = Date.now();
 document.body.classList.toggle("is-busy", !!busy);
 if (els.input) {
 // 允许边生成边打草稿，但不在 busy 时误触发送以外的快捷键
 els.input.disabled = false;
 els.input.placeholder = busy
 ? "生成中…可继续打草稿"
 : "有什么可以帮你的？";
 }
 if (!els.btnSend) return;
 if (busy) {
 els.btnSend.disabled = false;
 els.btnSend.classList.add("busy-stop");
 els.btnSend.classList.remove("is-empty");
 els.btnSend.title = "停止生成";
 els.btnSend.setAttribute("aria-label", "停止生成");
 const label = els.btnSend.querySelector(".btn-send-label");
 if (label) label.textContent = "停止";
 } else {
 els.btnSend.disabled = false;
 els.btnSend.classList.remove("busy-stop");
 els.btnSend.title = "发送（Enter）";
 els.btnSend.setAttribute("aria-label", "发送");
 const label = els.btnSend.querySelector(".btn-send-label");
 if (label) label.textContent = "发送";
 if (typeof L.syncSendButtonState === "function") L.syncSendButtonState();
 }
 }

 /**
  * 用户点「停止」：取消服务端后台 run + 断开本地监听。
  * 切换会话请用 detachWatchOnly（不取消服务端）。
  */
 function cancelRequest() {
 const sid = state.sessionId;
 const runMeta = sid && state.chatRuns ? state.chatRuns[sid] : null;
 const runId = (runMeta && runMeta.runId) || state.activeRunId;
 if (runId && typeof L.api === "function") {
  L.api(`/api/chat/runs/${encodeURIComponent(runId)}/cancel`, {
   method: "POST",
   body: {},
  }).catch(() => {});
 }
 if (sid && state.chatRuns) delete state.chatRuns[sid];
 if (typeof L.persistChatRuns === "function") L.persistChatRuns();
 state.activeRunId = null;
 state.detachWatch = false;
 const ctrl = state.abortController;
 if (ctrl && !ctrl.signal.aborted) {
 ctrl.abort();
 state.abortController = null;
 }
 if (state.phaseTimer) {
 clearInterval(state.phaseTimer);
 state.phaseTimer = null;
 }
 showToast("已停止生成", "info");
 setBusy(false);
 removeTyping();
 if (typeof L.loadSessions === "function") L.loadSessions().catch(() => {});
 }

 /** 只断开当前页监听，服务端继续生成 */
 function detachWatchOnly() {
 state.detachWatch = true;
 const ctrl = state.abortController;
 if (ctrl && !ctrl.signal.aborted) {
  try {
   ctrl.abort();
  } catch (_) {}
 }
 state.abortController = null;
 state.activeRunId = null;
 if (state.phaseTimer) {
  clearInterval(state.phaseTimer);
  state.phaseTimer = null;
 }
 removeTyping();
 setBusy(false);
 }

 function lastUserPromptText() {
 try {
  const nodes = els.messages?.querySelectorAll(".msg.user .bubble");
  if (!nodes || !nodes.length) return "";
  return String(nodes[nodes.length - 1].textContent || "").trim();
 } catch (_) {
  return "";
 }
 }

 function waitingJobLabel() {
 const q = lastUserPromptText();
 if (/工单|任务单|订单/i.test(q)) return "正在查询工单";
 if (/收款|付款|账单|入账/.test(q)) return "正在查询收款";
 if (/库存|进货|出货|物料/.test(q)) return "正在查询库存";
 if (/客户/.test(q)) return "正在查询客户";
 if (/天气|潮汐|日出/.test(q)) return "正在查询天气";
 if (/快递|物流|运单/.test(q)) return "正在查询快递";
 if (/下载|种子|qb|做种/i.test(q)) return "正在查看下载任务";
 if (/知识库|流程|怎么做|规定|sop/i.test(q)) return "正在检索知识库";
 if (/记住|记得|偏好/.test(q)) return "正在处理记忆";
 if (/文件|工作区|nas/i.test(q)) return "正在查看文件";
 return "模型正在处理你的问题";
 }

 function updateTypingPhase(elapsed, detail) {
 const phaseEl = document.getElementById("typingPhase");
 if (!phaseEl) return;
 const panel = document.getElementById("toolActivity");
 const hasToolSteps =
  panel &&
  !panel.classList.contains("hidden") &&
  panel.querySelector(".tool-activity-step");
 let text;
 if (detail) {
 text = detail;
 } else if (hasToolSteps) {
 text = phaseEl.textContent || `${waitingJobLabel()}（${elapsed}s）`;
 } else if (elapsed < 2) {
 text = "已收到，正在发给模型…";
 } else {
 text = `${waitingJobLabel()}（${elapsed}s）`;
 }
 phaseEl.textContent = text;

 const st = document.getElementById("toolActivityStatus");
 if (panel && st && !panel.classList.contains("hidden")) {
 if (detail && /工具||运行/.test(detail)) {
 st.textContent = detail.replace(/^\s*/, "");
 } else if (!st.dataset.locked) {
 st.textContent = `${elapsed}s`;
 }
 }
 }

 const SIDEBAR_COLLAPSED_KEY = "eva.sidebarCollapsed";

 function isNarrowSidebar() {
  try {
   return !!(window.matchMedia && window.matchMedia("(max-width: 900px)").matches);
  } catch (_) {
   return false;
  }
 }

 function isSidebarOpen() {
  if (isNarrowSidebar()) return document.body.classList.contains("sidebar-open");
  return !document.body.classList.contains("sidebar-collapsed");
 }

 function closeMobileSidebar() {
  if (isNarrowSidebar()) setSidebarOpen(false);
 }

 function setSidebarOpen(open) {
  const want = !!open;
  const btn = $("btnMenu");
  const scrim = $("sidebarScrim");
  if (isNarrowSidebar()) {
   document.body.classList.toggle("sidebar-open", want);
   document.body.classList.remove("sidebar-collapsed");
   if (scrim) scrim.classList.toggle("hidden", !want);
  } else {
   document.body.classList.toggle("sidebar-collapsed", !want);
   document.body.classList.remove("sidebar-open");
   if (scrim) scrim.classList.add("hidden");
   try {
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, want ? "0" : "1");
   } catch (_) {}
  }
  if (btn) {
   btn.setAttribute("aria-expanded", want ? "true" : "false");
   btn.setAttribute("title", want ? "关闭菜单" : "打开菜单");
   btn.setAttribute("aria-label", want ? "关闭菜单" : "打开菜单");
  }
 }

 function initSidebarLayout() {
  const apply = () => {
   if (isNarrowSidebar()) {
    setSidebarOpen(false);
    return;
   }
   let collapsed = false;
   try {
    collapsed = localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1";
   } catch (_) {}
   setSidebarOpen(!collapsed);
  };
  apply();
  try {
   const mq = window.matchMedia("(max-width: 900px)");
   const onChange = () => apply();
   if (typeof mq.addEventListener === "function") mq.addEventListener("change", onChange);
   else if (typeof mq.addListener === "function") mq.addListener(onChange);
  } catch (_) {}
 }

 function clearMessages() {
 els.messages.innerHTML = "";
 setHomeHeroMode(false);
 }

 /** 空会话主页：居中标题 + 输入框；有消息后退出 */
 function setHomeHeroMode(on) {
  const active = !!on;
  document.body.classList.toggle("home-hero", active);
  const main = document.querySelector("main.main");
  if (main) main.classList.toggle("home-hero", active);
  const head = document.getElementById("homeHeroHead");
  if (head) head.hidden = !active;
  const chips = document.getElementById("homeHeroChips");
  if (chips) {
   chips.classList.toggle("hidden", !active);
   if (!active) chips.innerHTML = "";
  }
 }

 const QUICK_PROMPTS = [
 {
  label: "现在几点",
  text: "现在几点了？",
  icon: "time",
 },
 {
  label: "你有什么技能",
  text: "你有什么技能",
  icon: "puzzle",
 },
 {
  label: "记一条偏好",
  text: "请记住：以后用中文简短回复。",
  icon: "brain",
 },
 {
  label: "今天的任务",
  text: "当前有哪些定时任务？最近跑得怎么样？",
  icon: "alarm-clock",
 },
 ];

 const PRODUCT_NAME = "EVA System OS";

 function hasChatLlm() {
  if (typeof state.llmConfigured === "boolean") return state.llmConfigured;
  const llms = state.config && state.config.llms;
  if (Array.isArray(llms) && llms.length) {
   return llms.some(
    (x) =>
     x &&
     x.enabled !== false &&
     String(x.model || "").trim() &&
     String(x.base_url || "").trim() &&
     (x.api_key_set || x.api_key)
   );
  }
  return false;
 }

 async function goAddLlm() {
  try {
   if (typeof L.openConfig === "function") await L.openConfig("llm");
   if (typeof L.openLlmEditor === "function") L.openLlmEditor({});
  } catch (_) {
   if (typeof L.openConfig === "function") L.openConfig("llm");
  }
 }

 function refreshHomeHero() {
  if (!document.body.classList.contains("home-hero")) return;
  const ready = hasChatLlm();
  const titleEl = document.getElementById("homeHeroTitle");
  const subEl = document.getElementById("homeHeroSub");
  const setup = document.getElementById("homeSetup");
  const chips = document.getElementById("homeHeroChips");
  if (titleEl) titleEl.textContent = PRODUCT_NAME;
  if (subEl) {
   subEl.textContent = ready
    ? "有什么可以帮你的？"
    : "先添加一个对话模型，才能开始聊天。";
   subEl.removeAttribute("title");
  }
  if (setup) setup.classList.toggle("hidden", ready);
  if (chips) chips.classList.toggle("hidden", !ready);
  if (els.input) {
   els.input.placeholder = ready
    ? "有什么可以帮你的？"
    : "添加模型后就可以聊天";
  }
  if (els.sessionHint && !state.sessionId) {
   els.sessionHint.textContent = ready
    ? "输入消息开始对话"
    : "先添加对话模型";
  }
  if (typeof L.hydrateIconPark === "function") {
   try {
    L.hydrateIconPark(document.getElementById("homeHeroHead"));
    L.hydrateIconPark(setup);
    L.hydrateIconPark(chips);
   } catch (_) {}
  }
 }

 function showEmpty() {
 setHomeHeroMode(true);
 els.messages.innerHTML = `<div class="empty" id="emptyStage"></div>`;
 const wrap = document.getElementById("homeHeroChips");
 if (wrap) {
  wrap.innerHTML = "";
  for (const p of QUICK_PROMPTS) {
   const btn = document.createElement("button");
   btn.type = "button";
   btn.className = "empty-chip home-hero-chip";
   btn.title = p.text;
   if (p.icon) {
    btn.innerHTML = `${_ipk(p.icon, "ipk-xs")} <span>${escapeHtml(p.label)}</span>`;
   } else {
    btn.textContent = p.label;
   }
   btn.addEventListener("click", () => {
    if (state.busy) return;
    if (!hasChatLlm()) {
     if (typeof L.goAddLlm === "function") L.goAddLlm();
     return;
    }
    els.input.value = p.text;
    autoResize();
    els.input.focus();
    if (typeof L.send === "function") L.send();
   });
   wrap.appendChild(btn);
  }
 }
 refreshHomeHero();
 }

 async function copyText(text, btn) {
 try {
 await navigator.clipboard.writeText(text || "");
 if (btn) {
 const iconOnly = !!btn.querySelector(".ipk");
 const oldTitle = btn.getAttribute("title") || "";
 btn.classList.add("is-copied");
 btn.setAttribute("title", "已复制");
 if (!iconOnly) {
 const old = btn.dataset.label || btn.textContent;
 btn.dataset.label = old;
 btn.textContent = "已复制";
 setTimeout(() => {
 btn.textContent = old;
 btn.classList.remove("is-copied");
 if (oldTitle) btn.setAttribute("title", oldTitle);
 }, 1200);
 } else {
 setTimeout(() => {
 btn.classList.remove("is-copied");
 if (oldTitle) btn.setAttribute("title", oldTitle);
 }, 1200);
 }
 }
 setStatus("已复制到剪贴板", "ok");
 } catch {
 setStatus("复制失败（浏览器权限）", "error");
 showToast("复制失败，请检查权限", "error");
 }
 }

 /** 从代码块 / 提示词块提取纯文本（不含工具栏） */
 function extractBlockCopyText(block) {
 if (!block) return "";
 const code = block.querySelector("pre code");
 if (code) return code.textContent || "";
 // 引用块等：去掉工具按钮后取文本
 const clone = block.cloneNode(true);
 clone
 .querySelectorAll(".btn-copy-block, .md-code-toolbar")
 .forEach((n) => n.remove());
 return (clone.textContent || "").replace(/\n{3,}/g, "\n\n").trim();
 }

 /** 气泡内「复制代码块」事件委托（整段复制仍用 role-row 按钮） */
 function bindBubbleCopyDelegation() {
 if (!els.messages || els.messages.dataset.copyBlockBound === "1") return;
 els.messages.dataset.copyBlockBound = "1";
 els.messages.addEventListener("click", (e) => {
 const t = e.target;
 if (!(t instanceof Element)) return;
 const btn = t.closest(".btn-copy-block");
 if (!btn || !els.messages.contains(btn)) return;
 e.preventDefault();
 e.stopPropagation();
 const block = btn.closest(".md-code-block, .md-quote-copy");
 const text = extractBlockCopyText(block);
 if (!text) {
 showToast("没有可复制的内容", "warn");
 return;
 }
 copyText(text, btn);
 });
 }
 bindBubbleCopyDelegation();

 // ==================== 消息渲染（Markdown 增强） ====================
 function assistantDisplayName() {
 const fromCfg = String(state.config?.agent?.name || "").trim();
 if (fromCfg) return fromCfg;
 const fromDom = String(document.getElementById("agentName")?.textContent || "").trim();
 if (fromDom && fromDom !== "Eva") return fromDom;
 return fromDom || "Eva";
 }

 function assistantAvatarLetter() {
 const n = assistantDisplayName();
 const ch = Array.from(n)[0] || "E";
 return /[a-z]/i.test(ch) ? ch.toUpperCase() : ch;
 }

 function roleAvatarLetter(role) {
 if (role === "user") return "你";
 if (role === "assistant") return assistantAvatarLetter();
 return "系";
 }

 function _actionIconBtn(cls, title, iconName) {
 const btn = document.createElement("button");
 btn.type = "button";
 btn.className = cls + " msg-icon-btn";
 btn.title = title;
 btn.setAttribute("aria-label", title);
 btn.innerHTML = _ipk(iconName, "ipk-sm") || title;
 return btn;
 }

 function buildMsgActions(role, clean, extra) {
 const actions = document.createElement("div");
 actions.className = "msg-actions";
 const retryPayload = extra?.retryMessage || clean;

 if (role === "assistant" || role === "user") {
 const copyBtn = _actionIconBtn(
 "btn-copy",
 role === "assistant" ? "复制整段回复" : "复制消息",
 "copy"
 );
 copyBtn.addEventListener("click", (e) => {
 e.stopPropagation();
 copyText(clean || "", copyBtn);
 });
 actions.appendChild(copyBtn);
 }
 if (role === "assistant" && typeof L.mountSpeakControls === "function") {
 L.mountSpeakControls(actions, () => clean || "");
 }
 if (role === "user") {
 const editBtn = _actionIconBtn("btn-edit-turn", "改这一句并重新发送", "edit");
 editBtn.addEventListener("click", (e) => {
 e.stopPropagation();
 if (typeof L.editLastUser === "function") L.editLastUser(clean);
 });
 actions.appendChild(editBtn);
 }
 if (role === "assistant") {
 const retryBtn = _actionIconBtn("btn-retry", "用上一句重新生成", "refresh");
 retryBtn.addEventListener("click", (e) => {
 e.stopPropagation();
 if (state.busy) return;
 if (typeof L.retryLastTurn === "function") L.retryLastTurn();
 });
 actions.appendChild(retryBtn);
 }
 if ((role === "assistant" || role === "user") && !extra?.ephemeral) {
 const delBtn = _actionIconBtn("btn-del-msg", "删除这条消息", "delete");
 delBtn.addEventListener("click", (e) => {
 e.stopPropagation();
 const wrap = actions.closest(".msg");
 if (typeof L.deleteChatMessage === "function") L.deleteChatMessage(wrap);
 });
 actions.appendChild(delBtn);
 }
 if (role === "system" && extra?.retry) {
 const retryBtn = _actionIconBtn("btn-retry", "重试", "refresh");
 retryBtn.addEventListener("click", () => {
 if (state.busy) return;
 els.input.value = retryPayload;
 autoResize();
 els.input.focus();
 if (typeof L.send === "function") L.send();
 });
 actions.appendChild(retryBtn);
 }
 if (typeof L.hydrateIconPark === "function") {
 try {
 L.hydrateIconPark(actions);
 } catch (_) {}
 }
 return actions;
 }

 function choiceLabel(field, value) {
  const v = String(value ?? "");
  const hit = (field.options || []).find((o) => String(o.value) === v);
  return (hit && hit.label) || v;
 }

 function formatAskFormReply(form, values) {
  if (form && form.kind === "integ") {
   const lab = String(form.title || "连接信息").replace(/^「|」还没配好$/g, "");
   return "已填写「" + (lab || "这项能力") + "」的连接信息";
  }
  const skip = { 补充: 1, 补充说明: 1, 请选择: 1, 单选: 1, 多选: 1 };
  const bits = [];
  (form?.fields || []).forEach((field) => {
   if (!field || !field.id) return;
   const raw = values[field.id];
   const type = field.type || "text";
   if (field.secret || type === "password") {
    if (raw == null || String(raw).trim() === "") return;
    const label = String(field.label || field.id).trim();
    bits.push((label || "密钥") + " 已填写");
    return;
   }
   if (type === "multi") {
    const picked = Array.isArray(raw)
     ? raw.map(String)
     : String(raw || "")
        .split(/[,，、]/)
        .map((s) => s.trim())
        .filter(Boolean);
    if (!picked.length) return;
    const labels = picked.map((v) => choiceLabel(field, v)).filter(Boolean);
    const name = String(field.label || "").trim();
    const joined = labels.join("、");
    bits.push(name && !skip[name] ? name + " " + joined : joined);
    return;
   }
   if (raw == null || String(raw).trim() === "") return;
   let text = String(raw).trim();
   if (type === "choice" || type === "single") {
    bits.push(choiceLabel(field, text));
    return;
   }
   const label = String(field.label || "").trim();
   bits.push(label && !skip[label] ? label + " " + text : text);
  });
  return bits.join("，").trim();
 }

 function unlockAskForm(wrap) {
  if (!wrap) return;
  wrap.classList.remove("is-done");
  wrap.querySelectorAll("button, input, textarea").forEach((el) => {
   el.disabled = false;
  });
 }

 function cancelAskForm(form, wrap) {
  if (state.busy || (wrap && wrap.classList.contains("is-done"))) return;
  if (wrap) {
   wrap.classList.add("is-done");
   wrap.querySelectorAll("button, input, textarea").forEach((el) => {
    el.disabled = true;
   });
  }
  if (typeof L.send === "function") {
   L.send({
    message: "取消",
    metadata: { form_reply: { _cancel: true } },
   });
  }
 }

 function submitAskForm(form, values, wrap) {
  if (state.busy) return;
  if (form.kind === "integ") {
   const filled = (form.fields || []).some((f) => {
    const v = values[f.id];
    return v != null && String(v).trim() !== "";
   });
   if (!filled) {
    showToast("请先填一项", "warn");
    return;
   }
   const text = formatAskFormReply(form, values);
   if (wrap) {
    wrap.classList.add("is-done");
    wrap.querySelectorAll("button, input, textarea").forEach((el) => {
     el.disabled = true;
    });
   }
   if (typeof L.send === "function") {
    L.send({ message: text, metadata: { form_reply: values } });
   }
   return;
  }
  if (form.kind === "deputy") {
   const pick = String(values.choice || "");
   const useDeputy = pick === "deputy" || pick === "1";
   if (wrap) wrap.classList.add("is-done");
   if (typeof L.send === "function") {
    L.send({
     message: useDeputy ? "用副模型做上一件" : "用主模型继续上一件",
     metadata: { use_deputy: useDeputy, skip_deputy: !useDeputy },
    });
   }
   return;
  }
  let text = formatAskFormReply(form, values);
  if (!text) {
   showToast("选一项，或写一点补充", "warn");
   return;
  }
  const pending = String(form.pending_user || "").trim();
  if (pending) text = "原需求：" + pending + "\n" + text;
  if (wrap) {
   wrap.classList.add("is-done");
   wrap.querySelectorAll("button, input, textarea").forEach((el) => {
    el.disabled = true;
   });
  }
  if (typeof L.send === "function") {
   L.send({ message: text, metadata: { form_reply: values } });
  }
 }

 function renderIntegNeededForm(form) {
  const wrap = document.createElement("div");
  wrap.className = "ask-form";
  const title = String(form.title || "").trim() || "还没配好";
  const hint = String(form.prompt || "").trim();
  const h = document.createElement("div");
  h.className = "ask-form-title";
  h.textContent = title;
  wrap.appendChild(h);
  if (hint && hint !== title) {
   const p = document.createElement("div");
   p.className = "ask-form-hint";
   p.textContent = hint;
   wrap.appendChild(p);
  }
  const bar = document.createElement("div");
  bar.className = "ask-form-bar";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn primary";
  btn.textContent = String(form.submit_label || "去填写");
  btn.addEventListener("click", async () => {
   const iid = String(form.integration_id || "").trim();
   try {
    if (typeof L.openConfig === "function") await L.openConfig("integrations");
    if (typeof L.loadIntegrations === "function") {
     await L.loadIntegrations({ soft: true });
    }
    if (iid && typeof L.openIntegrationEditor === "function") {
     L.openIntegrationEditor(iid);
    }
   } catch (_) {
    if (typeof L.openConfig === "function") L.openConfig("integrations");
   }
  });
  bar.appendChild(btn);
  if (form.cancellable !== false) {
   const cancel = document.createElement("button");
   cancel.type = "button";
   cancel.className = "ask-form-cancel";
   cancel.textContent = "取消";
   cancel.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    cancelAskForm(form, wrap);
   });
   bar.appendChild(cancel);
  }
  wrap.appendChild(bar);
  return wrap;
 }

 function renderAskForm(form) {
  if (!form || typeof form !== "object") return null;
  if (form.kind === "integ" && !(form.fields && form.fields.length)) {
   return renderIntegNeededForm(form);
  }
  if (!Array.isArray(form.fields) || !form.fields.length) return null;
  const wrap = document.createElement("div");
  wrap.className = "ask-form";
  wrap.addEventListener("mousedown", (e) => e.stopPropagation());
  wrap.addEventListener("click", (e) => e.stopPropagation());
  wrap.addEventListener("keydown", (e) => e.stopPropagation());
  wrap.addEventListener("keyup", (e) => e.stopPropagation());

  const title = String(form.title || "").trim();
  const hint = String(form.prompt || "").trim();
  if (title) {
   const h = document.createElement("div");
   h.className = "ask-form-title";
   h.textContent = title;
   wrap.appendChild(h);
  }
  if (hint && hint !== title) {
   const p = document.createElement("div");
   p.className = "ask-form-hint";
   p.textContent = hint;
   wrap.appendChild(p);
  }
  const howto = String(form.howto || "").trim();
  if (howto) {
   const box = document.createElement("div");
   box.className = "ask-form-howto";
   howto.split("\n").forEach((line) => {
    const d = document.createElement("div");
    d.textContent = line;
    box.appendChild(d);
   });
   wrap.appendChild(box);
  }

  const values = {};
  const isDeputy = form.kind === "deputy";
  let hasInputs = false;

  const fieldFilled = (f) => {
   const v = values[f.id];
   if (Array.isArray(v)) return v.length > 0;
   return String(v || "").trim() !== "";
  };

  const trySubmit = () => {
   if (state.busy || wrap.classList.contains("is-done")) return;
   const otherFilled = ["other", "note"].some((id) => {
    const v = values[id];
    return v != null && String(v).trim() !== "";
   });
   const missing = (form.fields || []).filter(
    (f) => f.required && f.id !== "other" && !fieldFilled(f)
   );
   if (missing.length && !otherFilled) {
    showToast("请先选一项或填一下，或写在「其他」", "warn");
    return;
   }
   submitAskForm(form, values, wrap);
  };

  const renderChips = (field, multi) => {
   const block = document.createElement("div");
   block.className = "ask-form-block";
   const name = String(field.label || "").trim();
   if (name && name !== "请选择") {
    const cap = document.createElement("div");
    cap.className = "ask-form-label";
    cap.textContent = name + (multi ? "（可多选）" : "");
    block.appendChild(cap);
   }
   const bar = document.createElement("div");
   bar.className = "ask-form-bar";
   if (multi) values[field.id] = [];
   (field.options || []).forEach((opt) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "ask-chip" + (multi ? " is-multi" : "");
    btn.textContent = opt.label || String(opt.value || "");
    btn.addEventListener("mousedown", (e) => e.preventDefault());
    btn.addEventListener("click", (e) => {
     e.preventDefault();
     e.stopPropagation();
     if (state.busy || wrap.classList.contains("is-done")) return;
     const val = String(opt.value);
     if (multi) {
      const cur = Array.isArray(values[field.id]) ? values[field.id].slice() : [];
      const i = cur.indexOf(val);
      if (i >= 0) cur.splice(i, 1);
      else cur.push(val);
      values[field.id] = cur;
      btn.classList.toggle("is-selected", i < 0);
     } else {
      values[field.id] = val;
      bar.querySelectorAll(".ask-chip").forEach((b) => b.classList.remove("is-selected"));
      btn.classList.add("is-selected");
      if (isDeputy) submitAskForm(form, values, wrap);
     }
    });
    bar.appendChild(btn);
   });
   block.appendChild(bar);
   wrap.appendChild(block);
  };

  form.fields.forEach((field) => {
   if (!field || !field.id) return;
   const type = field.type || "text";
   if (type === "choice" || type === "single") {
    renderChips(field, false);
    return;
   }
   if (type === "multi") {
    renderChips(field, true);
    return;
   }
   hasInputs = true;
   const lab = document.createElement("label");
   lab.className = "ask-form-field";
   const cap = document.createElement("span");
   cap.textContent = field.label || field.id;
   lab.appendChild(cap);
   const input =
    type === "textarea"
     ? document.createElement("textarea")
     : document.createElement("input");
   if (input.tagName === "INPUT") {
    input.type =
     type === "password" || field.secret ? "password" : "text";
   } else input.rows = 3;
   input.placeholder = field.placeholder || "点这里输入";
   input.autocomplete = "off";
   if (input.type === "password") input.autocomplete = "new-password";
   input.addEventListener("focus", (e) => e.stopPropagation());
   input.addEventListener("input", () => {
    values[field.id] = input.value;
   });
   input.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter" && input.tagName === "INPUT" && !e.shiftKey) {
     e.preventDefault();
     trySubmit();
    }
   });
   lab.appendChild(input);
   wrap.appendChild(lab);
  });

  if (!isDeputy) {
   const actions = document.createElement("div");
   actions.className = "ask-form-actions";
   if (form.cancellable !== false) {
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "ask-form-cancel";
    cancel.textContent = "取消";
    cancel.addEventListener("click", (e) => {
     e.preventDefault();
     e.stopPropagation();
     cancelAskForm(form, wrap);
    });
    actions.appendChild(cancel);
   }
   const submit = document.createElement("button");
   submit.type = "button";
   submit.className = "ask-form-submit";
   submit.textContent = form.submit_label || "发送";
   submit.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    trySubmit();
   });
   actions.appendChild(submit);
   wrap.appendChild(actions);
  }

  requestAnimationFrame(() => {
   const first = wrap.querySelector("input, textarea");
   if (first && !isDeputy) {
    try {
     first.focus({ preventScroll: true });
    } catch (_) {
     first.focus();
    }
   }
  });
  return wrap;
 }

 function appendMessage(role, content, extra = null) {
 const empty = els.messages.querySelector(".empty");
 if (empty) empty.remove();
 // 有实际消息后：退出居中主页，输入框回到底部
 setHomeHeroMode(false);

 // 助手正文：去掉思考块 + 误贴的上传/裸文件名图堆（用户气泡已有预览）
 let clean = role === "assistant" ? stripThinking(content) : content || "";
 if (role === "assistant" && clean) {
 clean = clean
 // 任意位置的 uploads 图（用户气泡已有预览）；生成图/视频要保留
 .replace(/!\[[^\]]*\]\((?:workspace\/)?uploads\/[^)\s]+\)\s*/gi, "")
 .replace(/\n{3,}/g, "\n\n")
 .trimEnd();
 }
 const wrap = document.createElement("div");
 wrap.className = `msg ${role}`;
 if (extra?.msgId) wrap.dataset.msgId = extra.msgId;
 if (extra?.ephemeral) wrap.dataset.ephemeral = "1";
 const roleLabel =
 role === "user" ? "你" : role === "assistant" ? assistantDisplayName() : "系统";

 const tsIso = extra?.timestamp || (role !== "system" ? new Date().toISOString() : "");
 const timestamp = tsIso ? (formatMsgTime || timeAgo)(tsIso) : "";

 const main = document.createElement("div");
 main.className = "msg-main";

 if (role !== "system") {
 const av = document.createElement("div");
 av.className = "msg-avatar";
 av.setAttribute("aria-hidden", "true");
 av.textContent = roleAvatarLetter(role);
 main.appendChild(av);
 }

 const col = document.createElement("div");
 col.className = "msg-col";

 const actions = buildMsgActions(role, clean, extra);

 const roleRow = document.createElement("div");
 roleRow.className = "role-row";
 const roleEl = document.createElement("div");
 roleEl.className = "role";
 roleEl.textContent = roleLabel;
 roleRow.appendChild(roleEl);
 const usedDeputy = !!(extra?.used_deputy || extra?.metadata?.used_deputy);
 const llmName = String(extra?.llm_name || extra?.metadata?.llm_name || "").trim();
 if (role === "assistant" && (usedDeputy || llmName)) {
  const tag = document.createElement("span");
  tag.className = "msg-llm-tag" + (usedDeputy ? " is-deputy" : "");
  tag.textContent = usedDeputy
   ? "副模型" + (llmName ? " · " + llmName : "")
   : llmName;
  roleRow.appendChild(tag);
 }

 const bubble = document.createElement("div");
 bubble.className =
 role === "assistant"
 ? "bubble md"
 : role === "system"
 ? "bubble"
 : "bubble";
 if (role === "assistant") {
 bubble.innerHTML = renderMarkdown(clean);
 } else {
 bubble.textContent = clean;
 }

 col.appendChild(roleRow);
 main.appendChild(col);
 wrap.appendChild(main);

 const toolCalls = normalizeToolCalls((extra && extra.tool_calls) || []).filter(
  (t) => (t && t.name) !== "ask_user"
 );

 // 媒体画廊：用户上传 或 助手「新生成」；助手侧不展示 uploads/
 const galleryPaths = [];
 const isUpload = (p) => {
 const s = String(p || "")
 .replace(/\\/g, "/")
 .replace(/\/+/g, "/")
 .replace(/^\.\//, "")
 .toLowerCase();
 return s.startsWith("uploads/") || s.includes("/uploads/");
 };
 const pushGallery = (p) => {
 if (!p || galleryPaths.includes(p)) return;
 if (role === "assistant" && isUpload(p)) return;
 galleryPaths.push(p);
 };
 if (Array.isArray(extra?.media_paths)) {
 for (const p of extra.media_paths) pushGallery(p);
 }
 if (Array.isArray(extra?.attachments)) {
 for (const a of extra.attachments) pushGallery(a?.path);
 }
 if (role === "assistant" && typeof extractMediaPaths === "function") {
 for (const p of extractMediaPaths(toolCalls, extra)) {
 // 正文 markdown 已含路径时不重复进画廊
 if (p && !(clean || "").includes(p)) pushGallery(p);
 }
 }
 if (galleryPaths.length) {
 const gallery = document.createElement("div");
 gallery.className =
 "msg-media-gallery" + (role === "user" ? " user-upload" : "");
 const label = document.createElement("div");
 label.className = "msg-media-label";
 label.textContent =
 role === "user"
 ? `上传（${galleryPaths.length}）`
 : `生成的文件（${galleryPaths.length}）`;
 gallery.appendChild(label);
 const row = document.createElement("div");
 row.className = "msg-media-row";
 for (const p of galleryPaths) {
 const kind = mediaKind(p);
 const src = toMediaSrc(p);
 if (!src) continue;
 const card = document.createElement("div");
 card.className = "msg-media-card";
 if (kind === "image") {
 const a = document.createElement("a");
 a.href = src;
 a.target = "_blank";
 a.rel = "noopener noreferrer";
 const img = document.createElement("img");
 img.src = src;
 img.alt = p;
 img.loading = "lazy";
 a.appendChild(img);
 card.appendChild(a);
 } else if (kind === "video") {
 const v = document.createElement("video");
 v.src = src;
 v.controls = true;
 v.preload = "metadata";
 v.playsInline = true;
 card.appendChild(v);
 } else {
 const link = document.createElement("a");
 link.className = "msg-media-file";
 link.href = src;
 link.target = "_blank";
 link.rel = "noopener noreferrer";
 link.textContent = "" + (p.split("/").pop() || p);
 card.appendChild(link);
 }
 const cap = document.createElement("div");
 cap.className = "msg-media-cap";
 cap.textContent = p;
 card.appendChild(cap);
 row.appendChild(card);
 }
 if (row.children.length) {
 gallery.appendChild(row);
 col.appendChild(gallery);
 }
 }

 const formSpec = extra?.form || extra?.metadata?.form || null;
 const formTitle = String(formSpec?.title || "").trim();
 const formHint = String(formSpec?.prompt || "").trim();
 const hideDupBubble =
  !!formSpec &&
  (!clean ||
   clean === formTitle ||
   clean === formHint ||
   clean === formTitle + "\n" + formHint ||
   clean === formHint + "\n" + formTitle);
 if (!(role === "assistant" && hideDupBubble)) {
  col.appendChild(bubble);
 }

 if (role === "assistant" && formSpec && typeof formSpec === "object") {
  const formEl = renderAskForm(formSpec);
  if (formEl) col.appendChild(formEl);
 } else if (role === "assistant" && extra?.ask_deputy) {
  const bar = document.createElement("div");
  bar.className = "ask-form-bar";
  const yes = document.createElement("button");
  yes.type = "button";
  yes.className = "btn primary";
  yes.textContent = "用副模型做这一件";
  yes.addEventListener("click", () => {
   if (state.busy) return;
   if (typeof L.send === "function") {
    L.send({
     message: "用副模型做上一件",
     metadata: { use_deputy: true },
    });
   }
  });
  const no = document.createElement("button");
  no.type = "button";
  no.className = "btn";
  no.textContent = "继续用主模型";
  no.addEventListener("click", () => {
   if (state.busy) return;
   if (typeof L.send === "function") {
    L.send({
     message: "用主模型继续上一件",
     metadata: { skip_deputy: true },
    });
   }
  });
  bar.appendChild(yes);
  bar.appendChild(no);
  col.appendChild(bar);
 }

 if (toolCalls.length) {
 const toolsBar = renderToolsBar(toolCalls);
 if (toolsBar) col.appendChild(toolsBar);
 }

 const meta = document.createElement("div");
 meta.className = "msg-foot";
 if (actions && actions.childNodes.length) meta.appendChild(actions);
 if (timestamp) {
 const t = document.createElement("span");
 t.className = "msg-time";
 t.textContent = timestamp;
 t.title = extra?.timestamp
 ? new Date(extra.timestamp).toLocaleString()
 : new Date().toLocaleString();
 meta.appendChild(t);
 }
 col.appendChild(meta);

 els.messages.appendChild(wrap);
 refreshTurnActions();
 scrollMessages(true);
 return wrap;
 }

 function refreshTurnActions() {
 const root = els.messages;
 if (!root) return;
 root.querySelectorAll(".msg.user").forEach((el) => el.classList.remove("is-last-user"));
 root.querySelectorAll(".msg.assistant").forEach((el) =>
 el.classList.remove("is-last-assistant")
 );
 const users = [...root.querySelectorAll(".msg.user")];
 const asst = [...root.querySelectorAll(".msg.assistant:not(.typing-msg)")];
 if (users.length) users[users.length - 1].classList.add("is-last-user");
 if (asst.length) asst[asst.length - 1].classList.add("is-last-assistant");
 }

 function appendTyping() {
 removeTyping();
 const wrap = document.createElement("div");
 wrap.className = "msg assistant typing-msg";
 wrap.id = "typing";
 // 结构拆开：工具活动面板（独立） + 轻量状态条（非回复气泡）
 wrap.innerHTML = `
 <div class="msg-main">
 <div class="msg-avatar" aria-hidden="true">${assistantAvatarLetter()}</div>
 <div class="msg-col">
 <div class="role-row">
 <div class="role">${escapeHtml(assistantDisplayName())}</div>
 <div class="msg-actions">
 <button type="button" class="btn-cancel" id="btnCancelRequest" title="停止这次生成">停止</button>
 </div>
 </div>
 <div class="status-strip" id="typingStrip">
 <span class="typing" aria-hidden="true"><i></i><i></i><i></i></span>
 <span class="typing-phase" id="typingPhase">已收到，正在发给模型…</span>
 </div>
 <div class="tool-activity hidden is-collapsed" id="toolActivity" aria-live="polite">
 <button type="button" class="tool-activity-head" id="toolActivityToggle" aria-expanded="false" title="展开步骤">
 <span class="tool-activity-title">正在做</span>
 <span class="tool-activity-status" id="toolActivityStatus">准备中…</span>
 </button>
 <div class="tool-activity-now" id="toolActivityNow"></div>
 <ol class="tool-activity-steps" id="toolActivitySteps"></ol>
 </div>
 </div>
 </div>`;
 els.messages.appendChild(wrap);
 scrollMessages(true);
 const cancelBtn = wrap.querySelector("#btnCancelRequest");
 if (cancelBtn) {
 cancelBtn.addEventListener("click", () => cancelRequest());
 }
 const toggle = wrap.querySelector("#toolActivityToggle");
 const panel = wrap.querySelector("#toolActivity");
 if (toggle && panel) {
  toggle.addEventListener("click", () => {
   const open = panel.classList.toggle("is-collapsed") === false;
   toggle.setAttribute("aria-expanded", open ? "true" : "false");
   toggle.title = open ? "收起步骤" : "展开步骤";
  });
 }
 }

 /** 工具英文名 → 一句人话 */
 function toolActionLabel(name) {
 const n = (name || "").toLowerCase();
 if (
  !n ||
  n === "meta" ||
  n === "metadata" ||
  n === "tool_meta" ||
  n === "filter_tools"
 ) {
  return "";
 }
 const map = {
  kb: "查知识库",
  memory: "读写记忆",
  workspace: "读写工作区",
  workflow: "跑工作流",
  integrations: "读集成配置",
  llms: "查看对话模型",
  list_skills: "列出技能",
  validate_skill: "校验技能",
  promote_skill: "发布技能",
  web_search: "搜索网页",
  create_tool: "创建技能",
  read_skill: "读技能代码",
  delete_tool: "删除技能",
  terminal: "执行终端命令",
  document: "读写办公文档",
  reload_runtime: "热重载",
  list_api_models: "拉取模型列表",
  server_health_check: "健康检查",
  scheduled_task: "查看定时任务",
  get_current_time: "读取当前时间",
 };
 if (map[n]) return map[n];
 const nice =
  L.toolDisplayName && typeof L.toolDisplayName === "function"
   ? L.toolDisplayName(name)
   : (name || "").replace(/_/g, " ");
 return `使用 ${nice}`;
 }

 /**
  * 从后端日志提炼「正在做什么」
  * @returns {{ tool?: string, title: string, detail?: string } | null}
  */
 function parseActivityFromLog(rawLine) {
 if (!rawLine) return null;
 let text = String(rawLine).trim();
 // 去时间戳 / logger 前缀
 text = text.replace(
  /^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[,.]?\d*\s*/g,
  ""
 );
 text = text.replace(/^\[[^\]]+\]\s*/g, "");
 text = text.replace(
  /^(?:INFO|DEBUG|WARNING|ERROR|CRITICAL)\s+[\w.]+:\s*/i,
  ""
 );
 text = text.replace(/^[\w.]+:\s*(?=Tool call|Force |Auto-)/i, "");

 // Structured: EVA_TOOL name=terminal action=run
 let m = text.match(
  /EVA_TOOL\s+name=([a-zA-Z0-9_.-]+)(?:\s+(.+))?$/i
 );
 if (m) {
  const tool = m[1];
  const title = toolActionLabel(tool);
  if (!title) return null;
  const detail = (m[2] || "").trim().slice(0, 80);
  return { tool, title, detail: detail || undefined };
 }

 // Agent core: Tool call round=0 name=workspace args={...}
 m = text.match(
  /Tool call round=(\d+)\s+name=([a-zA-Z0-9_.-]+)\s+args=(.*)$/i
 );
 if (m) {
  const tool = m[2];
  let hint = "";
  let title = toolActionLabel(tool);
  try {
   const args = JSON.parse(m[3]);
   if (args && typeof args === "object") {
    const act = args.action || args.op || args.method;
    const table = args.table || args.table_id;
    const path = args.path || args.filename || args.title || args.query || args.where;
    if (table) {
     title = `${act ? String(act) : "查询"}「${table}」`;
    } else if (act) {
     hint = String(act);
    }
    if (path) hint = (hint ? hint + " · " : "") + String(path).slice(0, 48);
   }
  } catch (_) {
   const am = m[3].match(/"action"\s*:\s*"([^"]+)"/);
   const tm = m[3].match(/"table(?:_id)?"\s*:\s*"([^"]+)"/);
   const pm = m[3].match(/"(?:path|filename|title|query|where)"\s*:\s*"([^"]+)"/);
   if (tm) {
    title = `${(am && am[1]) || "查询"}「${tm[1]}」`;
   } else if (am) {
    hint = am[1];
   }
   if (pm) hint = (hint ? hint + " · " : "") + pm[1].slice(0, 48);
  }
  return {
   tool,
   title,
   detail: hint || undefined,
  };
 }

 m = text.match(/(?:Force tool retry|Force durable persist)/i);
 if (m) {
  return { title: "补充必要步骤", detail: "按规则补调工具" };
 }

 m = text.match(/Auto-continue after tool-round/i);
 if (m) {
  return { title: "自动续跑", detail: "工具轮次达上限，继续完成任务" };
 }

 // 忽略内部筛选日志（filter_tools: ... meta=['llms'] 会被误识别成「使用 meta」）
 if (/filter_tools\b|tool_meta\b|sticky meta|allowed_meta\b/i.test(text)) {
  return null;
 }

 // 其它带工具名的行
 m = text.match(
  /(?:^|[\s])(?:tool|工具)[\s:：=]+[`'"]?([a-zA-Z][a-zA-Z0-9_.-]{1,40})/i
 );
 if (m) {
  const tool = m[1];
  const title = toolActionLabel(tool);
  if (!title) return null;
  return { tool, title };
 }

 // 噪声日志直接丢弃
 if (
  /^(httpx|httpcore|openai|urllib3|asyncio)/i.test(text) ||
  /HTTP Request:|connection pool|Retrying/i.test(text)
 ) {
  return null;
 }
 return null;
 }

 /** 工具进度：只显示「正在做什么」步骤，不刷原始日志 */
 function appendTypingLog(line) {
 const panel = document.getElementById("toolActivity");
 const stepsEl = document.getElementById("toolActivitySteps");
 const nowEl = document.getElementById("toolActivityNow");
 const st = document.getElementById("toolActivityStatus");
 if (!stepsEl || !line) return;

 const info = parseActivityFromLog(line);
 if (!info || !info.title) return;

 if (panel) panel.classList.remove("hidden");

 const tool = info.tool || "";
 const title = info.title || "处理中";
 const detail = info.detail || "";

 // 主状态：一句话
 if (nowEl) {
  nowEl.textContent = detail ? `${title}（${detail}）` : title;
 }
 // 顶部轻量条同步成「正在：xxx」
 const phaseEl = document.getElementById("typingPhase");
 if (phaseEl) {
  phaseEl.textContent = detail ? `正在：${title} · ${detail}` : `正在：${title}`;
 }

 // 同工具连点合并为更新最后一步
 const last = stepsEl.lastElementChild;
 if (
  last &&
  tool &&
  last.dataset.tool === tool &&
  Date.now() - Number(last.dataset.ts || 0) < 2500
 ) {
  last.querySelector(".tool-step-title").textContent = title;
  const d = last.querySelector(".tool-step-detail");
  if (d) d.textContent = detail || "";
  last.dataset.ts = String(Date.now());
  last.classList.add("is-current");
  Array.from(stepsEl.children).forEach((el) => {
   if (el !== last) el.classList.remove("is-current");
  });
  if (st) {
   const collapsed = panel && panel.classList.contains("is-collapsed");
   st.textContent = collapsed
    ? `${stepsEl.children.length} 步 · 点开看`
    : `第 ${stepsEl.children.length} 步`;
  }
  scrollMessages(false);
  return;
 }

 Array.from(stepsEl.children).forEach((el) =>
  el.classList.remove("is-current")
 );
 const li = document.createElement("li");
 li.className = "tool-activity-step is-current";
 if (tool) li.dataset.tool = tool;
 li.dataset.ts = String(Date.now());
 li.innerHTML = `
  <span class="tool-step-idx">${stepsEl.children.length + 1}</span>
  <span class="tool-step-body">
   <span class="tool-step-title"></span>
   <span class="tool-step-detail"></span>
  </span>`;
 li.querySelector(".tool-step-title").textContent = title;
 li.querySelector(".tool-step-detail").textContent = detail || "";
 stepsEl.appendChild(li);
 while (stepsEl.children.length > 6) stepsEl.removeChild(stepsEl.firstChild);
 // 重编号
 Array.from(stepsEl.children).forEach((el, i) => {
  const idx = el.querySelector(".tool-step-idx");
  if (idx) idx.textContent = String(i + 1);
 });
 if (st) {
  const collapsed = panel && panel.classList.contains("is-collapsed");
  st.textContent = collapsed
   ? `${stepsEl.children.length} 步 · 点开看`
   : `已完成 ${stepsEl.children.length} 步`;
 }
 scrollMessages(false);
 }

 /** 流式助手气泡：边写边渲染 */
 function appendStreamBubble() {
 const empty = els.messages.querySelector(".empty");
 if (empty) empty.remove();
 const wrap = document.createElement("div");
 wrap.className = "msg assistant";
 wrap.id = "streamMsg";
 wrap.innerHTML = `
 <div class="msg-main">
 <div class="msg-avatar" aria-hidden="true">${assistantAvatarLetter()}</div>
 <div class="msg-col">
 <div class="role-row">
 <div class="role">${escapeHtml(assistantDisplayName())}</div>
 <div class="msg-actions">
 <button type="button" class="btn-cancel" id="btnCancelRequest" title="停止这次生成">停止</button>
 </div>
 </div>
 <div class="bubble md stream-live"><span class="stream-cursor"></span></div>
 <div class="msg-foot"><span class="msg-foot-meta">正在输出…</span></div>
 </div>
 </div>`;
 els.messages.appendChild(wrap);
 scrollMessages(true);
 const cancelBtn = wrap.querySelector("#btnCancelRequest");
 if (cancelBtn) {
 cancelBtn.addEventListener("click", () => cancelRequest());
 }
 return wrap;
 }

 function updateStreamBubble(wrap, text) {
 if (!wrap) return;
 const bubble = wrap.querySelector(".bubble");
 if (!bubble) return;
 const clean = stripThinking(text);
 bubble.innerHTML = renderMarkdown(clean) + '<span class="stream-cursor"></span>';
 scrollMessages(false);
 }

 function finalizeStreamBubble(wrap, text, extra = {}) {
 if (!wrap) return appendMessage("assistant", text, { ...extra, streamed: true });
 wrap.removeAttribute("id");
 const bubble = wrap.querySelector(".bubble");
 const clean = stripThinking(text);
 if (bubble) {
 bubble.classList.add("md");
 bubble.classList.remove("stream-live");
 bubble.innerHTML = renderMarkdown(clean);
 }
 const cancelBtn = wrap.querySelector(".btn-cancel");
 if (cancelBtn) cancelBtn.remove();
 const col = wrap.querySelector(".msg-col") || wrap;
 if (!wrap.querySelector(".btn-copy")) {
 const actions = buildMsgActions("assistant", clean, extra);
 let meta = wrap.querySelector(".msg-foot");
 if (!meta) {
 meta = document.createElement("div");
 meta.className = "msg-foot";
 col.appendChild(meta);
 }
 meta.innerHTML = "";
 if (actions && actions.childNodes.length) meta.appendChild(actions);
 const t = document.createElement("span");
 t.className = "msg-time";
 const now = new Date();
 t.textContent = (formatMsgTime || timeAgo)(now.toISOString());
 t.title = now.toLocaleString();
 meta.appendChild(t);
 }
 scrollMessages(true);
 return wrap;
 }

 function removeTyping() {
 const t = document.getElementById("typing");
 if (t) t.remove();
 }


 // Export
 L.renderMarkdown = renderMarkdown;
 L.toMediaSrc = toMediaSrc;
 L.parseSmbRef = parseSmbRef;
 L.isSmbRef = isSmbRef;
 L.autoResize = autoResize;
 L.scrollInputCaretIntoView = scrollInputCaretIntoView;
 L.syncSendButtonState = syncSendButtonState;
 L.setStatus = setStatus;
 L.scrollMessages = scrollMessages;
 L.nearBottom = nearBottom;
 L.clearMessages = clearMessages;
 L.setHomeHeroMode = setHomeHeroMode;
 L.showEmpty = showEmpty;
 L.refreshHomeHero = refreshHomeHero;
 L.hasChatLlm = hasChatLlm;
 L.goAddLlm = goAddLlm;
 L.setSidebarOpen = setSidebarOpen;
 L.isSidebarOpen = isSidebarOpen;
 L.closeMobileSidebar = closeMobileSidebar;
 L.initSidebarLayout = initSidebarLayout;
 L.renderToolsBar = renderToolsBar;
 L.copyText = copyText;
 L.extractBlockCopyText = extractBlockCopyText;
 L.bindBubbleCopyDelegation = bindBubbleCopyDelegation;
 L.fenceKindLabel = fenceKindLabel;
 L.cancelRequest = cancelRequest;
 L.detachWatchOnly = detachWatchOnly;
 L.setBusy = setBusy;
 L.updateTypingPhase = updateTypingPhase;
 L.appendTypingLog = appendTypingLog;
 L.formatUsage = formatUsage;
 L.appendMessage = appendMessage;
 L.refreshTurnActions = refreshTurnActions;
 L.assistantDisplayName = assistantDisplayName;
 L.appendTyping = appendTyping;
 L.appendStreamBubble = appendStreamBubble;
 L.updateStreamBubble = updateStreamBubble;
 L.finalizeStreamBubble = finalizeStreamBubble;
 L.removeTyping = removeTyping;
 L.formatSchedule = formatSchedule;
 L.formatTime = formatTime;
})(window.Lily);
