# 变更记录 / Changelog

> 本文件主体为英文，最新版本附中文摘要。完整历史请继续阅读英文正文。
> The body of this file is in English; the latest release also has a Chinese
> summary above its English entry.

## 未发布 / Unreleased

### 新增 / Added

- 归约分析：`:shortest a , b` 用 BFS 在 redex 树上搜索到目标正规形的最短路径；`:growth <expr>` 同时跑应用序与正规序，输出每步项大小并在网页“曲线”面板作图。
  Reduction analysis: `:shortest a , b` performs BFS over redex paths, and `:growth <expr>` reports per-step term size for applicative vs normal order with a web chart.
- LSP 接入真实解释器：`textDocument/didOpen`/`didChange` 的诊断与 hover 类型都来自 `extension --batch --json`，二进制缺失时退回静态检查。
  The LSP now obtains diagnostics and hover types from the real interpreter, with a static fallback.
- 静态分享页可内嵌轨迹播放器：`POST /api/share/page` 接受 `trace`，生成的 HTML 自带步进/播放控制，内容全部转义。
  Static share pages can embed a trace player via the new `trace` field; all content is escaped.
- 测试新增一组（最短路径与规模曲线），共 69 组。
  One new test group (shortest path and growth); 69 groups total.
- 完善上一批能力：修正 System F 解析（类型抽象不再多出一层项抽象，`∀a. a → a` / `[Int]` 实例化正确），`:ftype` 结果接入“类型”面板；类型错误在终端回显中给失败子项画波浪线；推导步骤的焦点子项可点击插入；轨迹动画可录制 WebM；对比面板两侧改用独立会话归约。
  Completed the previous batch: fixed System F parsing (`∀a. a → a`, correct `[Int]` instantiation), `:ftype` now opens the Type panel, type errors underline the failing subterm, derivation focus is clickable, trace animations can be recorded as WebM, and the Compare tab uses two independent sessions.
- 元循环求值器 `lib/meta.lam`：用邱奇编码的 VAR/LAM/APP 在纯 λ 中定义 `EVAL`，可与解释器结果对照。
  A meta-circular evaluator in `lib/meta.lam`: Church-encoded VAR/LAM/APP and `EVAL` written in pure λ.
- System F 显式多态：`:ftype Λa. \x : a. x` 检查 `Λ` / 类型应用并给出擦除项；类型错误带失败子表达式，推导日志带焦点项。
  Explicit System F polymorphism via `:ftype`; type errors carry the failing subterm and derivations carry a focus term.
- 带注解递归 `rec f : T = e`：检查函数体类型并在类型环境保留方案；`:strategy need` 走共享抽象机，`:par` 一轮收缩所有 redex。
  Annotated recursion `rec f : T = e`; `:strategy need` uses the sharing machine and `:par` contracts all redexes per round.
- 网页新增“笔记”“对比”标签、AST redex 热力图、轨迹动画 HTML 导出、高对比/字号/`aria-live` 可读性控制，以及示例画廊入口。
  Web adds Notebook and Compare tabs, an AST redex heatmap, animated trace HTML export, accessibility controls and a gallery button.
- 工程工具：`tools/lsp.py`（.lam 的 stdio LSP）、`tools/benchmark.py`（基准日志与趋势图）、解析器 fuzz、示例画廊与 token 用量接口；测试共 68 组。
  Tooling: `tools/lsp.py`, `tools/benchmark.py`, parser fuzzing, gallery and token endpoints; 68 test groups.
- 数值编码切换：`:encoding church|scott`，`:church` / `:int` 支持两种编码；新增 `lib/scott.lam`（Scott 数、布尔、序对、惰性列表与双向转换），网页端增加编码选择器。
  Numeral encoding switch: `:encoding church|scott`, `:church` / `:int` support both encodings, plus `lib/scott.lam` (Scott numerals, booleans, pairs, lazy lists, conversions) and a web selector.
- `:machine <expr>`：环境 + 参数栈的带轨迹抽象机，不复制共享参数但保留精确步数与前后轨迹；网页工具标签提供入口。
  `:machine <expr>`: an environment/stack traced machine that shares arguments without copying yet reports exact steps and before/after traces; a Tools-tab entry was added.
- `:type` 的 JSON 增加 `derivation` 推导日志（统一、约束、泛化、实例化），网页“类型”面板可展开查看。
  `:type` now emits a `derivation` log (unify, bind, generalize, instantiate), expandable in the Type panel.
- `:stats <expr>` 报告节点数、深度、redex 数、自由变量、β/η 步数及是否为正规形。
  `:stats <expr>` reports node count, depth, redex count, free variables, β/η steps and normal-form status.
- 练习面板用 `:conv` 判题并记录进度；命令面板支持自然语言意图和拼写纠偏建议。
  A Practice panel checks answers with `:conv` and tracks progress; the command palette understands natural-language intents and fuzzy suggestions.
- 会话管理器：`GET /api/snapshots`、重命名与删除接口，网页“会话”标签可恢复/重命名/删除；快照支持 SQLite 后端以跨 worker 共享。
  A session manager with list/rename/delete endpoints and a Sessions tab; snapshots can use SQLite for cross-worker restore.
- 静态分享页：`POST /api/share/page` 与 `GET /api/share/page/<id>`，把对话渲染成自包含、带语言切换的 HTML。
  Static share pages: `POST /api/share/page` and `GET /api/share/page/<id>` render the transcript into a self-contained bilingual HTML page.
- `:prove` 的网页轨迹面板新增汇合菱形图；参考求值器 `tools/reference_eval.py` 与 Hypothesis 风格性质测试加入回归套件，总计 64 组。
  The proof view draws a confluence diamond; a reference evaluator and Hypothesis-style properties join the suite, now 64 groups.
- `:type` 现在把类型读作 Curry–Howard 命题，JSON 增加 `proposition` / `propositionZh` / `propositionEn` / `propositionFormula`，网页“类型”面板同步显示；`:prove` 的证明可在“轨迹”面板导出 Markdown / JSON / LaTeX。
  `:type` now reads the inferred type as a Curry–Howard proposition (`proposition` / `propositionZh` / `propositionEn` / `propositionFormula` in JSON), shown in the Type panel; proofs from `:prove` can be exported as Markdown / JSON / LaTeX.
- 新增“策略竞速”：工具标签页用同一表达式在四种策略下同时归约，竞速面板并排展示步数与结果，结束后恢复原策略；后端新增 `POST /api/race`。
  Added a strategy race: the Tools tab runs one expression under all four strategies and shows them side by side in the Race tab, restoring the original strategy; the backend gains `POST /api/race`.
- 会话快照：回放历史原子落盘到 `web/sessions.json`（`LAMBDA_SNAPSHOT_DB` 可覆盖，`off` 为内存模式），超时/过期后前端优先通过 `POST /api/session/<sid>/restore` 恢复；`/api/health` 增加 `snapshots` 计数。
  Session snapshots persist replay history to `web/sessions.json` (`LAMBDA_SNAPSHOT_DB`, `off` for memory); after a timeout/expiry the frontend restores via `POST /api/session/<sid>/restore`, and `/api/health` reports `snapshots`.
- 测试新增四组：快速模式与小步归约的随机差分（α 等价 + pretty 往返）、每条命令都有 UI 入口的静态检查、命题字段、竞速与快照接口；总计 58 组。
  Four test groups added: randomized fast-vs-step differential (alpha equivalence and pretty round-trip), a static every-command-has-a-UI-entry check, proposition fields, and race/snapshot endpoints; 58 groups in total.
- `:forward`（别名 `:redo`）重做被 `:back` 撤销的手动归约步骤；网页端在“上一步”旁提供“前进”按钮。
  `:forward` (alias `:redo`) redoes manual-reduction steps undone by `:back`; the web UI exposes a forward button next to back.
- 网页限流现在覆盖语言切换、取消、会话删除与分享读取等路由。
  Web rate limiting now covers language switch, cancel, session delete and share read routes.
- 新增 `:prove a , b`：输出 β 可转换性证明，含左右两边归约到共同正规式的完整步骤；网页端在“轨迹”面板并列展示两条序列，工具标签页提供入口。
  Added `:prove a , b`, a β-convertibility proof with both reduction sequences to the common normal form; the web UI shows the two sequences side by side in the Trace panel with a Tools tab entry.

### 修复 / Fixed

- 归约引擎：`:growth` 不再把刚访问的项误判为环，步数与曲线现在完整；抽象机改为真正共享 thunk（调用按需），引用处的绑定重命名不再捕获自由变量，轨迹前后项首尾相接。
  Reduction engines: `:growth` no longer flags a cycle after one step, so its step counts and curves are complete; the abstract machine now memoises thunks (call-by-need), and quoting binders no longer captures free variables, keeping trace steps chained.
- 快照归属现在写进 SQLite 表与 JSON 文件，重启和跨 worker 后仍生效；恢复不再全程持有全局锁，失败时清理新建会话；重命名/删除使用带 owner 条件的原子 SQL。
  Snapshot ownership is now persisted in SQLite and JSON, so it survives restarts and workers; restore no longer holds the global lock during replay and cleans up its session on failure; rename/delete use owner-conditional atomic SQL.
- 不可哈希的 `lang` 字段（数组/对象）现在回退 `both`，不再让六个接口抛 500；token 存储加入数量上限与空闲回收，无认证的 `/api/token` 不能无限增长。
  Unhashable `lang` values now fall back to `both` instead of raising 500 on six routes; the token store is capped and pruned so unauthenticated `/api/token` calls cannot grow it without bound.
- 网页：Ctrl+Enter 执行续行命令不再把裸换行拆成多条；补上未定义的 `--fg`；字号按钮改为缩放所有声明字号；证明摘要随语言切换刷新；手动归约条每步更新当前项。
  Web UI: Ctrl+Enter now joins continuation lines instead of sending raw newlines; the undefined `--fg` is declared; the font-size control scales every declared size; proof meta follows language switches; the manual bar updates its current term on every step.
- 工具：LSP 悬停正确换算 UTF-16 列并修正词尾边界，诊断保留中英双语，过滤 `:delete`/`:undo` 等有副作用别名；核心同步清单补齐 25 个原本未登记的共享声明；截图脚本改用 Chrome 自选调试端口并按真实倍率截取。
  Tooling: LSP hover converts UTF-16 columns and fixes the word-end boundary, diagnostics keep both languages, mutating aliases such as `:delete`/`:undo` are filtered; the core-sync manifest registers 25 previously untracked shared declarations; the screenshot script lets Chrome pick its debug port and captures at the real scale.
- 步数边界与抽象机：`:growth`/`:par` 在恰好用满步数且已归一时不再误报截断，`:par` 的一轮不再被吞掉；抽象机对中性 thunk 不再误判 β；`:machine` 在 η 开启时与小步引擎一致；跨步引用统一命名，轨迹前后项真正首尾相接。
  Step-limit boundaries: `:growth`/`:par` no longer report truncation at the exact limit when already normal, and `:par` no longer drops its first round; the machine no longer invents β work for neutral thunks; `:machine` honours η like the step engine; quoted binders use stable names so trace steps truly chain.
- System F 应用在函数位是未标注绑定（类型仍为变量）时不再误报“不是函数类型”，改为引入结果变量并合一。
  System F application now unifies a type-variable function position with an arrow instead of rejecting it as "not a function type".
- 快照 TTL / 数量回收现在能删除带归属的快照（此前会被 owner 条件挡住）；旧接口按命令数计费；非字符串会话 id 统一返回 400；分享页响应头不再重复 charset。
  Snapshot TTL/cap pruning can now delete owned snapshots (the owner filter used to block it); the legacy eval endpoint charges per command; non-string session ids return 400 consistently; share-page responses no longer duplicate the charset parameter.
- `:time <n> <expr>` 现在先去掉次数再解析表达式，不再解析错误对象。
  `:time <n> <expr>` now strips the run count before parsing the expression.
- 失效会话返回 410 + restart 而不是误报 408；流式求值的超时不再因心跳间隔而超时后延。
  Dead sessions return 410 + restart instead of 408; streaming timeouts no longer overshoot due to the heartbeat interval.
- 分享/本地存储的步数与布尔字段严格校验，命令回放统一走白名单。
  Share/local-storage limits and booleans are validated strictly; all replayed commands go through the whitelist.
- `:load` 行尾注释不再被误判为非法路径；`:edit` 的空白匹配与解释器一致。
  Trailing comments in `:load` no longer trip path checks; `:edit` whitespace matching now agrees with the interpreter.
- 桌面版选端口后立即绑定监听，消除了端口被抢占的竞态。
  The desktop wrapper binds and listens when picking a port, removing the port-stealing race.
- Web API 现在会剥掉行尾注释再做终端命令校验，`:quit -- bye` 不再绕过检查并杀死共享解释器。
  The web API strips trailing comments before the CLI-only check, so `:quit -- bye` can no longer kill the shared interpreter.
- 分享白名单补上 `:forward` 及其别名，使用“前进”按钮后仍可生成分享链接。
  The share allow-list now includes `:forward` and its aliases, so sharing works after using the forward button.
- 流式求值对非字符串会话 id 返回 400 而不是 500；输出持续不断时也会遵守总超时。
  Streaming returns 400 instead of 500 for a non-string session id, and now enforces the wall-clock deadline even when output keeps flowing.
- 会话回收不再误杀正在执行命令的会话；反向代理下限流按真实客户端 IP 分桶。
  Session reaping no longer kills a busy session, and rate limiting keys on the real client IP behind a reverse proxy.
- `:load`/`:save` 对解析后的路径复核隐藏段与后缀，堵住符号链接绕过。
  `:load`/`:save` re-check hidden segments and suffix on the resolved path, closing a symlink bypass.
- 内联类型标注支持 `List Int` 这类空格分隔的构造子应用，与 `:type expr : T` 一致。
  Inline annotations accept space-separated constructor application like `List Int`, matching `:type expr : T`.
- 类型标注里的变量改为刚性：`\x.x : a -> b` 不再被误报为 `t0 -> t0` 的实例。
  Annotation variables are now rigid: `\x.x : a -> b` is no longer reported as an instance of `t0 -> t0`.
- 步数、超时、节点上限等数值参数改为带范围校验的整数解析，超大数字不再静默回绕。
  Numeric options now use bounded integer parsing, so oversized values are rejected instead of wrapping around.
- `:back`/`:forward`/`:goto` 的输出重新附带当前项的可归约位置，回退后仍能选择 redex。
  `:back`/`:forward`/`:goto` now carry the redex list again, so an alternative redex can be picked after rewinding.
- 网页端：补全弹窗的 Escape 不再误取消求值，Ctrl+K 不再叠加弹窗；语言切换保留警告错误码并翻译 `:int` 元信息；重建/清空不再引发连环取消，历史里的 `:lang` 不会覆盖当前语言。
  Web UI: Escape on autocomplete no longer cancels evaluation, Ctrl+K no longer stacks dialogs; language switch keeps warning codes and translates `:int` meta; rebuild/clear no longer cascade cancels, and replayed `:lang` lines no longer override the chosen language.
- `main` 的 `:steps` 与扩展版一样拒绝超大数字，不再按补码回绕；`:time` 的次数超出 1-1000 时明确报错，不再把整个输入当表达式求值。
  `main` now rejects overflowing `:steps` like the extension; `:time` reports an out-of-range run count instead of silently evaluating a different term.
- Web API 对合法但非对象的 JSON 请求体统一返回 400 `bad_request`，不再在四个路由上抛出 500。
  The web API returns 400 `bad_request` for valid non-object JSON bodies instead of a 500 on four routes.
- 测试套件新增三个覆盖组（命令/CLI 边界、CLI 与差分、Web 边界）并大幅扩展 Node UI 冒烟测试：54 组全部通过。
  The test suite adds three groups (command/CLI edges, CLI & differential, web edges) and a much larger Node UI smoke test; all 54 groups pass.

## 最新版本中文摘要 / Latest release in Chinese

### 2.2.3 — 2026-11-14

- 修复：测试套件与核心同步工具现在无论控制台代码页如何都以 UTF-8 输出，
  Windows CI（cp1252）打印中文失败详情时不再崩溃。

## 2.2.3 — 2026-11-14

### Fixed

- The test suite and the core-sync tool write UTF-8 regardless of the
  console code page, so the Windows CI runner (cp1252) no longer fails
  while printing a Chinese failure detail.

## 2.2.2 — 2026-11-13

### Fixed

- Deeply nested `let` bindings used to blow up the parser: ReadP's built-in
  `many`/`sepBy` enumerate one candidate per prefix, so the alternatives
  multiplied until a 30-deep chain never finished and could exhaust memory.
  The parser now absorbs one longest match per step (greedy combinators) and
  `\x->x` still parses.
- Type inference now stops with an error once its step budget is exceeded or a
  single type grows too large: nested `let`s doubled the type at every level,
  so `:type` on a deeply nested term could grind forever.
- The core-sync check now compares the reduction loop (`evalUntil`) and the
  shared parser between `main.hs` and `extension.hs`; before, only their
  existence was verified, so a one-sided change to the evaluation loop went
  unnoticed. The one known difference (the minimal REPL's `TraceStep` has no
  "before" term) is normalised, and the test suite proves that a one-sided
  change fails while the same change on both sides passes.
- `.lam` loading reports the right definitions and errors: `:del`/`:reset`
  remove entries from the load summary, every failure carries its own `code`,
  `--max-term-size` also bounds loaded definitions, and `:reload` works after
  startup files. Multi-line logical lines continue while square brackets stay
  open, and the REPL does the same.
- `:type` rejects expressions that mention a defined name without a simple type
  instead of treating it as a free variable, and a redefined prelude name keeps
  its inferred scheme in `:env`, `:def` and `:save` instead of being hidden as a
  built-in. Help lists the full prelude.
- `:lang` and the language acknowledgement from a loaded file include the new
  language, so the web UI can follow file settings.
- Web UI: warnings keep their reason text, definition/delete/reset/load refresh
  the environment once instead of per line, settings from `:load` update the
  controls, editor bracket matching covers square brackets, the environment
  panel heading is translated, and a session that cannot be created is
  reported instead of only dimming the connection badge. Web backend:
  environment limits are clamped, rate-limit buckets are bounded, reaped
  sessions are killed outside the session lock, and streaming line splitting
  matches `/api/eval`.
- The web API refuses terminal-only commands (`:q`, `:quit`, `:edit`) with the
  new `cli_only` code, so a direct client cannot quit the session or start a
  server editor.
- A shared link keeps its strategy: the UI applied the strategy reported by
  every evaluation result, so replaying the history overwrote the shared
  setting. Only a loaded file changes the controls now.
- The web terminal shows the real message again: in the streaming mode every
  interpreter error was treated as a failed request and displayed as
  "request failed". Only the backend's stream-level failures end a request.
- The web editor joins multi-line input like the command line REPL, so a term
  wrapped over several lines is one command instead of several parse errors.
- Piped input is read as UTF-8 again: Haskeline decoded a redirected stdin with
  the console code page, so a UTF-8 file piped into the REPL came out garbled.
  Each stream also picks its encoding on its own instead of following stdout.
- Type inference is skipped for terms above the node budget: every JSON result
  inferred the type of the expression again, and a 200-element list literal took
  12 s to evaluate while a 400-element one never finished. `:type` now reports
  that the inference was skipped.
- Sessions with `:type`, `:trace`, `:eq` or the manual-reduction controls can be
  shared again: the share allow-list now accepts read-only queries,
  definitions and the manual-reduction commands, and only file, session and
  environment commands stay rejected.
- A client that disconnects from a streaming request now ends the session
  instead of leaving the command running and its output queued for the next
  request.
- The share store read from disk keeps only the newest unexpired entries, and
  the legacy one-shot `{code}` endpoint honours `LAMBDA_MAX_TERM_SIZE`.
- `$EDITOR` may now carry arguments (`EDITOR="code --wait"`); a path that
  contains spaces still works.
- The web backend reaps its interpreter processes when the server shuts down,
  and the desktop wrapper no longer creates a user directory when it runs from
  a source checkout.

## 2.2.1 — 2026-11-09

### Fixed

- The desktop build no longer flashes a console window on Windows: child
  `extension.exe` processes are started with `CREATE_NO_WINDOW` and a hidden
  `STARTUPINFO` while PyInstaller keeps the desktop app itself windowed.

## 2.2.0 — 2026-11-09

### Added

- CLI one-shot modes: repeatable `-e/--eval <cmd>`, `--check <file>` (exit 0/1),
  and `--strategy` / `--steps` / `--eta[=on|off]` / `--fast[=on|off]`.
- Surface syntax: `if c then t else f`, multiple sequential
  `let x = e1; y = e2 in e3` bindings, and list literals `[a, b, c]`.
- REPL commands `:back`, `:goto <n>`, `:def <name>`, `:search <substring>`,
  `:reload`, and `:edit [file]`, plus filename completion for
  `:load`/`:save`/`:edit`.
- Manual reduction keeps a history; the web UI adds back/start buttons.
- `:time [n] <expr>` and `:bench` now report min/max and median/stddev.
- Prelude additions: `I K S B C W`, `XOR NAND MIN MAX DIV MOD`, and
  `APPEND REV LENGTH MAP FILTER FOLD RANGE ZIP`.
- `lib/prelude.lam` teaching library (`FACT`, `FIB`, `SUM`, `SORT`, `TAKE`,
  `DROP`, `ZIPWITH`, and more).
- Web: `POST /api/eval/stream` (SSE output plus heartbeats), persistent short
  shares in `web/shares.json`, optional `LAMBDA_RATE_LIMIT`, JSON/LaTeX trace
  export, and `waitress` + `HEALTHCHECK` in the Docker image.
- `--max-term-size <n>` (and `LAMBDA_MAX_TERM_SIZE` for the web backend) rejects
  input expressions above a node budget with `code: "term_too_large"`.
- `:type expr : T` now reports `expected`/`actual` with a readable mismatch.
- `tools/check_core_sync.py --fix` copies shared declarations from
  `extension.hs` into `main.hs`.
- `.github/workflows/release.yml` builds Windows EXE archives and macOS DMGs
  (x64 and arm64) on a `v*` tag or manual dispatch and publishes them to a
  GitHub Release.
- Desktop packaging via `desktop.py` + `pywebview` + PyInstaller: a Windows
  one-file EXE and macOS `.app` DMGs (x64 and arm64). `web/app.py` resolves
  frozen resources from `sys._MEIPASS`, and `LAMBDA_INTERP_CWD` keeps the
  interpreter in a writable user directory.

### Changed

- `rec` definitions use the call-by-value `Z` combinator, so simple recursion
  also works under applicative order when the branch does not need lazy `if`.
- The test suite grew to 48 groups and covers the CLI modes, new syntax,
  prelude/library, rewind commands, timing fields, SSE, share persistence and
  rate limiting.

### Fixed

- `:int` evaluates with normal order, so Church arithmetic is not affected by
  the selected strict strategy.
- `:type` annotation mismatch text no longer omits the expected and actual
  types in JSON.

## 2.1.0 — 2026-11-08

### Added

- Expression syntax: `let x = e1 in e2` (with expression-level let-polymorphism
  in `:type`), `(expr : T)` type annotations, and `--` comments at the end of
  any line.
- REPL multi-line input: a trailing `\` or unclosed parentheses automatically
  continue onto the next line.
- `.lam` files now accept more commands: `:eta`, `:fast`, `:trace`, `:ast`,
  `:db`, `:del`, `:reset`, `:let`, and `rec` definitions.
- New commands `:time <expr>` (reports elapsed time; JSON gains `elapsedMs`),
  `:bench <n> <expr>` (mean elapsed time over `n` runs), and `:help <cmd>`
  (per-command help).
- Bounded cycle detection: a repeated whole term during reduction produces a
  bilingual `warn`, and the JSON carries `code: "cycle_detected"`.
- A machine-readable `code` field on every `error` / `fail` / `warn` JSON
  object.
- Web API: `POST /api/session/<sid>/cancel`; `/api/health` now reports
  `version`, `uptime`, `shares` and `sessionsMax`; share payloads are checked
  against a command allow-list; idle sessions are reaped in the background; and
  error responses are unified JSON with a `code`.
- Web editor: syntax highlighting, bracket matching, line numbers, undo/redo, a
  command palette (Ctrl+K), categorised examples and progressive exercises,
  clickable error locations, focus-preserving trace playback, and ARIA /
  focus-trap / reduced-motion support.
- `tools/check_core_sync.py` verifies that the shared core stays in sync between
  `main.hs` and `extension.hs`, and is wired into CI.
- A multi-stage `Dockerfile` (ghc:9.6 → python:3.13-slim), `CONTRIBUTING.md`,
  and the `VERSION` file as the single source of truth for the version.
- CI sets up Node 22 so `tests/ui_smoke.mjs` actually runs, adds
  `macos-latest` to the matrix, and runs `cabal build all`,
  `python tools/check_core_sync.py` and
  `python -m compileall -q web tests tools`, with a 20-minute job timeout.

### Fixed

- Parser diagnostics recognise `→` and `->` when reporting a missing lambda
  separator.
- Redefining a name to an untypable term no longer keeps its stale type scheme
  (REPL and `:load`); `:type` on a defined-but-untypable name (`Y`, `rec`) says
  it has no simple type instead of reporting a free `t0`.
- Free variables are monomorphic in type inference (`:type x x` is an infinite
  type), and `generalize` applies the substitution to the environment.
- Web `:load`/`:save` resolve relative paths against the interpreter's working
  directory before checking `LAMBDA_LOAD_ROOT`, closing a confinement bypass;
  multi-line web input is split into single commands (no sentinel desync and no
  hidden `:load`), and request bodies are capped.
- `:ast`/`:db` respect the 400-node cap in both interpreters (a huge term used
  to hang), and `main` caps traces at 500 steps.
- `:whnf` stops at a top-level lambda.
- Substitution no longer α-renames when `x` is absent from the body, and a
  redex's listed rule agrees with the trace.
- Call-by-name stops at weak head normal form instead of reducing arguments of
  neutral heads.
- Church-numeral/boolean detection no longer misclassifies a shadowed binder.
- Fast mode is lazy, so Y recursion (e.g. `rec fact THREE`) reaches a normal
  form instead of exhausting fuel.
- `.lam` files are read as UTF-8, a leading BOM is stripped, and errors during
  reading are caught.
- `main` survives `Ctrl+C`.
- Web: typing `:lang` in the terminal syncs the UI; crafted share/localStorage
  state is validated; a failed fetch shows an error instead of rejecting
  unhandled; clearing during an evaluation no longer adopts the stale session;
  and a missing interpreter binary returns a clear 500 instead of an unhandled
  one.
- Tests now include regression coverage for each fix and a Node + minimal-DOM
  web UI test. The suite grew from 32 to 45 groups: the new groups cover
  `let` / annotations, timing and topic help, error codes, cycle detection and
  macro fuel, eta redex selection, recursive type environments, extended file
  commands, version sources, core sync, random terms, a performance budget,
  style conventions, and the 2.1.0 web API (cancel, 408, concurrency, TTL).
- Documentation fact fixes: the "no Cabal/Stack project" and Windows
  `-package` claims in README.md / README-CN.md / AGENTS.md, the "all three"
  screenshot wording in `tools/screenshot.py`, and the `video/` ignore note
  (now truly ignored via `.gitignore`).

### Changed

- Build scripts are split by platform: `build.sh` gains a shebang and `set -eu`,
  keeps the GNU ld flags (`-split-sections -optl-Wl,--gc-sections -optl-s`) on
  Linux only (via `uname -s`), and makes `-optlc-march=native` opt-in under
  `LAMBDA_NATIVE=1`; `build.bat` uses `@echo off` / `setlocal`, checks for
  `ghc` and `errorlevel`, and carries no `-march=native` or GNU ld flags. Both
  keep `-O2 -Wall -threaded -rtsopts -package containers -package haskeline
  -package directory`, matching the Cabal `ghc-options`.
- `VERSION` is now the single source of truth for the version; the Cabal
  package moves to 2.1.0 and lists `VERSION`, `CONTRIBUTING.md` and `Dockerfile`
  in `extra-source-files`.
- `.gitignore` adds `/video/`, `/docs/screenshots/`, `*.mp4`, `/out/` and
  `.workbuddy/` (local agent notes) without dropping existing entries; the
  promo video no longer relies only on `.git/info/exclude`.

### Performance

- Bounded cycle detection stops divergent reductions at the first repeated
  whole term instead of consuming the full step budget.
- Background reaping of idle web sessions bounds the number of live
  `extension --batch --json` processes.
- Linux builds keep the section-stripping link flags for smaller binaries,
  while `-optlc-march=native` is opt-in via `LAMBDA_NATIVE=1` so default
  artifacts stay portable.

## 2.0.0 — 2026-11-03

### Added

- `:eq` (α-equivalence) and `:conv` (β-convertibility), with commas separating
  the two expressions.
- `:nf` and `:whnf` for full normal forms and weak head normal forms.
- `:eta on|off` (η reduction `λx. f x → f`), in both interpreters.
- Redex enumeration and picking: `:begin` lists every β-redex, `:step <n>`
  contracts a chosen one, and JSON exposes `redexes`/`redexCount`.
- Expanded prelude: `EXP`, `PRED`, `SUB`, `ISZERO`, `LEQ`, `EQ`, `PAIR`, `FST`,
  `SND`, `NIL`, `CONS`, `HEAD`, `TAIL`, and `Y`.
- `:int` / `:church` to decode and encode Church numerals.
- Recursive definitions: `rec name = expr` and `:let rec name = expr`.
- `:save` with a parser-readable source printer; recursive definitions are
  written back as `rec`.
- Definition files now support `--`/`#` comments, indented or parenthesised
  continuation lines, and in-file `:strategy` / `:steps` / `:lang` commands.
- Multiple startup files, `--lang=zh`, `--version`, and errors for unknown
  options.
- Arrow lambda syntax: `λx → body` and `\x -> body`.
- Web: Tools tab for all new commands, clickable redex list, collapsible AST and
  an SVG graph view, copy/insert/define/export actions, play/pause and keyboard
  stepping, server-side short share links (`#s=<id>`), `/api/health`,
  `/api/session/<sid>/lang`, an SVG favicon, and zero-replay language switching
  via the new `textZh`/`textEn` protocol fields.
- `--timeout <s>` for a per-command wall-clock limit and `Ctrl+C` handling in the
  interactive REPL.
- `:eq`/`:conv` report errors from both sides when both expressions fail.
- `:fast on|off` (also a header toggle and a Tools button in the web UI):
  de Bruijn terms plus an environment/closure evaluator that shares arguments.
  It returns a normal form only, so there is no trace or exact step count, and
  `:steps` becomes a β fuel budget. `:trace`, `:whnf` and manual stepping stay
  on the step engine.
- Persistent Haskeline history in `~/.lambda_history`.
- A Cabal package that builds both standalone executables.
- MIT license, changelog, GitHub Actions CI, and 11 new test groups (31 total),
  including randomized properties and a `main`/`extension` differential test.

### Fixed

- α-equivalence now ignores binder names (`\a.a` is recognised as the `I`
  combinator); `toDB` no longer stores the binder name in `DLam`.
- `:load` reports the real file line after blank lines and continuations.
- `:env` includes types for user definitions, and the web Env panel displays
  them.
- `defined` and `main`'s strategy/step messages now follow the selected language.
- Expired web sessions return 410 instead of silently starting an empty
  environment.
- Traces are capped at 500 steps in memory, long terms are clipped, structured
  ASTs are capped at 400 nodes, and redex lists at 200 entries.
- The text environment table aligns CJK headers and values.
- `--help` is UTF-8 when redirected on Windows.
- The favicon 404 is gone.

### Performance

- Fast mode shares arguments instead of rebuilding the whole term per step:
  `MULT 400 400` goes from about 0.65 s and 1.2 GB (text mode) to about 0.06 s
  and 140 MB here, and `MULT 800 800` from about 12 s to about 0.2 s. The JSON
  path is still bounded by printing the resulting term.

- `shorten` is now lazy: it uses `splitAt` and forces only the requested
  prefix, and the trace's long-term test does the same. Clipping a huge term no
  longer pretty-prints it in full first. `MULT 20 (MULT 20 20)` JSON dropped from
  about 5.4 s and a 122 MB payload to roughly 0.04 s and a few hundred KB.
- The text `ast` and `db` views are bounded like `astTree` (400 nodes), so an
  8,000-node Church numeral can no longer produce a multi-megabyte tree.
- Substitution computes the argument's free variables once, shares subtrees that
  do not contain the substituted variable, and reports α-renaming in the same
  pass; a β step no longer scans the body twice.
- α-equivalence walks both binding environments in lockstep instead of
  allocating de Bruijn trees.
- Pretty printers (`pretty`, `sourceExpr`, `deBruijnView`, `prettyTy`) now build
  `ShowS` functions, removing the quadratic string concatenation on deep terms.
  A 1,200-step identity chain dropped from ~26 s to under a second locally.
- Trace JSON and its truncation flag are built in one pass, so `pretty` runs
  once per step instead of twice.
- Redex listing collects path, subterm and rule in one traversal and no longer
  performs a substitution just to label a rule.
- `evalUntil` uses strict step counters/accumulators (`BangPatterns`).
- `main` uses the same four-flag `Order` table as `extension` instead of four
  hand-written `stepOnce` copies.
- `.lam` continuation assembly is linear instead of repeated `++`.
- Builds and Cabal now pass `-Wall`; both files are warning-free.

### Changed

- The web language switch re-renders existing output from `textZh`/`textEn` in
  the same interpreter process; it no longer replays or rebuilds the session.
- Text convention: Chinese uses the full-width quotes `“ ”`, English uses ASCII
  `"` and `'`, and the corner brackets U+300C/U+300D are no longer used anywhere.
- `:save` is disabled over the web unless `LAMBDA_ALLOW_SAVE=1`.
- Prelude schemes are hidden in `:env` to keep the table readable.

### Notes

- Substitution still copies terms; recursive definitions under applicative
  order can grow exponentially by design. Use a smaller `:steps`, normal order,
  or a larger timeout.
