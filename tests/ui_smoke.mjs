// 前端状态同步的冒烟测试 / Frontend state-sync smoke test.
// 用一个最小 DOM 桩加载 web/index.html 的脚本，验证在终端输入
// :lang/:steps/:eta/:fast 后，本地 state 与界面会同步更新。
// Loads the web/index.html script under a minimal DOM stub and checks that
// typing :lang/:steps/:eta/:fast in the terminal updates local state and UI.
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

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
script = script.slice(0, idx) + "window.__test = { state: state };\n" + script.slice(idx);

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
const failures = [];
function check(name, cond, detail) {
  if (!cond) failures.push(`${name}: ${detail}`);
}

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

if (failures.length) {
  console.error("FAILURES:\n  " + failures.join("\n  "));
  process.exit(1);
}
console.log("ui state sync ok");
