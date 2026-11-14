# Lambda Calculus Interpreter with Church Encoding ([中文版](./README-CN.md))

A Haskell implementation of pure lambda calculus: Church numerals, booleans,
pairs and lists, capture-avoiding substitution, reduction traces, four
evaluation strategies, eta reduction, simple type inference, and a small
definition environment. Two standalone interpreters are provided:

- `main` — the minimal core REPL.
- `extension` — definitions, file loading, traces, AST/de Bruijn views, types,
  redex picking, α/β equivalence checks, a batch/JSON mode for the web UI, and
  Chinese/English output.

## Online Demo

The enhanced interpreter runs in the browser at
**<http://47.116.114.77/lambda/>**. The page in `web/` is a thin Flask wrapper
around the same compiled `extension` binary.

## Features

- **Pure lambda calculus** with α-equivalence and capture-avoiding substitution.
- **Reduction traces** — every β/η step is recorded with its before/after term.
- **Four strategies** — applicative, normal, call-by-name, call-by-value
  (weak strategies stop at weak head normal form).
- **Eta reduction** — `:eta on|off` adds `λx. f x → f` when `x` is not free in `f`.
- **Fast mode** — `:fast on|off` (also a web toggle) evaluates with shared
  environments instead of rebuilding the whole term each step, which makes large
  Church arithmetic dramatically faster. It returns a normal form only: no
  trace and no exact step count, and `:steps` becomes a β fuel budget.
- **Normal forms** — `:nf` reduces to a full normal form, `:whnf` stops at the
  weak head normal form.
- **Redex picking** — `:begin` lists every β-redex; `:step <n>` contracts a
  chosen one. The web UI turns the list into clickable buttons.
- **Equivalence checks** — `:eq a , b` for α-equivalence, `:conv a , b` for
  β-convertibility (both sides reduced to normal form).
- **Richer expressions** — `let x = e1; y = e2 in e3` (with expression-level
  let-polymorphism in `:type`), `if c then t else f`, list literals `[a, b, c]`,
  `(expr : T)` type annotations, and a `--` comment at the end of any line.
- **Multi-line REPL** — a trailing `\` or unclosed parentheses/brackets
  automatically continue the input onto the next line.
- **Timing and help** — `:time [n] <expr>` reports elapsed time and a min/max
  range, `:bench <n> <expr>` reports average/median/standard deviation, and
  `:help <cmd>` shows per-command help.
- **CLI one-shot mode** — `-e/--eval <cmd>` runs commands and exits,
  `--check <file>` validates `.lam` files with exit code 0/1, and
  `--strategy/--steps/--eta/--fast` configure a run without a file.
- **Manual rewind** — `:back` and `:goto <n>` move through the stored manual
  reduction history; the web UI exposes both as buttons.
- **Definition tools** — `:def <name>`, `:search <substring>`, `:reload`, and
  `:edit [file]` plus filename completion for `:load`/`:save`/`:edit`.
- **Bounded cycle detection** — when a whole term repeats during reduction, a
  bilingual `warn` is emitted with `code: "cycle_detected"` in JSON.
- **Machine-readable codes** — every `error` / `fail` / `warn` JSON object
  carries a `code` field.
- **Step limit** (default 10,000) so non-terminating terms report instead of hang;
  `--timeout <s>` adds a wall-clock limit per command and `Ctrl+C` interrupts the
  current evaluation in the interactive REPL.
- **Semantic hints** — Church numerals/booleans/pairs and the `I K S B C W`
  combinators are recognised by α-equivalence; all six are also defined.
- **Prelude** — `TRUE FALSE NOT AND OR XOR NAND IF I K S B C W ZERO ONE TWO
  THREE SUCC PLUS MULT EXP PRED SUB ISZERO LEQ EQ MIN MAX DIV MOD PAIR FST SND
  NIL CONS HEAD TAIL APPEND REV LENGTH MAP FILTER FOLD RANGE ZIP Y`.
- **Teaching library** — `lib/prelude.lam` adds `FACT`, `FIB`, `ISEVEN`, `SUM`,
  `PRODUCT`, `CONCAT`, `TAKE`, `DROP`, `REPEAT`, `ANY`, `ALL`, `ZIPWITH`,
  `SORT`, `MAXLIST`, `MINLIST`, and more.
- **Simple types** — Hindley–Milner inference with let-generalisation (`:type`),
  including expression-level `let` polymorphism and `(expr : T)` annotations.
- **Definitions** — `name = expr`, recursive `rec name = expr`, `:let`, `:load`,
  `:save`, `:env`, `:del`, `:reset`.
- **Definition files** — comments (`--` or `#`), indented or
  parenthesised/bracketed continuation lines, and in-file commands `:strategy`,
  `:steps`, `:lang`, `:fast`, `:eta`, `:trace`, `:ast`, `:db`, `:del`, `:reset`,
  `:let` plus `rec` definitions.
- **Integer bridge** — `:int <expr>` decodes a Church numeral, `:church <n>`
  encodes 0–9999.
- **Views** — pretty syntax tree (`:ast`), structured/collapsible AST in the web
  panel, and de Bruijn indices (`:db`).
- **Bilingual** — every user-facing message has a Chinese and an English form;
  `--lang zh|en|both` or `:lang` selects them (default `both`).

## Screenshots

Light theme, captured from the web UI.

![REPL with a reduction trace](docs/screenshots/main.png)

*Reduction trace: every step with a before/after diff, a step player, and the
result annotated with its step count and Church-numeral value.*

![Syntax tree and de Bruijn view](docs/screenshots/ast.png)

*Syntax tree of the result, plus the de Bruijn index view for bound variables.*

![Environment inspector](docs/screenshots/env.png)

*Environment panel: definitions are listed with their terms and types; click a
name to insert it, hover to delete it.*

![Usage guide](docs/screenshots/guide.png)

*The built-in quick guide opens on the first visit and is always available from
the Guide tab.*

Regenerate them while the web UI is running:

```bash
pip install -r tools/requirements.txt
python tools/screenshot.py            # or: tools\screenshot.bat
```

## Building

```bash
./build.sh      # Linux / macOS
build.bat       # Windows
```

The primary build is two standalone single-file `ghc` compilations; a Cabal
package is also provided. Both scripts pass
`-O2 -Wall -threaded -rtsopts -package containers -package haskeline -package
directory -package process` and produce `main` / `extension` (`main.exe` /
`extension.exe` on Windows). `process` is only used by `:edit`. `build.sh` adds the GNU ld link flags
(`-split-sections -optl-Wl,--gc-sections -optl-s`) on Linux only (via
`uname -s`), treats `-optlc-march=native` as opt-in under `LAMBDA_NATIVE=1`,
and stays portable on macOS; `build.bat` checks for `ghc` and `errorlevel`,
and carries no `-march=native` or GNU ld flags. A missing `ghc` is a hard error,
and each script reports build success or failure.

A Cabal file builds the same two standalone executables (no shared library,
deliberately):

```bash
cabal build all
cabal run extension -- --help
```

Release artifacts are produced by `.github/workflows/release.yml`: pushing a
`v*` tag (or running the workflow manually) builds a Windows `.zip` with
`main.exe`/`extension.exe` and macOS `.dmg` images for x64 and arm64, then
publishes them to a GitHub Release with SHA-256 checksums.

## Version

`VERSION` at the repository root is the single source of truth (currently
2.2.2); the Cabal package version and `./extension -v|--version` follow it.
See [CHANGELOG.md](./CHANGELOG.md) for the release history.

## Usage

```bash
./extension [--lang zh|en|both] [--lang=zh] [--timeout 秒] [--batch] [--json] \
            [-e|--eval <cmd>] [--check <file>] [--strategy <s>] [--steps <n>] \
            [--eta[=on|off]] [--fast[=on|off]] [--max-term-size <n>] \
            [-v|--version] [-h|--help] [file...]
```

If files are given, their definitions and commands are loaded in order before
the REPL. `test.lam` is a sample definitions file; its `ERR`/`ERROR` lines are
intentionally malformed so load-error reporting is exercised. `-e/--eval` runs
one or more commands and exits (exit 1 on a parse error); `--check` loads each
file, reports failures and exits 0/1 without starting the REPL.

### REPL commands

| Command | Meaning |
| --- | --- |
| `:help [<cmd>]` | show help, or per-command help for `<cmd>` |
| `:load <file>` | load definitions/commands (`name = expr`, comments, continuations) |
| `:save <file>` | save user definitions in parser-readable source syntax |
| `:let name = expr` / `:let rec name = expr` | define a variable / recursive definition |
| `:env` / `:del <name>` / `:reset` | inspect (with types) / delete / reset the environment |
| `:strategy applicative\|normal\|cbn\|cbv` | switch evaluation strategy |
| `:steps <n>` | set the reduction step limit |
| `:eta on\|off` | enable/disable eta reduction |
| `:fast on\|off` | shared fast normalization (normal form only, uses `:steps` as fuel) |
| `:trace <expr>` | print the full reduction trace |
| `:time [n] <expr>` | report elapsed time over `n` runs (JSON gains `elapsedMs`) |
| `:bench <n> <expr>` | average/median/stddev timing over `n` runs |
| `:ast <expr>` / `:db <expr>` | syntax tree / de Bruijn indices |
| `:type <expr> [: <type>]` | infer the simple type (`let`-polymorphic, annotations honoured) |
| `:eq <a> , <b>` / `:conv <a> , <b>` | α-equivalence / β-convertibility |
| `:nf <expr>` / `:whnf <expr>` | full normal form / weak head normal form |
| `:int <expr>` / `:church <n>` | decode / encode a Church numeral |
| `:begin <expr>` / `:step [n]` / `:run` / `:end` | interactive reduction; `n` picks a redex |
| `:back` / `:goto <n>` | rewind / jump in the manual reduction history |
| `:def <name>` / `:search <substring>` | show one definition / search the environment |
| `:reload` / `:edit [file]` | reload the last file / open it in `$EDITOR` |
| `:lang zh\|en\|both` | switch output language |
| `:q` | quit |

### Syntax

- Variables: start with a letter or one of `+ - * / % ^ ? ! < > | & ~ # $`,
  then letters, digits, `_`, `'`, or operators.
- Abstraction: `λx.body`, `λx → body`, or `\x -> body`; multiple parameters:
  `λx y.body`.
- Application: `f a`, left-associative; grouping: `(expr)`.
- `let x = e1; y = e2 in e3` binds sequentially; `:type` generalises
  `let`-bound names (expression-level let-polymorphism).
- `if c then t else f` desugars to `IF c t f`; `[a, b, c]` desugars to
  `CONS a (CONS b (CONS c NIL))`.
- `(expr : T)` annotates an expression with a type. The annotation is
  syntax-checked and erased before reduction; use `:type expr : T` to verify
  that an inferred type matches (JSON reports `matches`, `expected`, `actual`).
- A `--` comment may end any line, for example `λx. x -- note`.
- Numbers: `0`…`9999` become Church numerals.
- Definitions: `name = expression`; recursion: `rec name = expression`.
- Equivalence commands separate the two expressions with a comma:
  `:eq \a.a , \b.b`.
- `.lam` files accept `--` or `#` comment lines, indented or
  parenthesised/bracketed continuation lines, and commands `:strategy`, `:steps`,
  `:lang`, `:fast`, `:eta`, `:trace`, `:ast`, `:db`, `:del`, `:reset`, `:let`
  plus `rec` definitions.
- REPL multi-line input: a line ending in `\` or with unclosed parentheses or
  brackets continues onto the next line.

### Examples

The extended library is optional; load it and use fast mode for recursive
Church arithmetic:

```bash
./extension -e ':load lib/prelude.lam' -e ':fast on' -e ':int (FACT 5)'
# 120
```

```text
λ> PLUS ONE TWO
⇒ λf → λx → f (f (f x))  (6 steps)  (Church numeral 3)

λ> :int (PRED THREE)
⇒ 2

λ> :eq \a.a , \b.b
⇒ alpha-equivalent: λa → a  ,  λb → b

λ> :conv PLUS ONE TWO , THREE
⇒ beta-equivalent: λf → λx → f (f (f x))  ,  λf → λx → f (f (f x))

λ> :eta on
λ> :nf \x. f x
⇒ f  (1 step)

λ> :begin (\x.x) ((\y.y) z)
λ> :step 2
⇒ (λx → x) z

λ> :type \f.\x.f (f x)
⊢ (t0 → t0) → t0 → t0 (polymorphic)

λ> :strategy normal
λ> (\x.y) ((\x.x x)(\x.x x))
⇒ y  (1 step)          -- normal order discards the argument

λ> :steps 40
λ> (\x.y) ((\x.x x)(\x.x x))
⚠ step limit 40 reached, reduction incomplete
```

## Web UI (`web/`)

`web/app.py` (Flask) keeps one persistent interpreter process per browser
session and speaks the `--batch --json` protocol.

- Terminal REPL with history, Tab completion, `Ctrl+L`, and error carets.
- **Editor** — syntax highlighting, bracket matching, line numbers, undo/redo,
  a command palette (`Ctrl+K`), categorised examples and progressive exercises,
  clickable error locations, focus-preserving trace playback, and ARIA labels /
  focus traps / reduced-motion support.
- Live panels for **reduction trace** (step player, play/pause, diff),
  **AST** (collapsible tree + text tree), **type**, and **environment**
  (click to insert, hover to delete, types shown for user definitions).
- **Tools** tab for `:eq`, `:conv`, `:nf`, `:whnf`, `:int`, `:church`, `:eta`,
  recursive definitions and `:save`; every command also works in the terminal.
- **Redex picker** under the terminal in manual mode: click any redex to
  contract it.
- **AST** panel with a collapsible tree and an **SVG graph** view.
- Output-row actions: copy, insert, define the result, and export the trace as
  Markdown, JSON or LaTeX.
- Strategy selector, step-limit control, share links (server-side short ids or
  a full `#state=` payload), `.lam` import/export, light/dark theme, and a
  Chinese/English/bilingual switch.
- **Streaming evaluation** — `POST /api/eval/stream` returns Server-Sent Events;
  reducer output is forwarded as it arrives and a heartbeat keeps long-running
  terms connected. It is used automatically when `ReadableStream` exists and
  falls back to `POST /api/eval` otherwise.
- **Persistent shares** — short links are stored in `web/shares.json` (override
  with `LAMBDA_SHARE_DB`, set `off` for memory-only) and survive a restart.
- **Production serving** — the Docker image uses `waitress` (single process,
  multiple threads, matching the in-process session model) and ships a
  `HEALTHCHECK`. `LAMBDA_RATE_LIMIT=<n>` enables a per-IP requests/minute cap,
  and `LAMBDA_MAX_TERM_SIZE=<n>` forwards `--max-term-size` to the interpreter.
- **Small screens**: below 900px the layout becomes one scrolling column with a
  sticky tab bar and a capped terminal area; below 600px controls grow to 32px+
  targets, inputs use 16px so iOS does not zoom on focus, the tab bar divides the
  row evenly, and result-row actions stay visible on touch.
- Language switching uses `POST /api/session/<sid>/lang` and re-renders existing
  output locally from the server's `textZh`/`textEn` fields; it does not replay
  commands or start a new interpreter.
- `GET /api/prelude`, `GET /api/health` (now with `version`, `uptime`, `shares`,
  `sessionsMax`), `POST /api/share`, `GET /api/share/<id>`, `POST /api/session`,
  `POST /api/eval` (`{"session", "line"}`), `POST /api/session/<sid>/lang`,
  `POST /api/session/<sid>/cancel`, and `DELETE /api/session/<sid>`. The legacy
  `{"code": "..."}` form still works. Share payloads are validated against a
  command allow-list: expressions, definitions, the settings (`:lang`,
  `:strategy`, `:steps`, `:eta`, `:fast`), the read-only queries (`:type`,
  `:trace`, `:ast`, `:db`, `:eq`, `:conv`, `:nf`, `:whnf`, `:int`, `:church`,
  `:env`, `:help`, `:def`, `:search`) and the manual-reduction commands may be
  shared, while file, session and environment commands (`:load`, `:save`,
  `:edit`, `:reload`, `:reset`, `:del`, `:q`) may not. Idle sessions are reaped
  in the background, and all error
  responses are unified JSON carrying a machine-readable `code`. A 408 response
  means the term timed out; a 410 means the session expired and the client should
  replay its history. Terminal-only commands (`:q`, `:edit`) are refused with
  `code: "cli_only"` so the web session stays alive and the server never starts
  an editor.
- `:load` is confined to the interpreter directory by default; the Env panel's
  **Load** button prompts for such a relative path. Set `LAMBDA_LOAD_ROOT=*`
  to allow any path (local use only).
- `:save` is disabled over the web by default; set `LAMBDA_ALLOW_SAVE=1` for
  local use. Client-side **Export** does not need the server.
- `HOST` and `PORT` override the default `127.0.0.1:8081`.
- Interpreter lookup: `$LAMBDA_INTERP_BIN`, `$LAMBDA_INTERP_DIR/extension[.exe]`,
  `<repo>/extension[.exe]`, `/opt/lambda-calculus-interpreter/extension`.
- `<base href="./">` keeps it working at `/` and behind the `/lambda/` prefix.
- `--batch` forces UTF-8; an interactive legacy Windows console may still garble
  Unicode, so use Windows Terminal or `chcp 65001` there.

```bash
pip install -r web/requirements.txt
python web/app.py          # http://127.0.0.1:8081
```

## Desktop app (`pywebview`)

`desktop.py` starts the same Flask UI on a loopback port and opens it in a native
`pywebview` window. PyInstaller bundles the Python runtime, `web/`, `lib/`,
`VERSION` and the compiled `extension` into one desktop application.

```bash
pip install -r web/requirements.txt -r desktop-requirements.txt
# after building extension (build.bat / build.sh)
pyinstaller --noconfirm --clean --onefile --windowed \
  --name lambda-calculus-interpreter-desktop \
  --collect-all webview \
  --add-binary "extension.exe;." \
  --add-data "web;web" --add-data "VERSION;." --add-data "lib;lib" \
  desktop.py
```

On macOS use `--windowed`, `--add-binary "extension:."` and
`--add-data "web:web"`, then wrap `dist/LambdaCalculusInterpreter.app` in a DMG.
The release workflow builds these desktop artifacts for Windows x64, macOS x64
and macOS arm64 alongside the command-line archives. On Windows the desktop app
and its child `extension.exe` processes run without console windows. Desktop
builds are unsigned, so Windows SmartScreen / macOS Gatekeeper may ask for
confirmation on first launch.

## Batch and JSON protocol

`--batch` reads one command per stdin line and prints `\x1e` after each result.
`--json` makes every output a JSON object:

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

`:time <expr>` and `:bench <n> <expr>` add `elapsedMs` (milliseconds; the mean
for `:bench`). Every `error`, `fail` and `warn` object now carries a
machine-readable `code`, for example `code: "cycle_detected"` on the bilingual
`warn` emitted when a whole term repeats during reduction.

Traces keep at most 500 steps in memory and clip long terms to 300 characters;
`traceTruncated` tells the client when either limit applied. Structured
`astTree` is emitted for terms up to 400 nodes and replaced by
`astTreeOmitted: true` for larger ones. `redexes` is capped at 200 entries while
`redexCount` is exact.

`--batch` also forces UTF-8 on stdin/stdout/stderr, which removes the old
Windows code-page workaround.

## Tests

The primary build is two standalone single-file `ghc` compilations, with a
Cabal package provided alongside it (CI also runs `cabal build all`); the test
suite drives the compiled binary end-to-end through the JSON protocol:

```bash
./test.sh          # Linux / macOS
test.bat           # Windows
python tests/run_tests.py --bin ./extension
```

48 groups cover parsing positions, β-reduction results, capture avoidance,
traces, all four strategies, step limits, Church/combinator hints, type
inference, environment commands, file loading (comments, continuations,
commands, line numbers, save/reload, recursion, multiple files), manual
reduction and redex picking, rewind/jump, normal forms, eta and fast mode,
α/β equivalence, integer encoding, AST/de Bruijn, bilingual output, JSON
protocol, determinism, cross-strategy agreement, trace capping, CLI one-shot
and check modes, new syntax and library functions, web API sessions,
expiry/language switching/health checks, short share links and persistence,
SSE streaming, rate limiting, bilingual protocol fields, wall-clock timeout,
randomized properties, web UI state sync (Node), and a `main`/`extension`
differential test.

`tools/check_core_sync.py` checks that the shared core stays in sync between
`main.hs` and `extension.hs` (`--fix` copies from `extension.hs` to `main.hs`),
and runs in CI alongside `cabal build all`, `python -m compileall -q web tests
tools` and the Node-based `tests/ui_smoke.mjs` (Node 22 is installed there, so
that smoke test really runs). CI covers Ubuntu, macOS and Windows with GHC 9.6
and Python 3.13.

## Contributing and Docker

See [CONTRIBUTING.md](./CONTRIBUTING.md) for the bilingual contribution rules:
build and test, `tr`/`renderMsg`/`Msg` bilingual strings, Chinese full-width
quotes `“ ”` versus ASCII `"` and `'`, the ban on U+300C/U+300D, comment lines
that must not end with `。`, a Web UI entry for every new command, and how to run
CI locally.

A multi-stage [Dockerfile](./Dockerfile) compiles `extension` on `ghc:9.6` and
serves the web UI on `python:3.13-slim`:

```bash
docker build -t lambda-calculus-interpreter .
docker run --rm -p 8081:8081 lambda-calculus-interpreter
```

The image sets `LAMBDA_INTERP_DIR`, `HOST=0.0.0.0`, `PORT=8081` and
`LAMBDA_SHARE_DB=/app/web/shares.json`, installs `web/requirements.txt`, copies
`lib/prelude.lam`, serves the app with `waitress` (single process, multiple
threads) and exposes 8081 with a `HEALTHCHECK`. Mount `/app/web` if you want
share links to survive a container replacement.

## Implementation

- A small-step evaluator contracts one β-redex per step and rewrites the whole
  term, so each recorded trace step is a real before/after pair. Strategies are
  described by four flags.
- Eta is a second rule tried after β; weak strategies do not reduce under
  lambdas. `:nf` uses normal order, `:whnf` stops as soon as a head normal form
  is reached.
- Redexes are enumerated by path (`[Int]`), so any β-redex can be contracted by
  index without changing the evaluator.
- Capture-avoiding substitution computes the argument's free variables once,
  shares subtrees that do not contain the substituted variable, and reports
  whether any α-renaming happened. α-equivalence walks both binding
  environments in lockstep, with no intermediate de Bruijn tree.
- Fast mode converts the expanded term to de Bruijn form and normalizes it with
  an environment/closure evaluator (`FastM`); shared arguments are evaluated
  once. `:steps` is read as a β fuel budget, so divergent terms still stop.
- Pretty printers build `ShowS` functions, and `shorten` forces only the first
  characters of a lazy string, so clipping a huge term does not print it first.
- Types are inferred with Hindley–Milner and let-generalisation, including
  expression-level `let` polymorphism and `(expr : T)` annotations.
- Definitions are stored already expanded; recursive definitions are encoded as
  `Z (λname. body)` (the call-by-value fixed point) and printed/saved as
  `rec name = body`; `Y` remains available as a user-facing combinator.
- The web backend keeps one interpreter process per session; expired sessions
  return 410 so the client replays its history rather than silently losing the
  environment.

## Conventions

- Chinese text uses the full-width Chinese quotes `“ ”`; English text uses ASCII
  `"` and `'`. The corner brackets U+300C and U+300D are never used, here or in
  code, comments, or UI strings.

## Limitations

- Substitution copies terms; terms with heavy duplication (for example `rec
  fact` under applicative order) can grow exponentially. Use fast mode, a
  smaller `:steps`, normal order, or accept the cost.
- Church encodings rely on a lazy `if`: the prelude `IF` and Church booleans are
  strict under applicative order, so recursive list/number functions may diverge
  there. Use `:strategy normal` or `:fast on` for `lib/prelude.lam`.
- `rec` definitions use the call-by-value `Z` combinator, but the branch
  selection inside `IF` is still eager; `Z` alone does not make every recursive
  function terminate under applicative order.
- Fast mode always computes a normal form: it ignores the selected strategy and
  η, records no trace, and reports no exact step count. `:trace`, `:whnf` and
  manual stepping always use the step-by-step engine.
- The CLI REPL has no wall-clock limit by default; pass `--timeout <s>` to set
  one, or use `Ctrl+C`. The web backend enforces its own timeout by killing the
  session.
- `:save` is intentionally unavailable over the web unless explicitly enabled.
- The parser reports one error per expression; `:eq`/`:conv` combine errors from
  both sides, and `.lam` loading reports every failing line.

## License

MIT. See [LICENSE](./LICENSE).
