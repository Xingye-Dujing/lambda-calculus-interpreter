# AGENTS.md

Two independent, single-file Haskell interpreters for pure lambda calculus. There is no Cabal/Stack project, test suite, linter, formatter, or CI — `ghc` compilation is the only check.

## Build and run

- Windows: `.\build.bat`; Unix: `./build.sh`. Both call `ghc` directly and produce `main`/`extension` (`main.exe`/`extension.exe` on Windows).
- `build.bat` also passes `-package containers -package haskeline`; keep those flags if adding Windows build steps.
- `./main` — minimal REPL (`:q` to quit).
- `./extension [file] [-h|--help]` — REPL with definitions; `file` loads `name = expr` lines at startup. REPL commands: `:load <file>`, `:let name = expr`, `:env`, `:q`.
- `test.lam` is a sample definitions file. Its `ERR` and `ERROR` lines are intentionally malformed to exercise load-error reporting; do not "fix" them.

## Web UI (`web/`)

- Flask wrapper (`web/app.py`) + terminal-style page (`web/index.html`) for `extension`; no build step for the frontend. Python deps: `pip install -r web/requirements.txt`, run `python web/app.py` (defaults `127.0.0.1:8081`, override with `HOST`/`PORT`).
- Interpreter lookup: `$LAMBDA_INTERP_BIN`, `$LAMBDA_INTERP_DIR/extension[.exe]`, `<repo>/extension[.exe]`, `/opt/lambda-calculus-interpreter/extension`. Build `extension` before running.
- The backend is stateless: the page replays all prior input lines so definitions persist. `POST /api/eval` takes `{"code": "..."}`; the 10-second timeout maps to HTTP 408.
- `index.html` uses `<base href="./">` so it works at `/` and behind the production `/lambda/` prefix (Caddy `handle_path` strips it). Fonts are served by Flask at `/fonts/<file>`.
- Windows: `run_interpreter` switches the console code page to UTF-8 and rewrites `λ` to `\`, because GHC otherwise writes GBK and crashes on `⇒`. Keep that workaround when changing the subprocess call; send bytes (not `text=True`) so Python does not translate `\n` to `\r\n`, which the REPL cannot parse.

## Architecture

- `main.hs` and `extension.hs` are deliberately standalone. The core (`Expr`, `freeVars`, `freshVar`, `subst`, `nf`, `pretty`, parser) is duplicated: apply core/reduction fixes to both files.
- `extension.hs` adds `Env` (`Data.Map`), macro expansion (`expand`/`expandTop`), definitions, file loading, `:env`, numeric literals, and wider identifier characters.
- Evaluation order is **applicative**: `nf` normalizes the argument before substitution, even though both READMEs call it "normal-order". Trust the code; do not switch order without being asked, since it changes termination behavior.
- Definitions are stored already expanded (`expandTop` at definition time), so a later redefinition does not retroactively change earlier definitions.
- Parsing uses `ReadP`; `extension` requires exactly one full parse (`[(x, "")]`), so ambiguous input is rejected rather than partially accepted.
- Church-numeral/boolean hints are shallow syntactic matches on `λf.λx.…` / `λt.λf.…`; equivalent terms may print without a hint. That is expected, not a reduction bug.
- REPL prompts, errors, and help text are Chinese, and `λ`/`→`/`⇒`/box-drawing characters are part of the output. Keep new UI strings Chinese and Unicode-consistent.

## Windows gotchas

- The binaries emit Unicode. On a legacy console this garbles output or crashes with `commitBuffer: invalid argument (cannot encode character ...)`; run under UTF-8 (`chcp 65001`) or Windows Terminal.
- Avoid piping test input through `cmd`/PowerShell `echo`: it appends `\r`, and `extension` matches `:q`/`:env` exactly, so the command is not recognized. Use an interactive terminal, or feed LF-only input.
- Build artifacts (`*.o`, `*.hi`, `*.exe`) are matched by the catch-all `.gitignore`; only `.hs`, `.lam`, `.sh`, `.bat`, `.md`, and `web/**` are whitelisted. Never commit compiled output.
