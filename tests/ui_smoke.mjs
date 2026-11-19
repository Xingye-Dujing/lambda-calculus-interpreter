// 前端状态同步的冒烟测试 / Frontend state-sync smoke test.
// 用一个最小 DOM 桩加载 web/index.html 的脚本，验证在终端输入
// :lang/:steps/:eta/:fast 后，本地 state 与界面会同步更新
// Loads the web/index.html script under a minimal DOM stub and checks that
// typing :lang/:steps/:eta/:fast in the terminal updates local state and UI.
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

// 未处理的 Promise 拒绝应让测试失败（网络错误必须被捕获）
// An unhandled rejection must fail the test (network errors must be caught).
let unhandled = 0;
process.on("unhandledRejection", () => { unhandled++; });

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const htmlPath = process.env.UI_HTML || path.join(root, "web", "index.html");
const html = fs.readFileSync(htmlPath, "utf8");

const match = html.match(/<script[^>]*>([\s\S]*?)<\/script>/);
if (!match) { console.error("no script found"); process.exit(1); }
let script = match[1];

// 暴露内部状态给测试 / expose internals for the test.
const marker = "})();";
const idx = script.lastIndexOf(marker);
if (idx < 0) { console.error("IIFE end not found"); process.exit(1); }
script = script.slice(0, idx) + "window.__test = { state: state, findBracketPair: findBracketPair, highlight: highlight, I18N: I18N, newSession: newSession, renderOutput: renderOutput, addErrorSnippet: addErrorSnippet, isStreamFailure: isStreamFailure, streamEval: streamEval, splitLogicalCommands: splitLogicalCommands, renderTrace: renderTrace, logicalCommandAt: logicalCommandAt, isSafeShareCommand: isSafeShareCommand, applySharePayload: applySharePayload, applyTranscriptLang: applyTranscriptLang, safeShareCode: safeShareCode };\n" + script.slice(idx);

function makeEl(tag = "div") {
  const el = {
    tagName: String(tag || "div").toUpperCase(),
    _listeners: {},
    _attrs: {},
    _cls: new Set(),
    other: {},
    value: "",
    textContent: "",
    innerHTML: "",
    className: "",
    hidden: false,
    disabled: false,
    checked: false,
    selectedIndex: 0,
    options: [],
    dataset: {},
    children: [],
    activeElement: null,
    style: { setProperty() {}, removeProperty() {}, getPropertyValue() { return ""; } },
    classList: {
      add: (c) => el._cls.add(c),
      remove: (c) => el._cls.delete(c),
      toggle: (c, f) => { if (f === undefined) { el._cls.has(c) ? el._cls.delete(c) : el._cls.add(c); } else if (f) el._cls.add(c); else el._cls.delete(c); },
      contains: (c) => el._cls.has(c),
    },
    addEventListener(t, fn) { (el._listeners[t] = el._listeners[t] || []).push(fn); },
    removeEventListener(t, fn) { const a = el._listeners[t]; if (a) { const i = a.indexOf(fn); if (i >= 0) a.splice(i, 1); } },
    dispatchEvent(ev) { (el._listeners[ev.type] || []).forEach((fn) => fn(ev)); return true; },
    setAttribute(k, v) { el._attrs[k] = String(v); },
    getAttribute(k) { return el._attrs[k]; },
    removeAttribute(k) { delete el._attrs[k]; },
    appendChild(c) { el.children.push(c); return c; },
    append(...cs) { el.children.push(...cs); },
    prepend(c) { el.children.unshift(c); },
    insertBefore(c) { el.children.unshift(c); return c; },
    removeChild(c) { const i = el.children.indexOf(c); if (i >= 0) el.children.splice(i, 1); return c; },
    querySelector(sel) {
      if (!el._q) el._q = {};
      if (!el._q[sel]) {
        const f = makeEl(sel === "select" ? "select" : "div");
        el._q[sel] = f;
      }
      return el._q[sel];
    },
    querySelectorAll() { return []; },
    closest() { return makeEl(); },
    contains() { return true; },
    focus() {}, blur() {}, click() {}, select() {}, setSelectionRange() {}, scrollIntoView() {},
    get scrollHeight() { return 0; },
    get scrollTop() { return el._scrollTop || 0; },
    set scrollTop(v) { el._scrollTop = v; },
  };
  return el;
}

const els = {};
const document = {
  documentElement: makeEl("html"),
  body: makeEl("body"),
  getElementById(id) { if (!els[id]) els[id] = makeEl(); return els[id]; },
  createElement(tag) { return makeEl(tag); },
  querySelectorAll() { return []; },
  addEventListener(t, fn) { (document._l = document._l || {}); (document._l[t] = document._l[t] || []).push(fn); },
  removeEventListener() {},
  _l: {},
};

const sandbox = {
  console,
  document,
  setTimeout, clearTimeout, setInterval, clearInterval,
  Promise, JSON, Math, Date, String, Number, Boolean, Array, Object, RegExp, Error, Set, Map,
  TextDecoder, TextEncoder,
  encodeURIComponent, decodeURIComponent,
  btoa: (s) => Buffer.from(s, "binary").toString("base64"),
  atob: (s) => Buffer.from(s, "base64").toString("binary"),
  escape: globalThis.escape,
  unescape: globalThis.unescape,
  Event: class { constructor(type) { this.type = type; } },
  URL: { createObjectURL: () => "blob:x", revokeObjectURL: () => {} },
  Blob: class {},
  localStorage: { _s: {}, getItem(k) { return this._s[k] || null; }, setItem(k, v) { this._s[k] = String(v); }, removeItem(k) { delete this._s[k]; } },
  location: { hash: "", pathname: "/", search: "", origin: "http://localhost" },
  history: { replaceState() {} },
  navigator: {},
  matchMedia: () => null,
  fetch: async (url) => ({
    status: 200,
    json: async () => (String(url).includes("api/prelude") ? ["TRUE", "FALSE"] : { ok: true, session: "s", outputs: [] }),
  }),
};
sandbox.window = sandbox;
sandbox.self = sandbox;

// 用一个手工构造（含非法字段）的 #state= 链接启动，验证逐字段校验
// Boot from a crafted #state= link with invalid fields to exercise validation.
const badPayload = {
  v: 2, code: ["PLUS ONE TWO", 99], strategy: "evil",
  limit: -5, theme: "weird", lang: "xx", eta: false, fast: false,
};
sandbox.location.hash = "#state=" +
  Buffer.from(JSON.stringify(badPayload), "utf8").toString("base64url");

// 模拟 HTML 中策略下拉框的默认选中项 / simulate the select's default option.
document.getElementById("strategy").value = "applicative";
document.getElementById("lang").value = "both";

vm.createContext(sandbox);
try {
  vm.runInContext(script, sandbox, { timeout: 5000 });
} catch (e) {
  console.error("script failed:", e && e.stack ? e.stack : e);
  process.exit(1);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function typeAndEnter(line) {
  const cmd = document.getElementById("cmd");
  cmd.value = line;
  const ev = { key: "Enter", shiftKey: false, preventDefault() {} };
  for (const fn of (cmd._listeners["keydown"] || [])) fn(ev);
  await sleep(40);
}

await sleep(120); // let boot() settle

const state = sandbox.window.__test.state;
const findBracketPair = sandbox.window.__test.findBracketPair;
const highlight = sandbox.window.__test.highlight;
const failures = [];
function check(name, cond, detail) {
  if (!cond) failures.push(`${name}: ${detail}`);
}

// 编辑器括号匹配同时支持圆括号与方括号 / editor matching covers both pairs.
check("bracket pair parens",
      JSON.stringify(findBracketPair("([a])", 1)) === "[0,4]",
      JSON.stringify(findBracketPair("([a])", 1)));
check("bracket pair square",
      JSON.stringify(findBracketPair("[a]", 1)) === "[0,2]",
      JSON.stringify(findBracketPair("[a]", 1)));
check("bracket pair closing",
      JSON.stringify(findBracketPair("([a])", 5)) === "[0,4]",
      JSON.stringify(findBracketPair("([a])", 5)));
check("bracket pair mismatch",
      findBracketPair("(a]", 1) === null,
      JSON.stringify(findBracketPair("(a]", 1)));
check("highlight marks square bracket",
      String(highlight("[a]", [0, 2])).includes("tok-paren-match"),
      highlight("[a]", [0, 2]));

// 警告与失败行要显示机器可读的错误码 / warnings and failures show their code.
const outEl2 = document.getElementById("out");
const beforeCode = outEl2.children.length;
sandbox.window.__test.renderOutput(
  { kind: "warn", code: "timeout", text: "timed out", textZh: "超时", textEn: "timed out" },
  "PLUS ONE TWO", false);
sandbox.window.__test.renderOutput(
  { kind: "fail", code: "term_too_large", text: "too large", textZh: "过大", textEn: "too large" },
  "PLUS ONE TWO", false);
const warnLine = outEl2.children[beforeCode];
const failLine = outEl2.children[beforeCode + 1];
check("warn line shows its code",
      String(warnLine && warnLine.title || "").includes("timeout"),
      String(warnLine && warnLine.title));
check("fail line shows its code",
      String(failLine && failLine.title || "").includes("term_too_large"),
      String(failLine && failLine.title));

// 界面文案必须有中英文两套 / every UI string needs both languages.
const I18N = sandbox.window.__test.I18N;
const usedKeys = Array.from(new Set((html.match(/\bt\("([A-Za-z0-9_]+)"\)/g) || [])
  .map((m) => m.slice(3, -2))));
const missingKeys = usedKeys.filter((k) => !I18N[k]);
check("i18n keys complete", missingKeys.length === 0, missingKeys.join(","));
const untranslated = usedKeys.filter((k) => I18N[k] && (!I18N[k].zh || !I18N[k].en));
check("i18n strings bilingual", untranslated.length === 0, untranslated.join(","));

// Crafted share state must be validated field by field.
check("share code filtered",
      state.codeLines.length === 1 && state.codeLines[0] === "PLUS ONE TWO",
      JSON.stringify(state.codeLines));
check("share limit ignored", state.limit === 10000, "limit=" + state.limit);
check("share theme ignored", state.theme === "light", "theme=" + state.theme);
check("share lang ignored", state.lang === "both", "lang=" + state.lang);
check("share strategy ignored",
      document.getElementById("strategy").value === "applicative",
      "strategy=" + document.getElementById("strategy").value);

// 构造的分享字段不能把字符串当成布尔值，也不能写入超大步数
// Crafted share fields must not coerce strings to booleans nor set a huge limit.
sandbox.window.__test.applySharePayload({ eta: "false", fast: "false", limit: 1e9 });
check("share boolean strings ignored",
      state.eta === false && state.fast === false,
      `eta=${state.eta} fast=${state.fast}`);
check("share huge limit ignored", state.limit === 10000, "limit=" + state.limit);
check("share code whitelist drops :load",
      JSON.stringify(sandbox.window.__test.safeShareCode(
        ["PLUS ONE TWO", ":load secret.lam", ":q"])) === JSON.stringify(["PLUS ONE TWO"]),
      "safeShareCode");

// 切换语言后错误码提示的标题仍保留机器可读的 code
// Re-rendering the transcript must keep the code in error tooltips.
sandbox.window.__test.applyTranscriptLang();
check("transcript lang keeps error code title",
      String(warnLine && warnLine.title || "").includes("timeout")
      && String(failLine && failLine.title || "").includes("term_too_large"),
      `${warnLine && warnLine.title} / ${failLine && failLine.title}`);

// Bug: typing :lang in the terminal must update local state and the select.
await typeAndEnter(":lang zh");
check("lang state", state.lang === "zh", "state.lang=" + state.lang);
check("lang select", document.getElementById("lang").value === "zh",
      "select=" + document.getElementById("lang").value);
check("lang static text", String(document.getElementById("subline").textContent).length > 0,
      "subline empty");

await typeAndEnter(":steps 42");
check("steps state", state.limit === 42, "limit=" + state.limit);
check("steps input", String(document.getElementById("st-limit").value) === "42",
      "input=" + document.getElementById("st-limit").value);

await typeAndEnter(":eta on");
check("eta state", state.eta === true, "eta=" + state.eta);

await typeAndEnter(":fast on");
check("fast state", state.fast === true, "fast=" + state.fast);

// 网络错误必须被捕获并显示失败行，不能产生未处理的拒绝
// A network error must be caught and shown, not become an unhandled rejection.
sandbox.fetch = async () => { throw new Error("network down"); };
const outEl = document.getElementById("out");
const beforeLines = outEl.children.length;
await typeAndEnter("PLUS ONE TWO");
await sleep(40);
check("network error handled", unhandled === 0, "unhandled=" + unhandled);
check("network error shown", outEl.children.length > beforeLines,
      "lines " + beforeLines + " -> " + outEl.children.length);

// 会话创建失败必须给出提示，不能只显示“未连接”
// A failed session must be reported, not only shown as a dead connection.
const beforeSessionFail = outEl.children.length;
await sandbox.window.__test.newSession();
check("session failure reported",
      outEl.children.length > beforeSessionFail && state.session === null,
      "lines " + beforeSessionFail + " -> " + outEl.children.length +
      " session=" + state.session);

// 清空界面时仍在进行的旧请求，返回后不能覆盖新会话
// A stale request that returns after clearing must not overwrite the new session.
let releaseOld = null;
sandbox.fetch = (url, opts) => {
  const body = opts && opts.body ? JSON.parse(opts.body) : {};
  if (String(url).includes("api/eval") && body.session === "OLD") {
    return new Promise((resolve) => {
      releaseOld = () => resolve({
        status: 200,
        json: async () => ({ ok: true, session: "OLD", outputs: [] }),
      });
    });
  }
  if (String(url).includes("api/eval")) {
    return Promise.resolve({ status: 200, json: async () => ({ ok: true, session: body.session, outputs: [] }) });
  }
  return Promise.resolve({ status: 200, json: async () => ({ ok: true, session: "NEW", outputs: [] }) });
};
state.session = "OLD";
const cmdEl = document.getElementById("cmd");
cmdEl.value = "PLUS ONE TWO";
for (const fn of (cmdEl._listeners["keydown"] || [])) fn({ key: "Enter", shiftKey: false, preventDefault() {} });
await sleep(20); // the eval is now awaiting releaseOld
const clearEl = document.getElementById("clear");
for (const fn of (clearEl._listeners["click"] || [])) fn({});
await sleep(20); // clearAll created session "NEW"
if (releaseOld) releaseOld();
await sleep(40);
check("clear race keeps new session", state.session === "NEW", "session=" + state.session);

// 普通求值结果里的 strategy/eta 是解释器当前设置，不能覆盖界面上的选择
// The strategy/eta of an ordinary result are the interpreter's current
// settings and must not overwrite what the UI shows.
sandbox.fetch = async (url) => {
  if (String(url).includes("api/eval")) {
    return {
      status: 200,
      json: async () => ({
        ok: true, session: "NEW",
        outputs: [{ kind: "result", term: "x", strategy: "applicative",
                    eta: false, text: "r", textZh: "r", textEn: "r" }],
      }),
    };
  }
  return { status: 200, json: async () => ({ ok: true, session: "NEW", outputs: [] }) };
};
document.getElementById("strategy").value = "normal";
await typeAndEnter("PLUS ONE TWO");
await sleep(40);
check("result does not override the strategy",
      document.getElementById("strategy").value === "normal",
      document.getElementById("strategy").value);

// 静态可访问性与新 UI 入口检查 / static a11y and new-UI-entry checks.
// 无浏览器时用 HTML 断言兜底，真实交互仍由上面的 DOM 桩覆盖
// With no browser available, assert on the HTML; the DOM stub covers behaviour.
check("tabs expose aria-controls", /role="tab"[^>]*aria-controls=/.test(html)
      || /aria-controls="panel"/.test(html), "aria-controls missing");
check("skip link present", html.includes('id="skip-link"'), "skip-link missing");
check("reduced motion rule", html.includes("prefers-reduced-motion"),
      "prefers-reduced-motion missing");
check("cancel control present", html.includes('id="cancel-eval"'),
      "cancel-eval missing");
check("status type uses bilingual fields", /typeZh[\s\S]{0,120}typeEn/.test(html),
      "typeZh/typeEn not paired");
check("command palette wired", html.includes("Ctrl+K") || html.includes("ctrl+k")
      || html.includes("cmdPaletteTitle"), "command palette missing");
check("timing commands in UI", html.includes(":time") && html.includes(":bench"),
      ":time / :bench UI entries missing");
check("cancel endpoint wired", html.includes("/cancel"), "cancel route missing");
// kind=term 的结果行不能继承终端卡片 .term 的盒子 / a "term" result line must not inherit the .term card box
check("term result line resets the card box",
      /\.line\.term\{[^}]*flex-direction:row/.test(html)
      && /\.line\.term\{[^}]*height:auto/.test(html)
      && /\.line\.term\{[^}]*border:0/.test(html),
      "the .line.term reset is missing");
// P0 修复：SVG 填充变量、I18N 键唯一、取消按钮初始禁用、复制失败回退
// P0 fixes: defined SVG fill var, unique I18N key, cancel disabled initially, copy fallback.
check("--card is defined for the AST SVG fill", /--card\s*:/.test(html),
      "--card CSS variable missing");
check("copied I18N key is unique", (html.match(/\n\s*copied\s*:/g) || []).length === 1,
      "duplicate copied I18N key");
check("share uses copiedLink", html.includes('t("copiedLink")'),
      "share link no longer uses copiedLink");
check("cancel button starts disabled", /id="cancel-eval"[^>]*disabled/.test(html),
      "cancel button is not disabled initially");
check("cancel toggle helper exists", html.includes("function setCancelActive"),
      "setCancelActive helper missing");
check("copy failure restores via fallback",
      html.includes("copyFailed:") && html.includes('toast(t("copyFailed"))'),
      "copy failure fallback missing");
// 阶段 2：Trace 删除高亮、历史持久化、运行当前逻辑命令
// Stage 2: trace deletion highlight, history persistence, run-current-command.
check("trace diff marks deletion", html.includes("<del>") && html.includes("</del>"),
      "before row has no <del> highlight");
check("history persisted locally", html.includes("history: state.history.slice(-100)"),
      "command history not written to localStorage");
check("history restored on boot", html.includes("saved.history"),
      "command history not restored on boot");
check("Ctrl/Cmd+Enter runs current command",
      html.includes('e.key === "Enter" && (e.ctrlKey || e.metaKey)'),
      "Ctrl/Cmd+Enter handler missing");
// 外部分享载荷必须过白名单，不能注入 :load/:reset/:q 等命令
// External share payloads must pass the whitelist.
const safeCmd = sandbox.window.__test.isSafeShareCommand;
check("share allows plain expressions", safeCmd("PLUS ONE TWO") === true, "plain term rejected");
check("share allows safe settings", safeCmd(":strategy normal") === true, ":strategy rejected");
check("share rejects file commands", safeCmd(":load secret.lam") === false, ":load accepted");
check("share rejects session commands", safeCmd(":reset") === false, ":reset accepted");
check("share rejects quit", safeCmd(":q") === false, ":q accepted");
check("share rejects control chars", safeCmd("id = x\x1ey") === false, "RS accepted");
check("share rejects unicode separators", safeCmd("x\u2028y") === false, "separator accepted");
check("share allows comments", safeCmd("-- note") === true, "comment rejected");
check("retry does not re-record history",
      html.includes("原命令已在回放历史里"), "retry re-records the command");

// 其他第二轮修复的静态断言 / static assertions for the second round of fixes
check("trace playback updates only a frame",
      html.includes("function updateTraceFrame"), "frame-local playback update missing");
check("step list is keyboard operable",
      /<button type="button" class="st/.test(html), "step list is not a button");
check("AST SVG fits container", /\.ast-svg svg\{[^}]*max-width:100%/.test(html),
      "AST SVG has no fit-to-width rule");
check("error codes have help entries", html.includes("var ERR_HELP"),
      "error code help table missing");
check("exports are timestamped", html.includes("function fileStamp"),
      "export filenames are not timestamped");
check("network errors offer retry", html.includes("retry.textContent = dual"),
      "no retry affordance on network errors");
check("share short id is validated", /\[0-9a-f\]\{10\}/.test(html),
      "share short id is not validated");
check("IIFE end marker intact", script.includes("})();"), "IIFE marker missing");

// 流式帧：解释器的 error 输出是普通结果，只有后端的流级失败才算失败
// In a stream, an interpreter error is a normal output; only the backend's
// stream-level failure ends the request.
const isStreamFailure = sandbox.window.__test.isStreamFailure;
check("interpreter error is not a stream failure",
      isStreamFailure({ kind: "error", text: "boom", textZh: "boom", textEn: "boom",
                        code: "parse_error" }) === false, "interpreter error");
check("backend error is a stream failure",
      isStreamFailure({ kind: "error", ok: false, error: "boom" }) === true,
      "backend error");
check("timeout is a stream failure",
      isStreamFailure({ kind: "timeout", ok: false, timeout: true }) === true,
      "timeout");
check("expired is a stream failure",
      isStreamFailure({ kind: "expired", ok: false, restart: true }) === true,
      "expired");

function fakeStreamResponse(frames) {
  const enc = new TextEncoder();
  let i = 0;
  return {
    ok: true,
    body: {
      getReader() {
        return {
          read: async () => (i < frames.length
            ? { done: false, value: enc.encode(frames[i++]) }
            : { done: true, value: undefined }),
        };
      },
    },
  };
}
const realFetch = sandbox.fetch;
sandbox.fetch = async () => fakeStreamResponse([
  'data: {"kind":"start","session":"S"}\n\n',
  'data: {"kind":"error","text":"parse error","textZh":"x","textEn":"y","code":"parse_error"}\n\n',
  'data: {"kind":"done","ok":true,"session":"S"}\n\n',
]);
const streamed = await sandbox.window.__test.streamEval("\\x");
check("stream keeps interpreter errors as output",
      streamed && streamed.status === 200 && streamed.data.outputs.length === 1
      && streamed.data.outputs[0].code === "parse_error",
      JSON.stringify(streamed));
sandbox.fetch = async () => fakeStreamResponse([
  'data: {"kind":"error","ok":false,"error":"boom"}\n\n',
]);
const failed = await sandbox.window.__test.streamEval("\\x");
check("stream reports a backend failure",
      failed && failed.status === 500 && failed.data && failed.data.error === "boom",
      JSON.stringify(failed));
sandbox.fetch = realFetch;

// 多行输入按命令行的规则拼接 / multi-line input joins like the CLI REPL
const splitLogicalCommands = sandbox.window.__test.splitLogicalCommands;
check("multi-line term is one command",
      JSON.stringify(splitLogicalCommands("(\\x.x\ny)")) === JSON.stringify(["(\\x.x y)"]),
      JSON.stringify(splitLogicalCommands("(\\x.x\ny)")));
check("separate commands stay separate",
      JSON.stringify(splitLogicalCommands("PLUS ONE\nPLUS TWO"))
      === JSON.stringify(["PLUS ONE", "PLUS TWO"]),
      JSON.stringify(splitLogicalCommands("PLUS ONE\nPLUS TWO")));
check("trailing backslash continues",
      JSON.stringify(splitLogicalCommands("\\x.x \\\ny"))
      === JSON.stringify(["\\x.x y"]),
      JSON.stringify(splitLogicalCommands("\\x.x \\\ny")));

// 普通结果不能覆盖手动归约的 redex 列表
// A plain result must not replace the redex list of the manual reduction.
const renderOutput = sandbox.window.__test.renderOutput;
renderOutput({ kind: "term", term: "(\\x.x) a",
               redexes: [{ i: 1, path: "root", term: "(\\x.x) a", rule: "β" }] },
             ":begin (\\x.x) a", false);
check("manual redex list is set", state.redexes.length === 1, String(state.redexes.length));
renderOutput({ kind: "result", term: "x", redexes: [] }, "PLUS ONE TWO", false);
check("manual redex list survives a plain result", state.redexes.length === 1,
      String(state.redexes.length));

// 解析错误要给出错行与脱字符，而不是只把插入符丢在错误文字下面
// A parse error must point at the failing source column, not under the message text.
const snippet = sandbox.window.__test.addErrorSnippet(9, ":beigin 1");
const snipMain = snippet.children[0];
const snipSrc = snipMain.children[0];
const snipCaret = snipMain.children[1];
check("error snippet marks the source line", String(snippet.innerHTML).includes("↳"),
      String(snippet.innerHTML));
check("error snippet highlights the failing character",
      snipSrc.children.some((c) => c.textContent === "1"), JSON.stringify(snipSrc.children.length));
check("error snippet keeps the caret", snipCaret && snipCaret.textContent === "^",
      snipCaret && String(snipCaret.textContent));
check("error snippet caret is operable", snipCaret._attrs.role === "button"
      && snipCaret._attrs.tabindex === "0", JSON.stringify(snipCaret._attrs));

// Trace 前后对比同时标出删除与新增片段
// The trace comparison highlights both the removed and inserted fragments.
state.selected = {
  term: "axc",
  trace: [{ before: "abc", after: "axc", note: "beta" }]
};
state.tracePos = 0;
const traceHtml = sandbox.window.__test.renderTrace();
check("trace before has <del> of replaced fragment", traceHtml.includes("<del>b</del>"),
      String(traceHtml).slice(0, 240));
check("trace after has <ins> of replacement", traceHtml.includes("<ins>x</ins>"),
      String(traceHtml).slice(0, 240));
state.selected = null;

// Ctrl/Cmd+Enter 只定位光标所在的逻辑命令
// Ctrl/Cmd+Enter locates only the logical command under the caret.
const seg = sandbox.window.__test.logicalCommandAt("PLUS ONE TWO\nI", 0);
check("logicalCommandAt picks the first command", seg && seg.text === "PLUS ONE TWO",
      JSON.stringify(seg));
const seg2 = sandbox.window.__test.logicalCommandAt("PLUS ONE TWO\nI", 14);
check("logicalCommandAt picks the second command", seg2 && seg2.text === "I",
      JSON.stringify(seg2));

if (failures.length) {
  console.error("FAILURES:\n  " + failures.join("\n  "));
  process.exit(1);
}
console.log("ui state sync ok");
