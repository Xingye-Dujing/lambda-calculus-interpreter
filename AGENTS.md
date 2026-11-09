# AGENTS.md

Two independent, single-file Haskell interpreters for pure lambda calculus. The
primary build is direct `ghc` compilation of two standalone files; a Cabal
package and GitHub Actions CI are also provided. There is no external linter:
`ghc -Wall`, the style checks in the test suite, and the end-to-end test suite
are the checks. Documentation and user-facing text are **bilingual
Chinese/English**.

## Build, run, test

- Windows: `.\build.bat`; Unix: `./build.sh`. Both call `ghc` directly with
  `-O2 -Wall -threaded -rtsopts -package containers -package haskeline
  -package directory -package process` and produce `main`/`extension`
  (`main.exe`/`extension.exe` on Windows). A Cabal file (`cabal build all`)
  packages the same two executables; the files stay standalone by design.
  `System.Process` is used only by `:edit`.
- The scripts are split by platform: `build.sh` keeps the GNU ld link flags
  (`-split-sections -optl-Wl,--gc-sections -optl-s`) on Linux only (via
  `uname -s`), treats `-optlc-march=native` as opt-in under `LAMBDA_NATIVE=1`,
  and stays portable on macOS; `build.bat` uses no GNU ld flags and no
  `-march=native`. Both pass the same four `-package` flags; keep them in sync
  when adding build steps on either platform.
- **Tests:** `.\test.bat` / `./test.sh`, or
  `python tests/run_tests.py [--bin path]`. The suite drives the compiled
  `extension --batch --json` binary end-to-end (48 groups), including a
  `main`/`extension` differential test, the web API (when Flask is installed),
  SSE streaming, share persistence, rate limiting, and the Node UI smoke test.
  Run it after any core change; it is the regression net for `main.hs` and
  `extension.hs`. `python tools/check_core_sync.py` compares the shared core;
  `--fix` copies differing shared declarations from `extension.hs` to `main.hs`.
- **Release:** `.github/workflows/release.yml` runs on a `v*` tag or manual
  dispatch, builds `main.exe`/`extension.exe` on Windows, packages macOS DMGs
  for x64 and arm64, and publishes them (plus SHA-256 files) with
  `softprops/action-gh-release`.
- `./main` — minimal REPL (`:q` to quit).
- `./extension [file...] [-h|--help] [-v|--version] [--lang zh|en|both] [--lang=zh]
  [--timeout 秒] [--batch] [--json] [-e|--eval cmd] [--check file]
  [--strategy s] [--steps n] [--eta[=on|off]] [--fast[=on|off]]
  [--max-term-size n]` — full REPL
  with definitions. `-e` may repeat, `--check` exits 0/1. REPL commands:
  `:help`, `:load`, `:save`, `:let`, `:env`, `:del`, `:reset`, `:strategy`,
  `:steps`, `:eta`, `:fast`, `:trace`, `:ast`, `:db`, `:type`, `:eq`, `:conv`,
  `:nf`, `:whnf`, `:int`, `:church`, `:begin`, `:step [n]`, `:run`, `:end`,
  `:back`, `:goto <n>`, `:def`, `:search`, `:reload`, `:edit`, `:time [n]`,
  `:bench`, `:lang`, `:q`. `:help <cmd>` shows per-command help.
- `VERSION` is the single source of truth for the version (cabal, both
  binaries and the test suite must match it). All `error`/`fail`/`warn` JSON
  carries a `code`; cycle detection additionally emits `cycle_detected`.
- Expressions accept `let x = e1; y = e2 in e3`, `if c then t else f`, list
  literals `[a, b, c]`, `(expr : T)` annotations (erased during reduction;
  verify with `:type expr : T`), trailing `--`/`#` comments, and REPL
  continuation on a trailing `\` or unclosed parentheses. `.lam` files also
  accept settings commands and replay query commands.
- `test.lam` is a sample definitions file. Its `ERR` and `ERROR` lines are
  intentionally malformed to exercise load-error reporting; do not "fix" them.

## Language and output

- All comments, help text, errors, and UI strings carry both Chinese and
  English. Use the `tr`/`renderMsg` helpers and the `Msg` type; do not add a
  Chinese-only or English-only string.
- Comment lines must not end with a Chinese full stop `。`: end with nothing or
  an English period instead.
- Quotation marks: Chinese text uses the full-width Chinese quotes `“ ”`;
  English text uses ASCII `"` and `'`. Never use the corner brackets U+300C and
  U+300D (the ones that look like square double quotes) anywhere: code, comments,
  Markdown, or UI strings.
- Default output language is `both`; `--lang` / `:lang` switch to `zh` or `en`.
  The web UI has its own `I18N` dictionary and sends `:lang` to the session.
- Keep `λ`/`→`/`⇒`/box-drawing characters and the terminal-style formatting.
- Calls from `:load`/`rec`/`:save` must use `say`/`renderMsg`; `defined` and
  other status words are localized.
- The parser accepts `.`, `→`, and `->` as lambda separators; `:save` writes
  parser-readable `\x.body` source, while `pretty` uses `λx → body`.

## Web UI (`web/`)

- Flask wrapper (`web/app.py`) + terminal-style page (`web/index.html`); no
  frontend build step. Python deps: `pip install -r web/requirements.txt`, run
  `python web/app.py` (defaults `127.0.0.1:8081`, override with `HOST`/`PORT`).
- Interpreter lookup: `$LAMBDA_INTERP_BIN`, `$LAMBDA_INTERP_DIR/extension[.exe]`,
  `<repo>/extension[.exe]`, `/opt/lambda-calculus-interpreter/extension`. Build
  `extension` before running.
- The backend keeps one **persistent** `extension --batch --json` process per
  browser session (reader thread + `\x1e` sentinel). `POST /api/eval` takes
  `{"session", "line"}`; legacy `{"code"}` still runs one-shot. A timeout kills
  the session and returns 408; an unknown/expired session returns 410 with
  `restart: true` so the frontend replays its history.
- `POST /api/session/<sid>/lang` switches language in the running process;
  `GET /api/health` reports sessions and interpreter availability.
  `POST /api/share` stores a state payload and `GET /api/share/<id>` returns it
  for the short `#s=<id>` links. Shares persist to `web/shares.json`
  (`LAMBDA_SHARE_DB` overrides, `off` = memory only).
- `POST /api/eval/stream` returns SSE frames (`start`, output objects,
  `heartbeat`, `done`); the frontend uses it when `ReadableStream` exists and
  falls back to `/api/eval`. The interpreter reader thread feeds a per-line
  queue while streaming, so a long reduction is not killed by the normal
  request timeout. `LAMBDA_RATE_LIMIT=<n>` adds a per-IP token bucket
  (default off); the Docker image serves the app with `waitress` and a
  `HEALTHCHECK`, and remains single-process because sessions live in memory.
- `index.html` uses `<base href="./">` so it works at `/` and behind the
  production `/lambda/` prefix (Caddy `handle_path` strips it). Fonts are served
  by Flask at `/fonts/<file>`; the favicon is `web/icon.svg`.
- Every `Command` has a UI entry: manual reduction controls (`:begin`/
  `:back`/`:goto 0`/`:step`/`:run`/`:end`), the step-limit input (`:steps`), Env
  **load** (`:load`) and **reset** (`:reset`), the **Tools** tab (`:eq`/`:conv`/
  `:nf`/`:whnf`/`:int`/`:church`/`:eta`/recursive `rec`/`:save`), and the redex
  buttons (`:step <n>`). Keep it that way when adding commands.
- Do not use native `select`, `prompt`, `confirm` or `alert`: use the custom
  `.sel` menus and the `dialog()` helper so popups match the wireframe theme.
- The desktop layout is a fixed `100vh` flex column: terminal and inspector share
  one row height, both scroll internally, and the page never scrolls. The AST
  view offers a collapsible `astTree` and an SVG graph, plus a text tree.
- Small screens: the responsive rules sit at the **end** of the stylesheet, since
  `main`, `.term` and `.panel` carry base rules of equal specificity. Below
  `900px` the page becomes one column that scrolls as a whole (`.term-out` keeps
  its own `max-height`, `.panel` does not), the tab bar is sticky, and inline row
  actions plus `.env-del` stay visible. Below `600px` controls get 32px+ touch
  targets, `#cmd`/modal inputs use 16px so iOS does not zoom on focus, the tab
  bar divides the width evenly, and `MatchMedia("(max-width:600px)")` swaps the
  input placeholder for the short `placeholderShort` string. Narrow screens show
  a one-time `narrowHint` toast pointing below the terminal. Only the CSS and
  that hint are viewport-driven; everything else is orthogonal to the breakpoints.
- The first visit defaults to the light theme; the toggle persists the choice in
  `localStorage` (the OS `prefers-color-scheme` is intentionally not consulted).
- The **Guide** tab (`renderGuide`) opens when there is no saved state; keep its
  steps in sync with UI changes.
- Switching language calls the lang route and re-renders the transcript locally
  from `textZh`/`textEn`; it must not replay `codeLines` or rebuild the session.
  Result meta uses `hintZh`/`hintEn`, types use `typeZh`/`typeEn`.
- Fast mode has two UI entries: the header `#fast-toggle` button and the Tools
  tab button. Both call `toggleFast`, which sends `:fast on|off`; the state is
  saved locally, carried in share links, and re-sent when a session is rebuilt.
- Share links use a server-side short `#s=<id>` (state stored via `/api/share`);
  the full `#state=` payload and legacy `#code=` forms are still accepted.
- `:q` is intercepted client-side; the web session must not quit the
  interpreter. `:clear` is also client-side.
- `:load` is confined to `INTERP_DIR` by default (`LAMBDA_LOAD_ROOT=*` disables
  the check); `web/app.py` rejects escaping paths with 400. `:save` is disabled
  over the web unless `LAMBDA_ALLOW_SAVE=1`.
- `--batch` sets stdin/stdout/stderr to UTF-8, which removes the old Windows
  `chcp` and `λ`→`\` workarounds. Keep the UTF-8 setup when changing the
  subprocess call; send bytes (not `text=True`) so Python does not translate
  `\n` to `\r\n`.

## Architecture

- `main.hs` and `extension.hs` are deliberately standalone. The core (`Expr`,
  `freeVars`, `freshVar`, substitution, `stepOnce`, `eval`, parser) is duplicated:
  apply core/reduction fixes to both files, or run
  `python tools/check_core_sync.py --fix` to copy the shared declarations from
  `extension.hs` (the single source) into `main.hs`.
- `extension.hs` adds `Env` (`Data.Map`), macro expansion (`expand`/`expandTop`,
  with an expansion fuel), definitions, file loading/saving, `:env`, numeric
  literals, types, and wider identifier characters.
- Reduction is small-step: `stepOnce` returns the whole rewritten term, so every
  `TraceStep` is a real before/after pair. Strategies are four booleans
  (`Order`): reduce under lambdas, try the root redex first, require the
  argument to be a value, and reduce the argument only when the head is a λ.
  The default is **applicative**, matching the historical `nf`.
- Eta is a separate rule (`etaRoot`/`etaStep`) tried after β via `stepFor`; it is
  off by default and only traverses under lambdas for strong strategies.
- `evalUntil` is the single evaluation loop; it stops on a step limit or a
  predicate and keeps at most `traceLimit` (500) steps during evaluation.
  `traceTruncated` also covers terms clipped to 300 characters. `:nf` uses
  normal order; `:whnf` stops at `isWHNF` (a lambda or a neutral application).
- `:fast on` switches `Eval`/`:nf`/`:conv`/`:int` to `fastNormalForm`:
  de Bruijn terms, environment-based closures and shared thunks (`FastM`). It
  yields only a normal form, uses `:steps` as a β fuel budget, ignores the
  selected strategy and falls back to the step engine while `:eta` is on.
  `:trace` and manual stepping always use the step engine.
- Rendering is bounded: `shorten` forces only the requested prefix of a lazy
  string, so clipping a huge term does not pretty-print it first. `ast`, `db`
  and `astTree` are capped at 400 nodes; huge terms get `astOmitted`,
  `astTreeOmitted`, or a shortened `db`.
- Redexes are enumerated by path (`[Int]`): `redexInfos`, `stepAt`,
  `stepAtIndex`. JSON emits `redexes` (≤200) and exact `redexCount`.
- Definitions are stored already expanded (`expandTop` at definition time), so
  a later redefinition does not retroactively change earlier definitions.
  Recursive definitions are `Z (λname. body)` (the call-by-value fixed point);
  `prettyDef`/`sourceDef` restore the `rec` form for display and saving.
  `Y` remains available as a user-facing combinator.
- Syntax sugar is parser-only: `if c then t else f` becomes `IF c t f`, list
  literals become `CONS`/`NIL`, and multiple `let` bindings nest. The shared
  `parseIf`/`parseList`/`parseLet` declarations are in the core-sync manifest.
- `.lam` loading: `logicalLines` skips `--`/`#` comments and blanks, joins
  continuation lines while parentheses are open or the next line is indented;
  original file line numbers are preserved in errors. `:strategy`, `:steps`,
  `:lang` and `:fast` inside a file are applied by `LoadOutcome`.
- Types are inferred with Hindley–Milner and let-generalisation. Prelude types
  are inferred from expanded terms and hidden in `:env` to keep the table short;
  user definitions show their scheme.
- Output has two modes: decorated text and JSON Lines. JSON is built with the
  `J` ADT and `.=` operator — add fields there rather than concatenating
  strings. `--batch` emits `\x1e` after each command. `emitL` also writes
  `textZh`/`textEn` (and `hintZh`/`hintEn` for results, `typeZh`/`typeEn` for
  types), which is what makes local language switching possible.
- `--timeout <s>` wraps each command with `System.Timeout.timeout` and emits a
  warning instead of a partial result; `Ctrl+C` is caught around `handleLine`
  so the REPL survives. Because a timeout can interrupt output, `emitL` masks
  the actual write.
- `:eq`/`:conv` parse both sides and combine their errors; `.lam` loading
  reports every failing logical line.
- Parsing uses `ReadP`; `parseCommand` returns `Either ParseError Command` with
  a 1-based column. `extension` requires exactly one full parse.
- Church-numeral/boolean/pair/list and combinator hints use α-equivalence
  (`alphaEq`, which walks both binding environments in lockstep), not textual
  matching.

## Repo hygiene

- `.gitignore` uses explicit, sectioned patterns (build artifacts, executables,
  Python caches, editor/OS files, local temp). Never commit compiled output;
  `git ls-files --others --exclude-standard` should only list real sources.
- Windows console note: interactive output is not forced to UTF-8, so a legacy
  console may still garble Unicode; use Windows Terminal or `chcp 65001` there.
