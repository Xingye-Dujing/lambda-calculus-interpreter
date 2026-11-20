# 架构说明 / Architecture

本文件从实现角度梳理项目结构，与 [README.md](../README.md)、[README-CN.md](../README-CN.md) 的用户视角互补
This document describes the implementation from the code's point of view, complementing the user-facing READMEs
本文件描述的能力均已落入源码，测试与用法见测试套件和 README
All capabilities described here are implemented; see the test suite and READMEs for tests and usage

## 1. 概览 / Overview

- 两个独立、单文件 Haskell 解释器：`main.hs` 是最小核心 REPL，`extension.hs` 是功能完整的解释器
- Two independent single-file Haskell interpreters: `main.hs` is the minimal core REPL, `extension.hs` is the full one
- `main` 只有 `:q` 等基础 REPL；`extension` 增加定义、文件加载、轨迹、AST/de Bruijn、类型、redex 选择与批处理 / JSON 模式
- `main` is a bare REPL; `extension` adds definitions, file loading, traces, AST/de Bruijn views, types, redex picking and batch/JSON mode
- 刻意不抽共享库：核心声明在两个文件里各自保有一份，因此语义改动必须同步到两边
- There is deliberately no shared library: the core is duplicated, so semantic changes must land in both files
- `tools/check_core_sync.py` 用 `MUST_EXIST` / `MUST_MATCH` / `MUST_MATCH_CHECK` / `MUST_MATCH_MODULO` 提取同名顶层声明比对
- `tools/check_core_sync.py` extracts same-named top-level declarations and checks them with those four manifests
- `--fix` 把不一致的共享声明从 `extension.hs`（单一来源）复制回 `main.hs`；`evalUntil` 与共享解析器只比对不复制
- `--fix` copies differing shared declarations from `extension.hs` (the single source) into `main.hs`; `evalUntil` and the parser are only compared
- `extension.hs` 的专有部分：`Env = Map String Expr`、宏展开 `expand`/`expandTop`（带燃料）、定义、`:env`、数字字面量、类型系统与更宽的标识符字符
- `extension.hs` alone owns `Env = Map String Expr`, macro expansion with fuel, definitions, `:env`, numeric literals, types and wider identifiers
- 主构建是直接 `ghc` 编译两个文件；Cabal 只是把它们打包成两个同样独立的可执行文件
- The primary build compiles both files directly with `ghc`; Cabal merely packages the same two standalone executables

## 2. 核心数据模型 / Core data model

- 表达式只有三种构造子：`Expr = Var String | Lam String Expr | App Expr Expr`
- Terms have exactly three constructors: `Expr = Var String | Lam String Expr | App Expr Expr`
- `freeVars` 与 `freshVar` 是所有绑定操作的地基，`freshVar` 用追加 `'` 的方式避开冲突
- `freeVars` and `freshVar` underpin every binding operation; `freshVar` avoids clashes by appending `'`
- `substRename` 只计算一次参数的自由变量并贯穿整次替换，返回值同时报告是否发生了 α-重命名
- `substRename` computes the argument's free variables once and threads them through, also reporting whether α-renaming happened
- 不含被替换变量的子树返回 `Nothing`，调用方直接复用原树，替换因此是“共享而非盲目复制”
- A subtree without the substituted variable returns `Nothing`, so the caller reuses it: substitution shares instead of blindly copying
- `alphaEq` 在两个绑定环境上同步下降，不构造 de Bruijn 中间树；邱奇编码与组合子提示都靠它识别
- `alphaEq` walks both binding environments in lockstep with no intermediate de Bruijn tree, and powers all semantic hints
- 策略 `Strategy = Applicative | Normal | CallByName | CallByValue | Need`；实现细节是一个四布尔的 `Order`
- `Strategy` has five constructors — `Applicative`, `Normal`, `CallByName`, `CallByValue` and `Need`; the implementation reduces each to a four-boolean `Order`
- 四个开关是 `underLambda`（是否进入 λ 体）、`redexFirst`（是否先试根）、`argsToValue`（参数须先成值）、`argsIfLam`（头非 λ 时也归约参数）
- The flags are `underLambda`, `redexFirst`, `argsToValue` and `argsIfLam`; their combination selects the strategy
- 默认是 applicative（最左最内），对应历史的 `nf`；normal 先试根 redex，两个弱策略不进入 λ 体
- The default is applicative (leftmost-innermost), matching the historical `nf`; normal tries the root first and weak strategies stop at the head
- `stepOnce` 是小步引擎：每步返回整个重写后的项 `StepOut { soWhole, soRed }`，所以每条 `TraceStep` 都是真实的 before/after
- `stepOnce` is the small-step engine: each step rewrites the whole term into `StepOut { soWhole, soRed }`, so traces are genuine before/after pairs
- `betaStep` 根据是否重命名给出规则 `β` 或 `β+α`，并把双语说明写进 `redNote`
- `betaStep` labels the rule `β` or `β+α` and carries a bilingual note in `redNote`
- η 是独立规则：`etaRoot` / `etaStep` 实现 `λx. f x → f`（`x` 不在 `f` 中自由出现），`stepFor` 先试 β 再试 η
- Eta is a separate rule (`etaRoot`/`etaStep`) for `λx. f x → f`; `stepFor` tries β first, then η, and eta is off by default
- `isWHNF` / `headSpine` 判定弱首正规形（λ 或中性头应用）；`:whnf` 把它作为 `evalUntil` 的终止谓词
- `isWHNF`/`headSpine` detect weak head normal form; `:whnf` passes `isWHNF` as the stopping predicate
- `evalUntil` 是唯一求值循环：接受 `eta`、`keepTrace`、步数上限、策略和 `done` 谓词，返回 `EvalResult`
- `evalUntil` is the single evaluation loop; it takes `eta`, `keepTrace`, a limit, a strategy and a `done` predicate and returns `EvalResult`
- 轨迹步骤上限 500，长项裁切到 300 字符（`traceTruncated`）；默认步数上限 10000
- Traces keep at most 500 steps and clip terms to 300 characters; the default step limit is 10000
- 循环检测用滚动窗口：只在小于 `cycleTermLimit = 400` 的项里查重，窗口长度 `cycleCheckLimit = 2000`
- Cycle detection uses a rolling window over terms smaller than 400 nodes, with a 2000-term window; repeats emit `code: "cycle_detected"`
- redex 用路径 `[Int]` 枚举，`redexInfos` / `stepAt` / `stepAtIndex` 可 contract 任意 redex；JSON 中 `redexes` ≤ 200 而 `redexCount` 精确
- Redexes are addressed by `Path = [Int]`; `redexInfos`/`stepAt`/`stepAtIndex` contract any one of them, with `redexes` capped at 200 and exact `redexCount`
- 定义在定义时就被 `expandTop` 展开；递归定义编码为 `Z (λname. body)`，`prettyDef`/`sourceDef` 再把 `rec` 形式还原出来
- Definitions are expanded at definition time; recursion is `Z (λname. body)`, while `prettyDef`/`sourceDef` restore the `rec` form for display and saving
- 语法糖只存在于解析层：`if c then t else f` → `IF c t f`，列表 → `CONS`/`NIL`，多 `let` 嵌套；`(expr : T)` 标注在归约前擦除
- Sugar is parser-only: `if` → `IF`, lists → `CONS`/`NIL`, multiple `let`s nest, and `(expr : T)` annotations are erased before reduction
- `.lam` 加载由 `logicalLines` 跳过注释与空行、合并续行并保留原始行号，文件内设置由 `LoadOutcome` 应用
- `.lam` loading uses `logicalLines` to skip comments and join continuations while preserving line numbers; `LoadOutcome` applies in-file settings
- 解析基于 `ReadP`；`parseCommand` 返回带 1 基列号的 `Either ParseError Command`，`extension` 要求唯一完整解析
- Parsing uses `ReadP`; `parseCommand` returns `Either ParseError Command` with 1-based columns and `extension` requires exactly one full parse
- `--timeout <s>` 用 `System.Timeout` 包住每条命令，`Ctrl+C` 在 `handleLine` 处被捕获；`emitL` 对实际写入加掩码
- `--timeout` wraps each command in `System.Timeout`, `Ctrl+C` is caught around `handleLine`, and `emitL` masks the actual write

## 3. 快速模式 / Fast mode

- `:fast on` 让 `Eval` / `:nf` / `:conv` / `:int` 改走 `fastNormalForm`，避开小步引擎每步重建整项的代价
- `:fast on` routes `Eval`/`:nf`/`:conv`/`:int` to `fastNormalForm`, avoiding the cost of rebuilding the whole term each step
- `toDB` 把展开后的 `Expr` 转成 de Bruijn 项 `DB = DVar Int | DFree String | DLam String DB | DApp DB DB`
- `toDB` converts the expanded term into de Bruijn form, with bound variables as indices and free names kept as strings
- `FastVal = FastLam String (Int -> FastM FastVal) | FastGen Int | FastFree String | FastApp FastVal Int`
- `FastVal` holds closures taking thunk ids, generated names, free names and neutral applications
- `Thunk = Thunk DB [Int] | Done FastVal`：参数作为带 id 的 thunk 传入，`force` 首次求值时写回 `Done`，因此共享参数只算一次
- `Thunk` values are forced on first use and memoized as `Done`, so a shared argument is evaluated once
- `FastState` 保存 `fsFuel`、`fsNext` 与 `fsStore :: IntMap Thunk`；`FastM` 是 `State -> Either () (a, State)` 的极简 monad
- `FastState` carries fuel, a fresh-id counter and the thunk heap; `FastM` is a minimal state monad failing on `Left ()`
- `tick` 每发生一次 β 消耗一格燃料；`freshThunk` / `freshVal` 分配 thunk，`applyFast` 在闭包上消耗它
- `tick` spends one fuel unit per β; `freshThunk`/`freshVal` allocate heap cells and `applyFast` applies closures to them
- 惰性求值是关键：只有真正用到参数才 force，因此 `rec fact` 这类仅惰性终止的项也能得到正规形
- Laziness is the point: arguments are forced only when used, so terms such as `rec fact` that terminate only lazily reach a normal form
- `quoteFast` 把 `FastVal` 重新引用成 `Expr`，生成名避开原项自由变量；`fastNormalForm` 返回 `Maybe Expr`
- `quoteFast` reifies a `FastVal` back into `Expr` with fresh names, and `fastNormalForm` returns `Maybe Expr`
- 快速模式只给正规形：无轨迹、无精确步数、忽略所选策略与 η；`:steps` 退化为 β 燃料预算
- Fast mode yields a normal form only: no trace, no exact step count, strategy and η ignored; `:steps` becomes a β fuel budget
- `:trace`、`:whnf`、`:prove` 与手动归约始终走逐步引擎，不受 `:fast` 影响
- `:trace`, `:whnf`, `:prove` and manual stepping always use the step engine regardless of `:fast`

## 4. 轨迹抽象机 `:machine` / Traced machine

- 新命令 `:machine <expr>` 用环境 / 栈抽象机求值，而不是每次重写整棵语法树
- The new `:machine <expr>` command evaluates with an environment/stack abstract machine instead of rewriting the whole tree
- 机器的每一步记录一条“配置”（configuration）：当前控制项、环境与求值栈 / 续延，而不是只记录前后两个项
- Each step records a configuration: the current control term, the environment and the evaluation stack/continuation
- 配置转移严格对应一次归约，因此它既有逐步引擎的精确步数，又保留中间状态
- Each transition corresponds to exactly one reduction, giving both an exact step count and the intermediate state
- `Var` 查环境、`App` 压栈、`Lam` 形成闭包、出栈时以绑定环境 contract，整个过程中共享环境而非复制项
- `Var` looks up the environment, `App` pushes a frame, `Lam` builds a closure, and popping contracts with the captured environment
- 共享体现在两个层面：环境里的绑定与参数 thunk 只分配一次，轨迹引用配置而非重复打印膨胀的项
- Sharing happens at two levels: bindings and argument thunks are allocated once, and the trace references configurations rather than re-printing bloated terms
- 每个 β 步把机器配置 quote 回一个真实项，输出复用现有 JSON 轨迹形状（`rule`、`before`、`after`、`note`）
- Each β step quotes the machine configuration back into a real term; output reuses the trace JSON shape
- 有界保护：β 步数受 `:steps` 限制，另有独立的 administrative 步上限防止发散；轨迹裁切沿用 `traceFields`
- Bounds: β steps respect `:steps`, a separate administrative-step cap prevents divergence, and trace clipping reuses `traceFields`

## 5. 类型推断 / Type inference

- `Ty = TVar String | TArr Ty Ty | TCon String [Ty]`；`TCon` 承载 `Int`、`Bool`、`List T` 等具体构造子
- `Ty` covers type variables, arrows and concrete constructors such as `Int`, `Bool` and `List T`
- `Scheme = Forall [String] Ty` 表示多态方案；`TypeEnv = Map String Scheme` 是类型环境
- `Scheme = Forall [String] Ty` is a polymorphic scheme and `TypeEnv` maps names to schemes
- `TI` 是 `TISt -> Either String (a, TISt)` 的 monad，`TISt` 维护种子、新鲜编号、替换表和步数
- `TI` is a state monad over `TISt`, which tracks fresh-name generation, the current substitution and a step counter
- `unify` 做 unify 与 occurs check，`instantiate` 展开 `Forall`，`generalize` 用环境自由变量做 let 泛化
- `unify` performs unification with an occurs check; `instantiate` and `generalize` implement let-polymorphism
- 表达式级 `let` 脱糖后带内部标记 `@let:`；只有这种 `App (Lam x body) val` 才做 let 泛化，普通 β-redex 不泛化实参
- Expression-level `let` desugars with an internal `@let:` marker; only that `App (Lam x body) val` shape is generalized, while ordinary β-redexes do not generalize their argument
- 自由变量按单态处理（`inferScheme` 先给它们种下单态 `Forall []`），否则 `x x` 会被错误地类型化
- Free variables are seeded monomorphically, otherwise an expression like `x x` would wrongly type-check
- `typeBudget = 20000` 与 `typeSizeLimit = 1000` 防止嵌套 let 造成的指数增长，超限以 `failTI` 报告
- Budgets on unifier steps and type size stop the exponential growth from nested lets
- 推导日志：`TISt.tiLog` 记录 unify / bind / generalize / instantiate 步骤，`runTILogged` 返回日志，`:type` 的 JSON 以 `derivation` 字段输出，Type 面板可展开查看
- A derivation log in `TISt.tiLog` records unify/bind/generalize/instantiate steps; `runTILogged` returns it and `:type` emits it as `derivation` for the Type panel
- `propositionMsg` 按 Curry–Howard 把类型读作命题：箭头变成 `⇒`，量化的类型变量写作 `∀t0 …`
- `propositionMsg` reads a type as a Curry–Howard proposition: arrows become `⇒` and quantified variables appear as `∀t0 …`
- `:type expr : T` 校验标注是否只是推断类型的实例；JSON 给出 `matches`、`expected`、`actual`，而 `(expr : T)` 在归约前擦除
- `:type expr : T` checks whether an annotation is an instance of the inferred type and reports `matches`/`expected`/`actual`; `(expr : T)` is erased before reduction

## 6. 输出协议 / Output protocol

- 两种输出模式：带装饰的纯文本，以及每行一个 JSON 对象（JSON Lines）
- Two output modes: decorated text and one JSON object per line (JSON Lines)
- JSON 由极简 `J` ADT 构造：`JStr | JNum | JDec | JBool | JArr | JObj`，字段用 `(.=)` 追加而不是拼字符串
- JSON is built with the tiny `J` ADT and the `(.=)` operator rather than by concatenating strings
- `emitL st kind zh en fields` 写入 `kind`、`text`（当前语言）、`textZh`、`textEn`，再叠加领域字段
- `emitL` writes `kind`, `text` in the current language plus `textZh`/`textEn`, then the domain fields
- 结果额外带 `hintZh` / `hintEn`，类型额外带 `typeZh` / `typeEn`，命题带 `propositionZh` / `propositionEn` / `propositionFormula`
- Results add `hintZh`/`hintEn`, types add `typeZh`/`typeEn`, and propositions add their own Zh/En/formula fields
- 前端因此能在本地重渲染语言，而不重放命令或重建解释器
- These bilingual fields let the client re-render on language switch without replaying commands or rebuilding the session
- `withCode` 给 `error` / `fail` / `warn` 自动补上机器可读 `code`，例如 `cycle_detected`、`term_too_large`、`type_error`、`cli_only`
- `withCode` adds a machine-readable `code` to errors and warnings, such as `cycle_detected` or `cli_only`
- `--batch` 每行一条命令，并在每条结果后输出记录分隔符 `\x1e`；同时把 stdin/stdout/stderr 固定为 UTF-8
- `--batch` reads one command per line and emits the record separator `\x1e` after each result, with UTF-8 streams
- 表示层还有 `shorten` 惰性截断、400 节点的 `astTree` 上限与 `astTreeOmitted`，防止巨型项先被完整打印
- `shorten`, a 400-node `astTree` cap and `astTreeOmitted` keep huge terms from being fully printed

## 7. Web 后端 / Web backend

- `web/app.py` 是 Flask 封装，计算引擎仍是编译好的 `extension --batch --json`
- `web/app.py` is a Flask wrapper whose engine is still the compiled `extension --batch --json`
- 每个浏览器会话对应一个常驻子进程加一个读线程：`Interpreter` 用 `\x1e` 切分结果，写进 `_q` 或流式 `_stream_q`
- Each browser session owns one persistent child process and a reader thread; `\x1e` splits results into `_q` or `_stream_q`
- 定义、策略和步数因此保存在进程内，不必整段重放；超时杀掉会话并返回 408，过期返回 410 + `restart: true`
- State lives in the process, so no replay is needed; a timeout returns 408, expiry returns 410 with `restart: true`
- `POST /api/eval` 接 `{"session", "line"}`（旧 `{"code"}` 仍可用），另有 `/api/session`、`/api/prelude`、`/api/health`
- Routes include `/api/eval`, `/api/session`, `/api/prelude` and `/api/health`, with the legacy `{"code"}` form still accepted
- `POST /api/eval/stream` 用 SSE 输出 `start`、逐条结果、`heartbeat`、`done`；读线程逐行喂队列，长归约不会被请求超时杀死
- `/api/eval/stream` streams SSE frames and feeds a per-line queue so a long reduction is not killed by the request timeout
- `POST /api/race` 在同一会话里用 `:trace` 跑遍 applicative / normal / cbn / cbv 四种策略，结束后恢复原策略
- `/api/race` runs one expression under all four strategies via `:trace` and restores the original strategy afterwards
- 分享短链存到 `web/shares.json`（`LAMBDA_SHARE_DB`，`off` 为纯内存），`#s=<id>` 指向服务端载荷；`GET /api/share/<id>` 取回
- Short share links persist in `web/shares.json` (`LAMBDA_SHARE_DB`, `off` for memory only) and the frontend also accepts `#state=`
- 分享载荷按命令白名单校验：表达式、定义、设置与只读查询可分享，`:load`/`:save`/`:edit`/`:q` 等不可
- Share payloads are checked against a command allow-list, excluding file, session and environment commands
- 会话快照把回放历史写到 `web/sessions.json`（`LAMBDA_SNAPSHOT_DB`；也可替换为 SQLite 之类的存储），由 TTL 与数量上限约束
- Session snapshots persist replay history in `web/sessions.json` (a SQLite-style store could replace it), bounded by TTL and count
- `POST /api/session/<sid>/restore` 从快照重建死会话；前端在 408/410 时优先 restore，再退回本地重放
- `/api/session/<sid>/restore` rebuilds a dead session; on 408/410 the client tries restore before replaying locally
- `POST /api/session/<sid>/lang` 在运行的进程内切语言；`:q`/`:edit` 被拒绝并返回 `code: "cli_only"`，保证会话不被结束
- The lang route switches language in place, and terminal-only commands are refused with `cli_only` so the session stays alive
- `LAMBDA_RATE_LIMIT=<n>` 打开每 IP 令牌桶限流；`LAMBDA_LOAD_ROOT=*` 放开 `:load` 路径限制，`LAMBDA_ALLOW_SAVE=1` 才允许 `:save`
- A per-IP token bucket is opt-in; `:load` is confined to the interpreter directory unless `LAMBDA_LOAD_ROOT=*`, and `:save` needs `LAMBDA_ALLOW_SAVE=1`
- 解释器查找顺序：`$LAMBDA_INTERP_BIN` → `$LAMBDA_INTERP_DIR/extension[.exe]` → 仓库根目录 → `/opt/lambda-calculus-interpreter/extension`
- Interpreter lookup runs through those four locations in order
- 静态资源由 Flask 提供，`<base href="./">` 让页面在本地 `/` 与生产 `/lambda/` 前缀下都能工作
- Flask serves static assets and `<base href="./">` keeps the page working at both `/` and the `/lambda/` prefix

## 8. 前端 / Frontend

- `web/index.html` 是原生 JS 单文件终端 + 检查器，没有前端构建步骤
- `web/index.html` is a vanilla-JS single-file terminal plus inspector, with no frontend build step
- 检查器标签页为轨迹、竞速、结构、类型、环境、曲线、笔记、对比、练习、会话、工具、帮助、指引；练习放在练习标签，会话状态由会话标签里的分享与快照入口管理
- Inspector tabs are trace, race, AST, type, env, growth, notebook, compare, practice, sessions, tools, help and guide; exercises live in the Practice tab and session state is managed via share/restore controls in the Sessions tab
- 每个 `Command` 都有 UI 入口；`test_command_ui_coverage` 比对 `knownCommands` 与页面里的 `CMDS` 目录
- Every `Command` has a UI entry, enforced by comparing `knownCommands` with the page's `CMDS` catalogue
- 终端提供历史、Tab 补全、`Ctrl+L`、`Ctrl+K` 命令面板、错误定位，以及手动归约的 begin/back/forward/goto/step/run/end 按钮
- The terminal has history, completion, palette, error carets and manual-reduction controls
- `I18N` 字典负责界面文案，结果文本用 `textZh`/`textEn` 本地重渲染；提示用 `hintZh`/`hintEn`，类型用 `typeZh`/`typeEn`
- An `I18N` dictionary covers UI labels while result text comes from the bilingual JSON fields
- 禁止原生 `select` / `prompt` / `confirm` / `alert`：用自定义 `.sel` 菜单与 `dialog()` 保持线框主题一致
- Native dialogs are banned: custom `.sel` menus and the `dialog()` helper keep the wireframe theme
- 桌面布局是固定 `100vh` 的 flex 列，终端与检查器同行、各自内部滚动，页面本身不滚动
- The desktop layout is a fixed `100vh` flex column where terminal and inspector share a row and scroll internally
- 响应式规则放在样式表末尾：小于 900px 变单列整页滚动、标签栏吸顶；小于 600px 扩大触控目标并用 16px 输入避免 iOS 缩放
- Responsive rules sit at the end of the stylesheet, switching to one scrolling column below 900px and touch-sized controls below 600px
- `MatchMedia("(max-width:600px)")` 切换短占位符并显示一次 `narrowHint`；其余逻辑与断点正交
- `MatchMedia` swaps the short placeholder and shows a one-time narrow-screen hint; the rest of the logic is breakpoint-independent
- 首次访问默认浅色主题，切换结果写入 `localStorage`，不参考系统 `prefers-color-scheme`
- First visits default to the light theme and the choice is persisted in `localStorage`
- Guide 标签在无保存状态时打开；`:q` 与 `:clear` 在客户端截获，不发给解释器
- The Guide tab opens when there is no saved state, while `:q` and `:clear` are intercepted client-side
- 快速模式有两个入口（页首 `#fast-toggle` 与工具标签），都调用 `toggleFast` 发送 `:fast on|off` 并随分享链接传递
- Fast mode has two entries that both send `:fast on|off` and carry the flag in share links
- AST 面板提供可折叠 `astTree`、SVG 图与文本树；Type 面板显示 Curry–Howard 命题，证明视图导出 Markdown / JSON / LaTeX
- The AST panel offers a collapsible tree, an SVG graph and a text tree; the Type panel shows propositions and proofs export as Markdown/JSON/LaTeX

## 9. 测试 / Testing

- `tests/run_tests.py` 是端到端回归网：驱动编译好的 `extension --batch --json`，共 69 组
- `tests/run_tests.py` is the end-to-end regression net, driving the compiled binary through JSON across 69 groups
- 覆盖解析列号、β 归约、捕获避免、轨迹、五策略（含按需）、步数上限、邱奇提示、类型与命题、环境、文件加载、手动归约、η 与快速模式
- Groups cover parsing, reduction, capture avoidance, traces, five strategies (including Need), limits, hints, types, environment, files, manual reduction and modes
- 包含 Web API 会话 / 过期 / 语言切换、分享持久化、快照与竞速、SSE 流式、限流，以及 CLI 一次性与 `--check` 模式
- Web sessions, expiry, language switching, shares, snapshots, races, SSE, rate limits and CLI one-shot/check modes are covered
- 参考差分：`tools/reference_eval.py` 是无依赖的纯 Python 预言机（正规序 β、α 等价、de Bruijn 诊断），并与最小 `main` 二进制一起对照 `extension`
- Reference differentials use `tools/reference_eval.py`, a dependency-free Python oracle (normal-order β, α-equivalence, de Bruijn diagnostics), alongside a `main`/`extension` comparison
- 属性式随机检查用固定种子的 `random.Random`（Hypothesis 风格），例如 α 自反、跨策略一致性与 fast/step 差分
- Seeded `random.Random` drives Hypothesis-style properties such as α-reflexivity, cross-strategy agreement and fast/step agreement
- `tools/check_core_sync.py` 保证两个文件的共享核心一致，`--fix` 可从 `extension.hs` 同步
- The core-sync tool guards the duplicated core and can sync from `extension.hs`
- `tests/ui_smoke.mjs` 用 Node 的 DOM 桩加载前端脚本，验证 `:lang`/`:steps`/`:eta`/`:fast` 的状态同步
- `tests/ui_smoke.mjs` loads the page script under a Node DOM stub and checks local state sync
- CI 在 Ubuntu / macOS / Windows 上跑 GHC 9.6、Python 3.13、Node 22，并追加 `cabal build all`、`compileall` 与 Docker 健康检查
- CI covers Ubuntu/macOS/Windows with GHC 9.6, Python 3.13 and Node 22, plus Cabal, byte-compilation and a Docker health-check job
- `ghc -Wall`、测试里的风格检查与这套端到端套件就是全部检查手段，没有独立 linter
- `ghc -Wall`, the in-suite style checks and the end-to-end suite are the only checks; there is no external linter

## 10. 部署 / Deployment

- `build.bat` / `build.sh` 直接用 `ghc -O2 -Wall -threaded -rtsopts` 加四个 `-package` 参数编译两个文件
- The build scripts call `ghc` directly with four `-package` flags and produce `main` / `extension`
- `build.sh` 只在 Linux 追加 GNU ld 参数，`-march=native` 需 `LAMBDA_NATIVE=1`，macOS 保持可移植
- `build.sh` adds GNU ld flags on Linux only, makes `-march=native` opt-in and stays portable on macOS
- `VERSION` 是版本单一来源，Cabal 包、两个二进制与测试套件都必须与它一致
- `VERSION` is the single source of truth for Cabal, both binaries and the test suite
- 多阶段 Dockerfile 在 `ghc:9.6` 编译，再以 `python:3.13-slim` + `waitress` 提供服务，带 `HEALTHCHECK`
- A multi-stage Dockerfile builds on `ghc:9.6` and serves with `waitress` on `python:3.13-slim`, including a health check
- `waitress` 保持单进程多线程，与“会话在内存中”的模型一致；生产站点由 Caddy 用 `handle_path` 去掉 `/lambda/` 前缀
- Waitress stays single-process to match in-memory sessions, and Caddy strips the `/lambda/` prefix in production
- `desktop.py` 在回环端口启动同一个 Flask 应用，用 `pywebview` 打开；PyInstaller 打包 `web/`、`lib/`、`VERSION` 与 `extension`
- `desktop.py` starts the same Flask app on loopback in a `pywebview` window; PyInstaller bundles the web assets, lib, version and binary
- `web/app.py` 通过 `sys.frozen` / `sys._MEIPASS` 定位资源，`LAMBDA_INTERP_CWD` 指向可写用户目录；Windows 上子进程用 `CREATE_NO_WINDOW`
- Frozen builds resolve assets from `_MEIPASS`, and Windows child processes use hidden windows
- `.github/workflows/release.yml` 在 `v*` 标签或手动触发时构建 Windows zip、Linux tar.gz、macOS x64/arm64 DMG 与桌面版产物
- The release workflow builds Windows/Linux archives, macOS DMGs for x64 and arm64, and desktop artifacts on `v*` tags
- 所有产物附 SHA-256 校验文件，并用 `softprops/action-gh-release` 发布；桌面版未签名
- All artifacts carry SHA-256 checksums and are published with `softprops/action-gh-release`; desktop builds are unsigned

## 11. 教学与工程延伸 / Teaching and engineering extensions

- `lib/meta.lam` 用邱奇编码的 VAR/LAM/APP 代数类型与 `rec EVAL` 在纯 λ 中写出元循环求值器，环境是惰性值列表
- `lib/meta.lam` implements a meta-circular evaluator in pure λ using Church-encoded VAR/LAM/APP terms and a lazy environment
- `:ftype` 独立解析 System F 项（`Λ`、`\x : T.`、类型应用），用 `FEVar` / `FExprLam` / `FEAnnLam` / `FETyLam` / `FETyApp` 与 `FTy` 做显式类型检查，再擦除成普通 `Expr`
- `:ftype` parses System F terms with a separate AST and `FTy`, checks types explicitly, then erases to the ordinary `Expr`
- `rec f : T = e` 在类型环境中以 `Forall [] T` 自引用检查函数体，并把方案保留下来，普通 `rec` 仍然清掉方案
- Annotated recursion checks the body against `Forall [] T` and keeps the scheme; plain `rec` still drops it
- `Need` 策略在 `Eval` 处理器里改走带轨迹抽象机，共享参数 thunk；`parallelStep` 递归收缩每个互不包含的 redex
- The `Need` strategy routes `Eval` through the traced machine for shared thunks; `parallelStep` contracts every maximal redex recursively
- 类型错误会扫描 `subExprs` 给出 `failing` 子项，`TISt.tiLog` 记录 `(kind, Msg, focus)` 三元组供 Type 面板定位
- Type errors scan `subExprs` for a `failing` subterm; `tiLog` stores `(kind, Msg, focus)` triples for the Type panel
- 网页新增 Notebook / Compare / Practice / Sessions 标签、AST redex 热力图（`data-redex-node`）、动画 HTML 导出、高对比与字号控制
- Web adds Notebook / Compare / Practice / Sessions tabs, an AST redex heatmap, animated HTML export and readability controls
- `tools/lsp.py` 是 .lam 的 stdio JSON-RPC 服务器（诊断、补全、悬停）；`tools/benchmark.py` 记录 `:bench` 趋势并画 SVG
- `tools/lsp.py` is a stdio JSON-RPC server for .lam files; `tools/benchmark.py` records `:bench` trends and renders SVG
- 解析器 fuzz 把随机字符串喂给 `parseCommand`，要求每行都有合法 JSON 响应；`GET /api/gallery` 与 `POST /api/token` 提供示例与轻量用量统计
- Parser fuzzing feeds random strings to `parseCommand`; gallery and token endpoints serve curated examples and lightweight usage counts

## 12. 归约分析与工具链 / Reduction analysis and tooling

- `:shortest` 用广度优先搜索遍历 `redexInfos` / `stepAt` 生成的配置，遇到与目标 α 等价的项即返回；有配置数与步数上限
- `:shortest` traverses configurations from `redexInfos` / `stepAt` by BFS and stops at an α-equivalent target, bounded by both a step and a configuration cap
- `:growth` 对应用序与正规序各跑一次 `evalTraceWith`，把每步 `tsBefore` / `tsAfter` 的 `exprSize` 作为序列输出，网页“曲线”面板画折线图
- `:growth` runs `evalTraceWith` under two strategies and emits per-step `exprSize`; the web Growth tab draws the series
- `tools/lsp.py` 通过 `run_extension()` 调用真实的 `--batch --json` 解释器，诊断按行对应命令结果，hover 用文档中的定义 + `:type` 查询类型
- `tools/lsp.py` calls the real interpreter through `run_extension()`; diagnostics map to commands line-by-line and hover queries `:type` with document definitions
- 静态分享页的 `trace` 字段生成自包含步进播放器，所有文本经 `html.escape`
- The static share page's `trace` field renders a self-contained step player with all text escaped
