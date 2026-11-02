# AGENTS.md

Two independent, single-file Haskell interpreters for pure lambda calculus. No
Cabal/Stack project or linter; `ghc` compilation plus the end-to-end test suite
are the checks. Documentation and user-facing text are **bilingual
Chinese/English**.

## Build, run, test

- Windows: `.\build.bat`; Unix: `./build.sh`. Both call `ghc` directly and
  produce `main`/`extension` (`main.exe`/`extension.exe` on Windows). A Cabal
  file (`cabal build all`) packages the same two executables; the files stay
  standalone by design.
- `build.bat` also passes `-package containers -package haskeline -package
  directory`; keep those flags if adding Windows build steps.
- **Tests:** `.\test.bat` / `./test.sh`, or
  `python tests/run_tests.py [--bin path]`. The suite drives the compiled
  `extension --batch --json` binary end-to-end (30 groups), including a
  `main`/`extension` differential test. Run it after any core change; it is the
  regression net for `main.hs` and `extension.hs`.
- `./main` — minimal REPL (`:q` to quit).
- `./extension [file...] [-h|--help] [-v|--version] [--lang zh|en|both] [--lang=zh]
  [--timeout 秒] [--batch] [--json]` — full REPL with definitions. REPL commands: `:help`, `:load`, `:save`, `:let`,
  `:env`, `:del`, `:reset`, `:strategy`, `:steps`, `:eta`, `:trace`, `:ast`,
  `:db`, `:type`, `:eq`, `:conv`, `:nf`, `:whnf`, `:int`, `:church`, `:begin`,
  `:step [n]`, `:run`, `:end`, `:lang`, `:q`.
- `test.lam` is a sample definitions file. Its `ERR` and `ERROR` lines are
  intentionally malformed to exercise load-error reporting; do not "fix" them.

## Language and output

- All comments, help text, errors, and UI strings carry both Chinese and
  English. Use the `tr`/`renderMsg` helpers and the `Msg` type; do not add a
  Chinese-only or English-only string.
- Comment lines must not end with a Chinese full stop `。`: end with nothing or
  an English period instead.
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
  for the short `#s=<id>` links. All are covered by tests.
- `index.html` uses `<base href="./">` so it works at `/` and behind the
  production `/lambda/` prefix (Caddy `handle_path` strips it). Fonts are served
  by Flask at `/fonts/<file>`; the favicon is `web/icon.svg`.
- Every `Command` has a UI entry: manual reduction controls (`:begin`/`:step`/
  `:run`/`:end`), the step-limit input (`:steps`), Env **load** (`:load`) and
  **reset** (`:reset`), the **Tools** tab (`:eq`/`:conv`/`:nf`/`:whnf`/`:int`/
  `:church`/`:eta`/recursive `rec`/`:save`), and the redex buttons
  (`:step <n>`). Keep it that way when adding commands.
- Do not use native `select`, `prompt`, `confirm` or `alert`: use the custom
  `.sel` menus and the `dialog()` helper so popups match the wireframe theme.
- The desktop layout is a fixed `100vh` flex column: terminal and inspector share
  one row height, both scroll internally, and the page never scrolls. The AST
  view offers a collapsible `astTree` and an SVG graph, plus a text tree.
- The first visit defaults to the light theme; the toggle persists the choice in
  `localStorage` (the OS `prefers-color-scheme` is intentionally not consulted).
- The **Guide** tab (`renderGuide`) opens when there is no saved state; keep its
  steps in sync with UI changes.
- Switching language calls the lang route and re-renders the transcript locally
  from `textZh`/`textEn`; it must not replay `codeLines` or rebuild the session.
  Result meta uses `hintZh`/`hintEn`, types use `typeZh`/`typeEn`.
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
  `freeVars`, `freshVar`, `subst`, `stepOnce`, `eval`, parser) is duplicated:
  apply core/reduction fixes to both files.
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
- `evalUntil` stops on a step limit or a predicate. `:nf` uses normal order;
  `:whnf` stops at `isWHNF` (a lambda or a neutral application).
- Redexes are enumerated by path (`[Int]`): `allRedexPaths`, `stepAt`,
  `stepAtIndex`. JSON emits `redexes` (≤200) and exact `redexCount`.
- Traces keep at most 500 steps (`traceLimit`) **during evaluation**, not just
  at output time; `traceTruncated` also covers terms clipped to 300 characters.
  `astTree` is capped at 400 nodes; larger terms get `astTreeOmitted`.
- Definitions are stored already expanded (`expandTop` at definition time), so
  a later redefinition does not retroactively change earlier definitions.
  Recursive definitions are `Y (λname. body)`; `prettyDef`/`sourceDef` restore
  the `rec` form for display and saving.
- `.lam` loading: `logicalLines` skips `--`/`#` comments and blanks, joins
  continuation lines while parentheses are open or the next line is indented;
  original file line numbers are preserved in errors. `:strategy`, `:steps` and
  `:lang` inside a file are applied by `LoadOutcome`.
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
  (`toDB`, which drops binder names), not textual matching.

## Repo hygiene

- `.gitignore` uses explicit, sectioned patterns (build artifacts, executables,
  Python caches, editor/OS files, local temp). Never commit compiled output;
  `git ls-files --others --exclude-standard` should only list real sources.
- Windows console note: interactive output is not forced to UTF-8, so a legacy
  console may still garble Unicode; use Windows Terminal or `chcp 65001` there.
