# Changelog

## Unreleased

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
  web UI test (32 groups).

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
