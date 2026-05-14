# Lambda Calculus Interpreter with Church Encoding

A Haskell-based interpreter for pure lambda calculus, supporting Church numerals, Church booleans, and a macro-like definition environment. Two versions are provided:

- `main`: Minimal interpreter with basic lambda calculus and normal-order reduction.
- `extension`: Enhanced interpreter with definitions, file loading, environment inspection, and extended syntax (operator symbols in variable names, automatic numeral conversion, etc.).

## Features

1. Pure lambda calculus with alpha-equivalence and capture-avoiding substitution.
2. Normal-order (applicative-order) reduction to beta-normal form.
3. Church numeral and Church boolean detection – results are annotated with their numeric/boolean values when applicable.
4. Extension only:

- Define variables (`name = expression`) and reuse them.
- Load definitions from a file (`:load file`).
- Show current environment (`:env`).
- Variables may contain operators (`+`, `-`, `*`, `/`, `%`, `^`, `?`, `!`, `<`, `>`, `|`, `&`, `~`, `#`, `$`), underscores, digits, and quotes, but must not start with a digit.
- Automatic conversion of decimal numbers to Church numerals.
- Built-in predefined environment: `TRUE`, `FALSE`, `NOT`, `AND`, `OR`, `IF`, `ZERO`, `ONE`, `TWO`, `THREE`, `SUCC`, `PLUS`, `MULT`.

## Building

Use the provided `build.sh` script:

```bash
chmod +x build.sh
./build.sh
```

This compiles both interpreters with optimizations (`-O2`, `-split-sections`, `-optlc-O3`, `-threaded`, etc.). The executables `main` and `extension` will be created.

## Usage

### Minimal interpreter (`main`)

```bash
./main
```

This starts a REPL. Enter lambda expressions:

```
λ> \x. x
⇒ λx → x
λ> (\x. x) y
⇒ y
λ> \f x. f (f x)
⇒ λf → λx → f (f x)
λ> (\a.\b.a ((\n.\a.\b.a (n a b)) b)) (\f.\x.f (f x)) (\f.\x.f (f (f x)))
⇒ λx → λb' → x (x (x (x (x (x (x (x (x (x (x (x (x (x (x (x b')))))))))))))))
```

Type `:q` to quit.

### Enhanced interpreter (`extension`)

```bash
./extension [-h,--help] [file]
```

If a file is given, definitions are loaded before entering the REPL.

1. REPL commands:

- `:load <file>`: Load definitions from a file (one `name = expr` per line).
- `:let name = expr`: Define a variable in the current environment.
- `:env`: Show all current definitions.
- `:q`: Quit the interpreter

2. Expression syntax:

- Variables: begin with a letter or an operator character (`+ - * / % ^ ? ! < > | & ~ # $`), followed by letters, digits, underscores, quotes, or more operators.
- Lambda abstraction: `λx.body` or multiple parameters: λx y.body.
- Application: `f a` (left-associative). Use parentheses for grouping.
- Numbers: `0`, `1`, `2`, ..., `9` are automatically converted to Church numerals.
- Definitions: `name = expression` (also allowed directly in REPL).

3. Examples:

```
λ> TRUE
⇒ λt → λf → t  (Church boolean True)
λ> TRUE 2 3
⇒ λf → λx → f (f x)  (Church numeral 2)
λ> PLUS 2 3
⇒ λf → λx → f (f (f (f (f x))))  (Church numeral 5)
λ> 3 2
⇒ λx → λx' → x (x (x (x (x (x (x (x x')))))))  (Church numeral 8)
λ> 2 3
⇒ λx → λx' → x (x (x (x (x (x (x (x (x x'))))))))  (Church numeral 9)
λ> + = PLUS
defined + = λm → λn → λf → λx → m f (n f x)
λ> + 4 3
⇒ λf → λx → f (f (f (f (f (f (f x))))))  (Church numeral 7)
λ> :env
┌──────────┬─────────────────────────────────┐
│ Var Name │ Value                           │
├──────────┼─────────────────────────────────┤
│ +        │ λm → λn → λf → λx → m f (n f x) │
│ AND      │ λb1 → λb2 → b1 b2 FALSE         │
│ FALSE    │ λt → λf → f                     │
│ IF       │ λc → λt → λf → c t f            │
│ MULT     │ λm → λn → λf → m (n f)          │
│ NOT      │ λb → b FALSE TRUE               │
│ ONE      │ λf → λx → f x                   │
│ OR       │ λb1 → λb2 → b1 TRUE b2          │
│ PLUS     │ λm → λn → λf → λx → m f (n f x) │
│ SUCC     │ λn → λf → λx → f (n f x)        │
│ THREE    │ λf → λx → f (f (f x))           │
│ TRUE     │ λt → λf → t                     │
│ TWO      │ λf → λx → f (f x)               │
│ ZERO     │ λf → λx → x                     │
└──────────┴─────────────────────────────────┘
λ> :load test.lam

成功加载 7 个定义：
┌─────────────────┬─────────────────────────────────────────────────────────────────┐
│ Var Name        │ Value                                                           │
├─────────────────┼─────────────────────────────────────────────────────────────────┤
│ id              │ λ? → ?                                                          │
│ *               │ λm → λn → λf → m (n f)                                          │
│ +               │ λm → λn → λf → λx → m f (n f x)                                 │
│ aPOWbPOWc       │ λa → λb → λc → c b a                                            │
│ tow_pow_eight   │ (λf → λx → f (f (f x))) (λf → λx → f (f x)) (λf → λx → f (f x)) │
│ POW             │ λa → λb → b a                                                   │
│ b_ADD_ONE_POW_a │ λa → λb → b ((λn → λf → λx → f (n f x)) a)                      │
└─────────────────┴─────────────────────────────────────────────────────────────────┘

！！！以下 2 行解析失败（已忽略）：
  第 4 行: ERROR = \a.a b c)
  第 2 行: ERR  = \a.

λ> :env
┌─────────────────┬─────────────────────────────────────────────────────────────────┐
│ Var Name        │ Value                                                           │
├─────────────────┼─────────────────────────────────────────────────────────────────┤
│ *               │ λm → λn → λf → m (n f)                                          │
│ +               │ λm → λn → λf → λx → m f (n f x)                                 │
│ AND             │ λb1 → λb2 → b1 b2 FALSE                                         │
│ FALSE           │ λt → λf → f                                                     │
│ IF              │ λc → λt → λf → c t f                                            │
│ MULT            │ λm → λn → λf → m (n f)                                          │
│ NOT             │ λb → b FALSE TRUE                                               │
│ ONE             │ λf → λx → f x                                                   │
│ OR              │ λb1 → λb2 → b1 TRUE b2                                          │
│ PLUS            │ λm → λn → λf → λx → m f (n f x)                                 │
│ POW             │ λa → λb → b a                                                   │
│ SUCC            │ λn → λf → λx → f (n f x)                                        │
│ THREE           │ λf → λx → f (f (f x))                                           │
│ TRUE            │ λt → λf → t                                                     │
│ TWO             │ λf → λx → f (f x)                                               │
│ ZERO            │ λf → λx → x                                                     │
│ aPOWbPOWc       │ λa → λb → λc → c b a                                            │
│ b_ADD_ONE_POW_a │ λa → λb → b ((λn → λf → λx → f (n f x)) a)                      │
│ id              │ λ? → ?                                                          │
│ tow_pow_eight   │ (λf → λx → f (f (f x))) (λf → λx → f (f x)) (λf → λx → f (f x)) │
└─────────────────┴─────────────────────────────────────────────────────────────────┘
λ> aPOWbPOWc 1 2 2
⇒ λx' → λx → x' x  (Church numeral 1)
λ> aPOWbPOWc 2 2 2
⇒ λx' → λx → x' (x' (x' (x' (x' (x' (x' (x' (x' (x' (x' (x' (x' (x' (x' (x' x)))))))))))))))  (Church numeral 16)
λ> id 3
⇒ λf → λx → f (f (f x))  (Church numeral 3)
λ> :let FOUR = \f x.f (f (f (f x)))
defined FOUR = λf → λx → f (f (f (f x)))
λ> FOUR
⇒ λf → λx → f (f (f (f x)))  (Church numeral 4)
λ> :q
```

## Technical Overview

1. Both interpreters implement:

- Capture-avoiding substitution using de Bruijn-like variable renaming (`freshVar`).
- Normal‑order reduction (`nf`) that fully reduces expressions to beta-normal form.
- Free variable calculation to avoid variable capture.

2. The extension adds:

- Macro expansion (`expand`): replaces defined variables with their bodies, respecting bound variables to avoid capture.
- Parser with custom identifier rules and automatic number‑to‑Church conversion.
- File loading with error reporting and a fold‑based line processor.
- Dynamic table printing that adjusts column widths to the longest variable name and expression.

## License

This project is open source. Feel free to use and modify it for learning or experimentation.
