/**
 * Lily - File upload (workspace/uploads)
 * 上传新文件 / 选用已有 uploads / 拖拽粘贴 → 附件条 → 发送时并入消息
 */
((L) => {
 "use strict";

 const { $, els, state, showToast } = L;

 if (!state.attachments) state.attachments = [];

 let _uploadsCache = null;
 let _uploadsFilter = "all"; // all | image | video | file

 function formatSize(n) {
 const b = Number(n) || 0;
 if (b < 1024) return `${b} B`;
 if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
 return `${(b / (1024 * 1024)).toFixed(1)} MB`;
 }

 function formatMtime(ts) {
 if (!ts) return "";
 try {
 const d = new Date(Number(ts) * 1000);
 if (Number.isNaN(d.getTime())) return "";
 const p = (n) => String(n).padStart(2, "0");
 return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(
 d.getHours()
 )}:${p(d.getMinutes())}`;
 } catch (_) {
 return "";
 }
 }

 function renderAttachBar() {
 const bar = $("attachBar");
 const list = $("attachList");
 if (!bar || !list) return;
 list.innerHTML = "";
 const items = state.attachments || [];
 if (!items.length) {
 bar.classList.add("hidden");
 if (typeof L.syncSendButtonState === "function") L.syncSendButtonState();
 return;
 }
 bar.classList.remove("hidden");
 for (const a of items) {
 const chip = document.createElement("div");
 chip.className = "attach-chip";
 chip.dataset.path = a.path;

 if (a.kind === "image" && a.preview_url) {
 const img = document.createElement("img");
 img.className = "attach-thumb";
 img.src = a.preview_url;
 img.alt = a.name || a.path;
 chip.appendChild(img);
 } else {
 const icon = document.createElement("span");
 icon.className = "attach-icon";
 icon.textContent =
 a.kind === "video" ? "" : a.kind === "audio" ? "" : "";
 chip.appendChild(icon);
 }

 const meta = document.createElement("div");
 meta.className = "attach-meta";
 const name = document.createElement("div");
 name.className = "attach-name";
 name.textContent = a.name || a.path;
 name.title = a.path;
 const sub = document.createElement("div");
 sub.className = "attach-sub";
 sub.textContent = `${a.path} · ${formatSize(a.size)}`;
 meta.appendChild(name);
 meta.appendChild(sub);
 chip.appendChild(meta);

 const rm = document.createElement("button");
 rm.type = "button";
 rm.className = "attach-remove";
 rm.title = "移除";
 rm.setAttribute("aria-label", "移除附件");
 rm.textContent = "×";
 rm.addEventListener("click", () => {
 state.attachments = (state.attachments || []).filter(
 (x) => x.path !== a.path
 );
 renderAttachBar();
 });
 chip.appendChild(rm);
 list.appendChild(chip);
 }
 if (typeof L.syncSendButtonState === "function") L.syncSendButtonState();
 }

 function addAttachments(savedList) {
 if (!Array.isArray(savedList) || !savedList.length) return;
 if (!state.attachments) state.attachments = [];
 for (const s of savedList) {
 if (!s || !s.path) continue;
 if (state.attachments.some((x) => x.path === s.path)) continue;
 state.attachments.push({
 path: s.path,
 name: s.name || s.original_name || s.path,
 size: s.size || 0,
 media_type: s.media_type || "",
 preview_url: s.preview_url || `/api/workspace/media/${s.path}`,
 kind: s.kind || "file",
 });
 }
 renderAttachBar();
 }

 async function uploadFiles(fileList) {
 const files = Array.from(fileList || []).filter(Boolean);
 if (!files.length) return [];

 const fd = new FormData();
 for (const f of files) fd.append("files", f, f.name);

 setUploadBusy(true);
 try {
 const res = await fetch("/api/workspace/upload", {
 method: "POST",
 body: fd,
 });
 let data = null;
 const text = await res.text();
 try {
 data = text ? JSON.parse(text) : null;
 } catch {
 data = { detail: text };
 }
 if (!res.ok) {
 const detail = data?.detail;
 let msg = "上传失败";
 if (typeof detail === "string") msg = detail;
 else if (detail?.message) msg = detail.message;
 else if (detail?.errors?.length) {
 msg = detail.errors.map((e) => e.error || e.name).join("；");
 }
 throw new Error(msg);
 }
 const saved = data?.saved || [];
 const errors = data?.errors || [];
 addAttachments(saved);
 if (saved.length) {
 showToast(
 `已上传 ${saved.length} 个文件（可在附件面板再次选用）`,
 "success"
 );
 _uploadsCache = null;
 if (typeof L.setStatus === "function") {
 L.setStatus(`已添加 ${saved.length} 个附件`, "ok");
 }
 }
 if (errors.length) {
 showToast(
 `部分失败: ${errors.map((e) => e.name || e.error).join(", ")}`,
 "warn",
 4000
 );
 }
 return saved;
 } catch (e) {
 showToast("上传失败: " + (e.message || e), "error");
 if (typeof L.setStatus === "function") {
 L.setStatus("上传失败: " + (e.message || e), "error");
 }
 return [];
 } finally {
 setUploadBusy(false);
 const input = $("fileInput");
 if (input) input.value = "";
 }
 }

 function setUploadBusy(busy) {
 const btn = $("btnAttach");
 const plus = $("btnComposerPlus");
 if (btn) {
 btn.disabled = !!busy;
 btn.classList.toggle("uploading", !!busy);
 btn.title = busy
 ? "上传中…"
 : "上传或选用已有文件（也可拖拽 / 粘贴）";
 }
 if (plus) {
 plus.disabled = !!busy;
 plus.classList.toggle("uploading", !!busy);
 plus.title = busy ? "上传中…" : "添加";
 }
 }

 function isPickerOpen() {
 const p = $("uploadPicker");
 return p && !p.classList.contains("hidden");
 }

 function openUploadPicker() {
 if (typeof L.closeComposerPlusMenu === "function") L.closeComposerPlusMenu();
 const p = $("uploadPicker");
 if (!p) {
 $("fileInput")?.click();
 return;
 }
 p.classList.remove("hidden");
 document.body.classList.add("upload-picker-open");
 loadUploadsList(false);
 }

 function closeUploadPicker() {
 $("uploadPicker")?.classList.add("hidden");
 document.body.classList.remove("upload-picker-open");
 }

 async function loadUploadsList(force) {
 const grid = $("uploadPickerGrid");
 if (!grid) return;
 if (!_uploadsCache || force) {
 // 先画上传格，避免空白
 renderUploadsGrid(true);
 try {
 const res = await fetch("/api/workspace/uploads?limit=300");
 const data = await res.json();
 if (!res.ok) throw new Error(data.detail || data.error || "加载失败");
 _uploadsCache = Array.isArray(data.files) ? data.files : [];
 } catch (e) {
 _uploadsCache = [];
 renderUploadsGrid(false, e.message || String(e));
 return;
 }
 }
 renderUploadsGrid(false);
 }

 function escapeHtml(s) {
 if (typeof L.escapeHtml === "function") return L.escapeHtml(s);
 return String(s || "")
 .replace(/&/g, "&amp;")
 .replace(/</g, "&lt;")
 .replace(/>/g, "&gt;")
 .replace(/"/g, "&quot;");
 }

 /**
 * 网格：第一格固定「上传」，其后为 uploads 文件方块
 */
 function renderUploadsGrid(loading, errMsg) {
 const grid = $("uploadPickerGrid");
 if (!grid) return;
 const attached = new Set(
 (state.attachments || []).map((a) => a.path)
 );
 let files = _uploadsCache || [];
 if (_uploadsFilter === "image") {
 files = files.filter((f) => f.kind === "image");
 } else if (_uploadsFilter === "video") {
 files = files.filter((f) => f.kind === "video" || f.kind === "audio");
 } else if (_uploadsFilter === "file") {
 files = files.filter(
 (f) => f.kind !== "image" && f.kind !== "video" && f.kind !== "audio"
 );
 }

 const uploadCell = `
 <button type="button" class="up-pick-card up-pick-upload" id="btnUploadNew" title="上传新文件">
 <div class="up-pick-icon up-pick-plus">+</div>
 <div class="up-pick-name">上传</div>
 </button>`;

 let body = "";
 if (loading) {
 body = `<div class="up-pick-card up-pick-muted"><div class="up-pick-name">…</div></div>`;
 } else if (errMsg) {
 body = `<div class="up-pick-card up-pick-muted"><div class="up-pick-name">${escapeHtml(
 errMsg
 )}</div></div>`;
 } else if (!files.length) {
 body = `<div class="up-pick-card up-pick-muted"><div class="up-pick-name">暂无</div></div>`;
 } else {
 body = files
 .map((f) => {
 const on = attached.has(f.path);
 const thumb =
 f.kind === "image"
 ? `<img class="up-pick-thumb" src="${escapeHtml(
 f.preview_url || "/api/workspace/media/" + f.path
 )}" alt="" loading="lazy" />`
 : `<div class="up-pick-icon">${
 f.kind === "video"
 ? "🎬"
 : f.kind === "audio"
 ? "🎵"
 : "📄"
 }</div>`;
 return `
 <button type="button" class="up-pick-card${
 on ? " is-on" : ""
 }" data-up-path="${escapeHtml(f.path)}" title="${escapeHtml(
 f.path
 )}">
 ${thumb}
 <div class="up-pick-name">${escapeHtml(f.name || f.path)}</div>
 ${on ? '<span class="up-pick-badge">✓</span>' : ""}
 </button>`;
 })
 .join("");
 }

 grid.innerHTML = uploadCell + body;
 }

 function toggleUploadSelection(file) {
 if (!file || !file.path) return;
 if (!state.attachments) state.attachments = [];
 const i = state.attachments.findIndex((x) => x.path === file.path);
 if (i >= 0) {
 state.attachments.splice(i, 1);
 showToast("已取消选用", "info", 1200);
 } else {
 state.attachments.push({
 path: file.path,
 name: file.name || file.path,
 size: file.size || 0,
 media_type: file.media_type || "",
 preview_url:
 file.preview_url || `/api/workspace/media/${file.path}`,
 kind: file.kind || "file",
 });
 showToast("已选用（发送时附带）", "success", 1400);
 }
 renderAttachBar();
 renderUploadsGrid();
 }

 /** 发送前把附件并入消息文本（模型可识别路径；前端气泡可预览） */
 function consumeAttachmentsForSend() {
 const items = Array.isArray(state.attachments)
 ? state.attachments.slice()
 : [];
 state.attachments = [];
 renderAttachBar();
 if (!items.length) {
 return { textSuffix: "", attachments: [] };
 }
 // 路径仅作引用；UI 已在用户气泡预览。仅图无文 → 只识图，不自动开任何 SOP
 const onlyImages =
  items.length > 0 && items.every((a) => a && a.kind === "image");
 const lines = [""];
 if (onlyImages) {
  lines.push(
   "【用户上传的图片】（workspace 相对路径；界面已在用户消息中预览）",
   "用户本轮未打字：用几句话描述这些图片后停止。不要检索知识库，不要分阶段，不要出选择题。"
  );
 } else {
  lines.push(
   "【用户上传的文件】（workspace 相对路径；界面已在用户消息中预览）",
   "说明：按用户文字意图处理这些文件；不要在回复中重复粘贴上传图。"
  );
 }
 for (const a of items) {
  if (a.kind === "image") {
   lines.push(`- 图片: ${a.path}`);
  } else if (a.kind === "video") {
   lines.push(`- 视频: ${a.path}`);
  } else {
   lines.push(`- 文件: ${a.path}`);
  }
 }
 return { textSuffix: lines.join("\n"), attachments: items };
 }

 function clearAttachments() {
 state.attachments = [];
 renderAttachBar();
 }

 function bindUploadUI() {
 const fileInput = $("fileInput");
 const btnAttach = $("btnAttach");
 const composer = $("composer") || document.querySelector(".composer");
 const overlay = $("dropOverlay");

 btnAttach?.addEventListener("click", () => {
 if (isPickerOpen()) closeUploadPicker();
 else openUploadPicker();
 });
 // 再点回形针关闭；Esc 关闭
 document.addEventListener("keydown", (e) => {
 if (e.key === "Escape" && isPickerOpen()) closeUploadPicker();
 });

 // 顶置筛选（横向）
 $("uploadPickerFilters")?.addEventListener("click", (e) => {
 const btn = e.target.closest?.("[data-up-filter]");
 if (!btn) return;
 _uploadsFilter = btn.getAttribute("data-up-filter") || "all";
 $("uploadPickerFilters")
 ?.querySelectorAll("[data-up-filter]")
 .forEach((b) => {
 b.classList.toggle(
 "is-active",
 b.getAttribute("data-up-filter") === _uploadsFilter
 );
 });
 renderUploadsGrid(false);
 });

 // 网格：首格上传 / 其余选用
 $("uploadPickerGrid")?.addEventListener("click", (e) => {
 const uploadBtn = e.target.closest?.("#btnUploadNew, .up-pick-upload");
 if (uploadBtn) {
 fileInput?.click();
 return;
 }
 const card = e.target.closest?.("[data-up-path]");
 if (!card) return;
 const path = card.getAttribute("data-up-path");
 const file = (_uploadsCache || []).find((f) => f.path === path);
 if (file) toggleUploadSelection(file);
 });

 fileInput?.addEventListener("change", async () => {
 if (fileInput.files?.length) {
 await uploadFiles(fileInput.files);
 _uploadsCache = null;
 if (isPickerOpen()) loadUploadsList(true);
 }
 });

 // 粘贴图片 / 文件
 els.input?.addEventListener("paste", (e) => {
 const cd = e.clipboardData;
 if (!cd) return;
 const files = [];
 if (cd.files && cd.files.length) {
 for (const f of cd.files) files.push(f);
 } else if (cd.items) {
 for (const item of cd.items) {
 if (item.kind === "file") {
 const f = item.getAsFile();
 if (f) files.push(f);
 }
 }
 }
 if (files.length) {
 e.preventDefault();
 uploadFiles(files);
 }
 });

 // 拖拽上传
 if (!composer) return;
 let dragDepth = 0;

 const showOverlay = (on) => {
 if (!overlay) return;
 overlay.classList.toggle("hidden", !on);
 composer.classList.toggle("drag-over", on);
 };

 composer.addEventListener("dragenter", (e) => {
 e.preventDefault();
 dragDepth += 1;
 showOverlay(true);
 });
 composer.addEventListener("dragover", (e) => {
 e.preventDefault();
 if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
 });
 composer.addEventListener("dragleave", (e) => {
 e.preventDefault();
 dragDepth = Math.max(0, dragDepth - 1);
 if (dragDepth === 0) showOverlay(false);
 });
 composer.addEventListener("drop", (e) => {
 e.preventDefault();
 dragDepth = 0;
 showOverlay(false);
 const files = e.dataTransfer?.files;
 if (files?.length) uploadFiles(files);
 });
 }

 L.uploadFiles = uploadFiles;
 L.addAttachments = addAttachments;
 L.renderAttachBar = renderAttachBar;
 L.openUploadPicker = openUploadPicker;
 L.closeUploadPicker = closeUploadPicker;
 L.consumeAttachmentsForSend = consumeAttachmentsForSend;
 L.clearAttachments = clearAttachments;
 L.bindUploadUI = bindUploadUI;
 L.openUploadPicker = openUploadPicker;
 L.closeUploadPicker = closeUploadPicker;
 L.loadUploadsList = loadUploadsList;
})(window.Lily);
