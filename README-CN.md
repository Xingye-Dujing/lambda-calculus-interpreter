# 支持邱奇数编码的 Lambda 演算解释器（[English](./README.md)）

一个用 Haskell 实现的纯 lambda 演算解释器：邱奇数、邱奇布尔值、序对与列表、无捕获替换、归约轨迹、四种求值策略、η 归约、简单类型推断，以及一个轻量的定义环境。提供两个独立可执行程序：

- `main` —— 最小核心 REPL。
- `extension` —— 支持定义、文件加载、归约轨迹、语法树 / de Bruijn 视图、类型推断、redex 选择、α/β 等价判断，以及供网页使用的批处理 / JSON 模式；输出中英双语。

## 在线使用

增强版解释器已提供网页界面：**<http://47.116.114.77/lambda/>**。页面代码位于 `web/`，由一层轻量 Flask 封装调用同一个编译好的 `extension` 二进制。

## 功能特点

- **纯 lambda 演算**：α 等价、无捕获替换。
- **归约轨迹**：记录每一步 β/η 归约的前后形态。
- **四种求值策略**：应用序、正规序、按名调用、按值调用（后两者为弱策略，停在弱首正规形）。
- **η 归约**：`:eta on|off` 在 `x` 不属于 `f` 的自由变量时执行 `λx. f x → f`。
- **快速模式**：`:fast on|off`（网页端也有开关）用共享环境和闭包求值，不再每步重建整项，大型 Church 算术会快很多。它只返回正规形：没有轨迹和精确步数，`:steps` 改作 β 燃料预算。
- **正规形**：`:nf` 归约到完整正规形，`:whnf` 停在弱首正规形。
- **任选 redex**：`:begin` 列出全部 β-redex，`:step <n>` 归约指定的一项；网页端直接点击。
- **等价判断**：`:eq a , b` 判断 α 等价，`:conv a , b` 判断 β 等价（两边都归约到正规形后比较）。
- **更丰富的表达式**：`let x = e1; y = e2 in e3`（`:type` 支持表达式内 let 多态）、`if c then t else f`、列表字面量 `[a, b, c]`、`(expr : T)` 类型标注，以及任意行尾的 `--` 注释。
- **REPL 多行输入**：行尾 `\` 或括号未闭合时自动续行。
- **计时与帮助**：`:time [n] <表达式>` 输出耗时与最小/最大值，`:bench <n> <表达式>` 给出平均/中位/标准差，`:help <cmd>` 显示分项帮助。
- **CLI 一次性模式**：`-e/--eval <命令>` 执行后退出，`--check <文件>` 校验 `.lam` 并以 0/1 退出，`--strategy/--steps/--eta/--fast` 无需文件即可配置一次运行。
- **手动回退**：`:back` 与 `:goto <n>` 在已保存的手动归约历史中移动；网页端也有对应按钮。
- **定义工具**：`:def <名字>`、`:search <子串>`、`:reload`、`:edit [文件]`，以及 `:load`/`:save`/`:edit` 的文件名补全。
- **有界循环检测**：归约中出现重复整项时给出双语 `warn`，JSON 带 `code: "cycle_detected"`。
- **机器可读的错误码**：所有 `error` / `fail` / `warn` 的 JSON 都带 `code` 字段。
- **步数上限**（默认 10000）：不终止的项给出提示，而不是卡死；`--timeout <秒>` 增加单条命令的墙钟上限，交互式 REPL 中可用 `Ctrl+C` 中断当前计算。
- **语义提示**：按 α 等价识别邱奇数 / 布尔值 / 序对，以及 `I K S B C W` 组合子；六个组合子现在也已定义。
- **预定义环境**：`TRUE FALSE NOT AND OR XOR NAND IF I K S B C W ZERO ONE TWO THREE SUCC PLUS MULT EXP PRED SUB ISZERO LEQ EQ MIN MAX DIV MOD PAIR FST SND NIL CONS HEAD TAIL APPEND REV LENGTH MAP FILTER FOLD RANGE ZIP Y`。
- **教材库**：`lib/prelude.lam` 提供 `FACT`、`FIB`、`ISEVEN`、`SUM`、`PRODUCT`、`CONCAT`、`TAKE`、`DROP`、`REPEAT`、`ANY`、`ALL`、`ZIPWITH`、`SORT`、`MAXLIST`、`MINLIST` 等。
- **简单类型**：Hindley–Milner 推断，支持 let 泛化（`:type`），含表达式级 let 多态与 `(expr : T)` 标注。
- **定义环境**：`name = expr`、递归定义 `rec name = expr`、`:let`、`:load`、`:save`、`:env`、`:del`、`:reset`。
- **定义文件**：`--` 或 `#` 注释、缩进/括号续行，以及文件内命令 `:strategy`、`:steps`、`:lang`、`:fast`、`:eta`、`:trace`、`:ast`、`:db`、`:del`、`:reset`、`:let` 与 `rec` 定义。
- **整数互转**：`:int <expr>` 解码邱奇数，`:church <n>` 编码 0–9999。
- **两种视图**：语法树（`:ast`）、网页端可折叠的结构化 AST、de Bruijn 索引（`:db`）。
- **中英双语**：所有面向用户的文本都有中英两种形式；用 `--lang zh|en|both` 或 `:lang` 切换（默认 `both`）。

## 界面截图

浅色主题，取自实际运行的网页界面。

![带归约轨迹的 REPL](docs/screenshots/main.png)

*归约轨迹：每一步的归约前后差异、步进播放器，结果附带步数与邱奇数释义。*

![语法树与 de Bruijn 视图](docs/screenshots/ast.png)

*结果的语法树，以及绑定变量的 de Bruijn 索引视图。*

![环境面板](docs/screenshots/env.png)

*环境面板：列出定义及其表达式与类型；点击名称插入，悬停删除。*

![使用指引](docs/screenshots/guide.png)

*内置使用指引在首次访问时打开，也可随时从“指引”标签页查看。*

在网页界面运行时重新生成截图：

```bash
pip install -r tools/requirements.txt
python tools/screenshot.py            # 或 tools\screenshot.bat
```

## 编译

```bash
./build.sh      # Linux / macOS
build.bat       # Windows
```

主构建方式是对两个独立单文件直接执行 `ghc` 编译，同时另附一个 Cabal 包。两个脚本都传入
`-O2 -Wall -threaded -rtsopts -package containers -package haskeline -package
directory -package process`，生成 `main` / `extension`（Windows 上为
`main.exe` / `extension.exe`）。`process` 只用于 `:edit`。
`build.sh` 仅在 Linux（通过 `uname -s` 判断）追加 GNU ld 链接参数
（`-split-sections -optl-Wl,--gc-sections -optl-s`），`-optlc-march=native` 需通过
`LAMBDA_NATIVE=1` 显式开启，macOS 保持可移植参数；`build.bat` 检查 `ghc` 与
`errorlevel`，不带 `-march=native` 与 GNU ld 专属参数。找不到 `ghc` 会直接报错退出，
两个脚本都会给出构建成功或失败的提示。

另提供 Cabal 文件，构建同样的两个独立可执行文件（刻意不拆共享库）：

```bash
cabal build all
cabal run extension -- --help
```

发布产物由 `.github/workflows/release.yml` 生成：推送 `v*` 标签（或手动运行工作流）会构建包含 `main.exe` / `extension.exe` 的 Windows `.zip` 与 x64/arm64 两份 macOS `.dmg`，连同 SHA-256 校验文件一起发布到 GitHub Release。

## 版本

仓库根目录的 `VERSION` 是版本单一来源（当前 2.2.0）；Cabal 包的版本号与
`./extension -v|--version` 都以此为准。发布历史见 [CHANGELOG.md](./CHANGELOG.md)。

## 使用方法

```bash
./extension [--lang zh|en|both] [--lang=zh] [--timeout 秒] [--batch] [--json] \
            [-e|--eval <命令>] [--check <文件>] [--strategy <策略>] [--steps <n>] \
            [--eta[=on|off]] [--fast[=on|off]] [--max-term-size <n>] \
            [-v|--version] [-h|--help] [文件...]
```

若给出文件，启动 REPL 前会按顺序加载其中的定义与命令。`test.lam` 是示例定义文件，其中 `ERR` / `ERROR` 两行故意写坏，用于演示加载错误报告。`-e/--eval` 执行一条或多条命令后退出（解析失败时退出码 1）；`--check` 只加载并校验文件，报告失败并以 0/1 退出，不进入 REPL。

### REPL 命令

| 命令 | 说明 |
| --- | --- |
| `:help [<命令>]` | 显示帮助，或显示某个命令的分项帮助 |
| `:load <文件>` | 加载定义/命令（`name = expr`、注释、续行） |
| `:save <文件>` | 用可被解析器重新读取的源码语法保存用户定义 |
| `:let name = expr` / `:let rec name = expr` | 定义变量 / 递归定义 |
| `:env` / `:del <名字>` / `:reset` | 查看（含类型）/ 删除 / 重置环境 |
| `:strategy applicative\|normal\|cbn\|cbv` | 切换求值策略 |
| `:steps <n>` | 设置归约步数上限 |
| `:eta on\|off` | 开启/关闭 η 归约 |
| `:fast on\|off` | 共享快速正规化（只给正规形，`:steps` 作为燃料） |
| `:trace <表达式>` | 打印完整归约轨迹 |
| `:time [n] <表达式>` | 输出耗时（JSON 增加 `elapsedMs`，n>1 时含最小/最大值） |
| `:bench <n> <表达式>` | 取 n 次的平均/中位/标准差耗时 |
| `:ast <表达式>` / `:db <表达式>` | 语法树 / de Bruijn 索引 |
| `:type <表达式>` | 推断简单类型（支持 let 多态与类型标注） |
| `:eq <a> , <b>` / `:conv <a> , <b>` | α 等价 / β 等价 |
| `:nf <表达式>` / `:whnf <表达式>` | 正规形 / 弱首正规形 |
| `:int <表达式>` / `:church <n>` | 解码 / 编码邱奇数 |
| `:begin <表达式>` / `:step [n]` / `:run` / `:end` | 交互式归约；`n` 选择 redex |
| `:back` / `:goto <n>` | 回退 / 跳到手动归约历史的第 n 步 |
| `:def <名字>` / `:search <子串>` | 显示单个定义 / 搜索环境 |
| `:reload` / `:edit [文件]` | 重新加载上次文件 / 用 `$EDITOR` 打开 |
| `:lang zh\|en\|both` | 切换输出语言 |
| `:q` | 退出 |

### 语法

- 变量：以字母或 `+ - * / % ^ ? ! < > | & ~ # $` 之一开头，后续可含字母、数字、`_`、`'` 或运算符。
- 抽象：`λx.body`、`λx → body` 或 `\x -> body`；多参数写为 `λx y.body`。
- 应用：`f a`，左结合；括号：`(expr)`。
- `let x = e1; y = e2 in e3` 依次绑定；`:type` 会对 let 绑定的名字做泛化（表达式级 let 多态）。
- `if c then t else f` 脱糖为 `IF c t f`；`[a, b, c]` 脱糖为 `CONS a (CONS b (CONS c NIL))`。
- `(expr : T)` 给表达式加类型标注；标注只做语法检查并在归约前擦除。用 `:type expr : T` 校验推断类型是否匹配（JSON 返回 `matches`、`expected`、`actual`）。
- `--` 注释可以出现在任意行尾，例如 `λx. x -- 说明`。
- 数字：`0`…`9999` 自动转为邱奇数。
- 定义：`name = expression`；递归：`rec name = expression`。
- 等价命令用逗号分隔两个表达式：`:eq \a.a , \b.b`。
- `.lam` 文件支持 `--` 或 `#` 注释行、缩进/括号续行，以及命令 `:strategy`、`:steps`、`:lang`、`:fast`、`:eta`、`:trace`、`:ast`、`:db`、`:del`、`:reset`、`:let` 与 `rec` 定义。
- REPL 多行输入：行尾 `\` 或括号未闭合时自动续行到下一行。

### 示例

扩展教材库是可选的；加载后配合快速模式运行递归 Church 算术：

```bash
./extension -e ':load lib/prelude.lam' -e ':fast on' -e ':int (FACT 5)'
# 120
```

```text
λ> PLUS ONE TWO
⇒ λf → λx → f (f (f x))  (6 步)  (邱奇数 3)

λ> :int (PRED THREE)
⇒ 2

λ> :eq \a.a , \b.b
⇒ α 等价：λa → a  ,  λb → b

λ> :conv PLUS ONE TWO , THREE
⇒ β 等价：λf → λx → f (f (f x))  ,  λf → λx → f (f (f x))

λ> :eta on
λ> :nf \x. f x
⇒ f  (1 步)

λ> :begin (\x.x) ((\y.y) z)
λ> :step 2
⇒ (λx → x) z

λ> :type \f.\x.f (f x)
⊢ (t0 → t0) → t0 → t0（多态）

λ> :strategy normal
λ> (\x.y) ((\x.x x)(\x.x x))
⇒ y  (1 步)          -- 正规序先丢弃参数，不会发散

λ> :steps 40
λ> (\x.y) ((\x.x x)(\x.x x))
⚠ 已达到 40 步上限，归约未完成
```

## 网页界面（`web/`）

`web/app.py`（Flask）为每个浏览器会话保留一个常驻解释器进程，直接使用 `--batch --json` 协议。

- 终端风格 REPL：历史、Tab 补全、`Ctrl+L`、错误位置指示。
- **编辑器**：语法高亮、括号匹配、行号、撤销重做、命令面板（`Ctrl+K`）、示例分类与渐进练习、可点击错误定位、轨迹播放保留焦点，以及 ARIA 标注 / 焦点陷阱 / reduced-motion。
- 实时面板：**归约轨迹**（步进播放器、播放/暂停、差异高亮）、**结构**（可折叠树 + 文本树）、**类型**、**环境**（点击插入、悬停删除、用户定义显示类型）。
- **工具**标签页：`:eq`、`:conv`、`:nf`、`:whnf`、`:int`、`:church`、`:eta`、递归定义与 `:save`；所有命令也可直接在终端输入。
- **redex 选择器**：手动归约模式下终端下方列出全部可归约位置，点击即归约。
- **结构**面板支持可折叠树与 **SVG 图**两种视图。
- 结果行操作：复制、插入、直接定义为新名字、把轨迹导出为 Markdown / JSON / LaTeX。
- 策略选择、步数上限、分享链接（服务端短 id 或完整 `#state=`）、`.lam` 导入导出、深浅色主题、中/英/双语切换。
- **流式求值**：`POST /api/eval/stream` 返回 Server-Sent Events，边归约边转发输出并定期发送心跳；浏览器支持 `ReadableStream` 时自动使用，否则回退到 `POST /api/eval`。
- **分享持久化**：短链保存在 `web/shares.json`（可用 `LAMBDA_SHARE_DB` 覆盖，设为 `off` 回到纯内存），重启后仍有效。
- **生产部署**：Docker 镜像改用 `waitress`（单进程多线程，匹配进程内会话模型），并带 `HEALTHCHECK`；`LAMBDA_RATE_LIMIT=<n>` 可开启每 IP 每分钟限流，`LAMBDA_MAX_TERM_SIZE=<n>` 会传给解释器的 `--max-term-size`。
- **窄屏适配**：宽度不足 900px 时改为单列、整页滚动，终端区保留自身高度上限，标签栏吸顶；不足 600px 时按钮放大到 32px 以上、输入框用 16px 字号（避免 iOS 聚焦自动放大）、标签栏等分整行，触屏上结果行操作常显。
- 切换语言通过 `POST /api/session/<sid>/lang` 只更新解释器语言，再由前端用服务端返回的 `textZh`/`textEn` 本地重渲染，不重放历史也不重建解释器。
- 接口：`GET /api/prelude`、`GET /api/health`（现含 `version`、`uptime`、`shares`、`sessionsMax`）、`POST /api/share`、`GET /api/share/<id>`、`POST /api/session`、`POST /api/eval`（`{"session", "line"}`）、`POST /api/eval/stream`（SSE）、`POST /api/session/<sid>/lang`、`POST /api/session/<sid>/cancel`、`DELETE /api/session/<sid>`；旧的 `{"code": "..."}` 仍可用。分享载荷做命令白名单校验，会话在后台回收，所有错误响应统一为带机器可读 `code` 的 JSON。返回 408 表示计算超时；410 表示会话过期，前端应回放历史。
- `:load` 默认只允许解释器目录内的文件；环境面板的“加载”按钮会提示输入相对路径。设置 `LAMBDA_LOAD_ROOT=*` 可放开限制（仅建议本地使用）。
- `:save` 在 Web 端默认关闭；本地使用可设 `LAMBDA_ALLOW_SAVE=1`。客户端的“导出”不经过服务器。
- `HOST`、`PORT` 可覆盖默认的 `127.0.0.1:8081`。
- 解释器查找顺序：`$LAMBDA_INTERP_BIN` → `$LAMBDA_INTERP_DIR/extension[.exe]` → `<仓库根目录>/extension[.exe]` → `/opt/lambda-calculus-interpreter/extension`。
- 页面使用 `<base href="./">`，本地 `/` 与线上 `/lambda/` 前缀下都能工作。
- `--batch` 会强制 UTF-8；旧的 Windows 交互式控制台仍可能乱码，请使用 Windows Terminal 或 `chcp 65001`。

```bash
pip install -r web/requirements.txt
python web/app.py          # http://127.0.0.1:8081
```

## 批处理与 JSON 协议

`--batch` 从 stdin 逐行读取命令，每条命令后输出记录分隔符 `\x1e`。`--json` 让每条输出成为 JSON 对象：

```json
{"kind":"result","text":"...","textZh":"...","textEn":"...",
 "term":"λf → λx → f x","steps":6,
 "limitHit":false,"hint":"...","hintZh":"...","hintEn":"...",
 "typeZh":"...","typeEn":"...","strategy":"applicative","eta":false,
 "ast":["λ x","└ • x"],"db":"λ.λ.#0",
 "redexes":[{"i":1,"path":"root","term":"...","rule":"β"}],"redexCount":1,
 "trace":[{"n":1,"rule":"β","note":"...","before":"...","after":"..."}],
 "traceShown":1,"traceTruncated":false,"elapsedMs":0.42}
```

`:time <expr>` 与 `:bench <n> <expr>` 会增加 `elapsedMs`（毫秒，`:bench` 为平均值）。所有
`error`、`fail`、`warn` 对象现在都带机器可读的 `code`，例如归约中出现重复整项时给出的
双语 `warn` 带 `code: "cycle_detected"`。

轨迹在内存中最多保留 500 步，长项截断到 300 字符；`traceTruncated` 会标明是否发生截断。结构化 `astTree` 只对不超过 400 个节点的项输出，更大的项返回 `astTreeOmitted: true`。`redexes` 最多 200 条，真实数量由 `redexCount` 给出。

`--batch` 还会把 stdin/stdout/stderr 统一设为 UTF-8，因此不再需要旧的 Windows 代码页变通。

## 测试

主构建方式是对两个独立单文件直接执行 `ghc` 编译，同时另附一个 Cabal 包（CI 也会执行
`cabal build all`）；测试直接驱动编译好的可执行文件，通过 JSON 协议做端到端校验：

```bash
./test.sh          # Linux / macOS
test.bat           # Windows
python tests/run_tests.py --bin ./extension
```

共 48 组，覆盖解析错误位置（含 `:eq` 两侧同时报错）、β 归约结果、变量捕获、归约轨迹、四种策略、步数上限、邱奇编码与组合子提示、类型推断、环境命令、文件加载（注释、续行、命令、行号、保存/重载、递归、多文件）、手动归约与 redex 选择、回退/跳转、正规形 / η / 快速模式、α/β 等价、整数互转、语法树 / de Bruijn、双语输出与 `textZh`/`textEn` 字段、JSON 协议、确定性与跨策略一致性、轨迹上限、CLI 一次性求值与校验模式、新语法与教材库、Web API 会话/过期/语言切换/短链分享与持久化/健康检查、SSE 流式求值、限流、前端状态同步（Node）、随机属性测试，以及 `main` 与 `extension` 的差分测试。

`tools/check_core_sync.py` 校验 `main.hs` 与 `extension.hs` 的共享核心一致性（`--fix` 会把共享声明从 `extension.hs` 复制到 `main.hs`），在 CI 中与
`cabal build all`、`python -m compileall -q web tests tools`、基于 Node 的
`tests/ui_smoke.mjs` 一同运行（CI 安装 Node 22，因此该冒烟测试会真正执行）。CI 覆盖
Ubuntu、macOS、Windows 三个平台，使用 GHC 9.6 与 Python 3.13。

## 贡献与 Docker

贡献规则见 [CONTRIBUTING.md](./CONTRIBUTING.md)，中英双语分节对应：构建与测试、
`tr`/`renderMsg`/`Msg` 双语字符串、中文全角引号 “ ” 与 ASCII 引号、禁用 U+300C/U+300D、
注释行不得以 `。` 结尾、新增命令必须有 Web UI 入口，以及本地跑 CI 的方法。

多阶段 [Dockerfile](./Dockerfile) 在 `ghc:9.6` 上编译 `extension`，再由
`python:3.13-slim` 提供网页界面：

```bash
docker build -t lambda-calculus-interpreter .
docker run --rm -p 8081:8081 lambda-calculus-interpreter
```

镜像会设置 `LAMBDA_INTERP_DIR`、`HOST=0.0.0.0`、`PORT=8081` 与
`LAMBDA_SHARE_DB=/app/web/shares.json`，安装 `web/requirements.txt`，复制
`lib/prelude.lam`，用 `waitress`（单进程多线程）提供服务，暴露 8081 端口并带
`HEALTHCHECK`。若希望分享链接在容器替换后仍保留，请挂载 `/app/web`。

## 实现要点

- 小步求值器每步只归约一个 β-redex 并重写整个项，因此每个轨迹步骤都是真实的前后对比；四种策略由四个布尔开关描述。
- η 是 β 之后尝试的第二条规则；弱策略不归约 λ 体内。`:nf` 使用正规序，`:whnf` 在到达首正规形时停止。
- redex 用路径（`[Int]`）枚举，因此可以按序号归约任意 β-redex，而不改变求值器结构。
- 无捕获替换只计算一次参数的自由的变量，对不含被替换变量的子树直接共享，并顺带报告是否发生 α-重命名。α 等价在两个绑定环境上同步下降，不构造 de Bruijn 中间树。
- 快速模式把展开后的项转成 de Bruijn 形式，用环境 + 闭包求值器（`FastM`）归一，共享参数只算一次；`:steps` 作为 β 燃料预算，所以发散项仍会中止。
- 打印器使用 `ShowS`；`shorten` 只强制惰性字符串的前若干个字符，截断巨型项时不会先把它完整打印出来。
- 类型使用 Hindley–Milner 推断并做 let 泛化，含表达式级 let 多态与 `(expr : T)` 标注。
- 定义以展开后的形式保存；递归定义编码为 `Z (λname. body)`（按值调用不动点），显示与保存时还原为 `rec name = body`；`Y` 仍作为用户可用组合子保留。
- Web 后端为每个会话保留一个解释器进程；过期会话返回 410，让前端回放历史而不是悄悄丢失环境。

## 约定

- 中文使用中文引号“ ”，英文使用英文引号 `"` 与 `'`；不使用角括号 U+300C 与 U+300D，代码、注释与界面文案都不例外。

## 限制

- 替换会复制项；重复度高的项（例如应用序下的 `rec fact`）可能指数级增长。请开启快速模式、降低 `:steps`、改用正规序，或接受这个代价。
- Church 布尔的 `IF` 在应用序下不是惰性的；递归列表/数值函数可能发散。`lib/prelude.lam` 建议配合 `:strategy normal` 或 `:fast on`。
- `rec` 定义使用按值调用的 `Z` 组合子，但 `IF` 的分支选择仍然是严格的；`Z` 本身不能保证所有递归函数在应用序下终止。
- 快速模式总是求正规形：忽略所选策略与 η，不记录轨迹，也不给精确步数。`:trace`、`:whnf` 与手动归约始终走逐步引擎。
- CLI REPL 默认没有墙钟上限；可用 `--timeout <秒>` 或 `Ctrl+C`。Web 后端通过杀掉超时会话来限制。
- 除显式开启外，`:save` 在 Web 端不可用。
- 解析器对单个表达式只报一个错误；`:eq` / `:conv` 会合并两侧错误，`.lam` 加载会逐行报告所有失败行。

## 许可证

MIT，见 [LICENSE](./LICENSE)。
