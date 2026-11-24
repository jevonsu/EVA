/**
 * DOM-free checks for evolution table helpers and XSS escaping.
 * Does not launch a browser or touch a running EVA.
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const src = fs.readFileSync(
  path.join(__dirname, "..", "app/static/js/app-session-persona.js"),
  "utf8"
);

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

const documentStub = {
  readyState: "complete",
  addEventListener() {},
  getElementById() { return null; },
  querySelector() { return null; },
};

const L = {
  $: () => null,
  state: {},
  escapeHtml,
  showToast() {},
  api: async () => ({}),
};

vm.runInNewContext(src, {
  window: { Lily: L },
  document: documentStub,
  console,
  setTimeout,
  clearTimeout,
  URLSearchParams,
});

assert.strictEqual(typeof L.evoQueryTable, "function", "evoQueryTable exported");
assert.strictEqual(L.EVO_PAGE_SIZE, 10);

const rows = [];
for (let i = 1; i <= 15; i++) {
  rows.push({
    content: i === 3 ? '<script>alert(1)</script>' : `条目${i}`,
    kind: i % 2 ? "fact" : "goal",
    tags: i % 2 ? ["t1"] : [],
    tag_names: i % 2 ? ["关系"] : [],
    source: "manual",
    scope: "session",
    updated_at: `2026-01-${String(i).padStart(2, "0")}`,
  });
}
const page2 = L.evoQueryTable(rows, { page: 2, pageSize: 10 });
assert.strictEqual(page2.total, 15);
assert.strictEqual(page2.page, 2);
assert.strictEqual(page2.items.length, 5);

const overflow = L.evoQueryTable(rows, { kind: "fact", page: 9, pageSize: 10 });
assert.strictEqual(overflow.page, 1);
assert.ok(overflow.total < 15);

const empty = L.evoQueryTable(rows, { q: "no-such-content" });
assert.strictEqual(empty.empty, true);

const xss = escapeHtml('<script>alert("x")</script>');
assert.ok(!xss.includes("<script>"));
assert.ok(xss.includes("&lt;script&gt;"));
assert.ok(xss.includes("&quot;x&quot;"));

const tagged = L.evoQueryTable(rows, { tag: "关系", pageSize: 10 });
assert.ok(tagged.total > 0);
assert.ok(tagged.items.every((e) => (e.tag_names || []).includes("关系") || (e.tags || []).includes("关系")));

// identity dropdown XSS + no roleplay fields in session modal
const optHtml = L.identitySelectHtml(
  [{ id: 'natural', label: '自然口语（说人话）' }, { id: '<img src=x onerror=alert(1)>', label: '<script>alert(1)</script>' }],
  '<script>x</script>'
);
assert.ok(!optHtml.includes("<script>"));
assert.ok(!optHtml.includes("<img"));
assert.ok(optHtml.includes("&lt;script&gt;"));
assert.ok(optHtml.includes("&lt;img"));
assert.strictEqual(L.mapLanguageId("跟随用户"), "follow_user");
assert.strictEqual(L.mapLanguageId("简体中文"), "zh-Hans");
assert.strictEqual(L.mapLanguageId("English"), "en");
assert.strictEqual(L.mapLanguageId("日本語"), "ja");
assert.ok(L.IDENTITY_DEFAULTS.language.some((o) => o.id === "inherit_public"));
assert.ok(L.IDENTITY_DEFAULTS.speech_style.some((o) => o.id === "natural" && o.label.includes("说人话")));

const modal = fs.readFileSync(path.join(__dirname, "..", "app/static/index.html"), "utf8");
const start = modal.indexOf("id=\"sessionPersonaBackdrop\"");
const end = modal.indexOf("id=\"sidebarScrim\"");
const sessionModal = modal.slice(start, end);
assert.ok(sessionModal.includes("spSpeechStyle"));
assert.ok(sessionModal.includes("讲话方式"));
assert.ok(!sessionModal.includes("spRoleplayEnabled"));
assert.ok(!sessionModal.includes("spRelationship"));
assert.ok(!sessionModal.includes("spExampleDialogue"));
assert.ok(!sessionModal.includes("启用角色扮演"));

const cfgHtml = fs.readFileSync(path.join(__dirname, "..", "app/static/html/config-modal.html"), "utf8");
assert.ok(cfgHtml.includes("cfgSpeechStyle"));
assert.ok(cfgHtml.includes("cfgRoleplayEnabled"), "public RP settings must remain");

console.log("ok", {
  page2: page2.items.length,
  factTotal: overflow.total,
  tagged: tagged.total,
  xssOptions: true,
});
