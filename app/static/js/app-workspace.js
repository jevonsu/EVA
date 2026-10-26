/**
 * Workspace file manager (设定 → 工作区)
 */
((L) => {
  "use strict";
  const { $, showToast, escapeHtml, setMsg } = L;
  const api = (...a) => L.api(...a);
  const _ipk = (n, c) => (typeof L.ipk === "function" ? L.ipk(n, c) : "");

  let _wsPath = "";
  let _wsEntries = [];
  let _wsSelected = new Set();
  let _wsAnchor = "";
  let _wsClipboard = null;
  let _wsFilter = "";
  let _wsView = "grid";
  try {
    _wsView = localStorage.getItem("eva.wsView") === "list" ? "list" : "grid";
  } catch (_) {
    _wsView = "grid";
  }
  let _wsNameResolver = null;
  let _wsPressTimer = 0;
  let _wsShared = false;

  const _WS_TEXT_EXT =
    /\.(txt|md|markdown|json|jsonl|csv|tsv|py|js|mjs|cjs|ts|tsx|jsx|html?|css|scss|less|ya?ml|toml|ini|cfg|conf|log|xml|svg|env|sh|bat|ps1|sql|r|go|rs|java|kt|c|h|cpp|hpp|vue|svelte|php|rb|pl|lua|rhai)$/i;

  function wsJoin(dir, name) {
    const d = String(dir || "").replace(/^\/+|\/+$/g, "");
    const n = String(name || "")
      .replace(/\\/g, "/")
      .replace(/^\/+/, "");
    if (!n) return d;
    return d ? d + "/" + n : n;
  }

  function wsBasename(p) {
    const s = String(p || "").replace(/\/+$/, "");
    const i = s.lastIndexOf("/");
    return i >= 0 ? s.slice(i + 1) : s;
  }

  function wsDirname(p) {
    const s = String(p || "").replace(/\/+$/, "");
    const i = s.lastIndexOf("/");
    return i >= 0 ? s.slice(0, i) : "";
  }

  function wsSanitizeName(name) {
    const n = String(name || "")
      .trim()
      .replace(/\\/g, "/")
      .replace(/^\/+/, "");
    if (!n || n === "." || n.split("/").some((p) => p === ".." || p === "."))
      return "";
    if (/[<>:"|?*\u0000-\u001f]/.test(n)) return "";
    return n;
  }

  function wsDisplayDir(dir) {
    return (_wsShared ? "公司文件/" : "本机工作区/") + (dir ? dir + "/" : "");
  }

  function wsShortRoot(p) {
    const s = String(p || "");
    if (!s) return "";
    return s.length > 64 ? "…" + s.slice(-60) : s;
  }

  function wsIsNestedDup(e, isDir) {
    if (!isDir) return false;
    if (e && e.nested_workspace) return true;
    const name = String((e && e.name) || "").toLowerCase();
    return !_wsPath && name === "workspace";
  }

  function renderWsNestedAlert(data) {
    const box = $("wsNestedAlert");
    const text = $("wsNestedAlertText");
    const nest = data && data.nested_workspace;
    const count = Number(nest && nest.count) || 0;
    const atRoot = !_wsPath;
    const show = !!(box && atRoot && count > 0);
    if (box) {
      box.classList.toggle("hidden", !show);
      if (show) box.removeAttribute("hidden");
      else box.setAttribute("hidden", "");
    }
    if (text && show) {
      const dup = !!(nest && nest.duplicate);
      text.textContent = dup
        ? "根目录里还有一个名为 workspace 的文件夹，内容和这里重复。用一段时间后常会这样套一层。"
        : "根目录里有一个名为 workspace 的文件夹。点进去会当成另一层工作区，容易越套越深。";
    }
    const chip = $("wsRootChip");
    if (chip) {
      const root = String((data && data.root) || "");
      chip.textContent = root ? "位置 " + wsShortRoot(root) : "";
      chip.hidden = !root;
      chip.classList.toggle("hidden", !root);
    }
  }

  async function flattenNestedWorkspace() {
    if (
      !confirm(
        "把嵌套的 workspace 文件夹整理到当前根目录？相同文件会跳过，多出来的会移上来。"
      )
    )
      return;
    try {
      const data = await api("/api/workspace/flatten-nested", { method: "POST" });
      const moved = Array.isArray(data?.moved) ? data.moved.length : 0;
      const skipped = Array.isArray(data?.skipped) ? data.skipped.length : 0;
      showToast(`已整理：移入 ${moved}，跳过相同 ${skipped}`, "success");
      await loadWorkspace("");
    } catch (err) {
      showToast("整理失败: " + (err.message || err), "error");
    }
  }

  function wsFormatSize(n) {
    const v = Number(n);
    if (!Number.isFinite(v) || v < 0) return "";
    if (v < 1024) return v + " B";
    if (v < 1024 * 1024) return (v / 1024).toFixed(v < 10 * 1024 ? 1 : 0) + " KB";
    return (v / (1024 * 1024)).toFixed(1) + " MB";
  }

  function wsEntryName(e) {
    const n = String((e && e.name) || "").trim();
    if (n) return n;
    return wsBasename((e && e.path) || "");
  }

  function wsFormatTime(ts) {
    let n = Number(ts);
    if (!Number.isFinite(n) || n <= 0) return "";
    if (n > 1e12) n = n / 1000;
    const d = new Date(n * 1000);
    if (Number.isNaN(d.getTime())) return "";
    const pad = (x) => String(x).padStart(2, "0");
    return (
      d.getFullYear() +
      "-" +
      pad(d.getMonth() + 1) +
      "-" +
      pad(d.getDate()) +
      " " +
      pad(d.getHours()) +
      ":" +
      pad(d.getMinutes())
    );
  }

  function wsIsEditableName(name) {
    const n = String(name || "");
    if (!n) return false;
    if ([".gitignore", ".editorconfig", ".env"].includes(n.toLowerCase()))
      return true;
    return _WS_TEXT_EXT.test(n) || !n.includes(".");
  }

  function wsIsImageName(name) {
    return /\.(png|jpe?g|gif|webp|bmp|svg|ico|heic|heif)$/i.test(String(name || ""));
  }
  function wsIsVideoName(name) {
    return /\.(mp4|webm|mov|m4v|ogv|mkv)$/i.test(String(name || ""));
  }
  function wsIsAudioName(name) {
    return /\.(mp3|wav|ogg|m4a|flac|aac)$/i.test(String(name || ""));
  }

  function wsKindLabel(e, isDir, editable) {
    if (isDir) return "文件夹";
    if (wsIsImageName(e.name)) return "图片";
    if (wsIsVideoName(e.name)) return "视频";
    if (wsIsAudioName(e.name)) return "音频";
    if (editable) return "文本";
    return "文件";
  }

  function wsEntryByPath(path) {
    return _wsEntries.find((e) => e.path === path) || null;
  }

  function wsExistingNames() {
    return new Set(_wsEntries.map((e) => wsEntryName(e)));
  }

  function wsUniqueName(name, taken) {
    if (!taken.has(name)) return name;
    const dot = name.lastIndexOf(".");
    const hasExt = dot > 0;
    const stem = hasExt ? name.slice(0, dot) : name;
    const ext = hasExt ? name.slice(dot) : "";
    for (let i = 1; i < 200; i++) {
      const n = `${stem} (${i})${ext}`;
      if (!taken.has(n)) return n;
    }
    return `${stem}-${Date.now()}${ext}`;
  }

  function wsIsInside(src, dest) {
    return dest === src || String(dest || "").startsWith(src + "/");
  }

  function wsDragHasFiles(dt) {
    const types = Array.from((dt && dt.types) || []);
    return types.includes("Files");
  }

  function renderWsBreadcrumb(rel) {
    const el = $("wsBreadcrumb");
    if (!el) return;
    el.innerHTML = "";
    const rootBtn = document.createElement("button");
    rootBtn.type = "button";
    rootBtn.className = "ws-crumb";
    rootBtn.textContent = _wsShared ? "公司文件" : "本机工作区";
    rootBtn.dataset.wsDrop = "";
    rootBtn.addEventListener("click", () => loadWorkspace(""));
    el.appendChild(rootBtn);
    const path = rel === "." || !rel ? "" : String(rel);
    if (!path) {
      const cur = document.createElement("span");
      cur.className = "ws-crumb-cur";
      cur.textContent = " /";
      el.appendChild(cur);
      return;
    }
    const parts = path.split("/").filter(Boolean);
    let acc = "";
    parts.forEach((part, i) => {
      const sep = document.createElement("span");
      sep.className = "ws-crumb-sep";
      sep.textContent = "/";
      el.appendChild(sep);
      acc = acc ? acc + "/" + part : part;
      if (i === parts.length - 1) {
        const cur = document.createElement("span");
        cur.className = "ws-crumb-cur";
        cur.textContent = part;
        el.appendChild(cur);
      } else {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "ws-crumb";
        b.textContent = part;
        const target = acc;
        b.dataset.wsDrop = target;
        b.addEventListener("click", () => loadWorkspace(target));
        el.appendChild(b);
      }
    });
  }

  function wsMountOverlay(el) {
    if (!el || el.parentElement === document.body) return;
    document.body.appendChild(el);
  }

  function wsAskName({ title, where, value, okText }) {
    return new Promise((resolve) => {
      const dlg = $("wsNameDialog");
      const input = $("wsNameInput");
      if (!dlg || !input) {
        const typed = window.prompt(title || "名称", value || "");
        resolve(typed == null ? null : String(typed));
        return;
      }
      if (_wsNameResolver) {
        _wsNameResolver(null);
        _wsNameResolver = null;
      }
      _wsNameResolver = resolve;
      wsMountOverlay(dlg);
      if ($("wsNameTitle")) $("wsNameTitle").textContent = title || "名称";
      if ($("wsNameWhere"))
        $("wsNameWhere").textContent = "位置：" + wsDisplayDir(where || _wsPath);
      if ($("btnWsNameOk")) $("btnWsNameOk").textContent = okText || "确定";
      setMsg("msgWsName", "");
      input.value = value || "";
      dlg.classList.remove("hidden");
      dlg.removeAttribute("hidden");
      requestAnimationFrame(() => {
        input.focus();
        input.select();
      });
    });
  }

  function wsCloseNameDialog(result) {
    $("wsNameDialog")?.classList.add("hidden");
    const fn = _wsNameResolver;
    _wsNameResolver = null;
    if (fn) fn(result);
  }

  function wsSelectedItems() {
    return _wsEntries.filter((e) => _wsSelected.has(e.path));
  }

  function wsSetSelection(paths, anchor) {
    _wsSelected = new Set(paths.filter(Boolean));
    if (anchor !== undefined) _wsAnchor = anchor || "";
    document.querySelectorAll("#workspaceList .ws-tile").forEach((tile) => {
      tile.classList.toggle("is-selected", _wsSelected.has(tile.dataset.path));
    });
    wsUpdateStatus();
  }

  function wsUpdateStatus(extra) {
    const n = _wsEntries.length;
    const sel = _wsSelected.size;
    const clip = _wsClipboard
      ? ` · 剪贴板 ${_wsClipboard.mode === "cut" ? "剪切" : "复制"} ${_wsClipboard.items.length} 项`
      : "";
    const here = _wsPath || "工作区根目录";
    setMsg(
      "msgWorkspace",
      extra ||
        `${n} 项 · ${here}` + (sel ? ` · 已选 ${sel}` : "") + clip,
      "ok"
    );
  }

  function wsApplyView() {
    const list = $("workspaceList");
    const btn = $("btnWsView");
    if (list) list.classList.toggle("is-list", _wsView === "list");
    if (!btn) return;
    const toGrid = _wsView === "list";
    const label = toGrid ? "图标" : "列表";
    btn.classList.toggle("is-on", _wsView === "list");
    btn.title = toGrid ? "切换为图标" : "切换为列表";
    btn.innerHTML =
      `<span data-ipk="${toGrid ? "all-application" : "list"}" data-ipk-class="ipk-xs"></span>` +
      `<span>${label}</span>`;
    if (typeof L.hydrateIconPark === "function") L.hydrateIconPark(btn);
  }

  function wsToggleView() {
    _wsView = _wsView === "list" ? "grid" : "list";
    try {
      localStorage.setItem("eva.wsView", _wsView);
    } catch (_) {}
    wsApplyView();
  }

  function wsOpenEntry(e, isDir, editable) {
    if (isDir) {
      loadWorkspace(e.path);
      return;
    }
    if (editable) {
      openWsFileEditor(e.path, false);
      return;
    }
    window.open(
      "/api/workspace/media/" + encodeURI(e.path || ""),
      "_blank",
      "noopener"
    );
  }

  function wsTileVisual(e, isDir, editable) {
    if (isDir) {
      return `<div class="ws-tile-icon ws-tile-folder">${_ipk("folder-open", "ipk-md")}</div>`;
    }
    if (wsIsImageName(e.name)) {
      const src =
        "/api/workspace/media/" +
        String(e.path || "")
          .split("/")
          .map(encodeURIComponent)
          .join("/");
      return `<img class="ws-tile-thumb" src="${escapeHtml(src)}" alt="" loading="lazy" />`;
    }
    if (wsIsVideoName(e.name)) {
      return `<div class="ws-tile-icon ws-tile-media">🎬</div>`;
    }
    if (wsIsAudioName(e.name)) {
      return `<div class="ws-tile-icon ws-tile-media">🎵</div>`;
    }
    if (editable) {
      return `<div class="ws-tile-icon ws-tile-text">${_ipk("file-doc", "ipk-md")}</div>`;
    }
    return `<div class="ws-tile-icon">${_ipk("file", "ipk-md")}</div>`;
  }

  function wsHideMenu() {
    const menu = $("wsContextMenu");
    if (!menu) return;
    menu.classList.add("hidden");
    menu.hidden = true;
    menu.innerHTML = "";
  }

  function wsShowMenu(x, y, items) {
    const menu = $("wsContextMenu");
    if (!menu) return;
    wsMountOverlay(menu);
    menu.innerHTML = "";
    items.forEach((it) => {
      if (it === "sep") {
        const sep = document.createElement("div");
        sep.className = "ws-menu-sep";
        menu.appendChild(sep);
        return;
      }
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = it.label;
      if (it.danger) b.className = "danger";
      b.disabled = !!it.disabled;
      b.addEventListener("click", () => {
        wsHideMenu();
        if (!b.disabled && typeof it.run === "function") it.run();
      });
      menu.appendChild(b);
    });
    menu.classList.remove("hidden");
    menu.hidden = false;
    const pad = 8;
    const w = menu.offsetWidth || 180;
    const h = menu.offsetHeight || 200;
    const left = Math.min(x, window.innerWidth - w - pad);
    const top = Math.min(y, window.innerHeight - h - pad);
    menu.style.left = Math.max(pad, left) + "px";
    menu.style.top = Math.max(pad, top) + "px";
  }

  function wsMenuFor(entry, x, y) {
    const selected = wsSelectedItems();
    const multi = selected.length > 1 && entry && _wsSelected.has(entry.path);
    const targets = multi ? selected : entry ? [entry] : [];
    const items = [];
    if (entry && !multi) {
      const isDir = entry.type === "dir";
      const editable = !isDir && wsIsEditableName(entry.name);
      items.push({
        label: isDir ? "打开" : editable ? "编辑" : "预览",
        run: () => wsOpenEntry(entry, isDir, editable),
      });
      if (!isDir) {
        items.push({
          label: "下载",
          run: () => downloadWsFile(entry.path, entry.name),
        });
      }
      items.push("sep");
      items.push({ label: "重命名", run: () => renameWsEntry(entry) });
    }
    if (targets.length) {
      items.push({
        label: "复制",
        run: () => wsSetClipboard("copy", targets),
      });
      items.push({
        label: "剪切",
        run: () => wsSetClipboard("cut", targets),
      });
    }
    items.push({
      label: "粘贴",
      disabled: !_wsClipboard || !_wsClipboard.items.length,
      run: () => pasteWsClipboard(_wsPath),
    });
    if (entry && !multi) {
      items.push({
        label: "复制路径",
        run: () => wsCopyText(entry.path),
      });
    }
    if (targets.length) {
      items.push("sep");
      items.push({
        label: targets.length > 1 ? `删除 ${targets.length} 项` : "删除",
        danger: true,
        run: () => deleteWsMany(targets),
      });
    }
    if (!entry) {
      items.unshift(
        { label: "新建文件", run: () => createWsFile() },
        { label: "新建文件夹", run: () => createWsDir() },
        "sep"
      );
      items.push("sep");
      items.push({ label: "刷新", run: () => loadWorkspace(_wsPath) });
    }
    wsShowMenu(x, y, items);
  }

  function wsCopyText(text) {
    const t = String(text || "");
    if (!t) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(t).then(
        () => showToast("已复制路径", "success"),
        () => showToast(t, "info")
      );
    } else {
      showToast(t, "info");
    }
  }

  function wsSetClipboard(mode, items) {
    _wsClipboard = {
      mode,
      items: items.map((e) => ({
        path: e.path,
        name: e.name,
        type: e.type,
      })),
    };
    document.querySelectorAll("#workspaceList .ws-tile").forEach((tile) => {
      tile.classList.toggle(
        "is-cut",
        mode === "cut" && _wsClipboard.items.some((it) => it.path === tile.dataset.path)
      );
    });
    showToast(
      (mode === "cut" ? "已剪切 " : "已复制 ") + items.length + " 项",
      "success"
    );
    wsUpdateStatus();
  }

  async function pasteWsClipboard(destDir) {
    if (!_wsClipboard || !_wsClipboard.items.length) return;
    const dest = destDir == null ? _wsPath : destDir;
    const mode = _wsClipboard.mode;
    const items = _wsClipboard.items.slice();
    const listing = dest === _wsPath ? wsExistingNames() : new Set();
    if (dest !== _wsPath) {
      try {
        const data = await api(
          "/api/workspace/browse?path=" + encodeURIComponent(dest) + "&limit=500"
        );
        (data?.entries || []).forEach((e) => listing.add(e.name));
      } catch (_) {}
    }
    let ok = 0;
    let fail = 0;
    for (const it of items) {
      if (it.type === "dir" && wsIsInside(it.path, dest)) {
        fail += 1;
        continue;
      }
      if (wsDirname(it.path) === dest && mode === "cut") continue;
      const name =
        wsDirname(it.path) === dest && mode === "copy"
          ? wsUniqueName(it.name, listing)
          : listing.has(it.name)
            ? wsUniqueName(it.name, listing)
            : it.name;
      listing.add(name);
      const newPath = wsJoin(dest, name);
      try {
        const url = mode === "cut" ? "/api/workspace/rename" : "/api/workspace/copy";
        await api(url, {
          method: "POST",
          body: JSON.stringify({ path: it.path, new_path: newPath }),
        });
        ok += 1;
      } catch (err) {
        fail += 1;
        console.warn("ws paste", it.path, err);
      }
    }
    if (mode === "cut") _wsClipboard = null;
    await loadWorkspace(_wsPath);
    showToast(
      ok ? `已${mode === "cut" ? "移动" : "粘贴"} ${ok} 项` + (fail ? ` · ${fail} 失败` : "") : "粘贴失败",
      ok ? "success" : "error"
    );
  }

  async function moveWsItems(items, destDir) {
    _wsClipboard = { mode: "cut", items: items.map((e) => ({ ...e })) };
    await pasteWsClipboard(destDir);
  }

  function renderWsTiles() {
    const list = $("workspaceList");
    if (!list) return;
    const q = _wsFilter.trim().toLowerCase();
    const entries = q
      ? _wsEntries.filter((e) =>
          wsEntryName(e).toLowerCase().includes(q)
        )
      : _wsEntries;
    list.innerHTML = "";
    wsApplyView();
    if (!entries.length) {
      list.innerHTML =
        '<div class="ws-tile ws-tile-muted"><div class="ws-tile-name">' +
        (q ? "没有匹配项" : "空目录") +
        "</div></div>";
      wsUpdateStatus(q ? "没有匹配项" : `0 项 · ${_wsPath || "工作区根目录"}`);
      return;
    }
    for (const e of entries) {
      const tile = document.createElement("div");
      const isDir = e.type === "dir";
      const displayName = wsEntryName(e);
      const editable = !isDir && wsIsEditableName(displayName);
      const sizeTxt = !isDir && e.size != null ? wsFormatSize(e.size) : "";
      const dateTxt = wsFormatTime(e.mtime);
      const kind = wsKindLabel({ ...e, name: displayName }, isDir, editable);
      const nestedDup = wsIsNestedDup(e, isDir);
      tile.className =
        "ws-tile" +
        (isDir ? " is-dir" : "") +
        (wsIsImageName(displayName) ? " is-image" : "") +
        (_wsSelected.has(e.path) ? " is-selected" : "") +
        (nestedDup ? " is-nested-dup" : "") +
        (_wsClipboard &&
        _wsClipboard.mode === "cut" &&
        _wsClipboard.items.some((it) => it.path === e.path)
          ? " is-cut"
          : "");
      tile.dataset.path = e.path || "";
      tile.dataset.type = e.type || "file";
      tile.draggable = false;
      tile.title = (e.path || displayName || "") + (sizeTxt ? " · " + sizeTxt : "");
      tile.innerHTML = `
 ${nestedDup ? '<span class="ws-tile-badge">重复副本</span>' : ""}
 ${wsTileVisual({ ...e, name: displayName }, isDir, editable)}
 <div class="ws-tile-name">${escapeHtml(displayName)}</div>
 <div class="ws-tile-meta">${escapeHtml(kind)}${
        sizeTxt ? " · " + escapeHtml(sizeTxt) : ""
      }</div>
 ${dateTxt ? `<div class="ws-tile-date" title="修改时间">${escapeHtml(dateTxt)}</div>` : ""}
 <div class="ws-tile-actions">
 ${
   !isDir && editable
     ? `<button type="button" class="ws-tile-btn edit-ws" title="编辑">${_ipk("edit", "ipk-xs")}</button>`
     : !isDir
       ? `<button type="button" class="ws-tile-btn open-ws-media" title="预览">${_ipk("preview-open", "ipk-xs")}</button>`
       : ""
 }
 ${
   !isDir
     ? `<button type="button" class="ws-tile-btn dl-ws" title="下载">${_ipk("download", "ipk-xs")}</button>`
     : ""
 }
 <button type="button" class="ws-tile-btn rename-ws" title="重命名">${_ipk("edit", "ipk-xs")}</button>
 <button type="button" class="ws-tile-btn danger del-ws" title="删除">${_ipk("delete", "ipk-xs")}</button>
 </div>`;
      tile.addEventListener("click", (ev) => {
        if (ev.target.closest(".ws-tile-actions")) return;
        const additive = ev.ctrlKey || ev.metaKey;
        const range = ev.shiftKey;
        if (range && _wsAnchor) {
          const vis = entries;
          const a = vis.findIndex((x) => x.path === _wsAnchor);
          const b = vis.findIndex((x) => x.path === e.path);
          if (a >= 0 && b >= 0) {
            const lo = Math.min(a, b);
            const hi = Math.max(a, b);
            wsSetSelection(
              vis.slice(lo, hi + 1).map((x) => x.path),
              _wsAnchor
            );
            return;
          }
        }
        if (additive) {
          const next = new Set(_wsSelected);
          if (next.has(e.path)) next.delete(e.path);
          else next.add(e.path);
          wsSetSelection([...next], e.path);
          return;
        }
        wsSetSelection([e.path], e.path);
        wsOpenEntry(e, isDir, editable);
      });
      tile.addEventListener("mousedown", () => {
        tile.draggable = _wsSelected.has(e.path);
      });
      tile.addEventListener("dragend", () => {
        tile.draggable = false;
      });
      tile.addEventListener("contextmenu", (ev) => {
        ev.preventDefault();
        if (!_wsSelected.has(e.path)) wsSetSelection([e.path], e.path);
        wsMenuFor(e, ev.clientX, ev.clientY);
      });
      tile.addEventListener("dragstart", (ev) => {
        if (!_wsSelected.has(e.path)) wsSetSelection([e.path], e.path);
        ev.dataTransfer.setData("application/x-eva-ws", e.path);
        ev.dataTransfer.effectAllowed = "move";
      });
      if (isDir) {
        tile.addEventListener("dragover", (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          ev.dataTransfer.dropEffect = wsDragHasFiles(ev.dataTransfer)
            ? "copy"
            : "move";
          tile.classList.add("is-drop-target");
        });
        tile.addEventListener("dragleave", () => tile.classList.remove("is-drop-target"));
        tile.addEventListener("drop", async (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          tile.classList.remove("is-drop-target");
          const fl = await collectDroppedFiles(ev.dataTransfer);
          if (fl && fl.length) {
            uploadWsFiles(fl, e.path);
            return;
          }
          const items = wsSelectedItems();
          if (items.length) moveWsItems(items, e.path);
        });
      }
      tile.addEventListener("touchstart", () => {
        clearTimeout(_wsPressTimer);
        _wsPressTimer = window.setTimeout(() => {
          wsSetSelection([e.path], e.path);
          const r = tile.getBoundingClientRect();
          wsMenuFor(e, r.left + 20, r.bottom);
        }, 550);
      });
      tile.addEventListener("touchend", () => clearTimeout(_wsPressTimer));
      tile.addEventListener("touchmove", () => clearTimeout(_wsPressTimer));
      tile.querySelector(".edit-ws")?.addEventListener("click", (ev) => {
        ev.stopPropagation();
        openWsFileEditor(e.path, false);
      });
      tile.querySelector(".open-ws-media")?.addEventListener("click", (ev) => {
        ev.stopPropagation();
        window.open(
          "/api/workspace/media/" + encodeURI(e.path || ""),
          "_blank",
          "noopener"
        );
      });
      tile.querySelector(".dl-ws")?.addEventListener("click", (ev) => {
        ev.stopPropagation();
        downloadWsFile(e.path, displayName);
      });
      tile.querySelector(".rename-ws")?.addEventListener("click", (ev) => {
        ev.stopPropagation();
        renameWsEntry(e);
      });
      tile.querySelector(".del-ws")?.addEventListener("click", (ev) => {
        ev.stopPropagation();
        deleteWsMany([e]);
      });
      list.appendChild(tile);
    }
    if (typeof L.hydrateIconPark === "function") L.hydrateIconPark(list);
    wsUpdateStatus();
  }

  async function loadWorkspace(path, opts = {}) {
    if (path && typeof path === "object" && !Array.isArray(path)) {
      opts = path;
      path = undefined;
    }
    const soft = !!(opts && opts.soft);
    initWorkspacePanel();
    if (path !== undefined && path !== null) _wsPath = String(path);
    const list = $("workspaceList");
    if (!list) return;
    list.className = "ws-grid" + (_wsView === "list" ? " is-list" : "");
    const keepUi = soft && list.querySelector(".ws-tile:not(.ws-tile-muted)");
    if (!keepUi) {
      list.innerHTML =
        '<div class="ws-tile ws-tile-muted"><div class="ws-tile-name">载入中…</div></div>';
      setMsg("msgWorkspace", "载入中…");
    }
    const up = $("btnWsUp");
    try {
      const q = _wsPath
        ? `?path=${encodeURIComponent(_wsPath)}&limit=400`
        : "?limit=400";
      const data = await api("/api/workspace/browse" + q);
      const entries = Array.isArray(data?.entries) ? data.entries : [];
      _wsShared = !!data?.shared;
      const bannerHint =
        $("wsBannerHint") ||
        document.querySelector(
          'section[data-panel="workspace"] .panel-banner .hint'
        );
      if (bannerHint) {
        bannerHint.innerHTML = _wsShared
          ? "当前打开的是 <strong>Hub 公司文件</strong>（与 Hub 工作区同一份，不是拷贝）。新建/上传会写进公司目录。单击打开，Ctrl 多选。"
          : "当前是 <strong>本机独立工作区</strong>。接到 Hub 公司文件后，这里会变成与 Hub 同一份。单击打开，Ctrl 多选。";
      }
      _wsPath =
        data?.path === "." || !data?.path ? "" : String(data.path || _wsPath);
      _wsEntries = entries;
      _wsSelected = new Set([..._wsSelected].filter((p) => entries.some((e) => e.path === p)));
      renderWsNestedAlert(data);
      renderWsBreadcrumb(_wsPath);
      if (up) up.disabled = !_wsPath;
      renderWsTiles();
    } catch (err) {
      list.innerHTML =
        '<div class="ws-tile ws-tile-muted"><div class="ws-tile-name">加载失败</div></div>';
      setMsg("msgWorkspace", err.message || String(err), "error");
    }
    try {
      await refreshWsUndo();
    } catch (_) {}
  }

  function openWsFileModal() {
    const modal = $("wsFileModal");
    // 设定窗有 overflow/isolation，嵌在里面的 fixed 弹层会被裁掉，关不掉。
    wsMountOverlay(modal);
    if (typeof L.openNestedEditor === "function") {
      L.openNestedEditor("wsFileModal");
    } else {
      if (!modal) return;
      modal.classList.remove("hidden");
      document.body.classList.add("cfg-nested-open");
    }
    document.body.classList.add("ws-file-modal-open");
    if (typeof L.hydrateIconPark === "function") L.hydrateIconPark($("wsFileModal"));
  }

  function closeWsFileModal() {
    setMsg("msgWsFile", "");
    if (typeof L.closeNestedEditor === "function") {
      L.closeNestedEditor("wsFileModal");
    } else {
      $("wsFileModal")?.classList.add("hidden");
    }
    document.body.classList.remove("ws-file-modal-open");
  }

  async function openWsFileEditor(path) {
    const modal = $("wsFileModal");
    if (!modal) {
      setMsg("msgWorkspace", "编辑器未加载，请刷新页面", "error");
      return;
    }
    setMsg("msgWsFile", "");
    $("wsEditMode").value = "edit";
    try {
      setMsg("msgWorkspace", "读取中…");
      const data = await api(
        "/api/workspace/file?path=" + encodeURIComponent(path)
      );
      $("wsFilePath").value = data.path || path;
      $("wsFilePath").readOnly = true;
      $("wsFileContent").value = data.content ?? "";
      $("wsFileTitle").innerHTML =
        '<span data-ipk="edit" data-ipk-class="ipk-sm"></span> 编辑 · ' +
        escapeHtml(data.name || path);
      if ($("wsFileLead"))
        $("wsFileLead").textContent =
          (data.size != null ? wsFormatSize(data.size) + " · " : "") +
          "保存后立即写入磁盘。";
      openWsFileModal();
      setMsg("msgWorkspace", "");
      requestAnimationFrame(() => $("wsFileContent")?.focus());
    } catch (err) {
      setMsg("msgWorkspace", err.message || String(err), "error");
      showToast("打开失败", "error");
    }
  }

  async function saveWsFile() {
    const path = ($("wsFilePath")?.value || "").trim();
    if (!path) {
      setMsg("msgWsFile", "请填写路径", "error");
      return;
    }
    const content = $("wsFileContent")?.value ?? "";
    try {
      setMsg("msgWsFile", "保存中…");
      await api("/api/workspace/file", {
        method: "PUT",
        body: JSON.stringify({ path, content, create_parents: true }),
      });
      setMsg("msgWsFile", "已保存", "ok");
      setMsg("msgWorkspace", "已保存 " + path, "ok");
      showToast("已保存", "success");
      closeWsFileModal();
      await loadWorkspace(_wsPath);
    } catch (err) {
      setMsg("msgWsFile", err.message || String(err), "error");
      showToast("保存失败", "error");
    }
  }

  async function refreshWsUndo() {
    const btn = $("btnWsUndo");
    if (!btn) return;
    try {
      const data = await api("/api/workspace/undo");
      btn.disabled = !data?.can_undo;
      btn.title = data?.can_undo ? "撤销：" + (data.label || "上一步") : "没有可撤销的操作";
    } catch (_) {
      btn.disabled = true;
    }
  }

  async function undoWsLast() {
    try {
      const data = await api("/api/workspace/undo", { method: "POST", body: {} });
      showToast("已撤销" + (data?.undone ? "：" + data.undone : ""), "success");
      await loadWorkspace(_wsPath);
    } catch (err) {
      showToast("无法撤销: " + (err.message || err), "error");
      await refreshWsUndo();
    }
  }

  async function deleteWsMany(items) {
    const rows = (items || []).filter((e) => e && e.path);
    if (!rows.length) return;
    const msg =
      rows.length === 1
        ? rows[0].type === "dir"
          ? `确定删除文件夹「${rows[0].name}」及其全部内容？可撤销。`
          : `确定删除文件「${rows[0].name}」？可撤销。`
        : `确定删除选中的 ${rows.length} 项？可撤销。`;
    if (!confirm(msg)) return;
    try {
      await api("/api/workspace/trash", {
        method: "POST",
        body: JSON.stringify({ paths: rows.map((e) => e.path) }),
      });
      showToast("已删除（可撤销）", "success");
    } catch (err) {
      showToast("删除失败: " + (err.message || err), "error");
    }
    await loadWorkspace(_wsPath);
  }

  async function createWsDir() {
    const raw = await wsAskName({
      title: "新建文件夹",
      where: _wsPath,
      value: "新建文件夹",
      okText: "创建",
    });
    if (raw == null) return;
    const name = wsSanitizeName(raw);
    if (!name) {
      showToast("名称无效", "error");
      return;
    }
    if (!_wsPath && name.toLowerCase() === "workspace") {
      showToast("不要在根目录再建名为 workspace 的文件夹", "error");
      return;
    }
    const path = wsJoin(_wsPath, name);
    try {
      await api("/api/workspace/mkdir", {
        method: "POST",
        body: JSON.stringify({ path, create_parents: true }),
      });
      showToast("已在当前目录创建文件夹", "success");
      await loadWorkspace(_wsPath);
    } catch (err) {
      setMsg("msgWorkspace", err.message || String(err), "error");
      showToast("创建失败", "error");
    }
  }

  async function createWsFile() {
    const raw = await wsAskName({
      title: "新建文件",
      where: _wsPath,
      value: "untitled.md",
      okText: "创建",
    });
    if (raw == null) return;
    const name = wsSanitizeName(raw);
    if (!name) {
      showToast("名称无效", "error");
      return;
    }
    const path = wsJoin(_wsPath, name);
    try {
      await api("/api/workspace/file", {
        method: "PUT",
        body: JSON.stringify({ path, content: "", create_parents: true }),
      });
      showToast("已在当前目录创建文件", "success");
      await loadWorkspace(_wsPath);
      if (wsIsEditableName(wsBasename(path))) openWsFileEditor(path);
    } catch (err) {
      setMsg("msgWorkspace", err.message || String(err), "error");
      showToast("创建失败", "error");
    }
  }

  async function renameWsEntry(entry) {
    if (!entry) return;
    const raw = await wsAskName({
      title: "重命名",
      where: wsDirname(entry.path),
      value: entry.name,
      okText: "重命名",
    });
    if (raw == null) return;
    const name = wsSanitizeName(raw);
    if (!name || name === entry.name) return;
    if (!wsDirname(entry.path) && name.toLowerCase() === "workspace") {
      showToast("不要把根目录条目改名为 workspace", "error");
      return;
    }
    const newPath = wsJoin(wsDirname(entry.path), name);
    try {
      await api("/api/workspace/rename", {
        method: "POST",
        body: JSON.stringify({ path: entry.path, new_path: newPath }),
      });
      showToast("已重命名", "success");
      await loadWorkspace(_wsPath);
    } catch (err) {
      setMsg("msgWorkspace", err.message || String(err), "error");
      showToast("重命名失败", "error");
    }
  }

  function downloadWsFile(path, name) {
    if (!path) return;
    const url = "/api/workspace/download?path=" + encodeURIComponent(path);
    const a = document.createElement("a");
    a.href = url;
    a.download = name || path.split("/").pop() || "download";
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
    showToast("开始下载 " + (name || path), "success");
  }

  async function collectDroppedFiles(dt) {
    const items = dt && dt.items;
    if (!items || !items.length) return Array.from((dt && dt.files) || []);
    const out = [];
    const walk = async (entry, prefix) => {
      if (!entry) return;
      if (entry.isFile) {
        const file = await new Promise((res, rej) => entry.file(res, rej));
        const rel = prefix ? prefix + "/" + entry.name : entry.name;
        try {
          Object.defineProperty(file, "wsRelPath", { value: rel });
        } catch (_) {
          file.wsRelPath = rel;
        }
        out.push(file);
        return;
      }
      if (!entry.isDirectory) return;
      const reader = entry.createReader();
      const kids = await new Promise((resolve) => {
        const acc = [];
        const rec = () =>
          reader.readEntries((ents) => {
            if (!ents.length) return resolve(acc);
            acc.push(...ents);
            rec();
          }, () => resolve(acc));
        rec();
      });
      const next = prefix ? prefix + "/" + entry.name : entry.name;
      for (const kid of kids) await walk(kid, next);
    };
    const entries = [];
    for (const it of items) {
      const ent = it.webkitGetAsEntry ? it.webkitGetAsEntry() : null;
      if (ent) entries.push(ent);
    }
    if (!entries.length) return Array.from(dt.files || []);
    for (const ent of entries) await walk(ent, "");
    return out;
  }

  async function uploadWsFiles(fileList, destPath) {
    const files = Array.from(fileList || []).filter(Boolean);
    if (!files.length) return;
    if (files.length > 200) {
      showToast("单次最多 200 个文件", "error");
      return;
    }
    const dest = destPath == null ? _wsPath : destPath;
    const fd = new FormData();
    for (const f of files) {
      fd.append("files", f);
      fd.append(
        "relpaths",
        String(f.wsRelPath || f.webkitRelativePath || "").replace(/\\/g, "/")
      );
    }
    fd.append("mode", "panel");
    fd.append("dest", dest || "");
    setMsg("msgWorkspace", `上传中（${files.length}）…`);
    try {
      const res = await fetch("/api/workspace/upload", {
        method: "POST",
        body: fd,
      });
      let data = null;
      const text = await res.text();
      try {
        data = text ? JSON.parse(text) : null;
      } catch (_) {
        data = { detail: text };
      }
      if (!res.ok) {
        const detail = data?.detail;
        const msg =
          typeof detail === "string"
            ? detail
            : detail?.message ||
              (Array.isArray(detail?.errors)
                ? detail.errors.map((e) => e.error || e).join("; ")
                : res.statusText);
        throw new Error(msg || "上传失败");
      }
      const n = data?.count || (data?.saved || []).length || 0;
      const errN = (data?.errors || []).length;
      showToast(
        n
          ? `已上传 ${n} 个文件到 ${data?.upload_dir || dest || "当前目录"}`
          : "没有文件上传成功",
        n ? "success" : "error"
      );
      if (errN && data.errors?.[0]) console.warn("workspace upload errors", data.errors);
      await loadWorkspace(_wsPath);
    } catch (err) {
      setMsg("msgWorkspace", err.message || String(err), "error");
      showToast("上传失败: " + (err.message || err), "error");
    }
  }

  function bindWsDropZone(list) {
    if (!list || list.dataset.wsDropBound) return;
    list.dataset.wsDropBound = "1";
    let depth = 0;
    list.addEventListener("dragenter", (e) => {
      e.preventDefault();
      depth += 1;
      list.classList.add("ws-drag-over");
    });
    list.addEventListener("dragleave", () => {
      depth = Math.max(0, depth - 1);
      if (!depth) list.classList.remove("ws-drag-over");
    });
    list.addEventListener("dragover", (e) => {
      e.preventDefault();
      if (e.dataTransfer) {
        e.dataTransfer.dropEffect = wsDragHasFiles(e.dataTransfer)
          ? "copy"
          : "move";
      }
    });
    list.addEventListener("drop", async (e) => {
      e.preventDefault();
      depth = 0;
      list.classList.remove("ws-drag-over");
      const crumb = e.target.closest?.("[data-ws-drop]");
      const files = await collectDroppedFiles(e.dataTransfer);
      if (crumb) {
        const dest = crumb.getAttribute("data-ws-drop") || "";
        if (files.length) uploadWsFiles(files, dest);
        else if (wsSelectedItems().length) moveWsItems(wsSelectedItems(), dest);
        return;
      }
      if (e.target.closest?.(".ws-tile.is-dir")) return;
      if (files.length) uploadWsFiles(files);
    });
    list.addEventListener("click", (e) => {
      if (e.target === list || e.target.classList.contains("ws-tile-muted")) {
        wsSetSelection([], "");
      }
    });
    list.addEventListener("contextmenu", (e) => {
      if (e.target.closest(".ws-tile") && !e.target.classList.contains("ws-tile-muted"))
        return;
      e.preventDefault();
      wsMenuFor(null, e.clientX, e.clientY);
    });
    list.addEventListener("keydown", (e) => {
      const tag = (e.target && e.target.tagName) || "";
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key === "Backspace" || (e.altKey && e.key === "ArrowUp")) {
        e.preventDefault();
        $("btnWsUp")?.click();
      } else if (e.key === "Enter") {
        const one = wsSelectedItems()[0];
        if (one)
          wsOpenEntry(one, one.type === "dir", wsIsEditableName(one.name));
      } else if (e.key === "Delete") {
        e.preventDefault();
        deleteWsMany(wsSelectedItems());
      } else if (e.key === "F2") {
        e.preventDefault();
        const one = wsSelectedItems()[0];
        if (one) renameWsEntry(one);
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") {
        e.preventDefault();
        wsSetSelection(_wsEntries.map((x) => x.path), _wsEntries[0]?.path || "");
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "c") {
        e.preventDefault();
        const items = wsSelectedItems();
        if (items.length) wsSetClipboard("copy", items);
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "x") {
        e.preventDefault();
        const items = wsSelectedItems();
        if (items.length) wsSetClipboard("cut", items);
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "v") {
        e.preventDefault();
        pasteWsClipboard(_wsPath);
      } else if (e.key === "Escape") {
        wsHideMenu();
        wsSetSelection([], "");
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        undoWsLast();
      }
    });
  }

  function bindWorkspaceDelegatedUi() {
    if (bindWorkspaceDelegatedUi._done) return;
    bindWorkspaceDelegatedUi._done = true;
    document.addEventListener("click", (e) => {
      const t = e.target;
      if (!(t instanceof Element)) return;
      if (t.id === "wsFileModal") {
        closeWsFileModal();
        return;
      }
      if (t.id === "wsNameDialog") {
        wsCloseNameDialog(null);
        return;
      }
      const btn = t.closest(
        "#btnRefreshWorkspace, #btnWsView, #btnWsUp, #btnWsNewFile, #btnWsNewDir, #btnWsUpload, #btnWsUploadDir, #btnWsUndo, #btnWsFlatten, #btnSaveWsFile, #btnCancelWsFile, #btnCloseWsFile, #btnWsNameOk, #btnWsNameCancel"
      );
      if (!btn) return;
      switch (btn.id) {
        case "btnRefreshWorkspace":
          e.preventDefault();
          loadWorkspace(_wsPath);
          break;
        case "btnWsView":
          e.preventDefault();
          wsToggleView();
          break;
        case "btnWsUp":
          e.preventDefault();
          if (!_wsPath) return;
          {
            const parts = _wsPath.split("/").filter(Boolean);
            parts.pop();
            loadWorkspace(parts.join("/"));
          }
          break;
        case "btnWsNewFile":
          e.preventDefault();
          createWsFile();
          break;
        case "btnWsNewDir":
          e.preventDefault();
          createWsDir();
          break;
        case "btnWsUpload":
          e.preventDefault();
          $("wsUploadInput")?.click();
          break;
        case "btnWsUploadDir":
          e.preventDefault();
          $("wsUploadDirInput")?.click();
          break;
        case "btnWsUndo":
          e.preventDefault();
          undoWsLast();
          break;
        case "btnWsFlatten":
          e.preventDefault();
          flattenNestedWorkspace();
          break;
        case "btnSaveWsFile":
          e.preventDefault();
          saveWsFile();
          break;
        case "btnCancelWsFile":
        case "btnCloseWsFile":
          e.preventDefault();
          closeWsFileModal();
          break;
        case "btnWsNameOk":
          e.preventDefault();
          wsCloseNameDialog($("wsNameInput")?.value ?? "");
          break;
        case "btnWsNameCancel":
          e.preventDefault();
          wsCloseNameDialog(null);
          break;
        default:
          break;
      }
    });
  }

  function initWorkspacePanel() {
    bindWorkspaceDelegatedUi();
    if (initWorkspacePanel._done) return;
    if (!$("workspaceList") && !$("btnWsNewFile")) return;
    initWorkspacePanel._done = true;
    $("wsUploadInput")?.addEventListener("change", (e) => {
      const input = e.target;
      if (input?.files?.length) uploadWsFiles(input.files);
      if (input) input.value = "";
    });
    $("wsUploadDirInput")?.addEventListener("change", (e) => {
      const input = e.target;
      if (input?.files?.length) uploadWsFiles(input.files);
      if (input) input.value = "";
    });
    $("wsFilter")?.addEventListener("input", (e) => {
      _wsFilter = e.target.value || "";
      renderWsTiles();
    });
    bindWsDropZone($("workspaceList"));
    $("wsBreadcrumb")?.addEventListener("dragover", (e) => {
      const crumb = e.target.closest?.("[data-ws-drop]");
      if (!crumb) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
    });
    $("wsBreadcrumb")?.addEventListener("drop", (e) => {
      const crumb = e.target.closest?.("[data-ws-drop]");
      if (!crumb) return;
      e.preventDefault();
      const dest = crumb.getAttribute("data-ws-drop") || "";
      const fl = e.dataTransfer?.files;
      if (fl && fl.length) uploadWsFiles(fl, dest);
      else if (wsSelectedItems().length) moveWsItems(wsSelectedItems(), dest);
    });
    $("wsNameInput")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        wsCloseNameDialog($("wsNameInput")?.value ?? "");
      } else if (e.key === "Escape") {
        e.preventDefault();
        wsCloseNameDialog(null);
      }
    });
    document.addEventListener("click", (e) => {
      const menu = $("wsContextMenu");
      if (menu && !menu.classList.contains("hidden") && !menu.contains(e.target))
        wsHideMenu();
    });
    wsApplyView();
  }

  initWorkspacePanel();
  if (window.__configModalReady && typeof window.__configModalReady.then === "function") {
    window.__configModalReady.then(() => initWorkspacePanel());
  }
  L.loadWorkspace = loadWorkspace;
  L.initWorkspacePanel = initWorkspacePanel;
  L.closeWsFileModal = closeWsFileModal;
  L.closeWsNameDialog = () => wsCloseNameDialog(null);
})(window.Lily || (window.Lily = {}));
