# Lambda Calculus Interpreter with Church Encoding ([中文版](./README-CN.md))

A Haskell implementation of pure lambda calculus: Church numerals and booleans,
capture-avoiding substitution, reduction traces, four evaluation strategies,
simple type inference, and a small definition environment. Two standalone
interpreters are provided:

- `main` — the minimal core REPL.
- `extension` — definitions, file loading, traces, AST/de Bruijn views, types,
  a batch/JSON mode for the web UI, and Chinese/English output.

## Features

- **Pure lambda calculus** with α-equivalence and capture-avoiding substitution.
- **Reduction traces** — every β-step is recorded with its before/after term.
- **Four strategies** — applicative, normal, call-by-name, call-by-value
  (weak strategies stop at weak head normal form).
- **Step limit** (default 10,000) so non-terminating terms report instead of hang.
- **Semantic hints** — Church numerals/booleans/pairs and the `I K S B C W`
  combinators are recognised by α-equivalence.
- **Simple types** — Hindley–Milner inference with let-generalisation (`:type`).
- **Definitions** — `name = expr`, `:load`, `:env`, `:del`, `:reset`.
- **Views** — pretty syntax tree (`:ast`) and de Bruijn indices (`:db`).
- **Bilingual** — every user-facing message has a Chinese and an English form;
  `--lang zh|en|both` or `:lang` selects them (default `both`).

## Screenshots

Light theme, captured from the web UI.

![REPL with a reduction trace](docs/screenshots/main.png)

*Reduction trace: every β-step with a before/after diff, a step player, and the
result annotated with its β-step count and Church-numeral value.*

![Syntax tree and de Bruijn view](docs/screenshots/ast.png)

*Syntax tree of the result, plus the de Bruijn index view for bound variables.*

![Environment inspector](docs/screenshots/env.png)

*Environment panel: definitions are listed with their terms; click a name to
insert it, hover to delete it.*

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

Both compile with `ghc -O2 ... -threaded -rtsopts`. The Windows script also
passes `-package containers -package haskeline`.

## Usage

```bash
./extension [--lang zh|en|both] [--batch] [--json] [-h|--help] [file]
```

If a file is given, its `name = expr` lines are loaded before the REPL.

### REPL commands

| Command | Meaning |
| --- | --- |
| `:help` | show help |
| `:load <file>` | load definitions (`name = expr` per line) |
| `:let name = expr` | define a variable |
| `:env` / `:del <name>` / `:reset` | inspect / delete / reset the environment |
| `:strategy applicative\|normal\|cbn\|cbv` | switch evaluation strategy |
| `:steps <n>` | set the reduction step limit |
| `:trace <expr>` | print the full reduction trace |
| `:ast <expr>` / `:db <expr>` | syntax tree / de Bruijn indices |
| `:type <expr>` | infer the simple type |
| `:begin <expr>` / `:step` / `:run` / `:end` | interactive, one-step reduction |
| `:lang zh\|en\|both` | switch output language |
| `:q` | quit |

### Syntax

- Variables: start with a letter or one of `+ - * / % ^ ? ! < > | & ~ # $`,
  then letters, digits, `_`, `'`, or operators.
- Abstraction: `λx.body` or `\x.body`; multiple parameters: `λx y.body`.
- Application: `f a`, left-associative; grouping: `(expr)`.
- Numbers: `0`…`9999` become Church numerals.
- Definitions: `name = expression`.

### Examples

```text
λ> PLUS ONE TWO
⇒ λf → λx → f (f (f x))  (6 steps)  (Church numeral 3)

λ> :trace (\x.\y.x) y
1. β: (λx. …) y    (α-rename to avoid capture)
2. λy' → y

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
session and speaks the `--batch --json` protocol, so state no longer needs to be
replayed on every keystroke.

- Terminal REPL with history, Tab completion, `Ctrl+L`, and error carets.
- Live panels for **reduction trace** (step player + diff), **AST**, **type**
  and **environment** (click to insert, hover to delete).
- A **Guide** tab (opened on the first visit) explains typing, panels, manual
  reduction and definitions.
- Strategy selector, step-limit control, share link, `.lam` import/export,
  light/dark theme, and a Chinese/English/bilingual switch.
- `GET /api/prelude`, `POST /api/session`, `POST /api/eval` with
  `{"session": "...", "line": "..."}`; the legacy `{"code": "..."}` form still
  works. A 408 response means the term timed out.
- `:load` is confined to the interpreter directory by default; the Env panel's
  **Load** button prompts for such a relative path. Set `LAMBDA_LOAD_ROOT=*` to
  allow any path (local use only).
- Interpreter lookup: `$LAMBDA_INTERP_BIN`, `$LAMBDA_INTERP_DIR/extension[.exe]`,
  `<repo>/extension[.exe]`, `/opt/lambda-calculus-interpreter/extension`.
- `<base href="./">` keeps it working at `/` and behind the `/lambda/` prefix.

```bash
pip install -r web/requirements.txt
python web/app.py          # http://127.0.0.1:8081
```

## Batch and JSON protocol

`--batch` reads one command per stdin line and prints `\x1e` after each result.
`--json` makes every output a JSON object:

```json
{"kind":"result","text":"...","term":"λf → λx → f x","steps":6,
 "limitHit":false,"hint":"...","strategy":"applicative",
 "ast":["λ x","└ • x"],"db":"λ.λ.#0",
 "trace":[{"n":1,"rule":"β","note":"...","before":"...","after":"..."}]}
```

`--batch` also forces UTF-8 on stdin/stdout/stderr, which removes the old
Windows code-page workaround.

## Tests

There is no Cabal/Stack project, so the test suite drives the compiled binary
end-to-end through the JSON protocol:

```bash
./test.sh          # Linux / macOS
test.bat           # Windows
python tests/run_tests.py --bin ./extension
```

19 groups cover parsing positions, β-reduction results, capture avoidance,
traces, all four strategies, step limits, Church/combinator hints, type
inference, environment commands, file loading, manual reduction, AST/de Bruijn,
bilingual output, JSON protocol, determinism, and cross-strategy agreement.

## Notes

- The two files are deliberately standalone; core changes (`Expr`, `subst`,
  `stepOnce`, parser) belong in both.
- `main` has no definitions, types, or environment commands.
- The default strategy is **applicative**, matching the historical `nf`.
  Normal order terminates on more terms but may return weak head normal forms
  under `cbn`/`cbv`.

## License

Open source; free to use and modify for learning or experimentation.
