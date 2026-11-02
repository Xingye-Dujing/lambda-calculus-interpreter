# AGENTS.md

Two independent, single-file Haskell interpreters for pure lambda calculus. No
Cabal/Stack project or linter; `ghc` compilation plus the end-to-end test suite
are the checks. Documentation and user-facing text are **bilingual
Chinese/English**.

## Build, run, test

- Windows: `.\build.bat`; Unix: `./build.sh`. Both call `ghc` directly and
  produce `main`/`extension` (`main.exe`/`extension.exe` on Windows).
- `build.bat` also passes `-package containers -package haskeline`; keep those
  flags if adding Windows build steps.
- **Tests:** `.\test.bat` / `./test.sh`, or
  `python tests/run_tests.py [--bin path]`. The suite drives the compiled
  `extension --batch --json` binary end-to-end (19 groups). Run it after any
  core change; it is the regression net for `main.hs` and `extension.hs`.
- `./main` — minimal REPL (`:q` to quit).
- `./extension [file] [-h|--help] [--lang zh|en|both] [--batch] [--json]` —
  full REPL with definitions. REPL commands: `:help`, `:load`, `:let`, `:env`,
  `:del`, `:reset`, `:strategy`, `:steps`, `:trace`, `:ast`, `:db`, `:type`,
  `:begin`/`:step`/`:run`/`:end`, `:lang`, `:q`.
- `test.lam` is a sample definitions file. Its `ERR` and `ERROR` lines are
  intentionally malformed to exercise load-error reporting; do not "fix" them.

## Language and output

- All comments, help text, errors, and UI strings carry both Chinese and
  English. Use the `tr`/`renderMsg` helpers and the `Msg` type; do not add a
  Chinese-only or English-only string.
- Default output language is `both`; `--lang` / `:lang` switch to `zh` or `en`.
  The web UI has its own `I18N` dictionary and sends `:lang` to the session.
- Keep `λ`/`→`/`⇒`/box-drawing characters and the terminal-style formatting.

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
  the session and returns 408; the frontend rebuilds and replays its lines.
- `index.html` uses `<base href="./">` so it works at `/` and behind the
  production `/lambda/` prefix (Caddy `handle_path` strips it). Fonts are served
  by Flask at `/fonts/<file>`.
- `--batch` sets stdin/stdout/stderr to UTF-8, which removes the old Windows
  `chcp` and `λ`→`\` workarounds. Keep the UTF-8 setup when changing the
  subprocess call; send bytes (not `text=True`) so Python does not translate
  `\n` to `\r\n`.

## Architecture

- `main.hs` and `extension.hs` are deliberately standalone. The core (`Expr`,
  `freeVars`, `freshVar`, `subst`, `stepOnce`, `evalTrace`, `pretty`, parser) is
  duplicated: apply core/reduction fixes to both files.
- `extension.hs` adds `Env` (`Data.Map`), macro expansion (`expand`/`expandTop`,
  with an expansion fuel), definitions, file loading, `:env`, numeric literals,
  types, and wider identifier characters.
- Reduction is small-step: `stepOnce` returns the whole rewritten term, so every
  `TraceStep` is a real before/after pair. Strategies are four booleans
  (`Order`): reduce under lambdas, try the root redex first, require the
  argument to be a value, and reduce the argument only when the head is a λ.
  The default is **applicative**, matching the historical `nf`.
- `nf` and `:eval` stop at the step limit (default 10000) and report
  `limitHit` instead of hanging. Weak strategies (`cbn`, `cbv`) stop at weak
  head normal form; that is intentional.
- Definitions are stored already expanded (`expandTop` at definition time), so
  a later redefinition does not retroactively change earlier definitions. Types
  are inferred from the source expression and generalized (HM with let).
- Output has two modes: decorated text and JSON Lines. JSON is built with the
  `J` ADT and `.=` operator — add fields there rather than concatenating
  strings. `--batch` emits `\x1e` after each command.
- Parsing uses `ReadP`; `parseCommand` returns `Either ParseError Command` with
  a 1-based column. `extension` requires exactly one full parse.
- Church-numeral/boolean/pair and combinator hints use α-equivalence
  (`toDB`), not textual matching.

## Repo hygiene

- `.gitignore` uses explicit, sectioned patterns (build artifacts, executables,
  Python caches, editor/OS files, local temp). Never commit compiled output;
  `git ls-files --others --exclude-standard` should only list real sources.
- Windows console note: interactive output is not forced to UTF-8, so a legacy
  console may still garble Unicode; use Windows Terminal or `chcp 65001` there.
