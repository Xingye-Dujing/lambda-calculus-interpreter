# Changelog

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
- Persistent Haskeline history in `~/.lambda_history`.
- A Cabal package that builds both standalone executables.
- MIT license, changelog, GitHub Actions CI, and 10 new test groups (30 total),
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

### Changed

- The web language switch replays history in the same interpreter process
  instead of creating a new session.
- `:save` is disabled over the web unless `LAMBDA_ALLOW_SAVE=1`.
- Prelude schemes are hidden in `:env` to keep the table readable.

### Notes

- Substitution still copies terms; recursive definitions under applicative
  order can grow exponentially by design. Use a smaller `:steps`, normal order,
  or a larger timeout.
