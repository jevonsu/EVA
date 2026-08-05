/**
 * Lily - Render (Markdown + Messages)
 */
((L) => {
 "use strict";
 const { $, els, state, showToast, debounce, timeAgo, renderSkeleton, escapeHtml, stripThinking, normalizeToolCalls, extractToolCalls, summarizeToolNames, extractMediaPaths, renderToolsBar, ipk, ipkLabel } = L;
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

 /** 是否像内网/NAS 主机（避免把 //cdn.com 误判成 SMB） */
 function isLikelySmbHost(host) {
 const h = String(host || "").toLowerCase();
 if (!h) return false;
 if (/^\d{1,3}(\.\d{1,3}){3}$/.test(h)) return true; // IPv4
 if (h.endsWith(".local") || h.endsWith(".lan") || h.endsWith(".home")) return true;
 if (/^(nas|smb|fileserver|storage)/i.test(h)) return true;
 return false;
 }

 /**
 * 解析 SMB/UNC/nas 引用 → { host, share, path } 或 null
 * 支持:
 *   \\10.11.11.123\share\folder\a.jpg
 *   //10.11.11.123/share/folder/a.jpg
 *   smb://10.11.11.123/share/folder/a.jpg
 *   nas://share/folder/a.jpg          （默认主机）
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

 // nas://share/path （默认主机，由后端填）
 m = s.match(/^nas:\/\/([^/]+)\/(.+)$/i);
 if (m) {
 return { host: "", share: m[1], path: m[2].replace(/^\/+/, "") };
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

 // SMB / UNC / nas:// 优先（避免 //10.x.x.x 被当成 https）
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
 // 远程/NAS：优先显示链接文字，否则显示路径
 const captionText =
 alt && String(alt).trim() && String(alt).trim() !== raw
   ? String(alt).trim()
   : isSmb && smbRef
     ? `NAS · ${smbRef.share}/${smbRef.path}`
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

 // 普通链接指向图片/媒体（含 SMB）：[寫真1](url) / [封面](nas://share/a.jpg)
 src = src.replace(
 /\[([^\]]*)\]\(\s*<?((?:https?:\/\/|\/\/|smb:\/\/|nas:\/\/|\\\\|\\)[^)\n]+?|\/api\/workspace\/smb-media\?[^)\s]+)>?(?:\s+(?:"[^"]*"|'[^']*'))?\s*\)/gi,
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

 // 单独一行的媒体：本地 / 远程 / SMB UNC / nas:// / smb://
 src = src.replace(
 /(?:^|\n)[ \t]*((?:smb:\/\/|nas:\/\/|\\\\|\/\/)[^\s<>"'|]+|(?:https?:\/\/)[^\s<>"'|]+|(?:\.\/)?(?:workspace[\\/])?[^\s<>"'|]+\.(?:png|jpe?g|gif|webp|bmp|svg|avif|mp4|webm|mov|m4v|ogv|mp3|wav)|\/api\/workspace\/smb-media\?[^\s<>"']+)[ \t]*(?=\n|$)/gi,
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
 /\[([^\]]*)\]\(\s*<?((?:https?:\/\/|\/\/|smb:\/\/|nas:\/\/|\\\\)[^)\n]+?|\/api\/workspace\/smb-media\?[^)\s]+)>?(?:\s+(?:"[^"]*"|'[^']*'))?\s*\)/gi,
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

 function setMsg(id, text, type = "") {
 const el = $(id);
 if (!el) return;
 const map = { ok: "check-one", error: "close-one", warn: "attention" };
 const icon = map[type] || "";
 if (icon && text) {
   el.innerHTML = _ipkLabel(icon, text, "ipk-xs");
 } else {
   el.textContent = text || "";
 }
 el.className = "form-msg" + (type ? ` ${type}` : "");
 }

 function autoResize() {
 if (!els.input) return;
 els.input.style.height = "auto";
 // 主流 AI 输入：默认单行高度，随内容增高
 const maxH = 200;
 const minH = 24;
 const next = Math.min(Math.max(els.input.scrollHeight, minH), maxH);
 els.input.style.height = next + "px";
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
 els.btnSend.title = "取消当前请求";
 els.btnSend.setAttribute("aria-label", "停止生成");
 const sendIcon = els.btnSend.querySelector(".ci-send");
 if (sendIcon) {
   const stopSvg = _ipk("close", "ipk-md");
   if (stopSvg) sendIcon.innerHTML = stopSvg;
 }
 const label = els.btnSend.querySelector(".btn-send-label");
 if (label) label.textContent = "停止";
 } else {
 els.btnSend.disabled = false;
 els.btnSend.classList.remove("busy-stop");
 els.btnSend.title = "发送（Enter）";
 els.btnSend.setAttribute("aria-label", "发送");
 const sendIcon = els.btnSend.querySelector(".ci-send");
 if (sendIcon) {
   const sendSvg = _ipk("send", "ipk-md");
   if (sendSvg) sendIcon.innerHTML = sendSvg;
 }
 const label = els.btnSend.querySelector(".btn-send-label");
 if (label) label.textContent = "发送";
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

 function updateTypingPhase(elapsed, detail) {
 const phaseEl = document.getElementById("typingPhase");
 if (!phaseEl) return;
 let text;
 if (detail) {
 text = detail;
 } else if (elapsed < 3) {
 text = "已发送…";
 } else if (elapsed < 10) {
 text = `⏳ 思考 / 处理中…（${elapsed}s）`;
 } else if (elapsed < 25) {
 text = `可能正在调用工具…（${elapsed}s）`;
 } else {
 text = `⏱ 仍在生成，请稍候…（${elapsed}s）`;
 }
 phaseEl.textContent = text;

 // 若工具面板已展开，同步右侧状态文案
 const panel = document.getElementById("toolActivity");
 const st = document.getElementById("toolActivityStatus");
 if (panel && st && !panel.classList.contains("hidden")) {
 if (detail && /工具||运行/.test(detail)) {
 st.textContent = detail.replace(/^\s*/, "");
 } else if (!st.dataset.locked) {
 st.textContent = `${elapsed}s`;
 }
 }
 }

 function setSidebarOpen(open) {
 document.body.classList.toggle("sidebar-open", open);
 const scrim = $("sidebarScrim");
 if (scrim) scrim.classList.toggle("hidden", !open);
 }

 function clearMessages() {
 if (typeof stopEmptyAnimations === "function") stopEmptyAnimations();
 els.messages.innerHTML = "";
 }

 const QUICK_PROMPTS = [
 { label: "今日任务概况", text: "帮我看一下现在有哪些定时任务，以及最近运行情况。", icon: "alarm-clock" },
 { label: "记住偏好", text: "帮我记住：以后回复简洁一些，优先用中文。", icon: "brain" },
 { label: "系统健康", text: "检查一下后端健康状态和可用工具，简单汇报。", icon: "like" },
 { label: "随便聊聊", text: "你好呀，讲讲你现在能帮我做什么？", icon: "comment" },
 ];

 /** 能力词轮播（类比 animejs.com 的 “the web” 可替换词） */
 const EMPTY_ROTATOR_WORDS = ["技能", "记忆", "任务", "工作流", "知识库", "工具"];

 /** @type {any} */
 let _emptyTimeline = null;
 /** @type {any[]} */
 let _emptyLoops = [];
 /** @type {null | (() => void)} */
 let _emptyPointerCleanup = null;
 let _emptyRaf = 0;
 let _emptyRotatorTimer = 0;
 let _emptySafetyTimer = 0;

 function stopEmptyAnimations() {
 try {
 if (_emptyTimeline && typeof _emptyTimeline.pause === "function") _emptyTimeline.pause();
 } catch (_) {}
 _emptyTimeline = null;
 for (const a of _emptyLoops) {
 try {
 if (a && typeof a.pause === "function") a.pause();
 else if (a && typeof a.cancel === "function") a.cancel();
 } catch (_) {}
 }
 _emptyLoops = [];
 if (typeof _emptyPointerCleanup === "function") {
 try {
 _emptyPointerCleanup();
 } catch (_) {}
 }
 _emptyPointerCleanup = null;
 if (_emptyRaf) {
 cancelAnimationFrame(_emptyRaf);
 _emptyRaf = 0;
 }
 if (_emptyRotatorTimer) {
 clearInterval(_emptyRotatorTimer);
 _emptyRotatorTimer = 0;
 }
 if (_emptySafetyTimer) {
 clearTimeout(_emptySafetyTimer);
 _emptySafetyTimer = 0;
 }
 }

 /**
  * anime 不可用 / 入场失败时：清掉内联 opacity/transform，保证文案可见。
  * 部署环境若 vendor 文件 404、被拦截、或 UMD 未挂到 window.anime，都走此回退。
  */
 function markEmptyNoAnime(root) {
 if (!root) return;
 try {
  stopEmptyAnimations();
 } catch (_) {}
 root.classList.add("is-ready", "no-anime");
 root.classList.remove("is-animating", "is-pointer");
 try {
  root
   .querySelectorAll(
    ".empty-shape, .empty-title-line, .empty-home-lead, .empty-chip, .empty-accent-dot, .empty-rotator-word"
   )
   .forEach((el) => {
    el.style.opacity = "";
    el.style.transform = "";
    el.style.translate = "";
    el.style.rotate = "";
    el.style.scale = "";
   });
 } catch (_) {}
 }

 /** 解析 anime v4 UMD 全局（兼容 window.anime / globalThis.anime） */
 function getAnimeApi() {
 try {
  const api = (typeof window !== "undefined" && window.anime) ||
   (typeof globalThis !== "undefined" && globalThis.anime) ||
   null;
  // 入场只依赖 animate；stagger/createTimeline 可选
  if (!api || typeof api.animate !== "function") return null;
  return api;
 } catch (_) {
  return null;
 }
 }

 function prefersReducedMotion() {
 try {
 return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
 } catch (_) {
 return false;
 }
 }

 /** 是否为窄屏触控（动画参数可略减负，但不禁用动画） */
 function isMobileLayout() {
 try {
  if (window.matchMedia && window.matchMedia("(max-width: 900px)").matches) return true;
  if (window.matchMedia && window.matchMedia("(hover: none) and (pointer: coarse)").matches) {
   return true;
  }
 } catch (_) {}
 return false;
 }

 /** 设定选项卡图标（与 config-modal 顶栏 tabs 一致） */
 const EMPTY_TAB_ICONS = [
  { name: "robot-one", label: "Agent" },
  { name: "lightning", label: "LLM" },
  { name: "tool", label: "Tools" },
  { name: "puzzle", label: "Skills" },
  { name: "api", label: "MCP" },
  { name: "connection", label: "集成" },
  { name: "alarm-clock", label: "任务" },
  { name: "brain", label: "记忆" },
  { name: "book-open", label: "知识库" },
  { name: "network-tree", label: "工作流" },
  { name: "folder-open", label: "工作区" },
  { name: "link", label: "Webhook" },
 ];

 function buildEmptyShapesHtml(count) {
 const colors = ["c-green", "c-cyan", "c-amber", "c-mint", "c-soft"];
 const n = Math.max(count || EMPTY_TAB_ICONS.length * 2, EMPTY_TAB_ICONS.length);
 const parts = [];
 for (let i = 0; i < n; i++) {
  const tab = EMPTY_TAB_ICONS[i % EMPTY_TAB_ICONS.length];
  const color = colors[i % colors.length];
  // 全区域网格散布（含边角），略错开避免整齐网格感
  const cols = 6;
  const col = i % cols;
  const row = Math.floor(i / cols);
  const left = 3 + col * (94 / (cols - 1)) + ((i * 7) % 5) - 2;
  const top = 4 + row * 16 + ((i * 11) % 7) - 2;
  const size = 22 + ((i * 13) % 18);
  const iconHtml = _ipk(tab.name, "ipk-md empty-shape-ipk") || "";
  // 无 IconPark 时退回 data-ipk 占位，稍后 hydrate
  const inner =
   iconHtml ||
   `<span data-ipk="${escapeHtml(tab.name)}" data-ipk-class="ipk-md empty-shape-ipk"></span>`;
  parts.push(
   `<span class="empty-shape empty-shape-icon ${color}" style="left:${Math.min(Math.max(left, 1), 93)}%;top:${Math.min(Math.max(top, 1), 90)}%;--sz:${size}px" data-shape-i="${i}" data-tab-icon="${escapeHtml(tab.name)}" title="${escapeHtml(tab.label)}">${inner}</span>`
  );
 }
 return parts.join("");
 }

 /**
  * 主页空状态 · 灵感来自 animejs.com 主页：
  * 浮动图形 + 大标题入场 + 跟手混合位移（本地 animejs v4 UMD）
  * @see https://animejs.com/
  *
  * 实现要点：
  * - 不用 createTimeline（部分环境 onComplete 不触发 → 文案卡在 opacity:0）
  * - 用 animate() + 完成计数；手机/桌面均启用
  * - 安全网超时后 markEmptyNoAnime，保证永不白屏
  */
 function animateEmptyState(root) {
 if (!root) return;
 if (prefersReducedMotion()) {
  markEmptyNoAnime(root);
  return;
 }
 const api = getAnimeApi();
 if (!api || typeof api.animate !== "function") {
  markEmptyNoAnime(root);
  return;
 }

 try {
 stopEmptyAnimations();
 root.classList.remove("is-ready", "no-anime");
 root.classList.add("is-animating");

 const mobile = isMobileLayout();
 // 安全网：入场异常时露出文案（手机略短）
 _emptySafetyTimer = window.setTimeout(() => {
  if (!root.isConnected) return;
  if (root.classList.contains("is-ready")) return;
  console.warn("[empty-state] anime entrance timed out; falling back to static UI");
  markEmptyNoAnime(root);
 }, mobile ? 1600 : 2200);

 const { animate, stagger, random } = api;
 const rnd =
  typeof random === "function"
   ? random
   : (min, max) => min + Math.random() * (max - min);
 const stg =
  typeof stagger === "function"
   ? stagger
   : (ms) => (_el, i) => i * (Number(ms) || 40);

 // anime v4 composition 枚举：replace=0, none=1, blend=2
 const COMP_BLEND = 2;

 const shapes = Array.from(root.querySelectorAll(".empty-shape"));
 const titleLines = Array.from(root.querySelectorAll(".empty-title-line"));
 const lead = root.querySelector(".empty-home-lead");
 const chips = Array.from(root.querySelectorAll(".empty-chip"));
 const accent = root.querySelector(".empty-accent-dot");
 const wordEl = root.querySelector(".empty-rotator-word");
 const field = root.querySelector(".empty-shapes");

 // 初始隐藏（仅内联，失败回退会清掉）
 shapes.forEach((el) => {
  el.style.opacity = "0";
 });
 titleLines.forEach((el) => {
  el.style.opacity = "0";
 });
 if (lead) lead.style.opacity = "0";
 chips.forEach((el) => {
  el.style.opacity = "0";
 });

 const finishEntrance = () => {
  if (!root.isConnected) return;
  if (root.classList.contains("is-ready")) return;
  if (_emptySafetyTimer) {
   clearTimeout(_emptySafetyTimer);
   _emptySafetyTimer = 0;
  }
  root.classList.add("is-ready");
  root.classList.remove("is-animating");
  // 确保文案可见
  titleLines.forEach((el) => {
   el.style.opacity = "1";
   el.style.transform = "";
  });
  if (lead) {
   lead.style.opacity = "1";
   lead.style.transform = "";
  }
  chips.forEach((el) => {
   el.style.opacity = "1";
   el.style.transform = "";
  });
  try {
   startIdle();
  } catch (e) {
   console.warn("[empty-state] idle animations failed", e);
  }
 };

 const startIdle = () => {
  if (!root.isConnected) return;

  // 1) 图形漫游（手机幅度略小、数量可全开）
  const rangeX = mobile ? 120 : 280;
  const rangeY = mobile ? 90 : 220;
  const wanderAnims = [];
  shapes.forEach((shape, i) => {
   const baseOpacity = 0.45 + (i % 5) * 0.08;
   shape.style.opacity = String(baseOpacity);
   const wander = () => {
    if (!root.isConnected) return;
    try {
     const a = animate(shape, {
      x: rnd(-rangeX, rangeX),
      y: rnd(-rangeY, rangeY),
      rotate: rnd(-180, 180),
      scale: rnd(0.78, 1.28),
      duration: rnd(mobile ? 1800 : 1400, mobile ? 3200 : 2800),
      ease: "inOut(2)",
      composition: COMP_BLEND,
      onComplete: wander,
     });
     wanderAnims[i] = a;
    } catch (_) {}
   };
   window.setTimeout(wander, i * (mobile ? 50 : 40));
  });
  _emptyLoops.push({
   pause() {
    wanderAnims.forEach((a) => {
     try {
      if (a && typeof a.pause === "function") a.pause();
     } catch (_) {}
    });
   },
  });

  // 2) 强调点脉冲
  if (accent) {
   try {
    _emptyLoops.push(
     animate(accent, {
      scale: [
       { to: 1.35, duration: 520, ease: "out(3)" },
       { to: 1, duration: 680, ease: "inOut(2)" },
      ],
      opacity: [
       { to: 1, duration: 520 },
       { to: 0.72, duration: 680 },
      ],
      loop: true,
     })
    );
   } catch (_) {}
  }

  // 3) 能力词轮播
  if (wordEl && EMPTY_ROTATOR_WORDS.length) {
   let wi = 0;
   _emptyRotatorTimer = window.setInterval(() => {
    if (!root.isConnected || !wordEl.isConnected) return;
    wi = (wi + 1) % EMPTY_ROTATOR_WORDS.length;
    const next = EMPTY_ROTATOR_WORDS[wi];
    try {
     animate(wordEl, {
      y: [0, -10],
      opacity: [1, 0],
      duration: 220,
      ease: "in(2)",
      onComplete: () => {
       wordEl.textContent = next;
       try {
        animate(wordEl, {
         y: [12, 0],
         opacity: [0, 1],
         duration: 320,
         ease: "out(3)",
        });
       } catch (_) {
        wordEl.style.opacity = "1";
       }
      },
     });
    } catch (_) {
     wordEl.textContent = next;
    }
   }, 2200);
  }

  // 4) 指针/触摸跟随（节流 + 异常隔离）
  try {
   bindEmptyShapePointer(root, shapes, field, animate, rnd, COMP_BLEND);
  } catch (e) {
   console.warn("[empty-state] pointer bind failed", e);
  }
 };

 // —— 入场：并行 animate + 完成计数（比 createTimeline 更稳）——
 let pending = 0;
 let finished = false;
 const oneDone = () => {
  if (finished) return;
  pending -= 1;
  if (pending <= 0) {
   finished = true;
   finishEntrance();
  }
 };

 const runGroup = (targets, params) => {
  if (!targets || (Array.isArray(targets) && !targets.length)) return;
  pending += 1;
  try {
   const anim = animate(targets, {
    ...params,
    onComplete: () => {
     try {
      if (typeof params.onComplete === "function") params.onComplete();
     } catch (_) {}
     oneDone();
    },
   });
   if (anim && typeof anim.then === "function") {
    // 部分构建返回 Promise-like
    anim.then?.(() => {}).catch?.(() => oneDone());
   }
   _emptyLoops.push(anim);
  } catch (e) {
   console.warn("[empty-state] group animate failed", e);
   oneDone();
  }
 };

 if (shapes.length) {
  runGroup(shapes, {
   opacity: [0, 0.7],
   scale: [0.2, 1],
   duration: mobile ? 560 : 720,
   delay: stg(mobile ? 18 : 24),
   ease: "out(3)",
  });
 }
 if (titleLines.length) {
  runGroup(titleLines, {
   opacity: [0, 1],
   y: [mobile ? 18 : 28, 0],
   duration: mobile ? 520 : 680,
   delay: stg(mobile ? 80 : 100),
   ease: "out(3)",
  });
 }
 if (lead) {
  runGroup(lead, {
   opacity: [0, 1],
   y: [14, 0],
   duration: mobile ? 420 : 520,
   ease: "out(3)",
  });
 }
 if (chips.length) {
  runGroup(chips, {
   opacity: [0, 1],
   y: [mobile ? 14 : 22, 0],
   scale: [0.92, 1],
   duration: mobile ? 420 : 520,
   delay: stg(mobile ? 50 : 60),
   ease: "out(3)",
  });
 }

 // 无目标时直接完成
 if (pending === 0) {
  finished = true;
  finishEntrance();
 }

 // 兜底：最长动画时间后强制完成（即使某 onComplete 丢了）
 window.setTimeout(() => {
  if (!finished && root.isConnected && !root.classList.contains("is-ready")) {
   finished = true;
   finishEntrance();
  }
 }, mobile ? 1200 : 1600);
 } catch (err) {
  console.warn("[empty-state] anime entrance failed; static fallback", err);
  markEmptyNoAnime(root);
 }
 }

 /**
  * 鼠标大范围驱动图形（composition: blend），离开后自然回漫游
  */
 function bindEmptyShapePointer(root, shapes, field, animate, rnd, compositionBlend) {
 if (!root || !shapes.length || prefersReducedMotion()) return;
 if (typeof _emptyPointerCleanup === "function") {
  try {
   _emptyPointerCleanup();
  } catch (_) {}
  _emptyPointerCleanup = null;
 }

 const trackHost =
  document.querySelector(".messages-wrap") ||
  document.querySelector(".main") ||
  els.messages ||
  root;

 const COMP_BLEND = compositionBlend != null ? compositionBlend : 2;
 let targetX = 0;
 let targetY = 0;
 let curX = 0;
 let curY = 0;
 let active = false;
 let running = true;
 let lastPush = 0;

 const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
 const trackRect = () =>
  trackHost.getBoundingClientRect?.() || root.getBoundingClientRect();

 const readPointer = (clientX, clientY) => {
  const rect = trackRect();
  if (!rect.width || !rect.height) return;
  targetX = clamp(((clientX - rect.left) / rect.width) * 2 - 1, -1.4, 1.4);
  targetY = clamp(((clientY - rect.top) / rect.height) * 2 - 1, -1.4, 1.4);
  active = true;
  root.classList.add("is-pointer");
 };

 const onPointerMove = (e) => {
  if (typeof e.clientX !== "number") return;
  readPointer(e.clientX, e.clientY);
 };
 const onPointerLeave = () => {
  active = false;
  targetX = 0;
  targetY = 0;
  root.classList.remove("is-pointer");
 };

 const tick = () => {
  if (!running || !root.isConnected) {
   running = false;
   return;
  }
  const ease = active ? 0.16 : 0.07;
  curX += (targetX - curX) * ease;
  curY += (targetY - curY) * ease;

  const now = performance.now();
  // 节流 blend 推送（约 12fps），减轻弱机/远程桌面卡顿
  if (now - lastPush > 80) {
   lastPush = now;
   const pullX = curX * 200;
   const pullY = curY * 160;
   // 只驱动一半图形，降低 anime 实例创建频率
   for (let i = 0; i < shapes.length; i += 2) {
    const shape = shapes[i];
    const depth = 0.4 + (i % 7) * 0.12;
    try {
     animate(shape, {
      x: pullX * depth + (active ? 0 : rnd(-10, 10)),
      y: pullY * depth + (active ? 0 : rnd(-8, 8)),
      duration: active ? 520 : 900,
      ease: active ? "out(3)" : "inOut(2)",
      composition: COMP_BLEND,
     });
    } catch (_) {}
   }
  }

  _emptyRaf = requestAnimationFrame(tick);
 };

 trackHost.addEventListener("pointermove", onPointerMove, { passive: true });
 trackHost.addEventListener("pointerleave", onPointerLeave, { passive: true });
 const onWinMove = (e) => {
  if (!root.isConnected) return;
  const rect = trackRect();
  const pad = 140;
  const inside =
   e.clientX >= rect.left - pad &&
   e.clientX <= rect.right + pad &&
   e.clientY >= rect.top - pad &&
   e.clientY <= rect.bottom + pad;
  if (inside) readPointer(e.clientX, e.clientY);
  else if (active) onPointerLeave();
 };
 window.addEventListener("pointermove", onWinMove, { passive: true });
 _emptyRaf = requestAnimationFrame(tick);

 _emptyPointerCleanup = () => {
  running = false;
  trackHost.removeEventListener("pointermove", onPointerMove);
  trackHost.removeEventListener("pointerleave", onPointerLeave);
  window.removeEventListener("pointermove", onWinMove);
  if (_emptyRaf) {
   cancelAnimationFrame(_emptyRaf);
   _emptyRaf = 0;
  }
  root.classList.remove("is-pointer");
 };
 }

 function showEmpty() {
 stopEmptyAnimations();
 const brand =
  (document.getElementById("agentName")?.textContent || "AgentOS").trim() ||
  "AgentOS";
 els.messages.innerHTML = `
 <div class="empty empty-stage empty-anime-home" id="emptyStage">
  <div class="empty-shapes" aria-hidden="true">${buildEmptyShapesHtml(24)}</div>
  <div class="empty-home-content">
   <div class="empty-home-kicker icon-inline">${_ipk("robot-one", "ipk-sm")} <span>Agent Workspace</span></div>
   <h2 class="empty-home-title">
    <span class="empty-title-line">在下面输入</span>
    <span class="empty-title-line">消息，开始对话</span>
    <span class="empty-title-line empty-title-brand">${escapeHtml(brand)}<span class="empty-accent-dot">.</span></span>
   </h2>
   <p class="empty-home-lead">
    左侧可管理会话；「设定」里配置 LLM、工具与任务。<br>
    默认可调用 <span class="empty-rotator"><span class="empty-rotator-word">技能</span></span>、记忆与任务，在下方输入即可开始。
   </p>
   <div class="empty-chips" id="emptyChips"></div>
  </div>
 </div>`;
 const wrap = $("emptyChips");
 if (!wrap) return;
 for (const p of QUICK_PROMPTS) {
 const btn = document.createElement("button");
 btn.type = "button";
 btn.className = "empty-chip";
 btn.title = p.text;
 if (p.icon) {
  btn.innerHTML = `${_ipk(p.icon, "ipk-xs")} <span>${escapeHtml(p.label)}</span>`;
 } else {
  btn.textContent = p.label;
 }
 btn.addEventListener("click", () => {
 if (state.busy) return;
 els.input.value = p.text;
 autoResize();
 els.input.focus();
 if (typeof L.send === "function") L.send();
 });
 btn.addEventListener("pointerenter", () => {
  const api = getAnimeApi();
  if (!api || prefersReducedMotion()) return;
  try {
   api.animate(btn, {
    scale: 1.06,
    y: -2,
    duration: 220,
    ease: "out(3)",
   });
  } catch (_) {}
 });
 btn.addEventListener("pointerleave", () => {
  const api = getAnimeApi();
  if (!api || prefersReducedMotion()) return;
  try {
   api.animate(btn, {
    scale: 1,
    y: 0,
    duration: 280,
    ease: "out(3)",
   });
  } catch (_) {}
 });
 wrap.appendChild(btn);
 }
 const stage = $("emptyStage") || els.messages.querySelector(".empty-stage");
 // 若 build 时走了 data-ipk 占位，补一次 IconPark 注入
 if (typeof L.hydrateIconPark === "function" && stage) {
  try {
   L.hydrateIconPark(stage);
  } catch (_) {}
 }
 requestAnimationFrame(() => animateEmptyState(stage));
 }

 async function copyText(text, btn) {
 try {
 await navigator.clipboard.writeText(text || "");
 if (btn) {
 const old = btn.dataset.label || btn.textContent;
 btn.dataset.label = old;
 btn.textContent = "已复制";
 btn.classList.add("is-copied");
 setTimeout(() => {
 btn.textContent = old;
 btn.classList.remove("is-copied");
 }, 1200);
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
 function roleAvatarLetter(role) {
 if (role === "user") return "你";
 if (role === "assistant") return "L";
 return "系";
 }

 function buildMsgActions(role, clean, extra) {
 const actions = document.createElement("div");
 actions.className = "msg-actions";
 const retryPayload = extra?.retryMessage || clean;

 if (role === "assistant" || role === "user") {
 const copyBtn = document.createElement("button");
 copyBtn.type = "button";
 copyBtn.className = "btn-copy";
 copyBtn.title = role === "assistant" ? "复制整段回复" : "复制消息";
 copyBtn.textContent = role === "assistant" ? "复制" : "复制";
 copyBtn.addEventListener("click", (e) => {
 e.stopPropagation();
 copyText(clean || "", copyBtn);
 });
 actions.appendChild(copyBtn);
 }
 if (role === "assistant" && typeof L.mountSpeakControls === "function") {
 L.mountSpeakControls(actions, () => clean || "");
 }
 if (role === "system" && extra?.retry) {
 const retryBtn = document.createElement("button");
 retryBtn.type = "button";
 retryBtn.className = "btn-retry";
 retryBtn.textContent = "重试";
 retryBtn.addEventListener("click", () => {
 if (state.busy) return;
 els.input.value = retryPayload;
 autoResize();
 els.input.focus();
 if (typeof L.send === "function") L.send();
 });
 actions.appendChild(retryBtn);
 }
 return actions;
 }

 function appendMessage(role, content, extra = null) {
 const empty = els.messages.querySelector(".empty");
 if (empty) empty.remove();

 // 助手正文：去掉思考块 + 误贴的上传/裸文件名图堆（用户气泡已有预览）
 let clean = role === "assistant" ? stripThinking(content) : content || "";
 if (role === "assistant" && clean) {
 clean = clean
 // 任意位置的 uploads 图
 .replace(/!\[[^\]]*\]\((?:workspace\/)?uploads\/[^)\s]+\)\s*/gi, "")
 // 文末自动粘贴的「无目录」裸路径图（如 ![1.jpg](1.jpg)），保留 images/generated 等
 .replace(
 /(?:\n{0,2}!\[[^\]]*\]\((?:workspace\/)?[^\/\\\s)]+\.(?:png|jpe?g|gif|webp|bmp|svg)\)\s*)+$/gi,
 ""
 )
 .replace(/\n{3,}/g, "\n\n")
 .trimEnd();
 }
 const wrap = document.createElement("div");
 wrap.className = `msg ${role}`;
 const roleLabel =
 role === "user" ? "你" : role === "assistant" ? "Lily" : "系统";

 const timestamp = extra?.timestamp
 ? timeAgo(extra.timestamp)
 : role !== "system"
 ? timeAgo(new Date().toISOString())
 : "";

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
 roleRow.appendChild(actions);

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

 // 工具调用独立区块：放在气泡上方，不混进回复正文
 const toolCalls = normalizeToolCalls((extra && extra.tool_calls) || []);
 if (toolCalls.length) {
 const toolsBar = renderToolsBar(toolCalls);
 if (toolsBar) col.appendChild(toolsBar);
 }

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

 col.appendChild(bubble);

 const meta = document.createElement("div");
 meta.className = "msg-foot";
 const left = document.createElement("span");
 left.className = "msg-foot-meta";
 const parts = [];
 if (role === "assistant") {
 if (extra?.streamed) parts.push("流式");
 if (toolCalls.length) {
 const labels = summarizeToolNames(toolCalls);
 parts.push(`${toolCalls.length} 工具 · ${labels.slice(0, 3).join(" · ")}`);
 }
 if (extra && extra.usage) {
 const u = formatUsage(extra.usage).replace(/^ · /, "");
 if (u) parts.push(u);
 }
 }
 left.textContent = parts.join(" · ");
 meta.appendChild(left);
 if (timestamp) {
 const t = document.createElement("span");
 t.className = "msg-time";
 t.textContent = timestamp;
 t.title = extra?.timestamp || new Date().toLocaleString();
 meta.appendChild(t);
 }
 col.appendChild(meta);

 els.messages.appendChild(wrap);
 scrollMessages(true);
 return wrap;
 }

 function appendTyping() {
 removeTyping();
 const wrap = document.createElement("div");
 wrap.className = "msg assistant typing-msg";
 wrap.id = "typing";
 // 结构拆开：工具活动面板（独立） + 轻量状态条（非回复气泡）
 wrap.innerHTML = `
 <div class="msg-main">
 <div class="msg-avatar" aria-hidden="true">L</div>
 <div class="msg-col">
 <div class="role-row">
 <div class="role">Lily</div>
 <div class="msg-actions">
 <button type="button" class="btn-cancel" id="btnCancelRequest" title="取消这次请求">取消</button>
 </div>
 </div>
 <div class="status-strip" id="typingStrip">
 <span class="typing" aria-hidden="true"><i></i><i></i><i></i></span>
 <span class="typing-phase" id="typingPhase">思考中…</span>
 </div>
 <div class="tool-activity hidden" id="toolActivity" aria-live="polite">
 <div class="tool-activity-head">
 <span class="tool-activity-title">正在做</span>
 <span class="tool-activity-status" id="toolActivityStatus">准备中…</span>
 </div>
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
 }

 /** 工具英文名 → 一句人话 */
 function toolActionLabel(name) {
 const n = (name || "").toLowerCase();
 const map = {
  analyze_image_auto: "识别图片",
  kb: "查知识库",
  memory: "读写记忆",
  workspace: "读写工作区",
  workflow: "跑工作流",
  integrations: "读集成配置",
  office: "处理文档",
  http: "请求网络",
  web_search: "搜索网页",
  grok_media: "生成图片/视频",
  create_tool: "创建技能",
  read_skill: "读技能代码",
  delete_tool: "删除技能",
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

 // Agent core: Tool call round=0 name=workspace args={...}
 let m = text.match(
  /Tool call round=(\d+)\s+name=([a-zA-Z0-9_.-]+)\s+args=(.*)$/i
 );
 if (m) {
  const tool = m[2];
  let hint = "";
  try {
   const args = JSON.parse(m[3]);
   if (args && typeof args === "object") {
    const act = args.action || args.op || args.method;
    const path = args.path || args.filename || args.title || args.query;
    if (act) hint = String(act);
    if (path) hint = (hint ? hint + " · " : "") + String(path).slice(0, 48);
   }
  } catch (_) {
   // args 可能被截断
   const am = m[3].match(/"action"\s*:\s*"([^"]+)"/);
   const pm = m[3].match(/"(?:path|filename|title|query)"\s*:\s*"([^"]+)"/);
   if (am) hint = am[1];
   if (pm) hint = (hint ? hint + " · " : "") + pm[1].slice(0, 48);
  }
  return {
   tool,
   title: toolActionLabel(tool),
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

 // 其它带工具名的行
 m = text.match(
  /(?:tool|工具)[\s:：=]+[`'"]?([a-zA-Z][a-zA-Z0-9_.-]{1,40})/i
 );
 if (m) {
  return { tool: m[1], title: toolActionLabel(m[1]) };
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
 if (!info) return;

 if (panel) panel.classList.remove("hidden");

 const tool = info.tool || "";
 const title = info.title || "处理中";
 const detail = info.detail || "";

 // 主状态：一句话
 if (nowEl) {
  nowEl.textContent = detail ? `${title}（${detail}）` : title;
 }
 if (st) {
  st.textContent = tool
   ? `第 ${stepsEl.children.length + 1} 步`
   : "进行中";
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
 if (st) st.textContent = `已完成 ${stepsEl.children.length} 步`;
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
 <div class="msg-avatar" aria-hidden="true">L</div>
 <div class="msg-col">
 <div class="role-row">
 <div class="role">Lily</div>
 <div class="msg-actions">
 <button type="button" class="btn-cancel" id="btnCancelRequest" title="取消这次请求">取消</button>
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
 const roleRow = wrap.querySelector(".role-row");
 let actions = wrap.querySelector(".msg-actions");
 if (roleRow && !wrap.querySelector(".btn-copy")) {
 if (!actions) {
 actions = document.createElement("div");
 actions.className = "msg-actions";
 roleRow.appendChild(actions);
 }
 const copyBtn = document.createElement("button");
 copyBtn.type = "button";
 copyBtn.className = "btn-copy";
 copyBtn.title = "复制整段回复";
 copyBtn.textContent = "复制";
 copyBtn.addEventListener("click", () => copyText(clean || "", copyBtn));
 actions.appendChild(copyBtn);
 if (typeof L.mountSpeakControls === "function") {
 L.mountSpeakControls(actions, () => clean || "");
 }
 }
 let meta = wrap.querySelector(".msg-foot");
 const col = wrap.querySelector(".msg-col") || wrap;
 if (!meta) {
 meta = document.createElement("div");
 meta.className = "msg-foot";
 col.appendChild(meta);
 }
 meta.innerHTML = "";
 const left = document.createElement("span");
 left.className = "msg-foot-meta";
 const parts = ["流式"];
 if (extra.usage) {
 const u = formatUsage(extra.usage).replace(/^ · /, "");
 if (u) parts.push(u);
 }
 left.textContent = parts.join(" · ");
 meta.appendChild(left);
 const t = document.createElement("span");
 t.className = "msg-time";
 t.textContent = timeAgo(new Date().toISOString());
 meta.appendChild(t);
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
 L.setStatus = setStatus;
 L.scrollMessages = scrollMessages;
 L.nearBottom = nearBottom;
 L.clearMessages = clearMessages;
 L.showEmpty = showEmpty;
 L.setSidebarOpen = setSidebarOpen;
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
 L.appendTyping = appendTyping;
 L.appendStreamBubble = appendStreamBubble;
 L.updateStreamBubble = updateStreamBubble;
 L.finalizeStreamBubble = finalizeStreamBubble;
 L.removeTyping = removeTyping;
 L.formatSchedule = formatSchedule;
 L.formatTime = formatTime;
})(window.Lily);
