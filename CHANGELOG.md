# Changelog

## Unreleased

### Fixed

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
  the environment once instead of per line, and settings from `:load` update the
  controls. Web backend: environment limits are clamped, rate-limit buckets are
  bounded, reaped sessions are killed outside the session lock, and streaming
  line splitting matches `/api/eval`.

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
