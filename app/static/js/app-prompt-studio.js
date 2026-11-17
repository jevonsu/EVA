/* Grok提示词 — 主侧栏「新对话」与「工作区」之间的入口（独立文件，最小侵入） */
(function () {
  "use strict";
  var SRC = "/static/tools/imagine-prompt-studio.html?v=98-11101126";
  var overlay = null;
  function injectStyle() {
    if (document.getElementById("ipsOverlayStyle")) return;
    var st = document.createElement("style");
    st.id = "ipsOverlayStyle";
    st.textContent =
      ".ips-overlay{position:fixed;inset:0;z-index:9000;background:rgba(0,0,0,.55);backdrop-filter:blur(2px);display:flex;align-items:stretch;justify-content:center;padding:2vh 2vw}" +
      ".ips-overlay[hidden]{display:none}" +
      ".ips-panel{flex:1;display:flex;flex-direction:column;border-radius:14px;overflow:hidden;background:var(--surface,#1c1c1c);border:1px solid rgba(255,255,255,.1);box-shadow:0 16px 48px rgba(0,0,0,.45);max-width:1500px}" +
      ".ips-bar{display:flex;align-items:center;gap:8px;min-height:44px;padding:6px 10px 6px 14px;background:var(--sidebar-bg,#141414);color:var(--text,#fafafa);font-size:13px;border-bottom:1px solid rgba(255,255,255,.08)}" +
      ".ips-bar b{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:600}" +
      ".ips-bar button{flex:none;min-height:32px;border:1px solid rgba(255,255,255,.12);background:var(--surface-2,#262626);color:var(--text,#fafafa);border-radius:8px;padding:0 12px;cursor:pointer;font:inherit;white-space:nowrap}" +
      ".ips-bar button:hover{background:var(--surface-3,#333);border-color:rgba(255,255,255,.22)}" +
      ".ips-frame{flex:1;border:0;width:100%;background:#171717}" +
      "@media(max-width:720px){.ips-overlay{padding:0}.ips-panel{border-radius:0;border:0}.ips-bar{padding-top:calc(6px + env(safe-area-inset-top))}.ips-bar [data-ips=newtab]{display:none}}";
    document.head.appendChild(st);
  }
  function close() { if (overlay) overlay.hidden = true; document.removeEventListener("keydown", onKey); }
  function onKey(e) { if (e.key === "Escape") close(); }
  function open() {
    injectStyle();
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.className = "ips-overlay";
      overlay.id = "ipsOverlay";
      overlay.innerHTML =
        '<div class="ips-panel" role="dialog" aria-label="Grok提示词">' +
        '<div class="ips-bar"><b>🎬 Grok提示词</b>' +
        '<button type="button" data-ips="newtab" title="在新窗口打开">新窗口打开</button>' +
        '<button type="button" data-ips="close" title="关闭 (Esc)">关闭</button></div>' +
        '<iframe class="ips-frame" title="Grok提示词"></iframe></div>';
      overlay.addEventListener("click", function (e) {
        if (e.target === overlay) return close();
        var b = e.target.closest ? e.target.closest("[data-ips]") : null;
        if (!b) return;
        if (b.getAttribute("data-ips") === "close") close();
        else window.open(SRC, "_blank", "noopener");
      });
      document.body.appendChild(overlay);
    }
    var fr = overlay.querySelector("iframe");
    if (!fr.getAttribute("src")) {
      fr.addEventListener("load", function () {
        try { fr.contentWindow.document.addEventListener("keydown", onKey); } catch (_) {}
      });
      fr.setAttribute("src", SRC);
    }
    overlay.hidden = false;
    document.addEventListener("keydown", onKey);
  }
  function bind() {
    var btn = document.getElementById("btnQuickPromptStudio");
    if (!btn || btn.dataset.ipsBound) return;
    btn.dataset.ipsBound = "1";
    btn.addEventListener("click", function () {
      open();
      try { if (typeof closeMobileSidebar === "function") closeMobileSidebar(); } catch (_) {}
    });
  }
  window.evaOpenPromptStudio = open;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bind);
  else bind();
})();
