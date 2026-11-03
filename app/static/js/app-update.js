/* 新版本检测：左上角 EVA 名下显示版本号；无新版不显示。点击弹窗看说明 → 确认更新 / 取消 */
(function () {
  "use strict";
  var badge = null, info = null, busy = false;

  function esc(s) { var d = document.createElement("div"); d.textContent = String(s == null ? "" : s); return d.innerHTML; }
  function fmt(v) { v = String(v || "").trim(); return v ? (/^v/i.test(v) ? v : "v" + v) : ""; }

  async function check(force) {
    badge = badge || document.getElementById("evaUpdateBadge");
    if (!badge) return;
    try {
      var r = await fetch("/api/update/status" + (force ? "?force=true" : ""), { credentials: "same-origin", cache: "no-store" });
      if (!r.ok) return fail("HTTP " + r.status);
      info = await r.json();
      if (!info || !info.ok) return fail((info && info.error) || "检测失败");
      if (info.error) console.warn("[EVA update] 检测失败，使用上次结果：", info.error);
      if (!info.newer) {
        if (info.error) return fail(info.error);
        return hide();
      }
      badge.textContent = "新版本 " + fmt(info.remote && (info.remote.tag || info.remote.version));
      badge.title = info.error ? ("最新检测失败，显示的是上次结果：" + info.error) : "点击查看更新说明";
      badge.hidden = false;
    } catch (e) { fail(e && e.message ? e.message : String(e)); }
  }
  function fail(msg) {
    info = null;
    console.warn("[EVA update] 版本检测失败：", msg);
    if (!badge) return;
    badge.textContent = "更新检测失败";
    badge.title = "版本检测失败：" + msg + "（点击重试）";
    badge.hidden = false;
  }
  function hide() { if (badge) { badge.hidden = true; badge.textContent = ""; badge.title = ""; } }

  function waitBack(oldTag) {
    var tries = 0;
    var t = setInterval(async function () {
      tries++;
      try {
        var r = await fetch("/health", { cache: "no-store" });
        if (r.ok && tries > 2) { clearInterval(t); location.reload(); }
      } catch (_) {}
      if (tries > 120) clearInterval(t);
    }, 2000);
  }

  function openDialog() {
    if (!info || !info.newer) return check(true);
    var rm = info.remote || {};
    var mask = document.createElement("div");
    mask.className = "eva-upd-mask";
    mask.innerHTML =
      '<div class="eva-upd-box" role="dialog" aria-modal="true">' +
      "<h3>发现新版本 " + esc(fmt(rm.tag || rm.version)) + "</h3>" +
      '<div class="eva-upd-ver">当前 ' + esc(fmt(info.local && info.local.version)) + " → 最新 " + esc(fmt(rm.tag || rm.version)) +
      (rm.published_at ? " · " + esc(new Date(rm.published_at).toLocaleString()) : "") + "</div>" +
      '<div class="eva-upd-notes">' + esc(rm.notes || "（无版本说明）") + "</div>" +
      (info.hint ? '<div class="eva-upd-hint">' + esc(info.hint) + "</div>" : "") +
      '<div class="eva-upd-msg" hidden></div>' +
      '<div class="eva-upd-actions">' +
      '<button type="button" class="btn" data-act="cancel">取消更新</button>' +
      '<button type="button" class="btn primary" data-act="ok"' + (info.can_apply ? "" : " disabled") + ">确认更新</button>" +
      "</div></div>";
    document.body.appendChild(mask);
    var msg = mask.querySelector(".eva-upd-msg");
    var okBtn = mask.querySelector('[data-act="ok"]');
    function close() { if (!busy) mask.remove(); }
    mask.addEventListener("click", function (e) { if (e.target === mask) close(); });
    mask.querySelector('[data-act="cancel"]').onclick = close;
    okBtn.onclick = async function () {
      if (busy) return;
      busy = true; okBtn.disabled = true;
      mask.querySelector('[data-act="cancel"]').disabled = true;
      msg.hidden = false; msg.textContent = "正在下载并应用更新，请勿关闭页面…";
      try {
        var r = await fetch("/api/update/apply", { method: "POST", credentials: "same-origin" });
        var j = {}; try { j = await r.json(); } catch (_) {}
        if (!r.ok) throw new Error(j.detail || ("HTTP " + r.status));
        msg.textContent = j.message || "已更新";
        if (j.restarting) { msg.textContent += "（等待服务恢复后自动刷新）"; waitBack(); }
        else { busy = false; mask.querySelector('[data-act="cancel"]').disabled = false; }
      } catch (e) {
        busy = false; okBtn.disabled = false;
        mask.querySelector('[data-act="cancel"]').disabled = false;
        msg.textContent = "更新失败：" + (e && e.message ? e.message : e);
      }
    };
  }

  function init() {
    badge = document.getElementById("evaUpdateBadge");
    if (!badge) return;
    badge.addEventListener("click", openDialog);
    // 打开/刷新页面立即强制检测；之后每 60s 轮询，切回标签页时也强制检测
    setTimeout(function () { check(true); }, 800);
    setInterval(function () { if (!document.hidden) check(false); }, 60 * 1000);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) check(true); });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
  window.evaCheckUpdate = check;
})();
