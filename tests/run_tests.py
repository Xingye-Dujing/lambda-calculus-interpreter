#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端回归测试 / End-to-end regression tests.

设计目标 / Design goals
-----------------------
* 只依赖 Python 标准库，无需 Cabal / Stack / pytest
  Only the Python standard library is required (no Cabal, Stack or pytest).
* 直接驱动编译好的 `extension --batch --json`，因此测的是最终产物本身
  It drives the compiled `extension --batch --json` binary, so the shipped
  artifact is what gets tested.
* 覆盖：解析错误位置、β 归约结果、求值策略、步数上限、Church 编码提示、
  类型推断、环境操作、手动归约与 redex 选择、正规形/η、α/β 等价、文件功能、
  语法树、de Bruijn、双语输出、JSON 协议、属性测试与 main/extension 差分
  Covers parse positions, β-reduction results, strategies, step limits,
  Church hints, type inference, environment commands, manual reduction and
  redex picking, normal forms/eta, α/β equivalence, file features, syntax trees,
  de Bruijn view, bilingual output, the JSON protocol, randomized properties
  and a main/extension differential test.

用法 / Usage
------------
    python tests/run_tests.py
    python tests/run_tests.py --bin path/to/extension
    python tests/run_tests.py -v
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RS = "\x1e"  # 批处理模式每条命令后的记录分隔符 / record separator

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILURES.append(f"{name}: {detail}" if detail else name)


def find_binary(explicit: str | None = None) -> Path:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    env_bin = os.environ.get("LAMBDA_INTERP_BIN")
    if env_bin:
        candidates.append(Path(env_bin))
    names = ["extension.exe", "extension"] if os.name == "nt" else ["extension", "extension.exe"]
    candidates.extend(ROOT / n for n in names)
    for c in candidates:
        if c.is_file():
            return c
    raise SystemExit(
        "找不到解释器 / interpreter not found. 先运行 build.bat 或 build.sh"
    )


def run(lines: list[str], binary: Path, lang: str = "en", timeout: float = 30.0) -> list[list[dict]]:
    """运行一组命令，返回“每条命令的输出对象列表”

    Run a batch of commands and return one list of JSON objects per command.
    """
    code = "\n".join(lines) + "\n"
    proc = subprocess.run(
        [str(binary), "--batch", "--json", "--lang", lang],
        input=code.encode("utf-8"),
        capture_output=True,
        timeout=timeout,
        cwd=str(ROOT),
    )
    text = proc.stdout.decode("utf-8", "replace")
    if proc.returncode not in (0, 1):
        raise RuntimeError(proc.stderr.decode("utf-8", "replace"))
    chunks = text.split(RS)
    out: list[list[dict]] = []
    for chunk in chunks[:-1]:  # 最后一段是 RS 之后的空串 / trailing empty chunk
        objs = [json.loads(line) for line in chunk.splitlines() if line.strip()]
        out.append(objs)
    return out


def one(lines: list[str], binary: Path, lang: str = "en", index: int = -1) -> dict:
    """取最后一条命令的第一个输出对象（常用于单命令断言）

    First output object of one command (usually the last command).
    """
    results = run(lines, binary, lang)
    objs = results[index]
    return objs[0] if objs else {}


# ---------------------------------------------------------------------------
# 归约正确性 / Reduction correctness
# ---------------------------------------------------------------------------

def test_church_arithmetic(b: Path) -> None:
    cases = [
        ("PLUS ONE TWO", "λf → λx → f (f (f x))", 3),
        ("MULT TWO THREE", "λf → λx → f (f (f (f (f (f x)))))", 6),
        ("SUCC THREE", "λf → λx → f (f (f (f x)))", 4),
        ("IF TRUE ONE TWO", "λf → λx → f x", 1),
        ("IF FALSE ONE TWO", "λf → λx → f (f x)", 2),
    ]
    for expr, expected, numeral in cases:
        r = one([expr], b)
        check(f"{expr} term", r.get("term") == expected, repr(r.get("term")))
        check(f"{expr} steps", r.get("steps", 0) > 0, str(r.get("steps")))
        check(f"{expr} hint", f"Church numeral {numeral}" in r.get("hint", ""), r.get("hint", ""))
        check(f"{expr} kind", r.get("kind") == "result", r.get("kind", ""))


def test_booleans(b: Path) -> None:
    checks = [
        ("NOT FALSE", "λt → λf → t", "Church boolean True"),
        ("AND TRUE FALSE", "λt → λf → f", "boolean False"),
        ("OR FALSE TRUE", "λt → λf → t", "Church boolean True"),
        ("TRUE", "λt → λf → t", "Church boolean True"),
        ("FALSE", "λt → λf → f", "Church boolean False"),
    ]
    for expr, term, hint in checks:
        r = one([expr], b)
        check(f"{expr} term", r.get("term") == term, repr(r.get("term")))
        check(f"{expr} hint", hint in r.get("hint", ""), r.get("hint", ""))


def test_combinators_and_alpha(b: Path) -> None:
    r = one(["\\x.x"], b)
    check("I combinator", r.get("term") == "λx → x" and "I combinator" in r.get("hint", ""), str(r))
    r = one(["\\x.\\y.x"], b)
    check("K is also TRUE", "K combinator" in r.get("hint", ""), r.get("hint", ""))
    # 自由变量 y 不能被 λy 捕获：必须先 α-重命名
    # The free y must not be captured by λy, so an α-rename is required.
    r = one(["(\\x.\\y.x) y"], b)
    check("capture avoidance term", r.get("term") == "λy' → y", repr(r.get("term")))
    check("capture avoidance rule", r.get("trace", [{}])[0].get("rule") == "β+α", str(r.get("trace")))

    # x 不在 λ 体中时无需 α-重命名
    # No α-rename is needed when x is not free in the lambda body.
    r = one(["(\\x.\\y.y) y"], b)
    check("no spurious alpha term", r.get("term") == "λy → y", repr(r.get("term")))
    check("no spurious alpha rule", r.get("trace", [{}])[0].get("rule") == "β", str(r.get("trace")))
    # 内层同名绑定遮蔽 x 时，redex 列表与轨迹的规则必须一致
    # When an inner binder shadows x, the redex list and trace must agree.
    r = one([":begin (\\x.\\x.\\y.x) y"], b)
    check("redex rule matches trace", r.get("redexes", [{}])[0].get("rule") == "β", str(r.get("redexes")))


def test_beta_steps(b: Path) -> None:
    r = one(["PLUS ONE TWO"], b)
    trace = r.get("trace", [])
    check("trace non-empty", len(trace) == r.get("steps"), f"{len(trace)} vs {r.get('steps')}")
    check("trace indices", [t["n"] for t in trace] == list(range(1, len(trace) + 1)), str(trace))
    check("trace chain", all(trace[i]["before"] == trace[i - 1]["after"] for i in range(1, len(trace))), "")
    check("trace ends at result", trace[-1]["after"] == r.get("term"), "")


def test_no_step_is_identity(b: Path) -> None:
    r = one(["\\x.x"], b)
    check("normal form has no trace", "trace" not in r and r.get("steps") == 0, str(r))


# ---------------------------------------------------------------------------
# 求值策略 / Evaluation strategies
# ---------------------------------------------------------------------------

def test_strategies(b: Path) -> None:
    omega = "((\\x.x x)(\\x.x x))"
    # 正规序 / 按名调用会先消去 K，永不触及 Ω；应用序 / 按值调用会先归约参数，从而发散
    # Normal order and call-by-name discard Ω; applicative order and call-by-value diverge.
    r = one([":strategy normal", f"(\\x.y) {omega}"], b)
    check("normal order terminates on K Ω", r.get("term") == "y", repr(r.get("term")))
    check("normal order one step", r.get("steps") == 1, str(r.get("steps")))

    r = one([":strategy cbn", f"(\\x.y) {omega}"], b)
    check("call-by-name terminates on K Ω", r.get("term") == "y", repr(r.get("term")))

    # 按名调用是弱策略：中性头应用不归约参数
    # Call-by-name is weak: a neutral-head application does not reduce its argument.
    r = one([":strategy cbn", "x ((\\y.y) z)"], b)
    check("cbn weak neutral head", r.get("term") == "x ((λy → y) z)" and r.get("steps") == 0, str(r))

    results = run([":steps 40", ":strategy applicative", f"(\\x.y) {omega}"], b)
    r = results[-1][0]
    check("applicative order diverges on K Ω", r.get("limitHit") is True, str(r.get("limitHit")))
    check("applicative divergence warns", r.get("kind") == "warn", r.get("kind", ""))

    results = run([":steps 40", ":strategy cbv", f"(\\x.y) {omega}"], b)
    r = results[-1][0]
    check("call-by-value diverges on K Ω", r.get("limitHit") is True, str(r.get("limitHit")))

    # 强归约策略（应用序 / 正规序）对终止项应给出完整正规形
    # The strong strategies yield full normal forms on terminating terms.
    for strat in ("applicative", "normal"):
        r = one([f":strategy {strat}", "SUCC (PLUS ONE TWO)"], b)
        check(f"{strat} SUCC(PLUS ONE TWO)", r.get("term") == "λf → λx → f (f (f (f x)))", repr(r.get("term")))


def test_strategy_command(b: Path) -> None:
    r = one([":strategy normal"], b)
    check("strategy ack", "normal" in r.get("text", ""), str(r))
    r = one([":strategy nope"], b)
    check("bad strategy rejected", r.get("kind") == "error", str(r))


# ---------------------------------------------------------------------------
# 步数上限 / Step limit
# ---------------------------------------------------------------------------

def test_step_limit(b: Path) -> None:
    r = one([":steps 5", "(\\x.x x)(\\x.x x)"], b)
    check("limit hit", r.get("limitHit") is True, str(r))
    check("limit steps", r.get("steps") == 5, str(r.get("steps")))
    check("limit kind", r.get("kind") == "warn", r.get("kind", ""))
    check("limit message", "step limit" in r.get("text", "").lower(), r.get("text", ""))
    r = one([":steps 0"], b)
    check("zero limit rejected", r.get("kind") == "error", str(r))


# ---------------------------------------------------------------------------
# 解析错误 / Parse errors
# ---------------------------------------------------------------------------

def test_parse_errors(b: Path) -> None:
    r = one(["(\\x.x"], b)
    check("unbalanced paren pos", r.get("pos") == 1, str(r))
    check("unbalanced paren msg", "Unbalanced parenthesis" in r.get("text", ""), str(r))

    r = one(["\\x"], b)
    check("missing dot msg", "missing '.'" in r.get("text", ""), str(r))

    # 箭头存在但缺少函数体：不应再被误报为“缺少分隔符”
    # Arrow present but body missing: must not be misdiagnosed as missing separator.
    r = one(["\\x ->"], b)
    check("arrow no body not missing separator", "missing" not in r.get("text", ""), str(r))
    check("arrow no body is parse error", r.get("kind") == "error", str(r))

    r = one(["1a = 2"], b)
    check("invalid name pos", r.get("pos") == 1, str(r))
    check("invalid name msg", "Invalid name" in r.get("text", ""), str(r))

    r = one([":nope"], b)
    check("unknown command", "Unknown command" in r.get("text", ""), str(r))

    r = one(["(λx.x))"], b)
    check("extra close paren pos", r.get("pos") == 7, str(r))

    r = one([""], b)
    check("empty input", r.get("kind") == "error", str(r))


# ---------------------------------------------------------------------------
# 类型推断 / Type inference
# ---------------------------------------------------------------------------

def test_types(b: Path) -> None:
    r = one(["id = \\x.x"], b)
    check("definition is typed", "polymorphic" in r.get("type", ""), str(r))
    check("definition name/value", r.get("name") == "id" and r.get("value") == "λx → x", str(r))

    r = one(["id = \\x.x", ":type id"], b)
    check("type of id", r.get("type") == "t0 → t0 (polymorphic)", str(r))

    r = one([":type \\f.\\x.f (f x)"], b)
    check("type of church 2", r.get("type", "").startswith("(t0 → t0) → t0 → t0"), str(r))

    r = one([":type \\x.x x"], b)
    check("occurs check", "infinite type" in r.get("text", ""), str(r))

    # 自由变量是单态的：同一名字的两次出现共享一个类型
    # Free variables are monomorphic: both occurrences of a name share one type.
    r = one([":type x x"], b)
    check("free var self-application", "infinite type" in r.get("text", ""), str(r))
    r = one([":type x"], b)
    check("free var not polymorphic", "(polymorphic)" not in r.get("type", ""), str(r))
    r = one([":type x y"], b)
    check("free var result not polymorphic", "(polymorphic)" not in r.get("type", ""), str(r))

    # 重新定义为不可类型化的项后，旧类型方案必须被清除，且报告无简单类型
    # Redefining to an untypable term must drop the stale type scheme and
    # report that it has no simple type.
    outs = run(["f = \\x.x", ":type f", "f = \\x.x x", ":type f"], b)
    check("first type", outs[1][0].get("type") == "t0 → t0 (polymorphic)", str(outs[1]))
    check("stale type dropped", outs[3][0].get("kind") == "fail", str(outs[3]))

    # 已定义但无简单类型的名字不能当作自由变量返回 t0
    # A defined name with no simple type must not report a free t0.
    r = one([":type Y"], b)
    check("type of Y fails", r.get("kind") == "fail", str(r))
    r = one(["rec g = \\x.x", ":type g"], b)
    check("type of rec fails", r.get("kind") == "fail", str(r))

    # 无简单类型的定义出现在更大的表达式里时也必须拒绝
    # An untypable definition used inside a larger expression must be rejected too.
    r = one([":type Y x"], b)
    check("untyped name inside expression fails", r.get("kind") == "fail", str(r))
    r = one([":type PLUS Y"], b)
    check("untyped prelude name inside expression fails", r.get("kind") == "fail", str(r))

    # 多态定义可以在两种类型下使用
    # A polymorphic definition may be used at two different types.
    r = one(["id = \\x.x", ":type (\\f.f) id"], b)
    check("polymorphism usable", r.get("kind") == "type", str(r))


# ---------------------------------------------------------------------------
# 环境 / Environment
# ---------------------------------------------------------------------------

def test_environment(b: Path) -> None:
    results = run([":env"], b)
    rows = {r["name"]: r["value"] for r in results[-1][0].get("rows", [])}
    check("prelude TRUE", rows.get("TRUE") == "λt → λf → t", str(rows.get("TRUE")))
    check("prelude has PLUS", "PLUS" in rows, str(list(rows)))

    results = run(["x = \\a.a", ":del x", ":env"], b)
    check("del ack", "Deleted x" in results[1][0].get("text", ""), str(results[1]))
    rows = {r["name"] for r in results[2][0].get("rows", [])}
    check("deleted x gone", "x" not in rows, str(rows))

    results = run([":del NOPE"], b)
    check("delete missing", results[-1][0].get("kind") == "fail", str(results[-1]))

    results = run(["x = \\a.a", ":reset", ":env"], b)
    rows = {r["name"] for r in results[-1][0].get("rows", [])}
    check("reset drops user defs", "x" not in rows, str(rows))
    check("reset keeps prelude", "TRUE" in rows, str(rows))

    # 重定义预定义名字后应显示新定义的类型，而不是继续隐藏
    # A redefined prelude name must show the new definition's type.
    rows = {r["name"]: r for r in run(["TRUE = \\a.\\b.b", ":env"], b)[-1][0].get("rows", [])}
    check("redefined prelude keeps type", bool(rows.get("TRUE", {}).get("type")),
          str(rows.get("TRUE")))
    out = one(["TRUE = \\a.\\b.b", ":def TRUE"], b)
    check(":def redefined prelude keeps type", bool(out.get("type")), str(out))


def test_load_file(b: Path) -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "defs.lam"
        path.write_text("id = \\x.x\nbad = \\a.\nconst = \\x.\\y.x\n", encoding="utf-8")
        results = run([f":load {path}"], b)
        objs = results[-1]
        defines = [o for o in objs if o.get("kind") == "define"]
        errors = [o for o in objs if o.get("kind") == "error"]
        infos = [o for o in objs if o.get("kind") == "info"]
        check("load ok count", len(defines) == 2, str([o.get("name") for o in defines]))
        check("load error count", len(errors) == 1, str(errors))
        check("load summary", any("Loaded 2" in o.get("text", "") for o in infos), str(infos))
        check("load error line", "line 2" in errors[0].get("text", "").lower(), errors[0].get("text", ""))

        # 从文件加载时把已有变量重定义为不可类型化的项，旧类型方案必须被清除
        # Loading a file that redefines an existing var to an untypable term
        # must drop its stale type scheme.
        redef = Path(td) / "redef.lam"
        redef.write_text("f = \\x.x x\n", encoding="utf-8")
        outs = run(["f = \\x.x", ":type f", f":load {redef}", ":type f"], b)
        check("load redef first type", outs[1][0].get("type") == "t0 → t0 (polymorphic)", str(outs[1]))
        check("load redef stale dropped", outs[3][0].get("kind") == "fail", str(outs[3]))


# ---------------------------------------------------------------------------
# 手动归约 / Manual reduction
# ---------------------------------------------------------------------------

def test_manual_reduction(b: Path) -> None:
    results = run([":begin (\\x.x) ((\\y.y) z)", ":step", ":run"], b)
    started = results[0][0]
    check("begin term", started.get("kind") == "term" and started.get("term"), str(started))
    step = results[1][0]
    check("step kind", step.get("kind") == "step", str(step))
    check("applicative first arg", step.get("term") == "(λx → x) z", repr(step.get("term")))
    final = results[2][0]
    check("run final", final.get("term") == "z", repr(final.get("term")))

    results = run([":step"], b)
    check("step without begin", results[-1][0].get("kind") == "fail", str(results[-1]))


# ---------------------------------------------------------------------------
# 语法树 / de Bruijn / 显示
# ---------------------------------------------------------------------------

def test_views(b: Path) -> None:
    r = one([":ast \\x.x y"], b)
    check("ast tree", r.get("tree") == ["λ x", "└ App", "  ├ • x", "  └ • y"], str(r.get("tree")))

    r = one([":db \\x.\\y.x y"], b)
    check("de bruijn", r.get("text") == "λ.λ.(#1 #0)", repr(r.get("text")))
    check("de bruijn kind", r.get("kind") == "db", repr(r.get("kind")))
    check("de bruijn ast", isinstance(r.get("ast"), list) and len(r.get("ast")) == 5, str(r.get("ast")))
    check("de bruijn term", r.get("term") == "λx → λy → x y", repr(r.get("term")))

    # 大项的 :ast / :db 必须遵守 400 节点上限，不能生成巨型树（曾经会卡死）
    # :ast / :db must respect the 400-node cap on huge terms (once hung).
    r = one([":ast 9999"], b)
    check("ast huge omitted", r.get("astOmitted") is True and r.get("astTreeOmitted") is True,
          str(r)[:160])
    r = one([":db 9999"], b)
    check("db huge omitted", r.get("astOmitted") is True and r.get("astTreeOmitted") is True,
          str(r)[:160])
    check("db huge bounded", len(r.get("text", "")) <= 1100, str(len(r.get("text", ""))))

    r = one([":trace (\\x.x) a"], b)
    check("trace command", r.get("kind") == "trace" and r.get("steps") == 1, str(r))
    check("trace final", r.get("final") == "a", str(r.get("final")))


# ---------------------------------------------------------------------------
# 双语 / Bilingual output
# ---------------------------------------------------------------------------

def test_bilingual(b: Path) -> None:
    zh = run([":help"], b, lang="zh")[-1][0].get("text", "")
    en = run([":help"], b, lang="en")[-1][0].get("text", "")
    both = run([":help"], b, lang="both")[-1][0].get("text", "")
    check("help zh", "用法" in zh and "Usage" not in zh, zh[:80])
    check("help en", "Usage" in en and "用法" not in en, en[:80])
    check("help both", "用法" in both and "Usage" in both, both[:80])

    r = one(["\\x"], b, lang="zh")
    check("error zh", "解析错误" in r.get("text", ""), r.get("text", ""))
    r = one(["\\x"], b, lang="en")
    check("error en", "Parse error" in r.get("text", ""), r.get("text", ""))

    # 运行中切换语言 / switch language at runtime
    results = run([":lang zh", "\\x"], b)
    check("runtime lang switch", "解析错误" in results[-1][0].get("text", ""), str(results[-1]))

    # 管道输入的 UTF-8 标识符必须原样读入（REPL 模式，不是 --batch）
    # A piped UTF-8 identifier must survive: the REPL reads through the locale
    # encoding, which has to follow the redirected input.
    piped = ":let 名字 = \\x.x\n名字\n".encode("utf-8")
    proc = subprocess.run([str(b)], input=piped, capture_output=True, timeout=60,
                          cwd=str(ROOT))
    text = proc.stdout.decode("utf-8", "replace")
    check("piped utf-8 identifier survives", "名字" in text, text[:200])


# ---------------------------------------------------------------------------
# 协议与稳健性 / Protocol and robustness
# ---------------------------------------------------------------------------

def test_protocol(b: Path) -> None:
    lines = ["PLUS ONE TWO", ":env", ":", "\\x.x"]
    code = "\n".join(lines) + "\n"
    proc = subprocess.run(
        [str(b), "--batch", "--json", "--lang", "en"],
        input=code.encode("utf-8"), capture_output=True, timeout=30, cwd=str(ROOT),
    )
    text = proc.stdout.decode("utf-8", "replace")
    check("one sentinel per command", text.count(RS) == len(lines), str(text.count(RS)))
    for chunk in text.split(RS)[:-1]:
        for line in chunk.splitlines():
            if line.strip():
                try:
                    json.loads(line)
                except json.JSONDecodeError as exc:
                    check("json line", False, f"{line!r}: {exc}")

    # --lang 的参数不能被当成文件名
    # The value of --lang must not be treated as a file name.
    proc = subprocess.run(
        [str(b), "--batch", "--json", "--lang", "en"],
        input=b"\\x.x\n", capture_output=True, timeout=30, cwd=str(ROOT),
    )
    out = proc.stdout.decode("utf-8", "replace")
    check("no file error for --lang", "openFile" not in out and "File load error" not in out, out[:120])


def test_determinism(b: Path) -> None:
    lines = ["PLUS ONE TWO", ":trace (\\x.x) a", "id = \\x.x", ":type id", ":env"]
    first = run(lines, b)
    second = run(lines, b)
    check("deterministic output", first == second, "两次运行结果不同 / runs differ")


def test_cross_strategy_agreement(b: Path) -> None:
    terms = ["PLUS ONE TWO", "MULT TWO TWO", "IF TRUE ONE TWO", "SUCC (PLUS ONE ONE)"]
    for term in terms:
        variants = []
        for strat in ("applicative", "normal"):
            r = one([f":strategy {strat}", term], b)
            variants.append(r.get("term"))
        check(f"{term} agrees across strong strategies", len(set(variants)) == 1, str(variants))


# ---------------------------------------------------------------------------
# 最小解释器 main / minimal interpreter smoke test
# ---------------------------------------------------------------------------

def test_main_binary() -> None:
    exe = ROOT / ("main.exe" if os.name == "nt" else "main")
    if not exe.is_file():
        check("main binary present", False, "main 未编译 / main not built")
        return
    proc = subprocess.run(
        [str(exe), "--lang", "en"], input=b"(\\x.x) a\n:q\n",
        capture_output=True, timeout=30, cwd=str(ROOT),
    )
    out = proc.stdout.decode("utf-8", "replace")
    check("main evaluates", "⇒ a" in out, out[:200])

    # 多行列表按方括号深度继续读取，不能把第二行当成新命令
    # A multi-line list continues by bracket depth instead of splitting the input.
    proc = subprocess.run(
        [str(exe), "--lang", "en"], input=b"[a,\n b]\n:q\n",
        capture_output=True, timeout=30, cwd=str(ROOT),
    )
    out = proc.stdout.decode("utf-8", "replace")
    check("main list continuation", "CONS a" in out, out[:200])

    # 大项的 :ast 必须被上限拦截，不能卡死
    # A huge :ast must be capped instead of hanging.
    big = " ".join(["x"] * 500)
    proc = subprocess.run(
        [str(exe), "--lang", "en"], input=(f":ast {big}\n:q\n").encode("utf-8"),
        capture_output=True, timeout=30, cwd=str(ROOT),
    )
    out = proc.stdout.decode("utf-8", "replace").lower()
    check("main ast huge bounded", "omitted" in out, out[:120])

    # 长轨迹只保留前 500 步并提示（与扩展版一致）
    # A long trace keeps only the first 500 steps with a notice (like extension).
    expr = "a"
    for _ in range(520):
        expr = f"(\\x.x) ({expr})"
    proc = subprocess.run(
        [str(exe), "--lang", "en"], input=(f":steps 2000\n:trace {expr}\n:q\n").encode("utf-8"),
        capture_output=True, timeout=60, cwd=str(ROOT),
    )
    out = proc.stdout.decode("utf-8", "replace").lower()
    check("main trace capped", "only the first 500" in out, out[-240:])


# ---------------------------------------------------------------------------
# Web API：会话与 `:load` 路径限制 / web session and :load confinement
# ---------------------------------------------------------------------------

def test_web_api(b: Path) -> None:
    try:
        import flask  # noqa: F401
    except ImportError:
        return  # 未安装 Flask 时跳过 / skip when Flask is not installed
    import sys as _sys
    web_dir = str(ROOT / "web")
    if web_dir not in _sys.path:
        _sys.path.insert(0, web_dir)
    import app as webapp  # noqa: WPS433

    client = webapp.app.test_client()
    sid = client.post("/api/session", json={"lang": "en"}).get_json()["session"]
    try:
        r = client.post("/api/eval", json={"session": sid, "line": "PLUS ONE TWO"})
        out = r.get_json()["outputs"][0]
        check("web eval", r.status_code == 200 and out.get("term") == "λf → λx → f (f (f x))", str(out))

        r = client.post("/api/eval", json={"session": sid, "line": ":load test.lam"})
        out = r.get_json()["outputs"]
        check("web load ok", r.status_code == 200 and any(o["kind"] == "define" for o in out), str(out)[:120])
        check("web load line numbers", any(o["kind"] == "error" and "line 2" in o.get("text", "").lower() for o in out), "")

        r = client.post("/api/eval", json={"session": sid, "line": ":load ../../etc/passwd"})
        check("web load confined", r.status_code == 400, str(r.status_code))
        check("web load message", "restricted" in r.get_json().get("error", ""), r.get_json().get("error", ""))

        r = client.post("/api/eval", json={"session": sid, "line": ":db \\x.\\y.x y"})
        out = r.get_json()["outputs"][0]
        check("web db kind", out.get("kind") == "db" and out.get("text") == "λ.λ.(#1 #0)", str(out))

        # 多行输入必须拆成单条命令，不能打乱会话的哨兵流
        # Multi-line input must be split into single commands so the sentinel
        # stream stays in sync.
        r = client.post("/api/eval", json={"session": sid, "line": "a\nb\nc"})
        check("web multiline count", len(r.get_json()["outputs"]) == 3, str(r.get_json())[:120])
        out = client.post("/api/eval", json={"session": sid, "line": "MULT TWO TWO"}).get_json()["outputs"][0]
        check("web multiline no desync", out.get("term") == "λf → λx → f (f (f (f x)))", str(out)[:120])

        # 多行里隐藏的 :load 也必须被路径限制拦截
        # A :load hidden on a later line must still be confined.
        r = client.post("/api/eval", json={"session": sid, "line": "a\n:load ../../etc/passwd"})
        check("web multiline hidden load confined", r.status_code == 400, str(r.status_code))
    finally:
        client.delete(f"/api/session/{sid}")

    # 自定义 LAMBDA_LOAD_ROOT 时，相对路径必须按解释器工作目录（INTERP_DIR）解析，
    # 否则校验与解释器实际打开的文件不一致，可绕过路径限制
    # With a custom LAMBDA_LOAD_ROOT, relative paths must resolve against the
    # interpreter's cwd (INTERP_DIR); resolving against root lets the real open
    # land outside the configured root.
    saved_root = os.environ.get("LAMBDA_LOAD_ROOT")
    with tempfile.TemporaryDirectory() as td:
        os.environ["LAMBDA_LOAD_ROOT"] = td
        try:
            found = webapp.validate_line(":load test.lam")
            check("web load custom root relative confined",
                  found is not None and found[0] == "load_error"
                  and "restricted" in found[1], str(found))
        finally:
            if saved_root is None:
                os.environ.pop("LAMBDA_LOAD_ROOT", None)
            else:
                os.environ["LAMBDA_LOAD_ROOT"] = saved_root


# ---------------------------------------------------------------------------
# α 等价、扩展前奏、正规形与 η / alpha, prelude, normal forms and eta
# ---------------------------------------------------------------------------

def test_alpha_and_equivalence(b: Path) -> None:
    # α 等价必须忽略绑定名（回归：\a.a 应识别为 I）
    r = one(["\\a.a"], b)
    check("alpha I hint", "I combinator" in r.get("hint", ""), r.get("hint", ""))
    r = one(["\\p.\\q.\\r.p r (q r)"], b)
    check("alpha S hint", "S combinator" in r.get("hint", ""), r.get("hint", ""))
    for src in ("\\x->x", "\\x -> x", "λx→x"):
        r = one([src], b)
        check(f"arrow syntax {src}", r.get("term") == "λx → x", str(r))

    r = one([":eq \\a.a , \\b.b"], b)
    check("eq true", r.get("kind") == "eq" and r.get("equal") is True, str(r))
    r = one([":eq \\a.a , \\a.\\b.a"], b)
    check("eq false", r.get("equal") is False, str(r))
    r = one([":conv PLUS ONE TWO , THREE"], b)
    check("conv beta true", r.get("equal") is True, str(r))
    r = one([":conv \\x.x , \\y.y"], b)
    check("conv alpha true", r.get("equal") is True, str(r))

    results = run([":steps 50", ":conv (\\x.x x)(\\x.x x) , \\x.x"], b)
    r = results[-1][0]
    check("conv limit inconclusive", r.get("limitHit") is True and r.get("equal") is False, str(r))
    check("conv limit message", "inconclusive" in r.get("text", ""), r.get("text", ""))

    # 两个表达式都坏时，一次报告左右两侧
    r = one([":eq \\x. , \\y."], b)
    check("multi-error both sides", "left:" in r.get("text", "") and "right:" in r.get("text", ""), r.get("text", ""))


def test_extended_prelude(b: Path) -> None:
    cases = [
        (":int PRED THREE", 2),
        (":int (SUB THREE ONE)", 2),
        (":int (EXP TWO THREE)", 8),
        (":int (PLUS TWO THREE)", 5),
        (":int (HEAD (CONS ONE NIL))", 1),
        (":int (FST (PAIR ONE TWO))", 1),
        (":int (SND (PAIR ONE TWO))", 2),
    ]
    for expr, expected in cases:
        r = one([expr], b)
        check(f"{expr} value", r.get("value") == expected, str(r))

    r = one(["ISZERO ZERO"], b)
    check("ISZERO hint", "Church boolean True" in r.get("hint", ""), r.get("hint", ""))
    r = one(["LEQ ONE TWO"], b)
    check("LEQ true", "Church boolean True" in r.get("hint", ""), r.get("hint", ""))
    r = one(["EQ THREE THREE"], b)
    check("EQ true", "Church boolean True" in r.get("hint", ""), r.get("hint", ""))

    r = one([":church 4"], b)
    check("church encode", r.get("kind") == "church" and r.get("value") == 4, str(r))
    r = one([":church 10000"], b)
    check("church range", r.get("kind") == "error", str(r))
    r = one([":int \\x.x"], b)
    check("int non-numeral", r.get("kind") == "fail", str(r))

    # 同名绑定遮蔽时不是邱奇数（内层 x 应用自身，不是 f x）
    # A shadowing binder is not a Church numeral (inner x applied to itself).
    r = one([":int (\\x.\\x.x x)"], b)
    check("shadowed self-app not numeral", r.get("kind") == "fail", str(r))
    r = one(["\\x.\\x.x x"], b)
    check("shadowed self-app no numeral hint", "Church numeral" not in r.get("hint", ""), r.get("hint", ""))
    # λx.λx.x 仍然是 0，同时也是布尔 False
    # λx.λx.x is still 0, and also boolean False.
    r = one([":int \\x.\\x.x"], b)
    check("shadowed zero numeral", r.get("value") == 0, str(r))
    r = one(["\\x.\\x.x"], b)
    check("shadowed zero is false", "False" in r.get("hint", ""), r.get("hint", ""))


def test_normal_forms_and_eta(b: Path) -> None:
    r = one([":nf (\\x.\\y.x) a b"], b)
    check("nf term", r.get("term") == "a" and r.get("steps") == 2, str(r))
    r = one([":whnf (\\x.\\y.x) (\\x.x)"], b)
    check("whnf stops early", r.get("term") == "λy → λx → x" and r.get("steps") == 1, str(r))

    # 顶层 λ 本身已经是弱首正规形，不能继续归约 λ 体
    # A top-level lambda is already in WHNF; its body must not be reduced.
    r = one([":whnf \\x.(\\y.y) z"], b)
    check("whnf stops at lambda", r.get("term") == "λx → (λy → y) z" and r.get("steps") == 0, str(r))

    r = one([":eta on", ":nf \\x. f x"], b)
    check("eta reduces", r.get("term") == "f", str(r))
    r = one([":eta on", ":trace \\x. f x"], b)
    check("eta trace rule", r.get("trace", [{}])[0].get("rule") == "η", str(r.get("trace")))
    r = one([":eta off", "\\x. f x"], b)
    check("eta off keeps", r.get("term") == "λx → f x", str(r))


def test_redex_selection(b: Path) -> None:
    expr = "(\\x.x) ((\\y.y) z)"
    results = run([f":begin {expr}"], b)
    start = results[-1][0]
    check("begin redexes", len(start.get("redexes", [])) == 2, str(start.get("redexes")))
    check("begin redex count", start.get("redexCount") == 2, str(start.get("redexCount")))

    results = run([f":begin {expr}", ":step 2"], b)
    step = results[-1][0]
    check("pick second redex", step.get("term") == "(λx → x) z", str(step))
    check("step redexes left", len(step.get("redexes", [])) == 1, str(step.get("redexes")))

    results = run([f":begin {expr}", ":step 9"], b)
    check("bad redex index", results[-1][0].get("kind") == "fail", str(results[-1]))
    results = run([":begin \\x.x"], b)
    check("normal form no redex", results[-1][0].get("redexes") == [], str(results[-1]))


# ---------------------------------------------------------------------------
# 文件功能：注释、续行、命令、行号、保存、递归、多文件
# ---------------------------------------------------------------------------

def test_file_features(b: Path) -> None:
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "features.lam"
        src.write_text(
            "-- a comment\n"
            "# another comment\n"
            "id = \\x.x\n"
            "\n"
            "bad = \\a.\n"
            "multi = \\x.\n"
            "  (x)\n"
            ":strategy normal\n"
            ":steps 42\n",
            encoding="utf-8",
        )
        results = run([f":load {src}"], b)
        objs = results[-1]
        defines = [o for o in objs if o.get("kind") == "define"]
        errors = [o for o in objs if o.get("kind") == "error"]
        infos = [o for o in objs if o.get("kind") == "info"]
        names = {o.get("name") for o in defines}
        check("comments/continuation load", names == {"id", "multi"}, str(names))
        check("load correct line number", any(o.get("line") == 5 for o in errors), str(errors))
        check("load applies strategy", any("normal" in o.get("text", "") for o in infos), str(infos))
        check("load applies limit", any("42" in o.get("text", "") for o in infos), str(infos))

        out = Path(td) / "saved.lam"
        results = run([f":load {src}", "rec idr = \\x.x", f":save {out}"], b)
        check("save ok", out.is_file(), str(results[-1]))
        text = out.read_text(encoding="utf-8") if out.is_file() else ""
        check("save source syntax", "id = \\x.x" in text and "multi = \\x.x" in text, text[:200])
        check("save rec form", "rec idr = \\x.x" in text, text[:300])

        if out.is_file():
            results = run([f":load {out}", ":env"], b)
            rows = {r["name"] for r in results[-1][0].get("rows", [])}
            check("saved file reloads", {"id", "multi", "idr"} <= rows, str(rows))

        # UTF-8 文件（含中文注释与标识符）必须始终按 UTF-8 读取
        # UTF-8 files (Chinese comments/identifiers) must always be read as UTF-8.
        uni = Path(td) / "unicode.lam"
        uni.write_text("-- 中文注释\n变量 = \\x.x\n", encoding="utf-8")
        outs = run([f":load {uni}", ":env"], b)
        rows = {r["name"] for r in outs[-1][0].get("rows", [])}
        check("utf8 file load", "变量" in rows, str(rows))

        # 带 UTF-8 BOM 的文件也必须能加载（Windows 编辑器常见）
        # A file with a UTF-8 BOM must load too (common with Windows editors).
        bom = Path(td) / "bom.lam"
        bom.write_bytes(b"\xef\xbb\xbfbomid = \\x.x\n")
        outs = run([f":load {bom}", ":env"], b)
        rows = {r["name"] for r in outs[-1][0].get("rows", [])}
        check("bom file load", "bomid" in rows, str(rows))

        # 启动时加载多个文件，并在文件内设置策略
        f1 = Path(td) / "one.lam"
        f2 = Path(td) / "two.lam"
        f1.write_text("-- start\n:strategy normal\n:steps 100\na1 = \\x.x\n", encoding="utf-8")
        f2.write_text("b2 = \\x.y\n", encoding="utf-8")
        omega = "(\\x.y) ((\\x.x x)(\\x.x x))"
        proc = subprocess.run(
            [str(b), str(f1), str(f2), "--batch", "--json", "--lang", "en"],
            input=(omega + "\n:env\n").encode("utf-8"),
            capture_output=True, timeout=60, cwd=str(ROOT),
        )
        text = proc.stdout.decode("utf-8", "replace")
        objs = []
        for chunk in text.split(RS)[:-1]:
            for line in chunk.splitlines():
                if line.strip():
                    objs.append(json.loads(line))
        terms = [o.get("term") for o in objs if o.get("kind") in ("result", "warn")]
        rows = set()
        for o in objs:
            if o.get("kind") == "env":
                rows = {r["name"] for r in o.get("rows", [])}
        check("multiple files loaded", {"a1", "b2"} <= rows, str(rows))
        check("in-file strategy applied", "y" in terms, str(terms))

        # 文件内 :del / :reset 之后不能再报告已删除的定义
        # A file's :del / :reset must not keep reporting removed definitions.
        logfile = Path(td) / "log.lam"
        logfile.write_text(
            "aa = \\x.x\n:del aa\nbb = \\y.y\n:reset\ncc = \\z.z\n",
            encoding="utf-8",
        )
        outs = run([f":load {logfile}"], b)
        names = [o.get("name") for o in outs[-1] if o.get("kind") == "define"]
        check("load log drops deleted/reset defs", names == ["cc"], str(names))
        info = next((o for o in outs[-1]
                     if o.get("kind") == "info" and "loaded" in o), {})
        check("load summary counts live defs",
              info.get("loaded") == 1 and info.get("failed") == 0, str(info))

        # 文件内的 :lang 要作用到同一次加载的后续输出
        # A file's :lang applies to later output from the same load.
        langfile = Path(td) / "lang.lam"
        langfile.write_text(":lang zh\nzhid = \\x.x\n", encoding="utf-8")
        outs = run([f":load {langfile}"], b)
        check("file language applies to load output",
              any(o.get("kind") == "define" and o.get("text", "").startswith("已定义")
                  for o in outs[-1]), str(outs[-1]))
        check("file language field", any(o.get("lang") == "zh" for o in outs[-1]),
              str(outs[-1]))

        # 未缩进的列表续行也应按括号深度拼接
        # A list continued without indentation joins by bracket depth too.
        listfile = Path(td) / "list.lam"
        listfile.write_text("xs = [1,\n2]\n", encoding="utf-8")
        outs = run([f":load {listfile}", ":env"], b)
        rows = {r["name"] for r in outs[-1][0].get("rows", [])}
        check("bracket continuation in file", "xs" in rows, str(rows))

        # 启动时加载的文件也要被 :reload 记住
        # A startup file must be remembered by :reload.
        proc = subprocess.run(
            [str(b), str(f1), "--batch", "--json", "--lang", "en"],
            input=b":reload\n:def a1\n", capture_output=True, timeout=60, cwd=str(ROOT),
        )
        text = proc.stdout.decode("utf-8", "replace")
        objs = [json.loads(line) for chunk in text.split(RS)[:-1]
                for line in chunk.splitlines() if line.strip()]
        check("startup file can be reloaded",
              any(o.get("kind") == "define" and o.get("name") == "a1" for o in objs),
              str(objs)[:300])


# ---------------------------------------------------------------------------
# CLI 选项与轨迹上限 / CLI options and the trace cap
# ---------------------------------------------------------------------------

def test_cli_options(b: Path) -> None:
    # 版本号以根目录 VERSION 为单一来源；两个可执行文件与 Cabal 必须一致
    # VERSION is the single source of truth; both binaries and Cabal must match.
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    p = subprocess.run([str(b), "--version"], capture_output=True, timeout=30)
    check("version", version in p.stdout.decode("utf-8", "replace"),
          p.stdout.decode("utf-8", "replace"))
    p = subprocess.run([str(b), "--lang=zh", "--help"], capture_output=True, timeout=30)
    out = p.stdout.decode("utf-8", "replace")
    check("--lang= form", "用法" in out, out[:80])
    check("help lists new commands",
          ":eq" in out and ":whnf" in out and ":fast" in out and "--version" in out and "--timeout" in out, out[:200])
    p = subprocess.run([str(b), "--nope"], capture_output=True, timeout=30)
    check("unknown option fails", p.returncode != 0, str(p.returncode))
    p = subprocess.run([str(b), "--lang"], capture_output=True, timeout=30)
    check("missing lang value fails", p.returncode != 0, str(p.returncode))
    p = subprocess.run([str(b), "--timeout=abc"], capture_output=True, timeout=30)
    check("bad timeout fails", p.returncode != 0, str(p.returncode))

    omega = "((\\x.x x)(\\x.x x))"
    p = subprocess.run(
        [str(b), "--batch", "--json", "--lang", "en", "--timeout", "1"],
        input=(":steps 1000000000\n" + omega + "\n").encode("utf-8"),
        capture_output=True, timeout=30, cwd=str(ROOT),
    )
    out = p.stdout.decode("utf-8", "replace")
    check("wall-clock timeout", "timed out after 1 s" in out, out[:200])
    check("timeout keeps protocol", out.count(RS) == 2, str(out.count(RS)))


def test_trace_cap(b: Path) -> None:
    expr = "a"
    for _ in range(520):
        expr = f"(\\x.x) ({expr})"
    results = run([":steps 2000", expr], b)
    r = results[-1][0]
    check("trace total steps", r.get("steps") == 520, str(r.get("steps")))
    check("trace kept 500", len(r.get("trace", [])) == 500, str(len(r.get("trace", []))))
    check("trace truncated flag", r.get("traceTruncated") is True, str(r.get("traceTruncated")))
    check("trace final term", r.get("term") == "a", str(r.get("term")))


# ---------------------------------------------------------------------------
# Web：会话恢复、语言切换、环境类型、健康检查
# ---------------------------------------------------------------------------

def test_web_extras(b: Path) -> None:
    try:
        import flask  # noqa: F401
    except ImportError:
        return
    import sys as _sys
    web_dir = str(ROOT / "web")
    if web_dir not in _sys.path:
        _sys.path.insert(0, web_dir)
    import app as webapp  # noqa: WPS433

    client = webapp.app.test_client()
    r = client.get("/api/health")
    data = r.get_json()
    check("health", r.status_code == 200 and data.get("ok") is True and data.get("available") is True, str(data))
    prelude = client.get("/api/prelude").get_json()
    check("prelude extended", "Y" in prelude, "")
    check("prelude complete", {"XOR", "NAND", "ZIP", "FOLD", "LENGTH"} <= set(prelude),
          str(prelude))
    icon = client.get("/icon.svg")
    check("icon served", icon.status_code == 200 and "svg" in icon.content_type, icon.content_type)

    # 请求体上限：超大请求应直接 413，而不是被读进内存
    # Request body cap: an oversized request is rejected with 413.
    check("web body limit configured",
          webapp.app.config.get("MAX_CONTENT_LENGTH") == 1024 * 1024,
          str(webapp.app.config.get("MAX_CONTENT_LENGTH")))
    saved_limit = webapp.app.config["MAX_CONTENT_LENGTH"]
    webapp.app.config["MAX_CONTENT_LENGTH"] = 256
    try:
        big = client.post("/api/eval", json={"line": "x" * 1000})
        check("web oversized 413", big.status_code == 413, str(big.status_code))
    finally:
        webapp.app.config["MAX_CONTENT_LENGTH"] = saved_limit

    # 解释器缺失时返回清晰错误，而不是未处理的 500
    # A missing interpreter returns a clear error, not an unhandled 500.
    saved_bin = webapp.INTERP_BIN
    webapp.INTERP_BIN = ROOT / "definitely-missing-extension"
    try:
        r = client.post("/api/session", json={"lang": "en"})
        check("web session missing bin",
              r.status_code == 500 and "Not found" in r.get_json().get("error", ""),
              str(r.get_json()))
        r = client.post("/api/eval", json={"line": "PLUS ONE TWO"})
        check("web eval missing bin",
              r.status_code == 500 and "Not found" in r.get_json().get("error", ""),
              str(r.get_json()))
    finally:
        webapp.INTERP_BIN = saved_bin

    # 旧的一次性接口也要遵守表达式上限，不能绕过会话接口的保护
    # The legacy one-shot endpoint must honour the same term cap.
    old_cap = webapp.MAX_TERM_SIZE
    webapp.MAX_TERM_SIZE = "20"
    try:
        big_term = "\\x." + " ".join(["x"] * 40)
        r = client.post("/api/eval", json={"code": big_term})
        outs = r.get_json().get("outputs", [])
        check("legacy eval respects term cap",
              any(o.get("code") == "term_too_large" for o in outs), str(outs)[:200])
    finally:
        webapp.MAX_TERM_SIZE = old_cap

    # 短链分享：服务端保存状态并可按 id 取回
    payload = {"v": 2, "code": ["PLUS ONE TWO"], "strategy": "normal",
               "limit": 42, "theme": "dark", "lang": "en", "eta": False}
    r = client.post("/api/share", json=payload)
    share_id = r.get_json().get("id") if r.status_code == 200 else None
    check("share create", r.status_code == 200 and bool(share_id), str(r.get_json()))
    if share_id:
        r = client.get(f"/api/share/{share_id}")
        check("share get", r.status_code == 200 and r.get_json()["state"]["code"] == ["PLUS ONE TWO"],
              str(r.get_json()))
    check("share unknown", client.get("/api/share/does-not-exist").status_code == 404, "")
    check("share invalid", client.post("/api/share", json={"code": "nope"}).status_code == 400, "")

    sid = client.post("/api/session", json={"lang": "en"}).get_json()["session"]
    try:
        out = client.post("/api/eval", json={"session": sid, "line": "PLUS ONE TWO"}).get_json()["outputs"][0]
        check("web bilingual fields",
              "Church numeral" in out.get("textEn", "") and "邱奇数" in out.get("textZh", ""),
              str(out)[:200])
        check("web bilingual hint", bool(out.get("hintZh")) and bool(out.get("hintEn")), str(out.get("hintZh")))

        client.post("/api/eval", json={"session": sid, "line": "id = \\x.x"})
        out = client.post("/api/eval", json={"session": sid, "line": ":env"}).get_json()["outputs"]
        rows = {r["name"]: r for r in out[0].get("rows", [])}
        check("web env type", bool(rows.get("id", {}).get("type")), str(rows.get("id")))
        check("web env bilingual type",
              bool(rows.get("id", {}).get("typeZh")) and bool(rows.get("id", {}).get("typeEn")),
              str(rows.get("id")))

        r = client.post("/api/eval", json={"session": sid, "line": ":save blocked.lam"})
        check("web save disabled", r.status_code == 400 and "disabled" in r.get_json().get("error", ""),
              str(r.get_json()))
        for repl_only in (":q", ":quit", ":edit", ":edit README.md"):
            r = client.post("/api/eval", json={"session": sid, "line": repl_only})
            body = r.get_json()
            check(f"web rejects {repl_only.split()[0]}",
                  r.status_code == 400 and "CLI" in body.get("error", "")
                  and body.get("code") == "cli_only",
                  str(body))

        out = client.post("/api/eval", json={"session": sid, "line": ":fast on"}).get_json()["outputs"][0]
        check("web fast ack", out.get("fast") is True, str(out)[:160])
        out = client.post("/api/eval", json={"session": sid, "line": "MULT 3 3"}).get_json()["outputs"][0]
        check("web fast result",
              out.get("fast") is True and "steps" not in out
              and "Church numeral 9" in out.get("hint", ""), str(out)[:200])
        client.post("/api/eval", json={"session": sid, "line": ":fast off"})

        r = client.post(f"/api/session/{sid}/lang", json={"lang": "zh"})
        check("web lang route", r.status_code == 200 and r.get_json().get("ok") is True, str(r.get_json()))
        out = client.post("/api/eval", json={"session": sid, "line": "\\x"}).get_json()["outputs"]
        check("web lang applied", "解析错误" in out[0].get("text", ""), str(out)[:120])
    finally:
        # 删除后旧会话必须返回 410，让前端回放而不是悄悄清空环境
        client.delete(f"/api/session/{sid}")
        r = client.post("/api/eval", json={"session": sid, "line": "PLUS ONE TWO"})
        check("web expired 410", r.status_code == 410, str(r.status_code))
        check("web expired restart", r.get_json().get("restart") is True, str(r.get_json()))


# ---------------------------------------------------------------------------
# 属性测试：随机算术、α 重命名、策略一致性
# ---------------------------------------------------------------------------

def test_properties(b: Path) -> None:
    rng = random.Random(20261103)
    cmds: list[str] = []
    expected: list[int] = []
    for _ in range(8):
        n, m = rng.randint(0, 5), rng.randint(0, 5)
        cmds.append(f":int (PLUS {n} {m})")
        expected.append(n + m)
        cmds.append(f":int (MULT {n} {m})")
        expected.append(n * m)
    outs = run(cmds, b)
    for cmd, want, objs in zip(cmds, expected, outs):
        got = objs[0].get("value") if objs else None
        check(f"{cmd} = {want}", got == want, f"{got!r} vs {want}")

    names = ["a", "b", "c", "u", "v", "w"]
    pairs = []
    for _ in range(5):
        x, y = rng.sample(names, 2)
        pairs.append((f"\\{x}.\\{y}.{x}", f"\\{y}.\\{x}.{y}"))
        pairs.append((f"\\{x}.\\{y}.{x} {y}", f"\\{y}.\\{x}.{y} {x}"))
    cmds = [f":eq {a} , {b}" for a, b in pairs]
    outs = run(cmds, b)
    for cmd, objs in zip(cmds, outs):
        check(f"alpha property {cmd}", objs[0].get("equal") is True, str(objs[0]))

    # 强策略在随机算术项上结果一致
    terms = [f"PLUS {rng.randint(0,5)} {rng.randint(0,5)}" for _ in range(4)]
    cmds = []
    for t in terms:
        cmds.extend([":strategy applicative", t, ":strategy normal", t])
    outs = run(cmds, b)
    for i, t in enumerate(terms):
        a = outs[i * 4 + 1][0].get("term")
        n = outs[i * 4 + 3][0].get("term")
        check(f"strategy agreement {t}", a == n, f"{a!r} vs {n!r}")

    # 快速模式与逐步模式给出同一正规形
    # Fast mode and the step engine agree on the normal form.
    cmds = []
    for t in terms:
        cmds.extend([":fast on", t, ":fast off", t])
    outs = run(cmds, b)
    for i, t in enumerate(terms):
        f = outs[i * 4 + 1][0].get("term")
        s = outs[i * 4 + 3][0].get("term")
        check(f"fast agreement {t}", f == s, f"{f!r} vs {s!r}")


# ---------------------------------------------------------------------------
# main 与 extension 的差分测试 / differential test
# ---------------------------------------------------------------------------

def _main_terms(lines: list[str]) -> list[str]:
    exe = ROOT / ("main.exe" if os.name == "nt" else "main")
    proc = subprocess.run(
        [str(exe), "--lang", "en"], input=("\n".join(lines) + "\n:q\n").encode("utf-8"),
        capture_output=True, timeout=90, cwd=str(ROOT),
    )
    out = proc.stdout.decode("utf-8", "replace")
    terms = []
    for line in out.splitlines():
        idx = line.rfind("⇒ ")
        if idx < 0:
            continue
        term = line[idx + 2:]
        term = re.sub(r"\s+\(\d+\s+(?:steps|步)\).*$", "", term).strip()
        terms.append(term)
    return terms


def test_differential_main(b: Path) -> None:
    cases = [
        ["(\\x.x) a"],
        ["(\\x.\\y.x) a b"],
        ["(\\f.\\x.f (f x)) a b"],
        [":strategy normal", "(\\x.y) ((\\x.x x)(\\x.x x))"],
    ]
    for lines in cases:
        ext = one(lines, b)
        main_terms = _main_terms(lines)
        check(f"main differential {lines[-1]}", main_terms == [ext.get("term")],
              f"{main_terms!r} vs {ext.get('term')!r}")


def test_fast_mode(b: Path) -> None:
    info = one([":fast on"], b)
    check("fast ack", info.get("fast") is True and "Fast mode" in info.get("text", ""),
          str(info)[:160])

    fast = one([":fast on", "MULT 12 12"], b)
    check("fast result", fast.get("kind") == "result" and fast.get("fast") is True,
          str(fast)[:200])
    check("fast has no steps", "steps" not in fast, str(fast)[:200])
    check("fast church hint", "Church numeral 144" in fast.get("hint", ""), fast.get("hint", ""))
    check("fast text marks mode", "fast mode" in fast.get("text", ""), fast.get("text", "")[:120])

    slow = one(["MULT 12 12"], b)
    check("fast matches step term", fast.get("term") == slow.get("term"),
          f"{fast.get('term')!r} vs {slow.get('term')!r}")

    for term in ["\\x.\\y.x", "(\\x.\\y.y) a b", "\\f.\\x.f (f x)"]:
        f = one([":fast on", term], b)
        s = one([term], b)
        check(f"fast term {term}", f.get("term") == s.get("term"),
              f"{f.get('term')!r} vs {s.get('term')!r}")

    i = one([":fast on", ":int MULT 12 12"], b)
    check("fast int", i.get("value") == 144 and i.get("fast") is True, str(i)[:200])

    c = one([":fast on", ":conv MULT 12 12 , 144"], b)
    check("fast conv", c.get("equal") is True and c.get("limitHit") is False, str(c)[:200])

    # 步进类命令保持逐步语义 / stepping commands keep their exact semantics
    t = one([":fast on", ":trace (\\x.x) a"], b)
    check("fast keeps trace", t.get("kind") == "trace" and len(t.get("trace", [])) == 1,
          str(t)[:200])

    # 燃料：Ω 在低预算下中止 / low fuel stops Ω
    w = one([":steps 20", ":fast on", "((\\x.x x)(\\x.x x))"], b)
    check("fast fuel warning",
          w.get("kind") == "warn" and w.get("limitHit") is True and "fuel" in w.get("text", ""),
          str(w)[:200])

    off = one([":fast on", ":fast off", "MULT 3 3"], b)
    check("fast off restores steps", "steps" in off and "fast" not in off, str(off)[:160])

    # 快速模式必须求正规形：Y 递归只有惰性求值才终止，也应当能算出结果
    # Fast mode must normalize; Y recursion terminates only lazily, yet must work.
    rec = "rec fact = \\n. IF (ISZERO n) ONE (MULT n (fact (PRED n)))"
    r = one([rec, ":fast on", ":steps 5000", ":int (fact THREE)"], b)
    check("fast normalizes Y recursion", r.get("value") == 6, str(r)[:160])

    # .lam 内的 :fast 也会生效 / a :fast directive inside a .lam file applies too
    f = ROOT / "fast_mode_tmp.lam"
    try:
        f.write_text(":fast on\nid = \\x.x\n", encoding="utf-8")
        outs = run([f":load {f}", "id z"], b)
        check("fast file directive",
              outs[1][0].get("fast") is True and "steps" not in outs[1][0],
              str(outs[1][0])[:160])
    finally:
        f.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Web 前端状态同步 / web UI state sync (Node + minimal DOM stub)
# ---------------------------------------------------------------------------

def test_web_ui_state(b: Path) -> None:
    node = shutil.which("node")
    if not node:
        return  # 未安装 Node 时跳过 / skip when Node is unavailable
    proc = subprocess.run(
        [node, str(ROOT / "tests" / "ui_smoke.mjs")],
        capture_output=True, timeout=60, cwd=str(ROOT),
    )
    out = (proc.stdout + proc.stderr).decode("utf-8", "replace")
    check("web ui state sync", proc.returncode == 0, out[-400:])


# ---------------------------------------------------------------------------
# 2.1.0 新特性 / 2.1.0 features
# ---------------------------------------------------------------------------

def test_let_and_annotations(b: Path) -> None:
    r = one(["let id = \\x.x in id ONE"], b)
    check("let reduces", r.get("term") == "λf → λx → f x", str(r))
    r = one(["(let id = \\x.x in id) TRUE"], b)
    check("let inside parens", r.get("term") == "λt → λf → t", str(r))
    r = one(["let x = (\\y.y) in x x"], b)
    check("let shadowing binder", r.get("term") == "λy → y", str(r))
    r = one([":type let id = \\x.x in PAIR (id TRUE) (id ONE)"], b)
    check("let polymorphism", r.get("kind") == "type", str(r))
    r = one(["(\\x.x : a -> a) ONE"], b)
    check("annotation erased", r.get("term") == "λf → λx → f x", str(r))
    r = one([":type \\x.x : a -> a"], b)
    check("annotation matches", r.get("matches") is True, str(r))
    r = one([":type \\x.x : a -> b"], b)
    check("annotation mismatch", r.get("matches") is False, str(r))
    r = one([":type \\x.x"], b)
    check("type lists free vars", r.get("freeVars") == [], str(r))
    r = one(["PLUS ONE TWO -- 加法"], b)
    check("trailing -- comment", r.get("term") == "λf → λx → f (f (f x))", str(r))
    r = one(["PLUS ONE TWO # 注释"], b)
    check("trailing # comment", r.get("term") == "λf → λx → f (f (f x))", str(r))


def test_new_commands(b: Path) -> None:
    r = one([":time PLUS ONE TWO"], b)
    check("time elapsedMs", isinstance(r.get("elapsedMs"), (int, float))
          and r.get("elapsedMs") >= 0, str(r))
    r = one([":bench 3 (\\x.x) ONE"], b)
    check("bench runs", r.get("runs") == 3 and "elapsedTotalMs" in r, str(r))
    r = one([":bench 0 (\\x.x)"], b)
    check("bench rejects zero", r.get("kind") == "error", str(r))
    r = one([":help :step"], b)
    check("topic help", r.get("kind") == "help" and "Usage" in r.get("text", ""), str(r))
    r = one([":help :nope"], b)
    check("unknown topic", r.get("kind") == "fail"
          and r.get("code") == "unknown_command", str(r))
    r = one([":help"], b)
    check("full help", ":bench" in r.get("text", "") and ":time" in r.get("text", ""), str(r)[:200])


def test_error_codes(b: Path) -> None:
    for cmd, want in (("\\x", "parse_error"), (":nope", "parse_error"),
                      (":type Y", "type_error"), (":del missing", "command_failed")):
        r = one([cmd], b)
        check(f"code for {cmd}", r.get("code") == want, str(r))
    r = one([":steps 3", "(\\x.x x)(\\x.x x)"], b)
    check("step_limit code", r.get("code") == "step_limit", str(r))
    r = one([":fast on", ":steps 1", "MULT 9 9"], b)
    check("fast_budget code", r.get("code") == "fast_budget", str(r))


def test_cycle_and_fuel(b: Path) -> None:
    outs = run([":steps 20", "(\\x.x x)(\\x.x x)"], b)
    r = outs[-1][0]
    check("cycle detected", r.get("cycle") is True, str(r))
    check("cycle text", "divergent" in r.get("text", ""), str(r))
    codes = [o.get("code") for o in outs[-1]]
    check("cycle_detected event", "cycle_detected" in codes, str(codes))
    r = one(["PLUS ONE TWO"], b)
    check("cycle false on normal term", r.get("cycle") is False, str(r))
    outs = run(["x = x", "x"], b)
    check("macro fuel warns", outs[-1][0].get("code") == "macro_fuel", str(outs[-1]))
    check("macro fuel still evaluates", any(o.get("kind") == "result" for o in outs[-1]),
          str(outs[-1]))


def test_eta_redex_selection(b: Path) -> None:
    outs = run([":eta on", ":begin \\x. f x", ":step 1"], b)
    check("eta redex listed", outs[1][0].get("redexCount") == 1, str(outs[1][0]))
    check("eta redex contractible", outs[2][0].get("term") == "f", str(outs[2][0]))
    outs = run([":eta off", ":begin \\x. f x"], b)
    check("eta redex hidden when off", outs[-1][0].get("redexCount") == 0,
          str(outs[-1][0]))


def test_rec_type_env(b: Path) -> None:
    outs = run(["g = \\x.x", ":type g", "rec g = \\x.x", ":type g"], b)
    check("rec type before", outs[1][0].get("kind") == "type", str(outs[1]))
    check("rec clears stale type", outs[3][0].get("kind") == "fail", str(outs[3]))


def test_file_commands(b: Path) -> None:
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "extended.lam"
        f.write_text(
            "-- 扩展文件命令 / extended file commands\n"
            ":eta on\n"
            ":steps 200\n"
            ":fast off\n"
            "a1 = \\x.x -- 行尾注释 / trailing comment\n"
            "rec r1 = \\x.x\n"
            ":del a1\n"
            ":type \\x.x\n"
            ":reset\n"
            "b2 = \\y.y\n",
            encoding="utf-8",
        )
        outs = run([f":load {f}", ":env"], b)
        kinds = [o.get("kind") for o in outs[0]]
        check("file query echoed", "type" in kinds, str(kinds))
        info = next((o for o in outs[0] if o.get("kind") == "info" and "failed" in o), {})
        check("file has no failed lines", info.get("failed") == 0, str(info))
        rows = {r["name"] for r in outs[-1][0].get("rows", [])}
        check("file :del applied", "a1" not in rows, str(sorted(rows)[:8]))
        check("file :reset applied", "r1" not in rows and "b2" in rows,
              str(sorted(rows)[:8]))


def test_version_sources(b: Path) -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    check("VERSION format", re.fullmatch(r"\d+\.\d+\.\d+", version) is not None, version)
    cabal = (ROOT / "lambda-calculus-interpreter.cabal").read_text(encoding="utf-8")
    check("cabal version", re.search(r"^version:\s+" + re.escape(version),
                                     cabal, re.M) is not None, cabal[:160])
    for name in ("extension.exe", "extension", "main.exe", "main"):
        exe = ROOT / name
        if not exe.is_file():
            continue
        p = subprocess.run([str(exe), "--version"], capture_output=True, timeout=30)
        check(f"{name} version", version in p.stdout.decode("utf-8", "replace"),
              p.stdout.decode("utf-8", "replace")[:100])
        break


def test_core_sync(b: Path) -> None:
    script = ROOT / "tools" / "check_core_sync.py"
    check("core sync script present", script.is_file(), str(script))
    if not script.is_file():
        return
    p = subprocess.run([sys.executable, str(script)], capture_output=True,
                       timeout=60, cwd=str(ROOT))
    check("core sync", p.returncode == 0,
          (p.stdout + p.stderr).decode("utf-8", "replace")[-500:])

    # 归约循环也必须被校验：只改一边时工具要报错，两边同改时要通过
    # The evaluation loop must be checked too: a one-sided change must fail
    # and the same change on both sides must pass.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "tools").mkdir()
        shutil.copy2(script, root / "tools" / "check_core_sync.py")
        shutil.copy2(ROOT / "main.hs", root / "main.hs")
        shutil.copy2(ROOT / "extension.hs", root / "extension.hs")
        probe = root / "tools" / "check_core_sync.py"
        old = b"n > limit = EvalResult"
        new = b"n > limit + 1 = EvalResult"

        def run_probe():
            return subprocess.run([sys.executable, str(probe)], capture_output=True,
                                  timeout=60, cwd=str(root))

        ext = root / "extension.hs"
        data = ext.read_bytes()
        check("eval loop probe applies", old in data, "")
        ext.write_bytes(data.replace(old, new))
        r = run_probe()
        out = (r.stdout + r.stderr).decode("utf-8", "replace")
        check("core sync catches a one-sided eval change",
              r.returncode != 0 and "evalUntil" in out, out[-300:])
        main_file = root / "main.hs"
        main_file.write_bytes(main_file.read_bytes().replace(old, new))
        r = run_probe()
        out = (r.stdout + r.stderr).decode("utf-8", "replace")
        check("core sync accepts the same change on both sides",
              r.returncode == 0, out[-300:])


def test_random_terms(b: Path) -> None:
    # 随机生成项，验证 α 自反与归约结果在多种语法形态下都稳定
    # Generate random terms to check α-reflexivity and parse robustness.
    rng = random.Random(20261108)
    pool = ["p", "q", "a", "b", "c", "x", "y", "z"]

    def gen(depth: int) -> str:
        if depth <= 0 or rng.random() < 0.3:
            return rng.choice(pool)
        if rng.random() < 0.4:
            v = rng.choice(pool)
            return f"(\\{v}.{gen(depth - 1)})"
        return f"({gen(depth - 1)} {gen(depth - 1)})"

    terms = [gen(3) for _ in range(12)]
    outs = run([f":eq {t} , {t}" for t in terms], b)
    for term, objs in zip(terms, outs):
        check(f"alpha reflexive {term[:20]}",
              bool(objs) and objs[0].get("equal") is True, str(objs[:1]))


def test_performance_budget(b: Path) -> None:
    # 宽松阈值：只挡住数量级退化，不对具体机器性能做断言
    # Loose threshold: catch order-of-magnitude regressions, not machine speed.
    r = one([":time PLUS 20 20"], b)
    ms = r.get("elapsedMs", 10 ** 6)
    check("evaluation budget", isinstance(ms, (int, float)) and 0 <= ms < 5000, str(ms))

    # 大项的类型推断代价很高，必须跳过而不是把解释器拖住
    # Type inference on a large term is expensive, so it must be skipped
    # instead of stalling the interpreter.
    big = "[" + ",".join(["1"] * 400) + "]"
    start = time.monotonic()
    r = one([big], b)
    secs = time.monotonic() - start
    check("large term stays fast", secs < 5, f"{secs:.1f}s")
    check("large term carries no type", "type" not in r, str(r)[:120])
    r = one([f":type {big}"], b)
    check("large term type inference skipped",
          r.get("code") == "term_too_large", str(r)[:120])


def test_style_conventions(b: Path) -> None:
    # 轻量规范检查，代替独立 linter / lightweight convention check instead of a linter.
    sources = (
        "main.hs", "extension.hs", "web/app.py", "web/index.html",
        "tests/run_tests.py", "tests/ui_smoke.mjs", "tools/check_core_sync.py",
        "README.md", "README-CN.md", "AGENTS.md", "CHANGELOG.md",
        "CONTRIBUTING.md", "tools/screenshot.py", "lib/prelude.lam",
        "Dockerfile", "web/requirements.txt", "desktop.py",
        "desktop-requirements.txt", "web/__init__.py",
        ".github/workflows/release.yml",
    )
    comment_prefixes = ("#", "--", "//", "rem ", "/*", "*")
    for name in sources:
        path = ROOT / name
        check(f"source present {name}", path.is_file(), str(path))
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        check(f"no corner brackets {name}",
              "\u300c" not in text and "\u300d" not in text, name)
        check(f"no emoji {name}",
              not any(0x1F300 <= ord(ch) <= 0x1FAFF for ch in text), name)
        bad_lines = [i + 1 for i, line in enumerate(text.splitlines())
                     if line.lstrip().startswith(comment_prefixes)
                     and line.rstrip().endswith("。")]
        check(f"comment does not end with 。 {name}", not bad_lines, str(bad_lines[:5]))
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    for native in ("prompt(", "confirm(", "alert("):
        check(f"no native {native[:-1]}", native not in html, html[:80])


def test_web_21(b: Path) -> None:
    try:
        import flask  # noqa: F401
    except ImportError:
        return  # 未安装 Flask 时跳过 / skip when Flask is unavailable
    import sys as _sys
    web_dir = str(ROOT / "web")
    if web_dir not in _sys.path:
        _sys.path.insert(0, web_dir)
    import app as webapp  # noqa: WPS433

    client = webapp.app.test_client()
    health = client.get("/api/health").get_json()
    for key in ("version", "uptime", "shares", "sessionsMax", "interpreterPath"):
        check(f"health field {key}", key in health, str(health))
    check("health version matches VERSION",
          health.get("version") == (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
          str(health.get("version")))
    check("request id header",
          "X-Request-ID" in client.get("/api/health").headers, "")

    sid = client.post("/api/session").get_json()["session"]
    try:
        r = client.post(f"/api/session/{sid}/cancel")
        check("cancel session", r.status_code == 200
              and r.get_json().get("cancelled") is True, str(r.get_json()))
    finally:
        pass
    r = client.post(f"/api/session/{sid}/cancel")
    check("cancel unknown returns JSON 404", r.status_code == 404
          and r.get_json().get("code") == "not_found", str(r.get_json()))

    r = client.post("/api/share", json={"code": [":load /etc/passwd"]})
    check("share rejects :load", r.status_code == 400, str(r.get_json()))
    r = client.post("/api/share", json={"code": [":save evil.lam"]})
    check("share rejects :save", r.status_code == 400, str(r.get_json()))
    r = client.post("/api/share", json={"code": ["PLUS ONE TWO", ":lang en"]})
    check("share accepts safe payload", r.status_code == 200, str(r.get_json()))
    # 只读查询与定义可以分享，会话/文件类命令不行
    # Read-only queries and definitions may be shared; session and file
    # commands may not.
    for safe in (":type PLUS ONE TWO", ":trace \\x.x", ":eq \\a.a , \\b.b",
                 ":nf \\x.x", ":env", ":help", ":let id = \\x.x",
                 ":begin \\x.x", ":step 1", ":end"):
        r = client.post("/api/share", json={"code": [safe]})
        check(f"share accepts {safe.split()[0]}", r.status_code == 200,
              str(r.get_json()))
    for unsafe in (":del id", ":reset", ":q", ":edit x.lam", ":reload",
                   ":load x.lam", ":save x.lam", ":time 5 \\x.x"):
        r = client.post("/api/share", json={"code": [unsafe]})
        check(f"share rejects {unsafe.split()[0]}", r.status_code == 400,
              str(r.get_json()))
    if r.status_code == 200:
        got = client.get(f"/api/share/{r.get_json()['id']}").get_json()
        check("share roundtrip", got.get("ok") is True
              and got.get("state", {}).get("code") == ["PLUS ONE TWO", ":lang en"], str(got))
    r = client.post("/api/share", json={"code": ["ok"] * 201})
    check("share line cap", r.status_code == 400, str(r.get_json()))

    r = client.get("/api/does-not-exist")
    check("404 returns JSON", r.status_code == 404
          and r.get_json().get("ok") is False, str(r.get_json()))
    r = client.post("/api/eval", json={"session": "missing", "line": "\\x.x"})
    check("expired session code", r.get_json().get("code") == "session_expired",
          str(r.get_json()))
    r = client.post("/api/eval", json={"line": ":load /etc/passwd"})
    check("load error code", r.get_json().get("code") == "load_error", str(r.get_json()))

    # 强制让解释器 send 超时，验证 408 的 JSON 形状与 timeout 标记
    # Force the interpreter send to time out and check the 408 JSON shape.
    original_send = webapp.Interpreter.send

    def fake_send(self, line, timeout=None):  # noqa: ANN001
        raise TimeoutError("forced timeout / 强制超时")

    webapp.Interpreter.send = fake_send
    try:
        timeout_sid = client.post("/api/session").get_json()["session"]
        r = client.post("/api/eval", json={"session": timeout_sid, "line": "\\x.x"})
        body = r.get_json()
        check("eval 408", r.status_code == 408 and body.get("timeout") is True
              and body.get("code") == "timeout", str(body))
    finally:
        webapp.Interpreter.send = original_send
        client.delete(f"/api/session/{timeout_sid}")

    # 并发创建会话不能互相覆盖 / concurrent session creation must not clobber.
    import threading as _threading
    statuses: list[int] = []

    def make_session() -> None:
        c = webapp.app.test_client()
        statuses.append(c.post("/api/session").status_code)

    threads = [_threading.Thread(target=make_session) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    check("concurrent session creation", statuses == [200] * 4, str(statuses))

    # 分享 TTL 生效后短链必须失效 / expired share links must disappear.
    saved_ttl = webapp.SHARE_TTL
    webapp.SHARE_TTL = -1.0
    try:
        stored = client.post("/api/share", json={"code": ["PLUS ONE TWO"]})
        short_id = stored.get_json().get("id")
        r = client.get(f"/api/share/{short_id}")
        check("share TTL", r.status_code == 404 and r.get_json().get("code") == "not_found",
              str(r.get_json()))
    finally:
        webapp.SHARE_TTL = saved_ttl


# ---------------------------------------------------------------------------
# 运行器 / Runner
# ---------------------------------------------------------------------------

TESTS = [
    test_church_arithmetic,
    test_booleans,
    test_combinators_and_alpha,
    test_beta_steps,
    test_no_step_is_identity,
    test_strategies,
    test_strategy_command,
    test_step_limit,
    test_parse_errors,
    test_types,
    test_environment,
    test_load_file,
    test_manual_reduction,
    test_views,
    test_bilingual,
    test_protocol,
    test_determinism,
    test_cross_strategy_agreement,
    test_web_api,
    test_alpha_and_equivalence,
    test_extended_prelude,
    test_normal_forms_and_eta,
    test_fast_mode,
    test_redex_selection,
    test_file_features,
    test_cli_options,
    test_trace_cap,
    test_web_extras,
    test_properties,
    test_differential_main,
    test_web_ui_state,
    test_main_binary,
    test_let_and_annotations,
    test_new_commands,
    test_error_codes,
    test_cycle_and_fuel,
    test_eta_redex_selection,
    test_rec_type_env,
    test_file_commands,
    test_version_sources,
    test_core_sync,
    test_random_terms,
    test_performance_budget,
    test_style_conventions,
    test_web_21,
]


def test_new_features(b: Path) -> None:
    # 1. CLI one-shot / check modes and exit codes
    run_cli = lambda *args, input_text=None: subprocess.run(  # noqa: E731
        [str(b), *args], input=(input_text or "").encode("utf-8"),
        capture_output=True, cwd=str(ROOT), timeout=60)
    p = run_cli("--eval", ":int (PLUS TWO THREE)", "--lang", "en")
    check("--eval runs and exits 0",
          p.returncode == 0 and b"5" in p.stdout, p.stdout.decode("utf-8", "replace"))
    p = run_cli("--eval", "BROKEN (", "--lang", "en")
    check("--eval parse error exits 1", p.returncode == 1, str(p.returncode))
    p = run_cli("--check", "lib/prelude.lam", "--lang", "en")
    check("--check library passes", p.returncode == 0, p.stdout.decode("utf-8", "replace"))
    p = run_cli("--check", "test.lam", "--lang", "en")
    check("--check test.lam reports failures", p.returncode == 1, str(p.returncode))
    p = run_cli("--check", "--batch", "test.lam", "--lang", "en")
    check("--check rejects --batch", p.returncode != 0, str(p.returncode))
    p = run_cli("--max-term-size", "2", "--json", "--eval", "PLUS ONE TWO", "--lang", "en")
    check("--max-term-size rejects a large term",
          p.returncode == 0 and b"term_too_large" in p.stdout,
          p.stdout.decode("utf-8", "replace")[:200])
    p = run_cli("--max-term-size", "200", "--json", "--eval", ":int (PLUS ONE TWO)", "--lang", "en")
    check("--max-term-size accepts a small term",
          p.returncode == 0 and b'"value":3' in p.stdout,
          p.stdout.decode("utf-8", "replace")[:200])

    # --max-term-size 也必须约束 :load，而不是只约束 REPL 输入
    # --max-term-size must also bound :load, not just REPL input.
    with tempfile.TemporaryDirectory() as td:
        big = Path(td) / "big.lam"
        big.write_text("big = 9999\n", encoding="utf-8")
        p = run_cli("--max-term-size", "50", "--json", "--batch",
                    input_text=f":load {big}\n:env\n", )
        out = p.stdout.decode("utf-8", "replace")
        check("--max-term-size bounds :load",
              "term_too_large" in out and '"name":"big"' not in out, out[:300])
        p = run_cli("--max-term-size", "50", "--check", str(big), "--lang", "en")
        check("--max-term-size applies to --check", p.returncode == 1,
              p.stdout.decode("utf-8", "replace")[:240])

    # 2. combinators, numeric and list library
    cases = [
        (":int (I 4)", "4"),
        (":int (K 4 9)", "4"),
        (":int (S K K 4)", "4"),
        (":int (C PLUS 1 2)", "3"),
        (":int (B SUCC SUCC 2)", "4"),
        (":int (W PLUS 3)", "6"),
        (":int (MIN THREE TWO)", "2"),
        (":int (MAX THREE TWO)", "3"),
        (":int (DIV 7 2)", "3"),
        (":int (MOD 7 2)", "1"),
        (":int (XOR TRUE FALSE 1 2)", "1"),
    ]
    for expr, want in cases:
        got = one([expr], b)
        check(f"new prelude {expr}", str(got.get("value")) == want, str(got))
    got = one([":strategy normal", ":int (LENGTH (RANGE 1 5))"], b)
    check("RANGE/LENGTH", str(got.get("value")) == "5", str(got))
    got = one([":strategy normal", ":int (FOLD PLUS 0 [1, 2, 3])"], b)
    check("FOLD + list literal", str(got.get("value")) == "6", str(got))

    # 3. surface syntax
    got = one([":int (if TRUE then 2 else 3)"], b)
    check("if/then/else", str(got.get("value")) == "2", str(got))
    got = one([":int (let x = 2; y = 3 in PLUS x y)"], b)
    check("multi-binding let", str(got.get("value")) == "5", str(got))
    got = one([":int (HEAD [7, 8])"], b)
    check("list literal", str(got.get("value")) == "7", str(got))

    # 4. manual reduction back/goto
    outs = run([":begin (\\x.x) 1", ":step", ":back", ":goto 0", ":goto 1"], b)
    check("manual step/back/goto",
          outs[1][0].get("kind") == "step"
          and outs[2][0].get("back") is True
          and outs[3][0].get("step") == 0
          and outs[4][0].get("code") == "step_out_of_range",
          str(outs))

    # 5. :def / :search / :reload
    outs = run([":def PLUS", ":search PLU"], b)
    check(":def shows a definition",
          outs[0][0].get("kind") == "define" and outs[0][0].get("name") == "PLUS",
          str(outs[0]))
    check(":search finds names",
          outs[1][0].get("kind") == "search"
          and any(r.get("name") == "PLUS" for r in outs[1][0].get("rows", [])),
          str(outs[1]))
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "reload.lam"
        path.write_text("RELOADED = 42\n", encoding="utf-8")
        outs = run([f":load {path}", ":reload", ":def RELOADED"], b)
        check(":reload re-reads the file",
              outs[-1][0].get("kind") == "define"
              and outs[-1][0].get("name") == "RELOADED", str(outs[-1]))

    # 6. timing statistics
    got = one([":bench 2 PLUS ONE TWO"], b)
    for key in ("elapsedMs", "elapsedMedianMs", "elapsedStddevMs", "elapsedMinMs"):
        check(f"bench field {key}", key in got, str(got))
    got = one([":time 2 PLUS ONE TWO"], b)
    check(":time N runs", got.get("runs") == 2, str(got))

    # 7. extended library
    outs = run([":load lib/prelude.lam", ":fast on", ":int (FACT 5)"], b)
    check("lib/prelude.lam FACT", str(outs[-1][0].get("value")) == "120", str(outs[-1]))

    # 8. annotation diagnostics
    got = one([":type \\x.x : a -> b"], b)
    check("annotation mismatch details",
          got.get("matches") is False and "expected" in got and "actual" in got,
          str(got))


def test_property_extensions(b: Path) -> None:
    """Additional randomized properties for the new syntax and commands."""
    rng = random.Random(20261109)
    terms = []
    for _ in range(6):
        a, c = rng.randint(0, 4), rng.randint(0, 4)
        terms.append(rng.choice([
            f"PLUS {a} {c}",
            f"let x = {a}; y = {c} in PLUS x y",
            f"if LEQ {a} {c} then {a} else {c}",
            f"(\\x.x) {a}",
        ]))
    cmds = [":nf " + t for t in terms]
    outs = run(cmds, b)
    for t, objs in zip(terms, outs):
        term = objs[0].get("term") if objs else None
        check(f"nf produced a term for {t}", bool(term), str(objs))
        if term:
            again = one([":nf " + term], b).get("term")
            check(f"nf idempotent {t}", again == term, f"{term!r} vs {again!r}")

    eqs = [f":eq {t} , {t}" for t in terms]
    for t, objs in zip(terms, run(eqs, b)):
        check(f"eq reflexive {t}", objs and objs[0].get("equal") is True, str(objs))

    for n in [0, 1, 3, 7]:
        got = one([f":church {n}"], b)
        decoded = one([f":int ({got.get('term')})"], b)
        check(f"church/int roundtrip {n}", decoded.get("value") == n, str(decoded))

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "source.lam"
        dst = Path(td) / "saved.lam"
        src.write_text("ROUNDTRIP = let x = 2; y = 3 in PLUS x y\n", encoding="utf-8")
        outs = run([f":load {src}", f":save {dst}", ":reset",
                    f":load {dst}", ":def ROUNDTRIP"], b)
        check("save/load roundtrip keeps a definition",
              outs[-1] and outs[-1][0].get("kind") == "define",
              str(outs[-1]))
        check("saved file is parser-readable", dst.is_file(), str(dst))


def test_web_stream_and_storage(b: Path) -> None:
    try:
        import flask  # noqa: F401
    except ImportError:
        return
    import sys as _sys
    web_dir = str(ROOT / "web")
    if web_dir not in _sys.path:
        _sys.path.insert(0, web_dir)
    import app as webapp  # noqa: WPS433

    if os.name == "nt":
        kw = webapp._hidden_process_kwargs()
        check("desktop child process hides console",
              kw.get("creationflags") == webapp.subprocess.CREATE_NO_WINDOW
              and kw.get("startupinfo") is not None,
              str(kw))

    client = webapp.app.test_client()
    sid = client.post("/api/session").get_json()["session"]
    try:
        r = client.post("/api/eval/stream",
                        json={"session": sid, "line": "PLUS ONE TWO"})
        body = r.data.decode("utf-8", "replace")
        check("stream is SSE", r.status_code == 200
              and r.mimetype == "text/event-stream", r.content_type)
        check("stream frames decode", "data: " in body and '"kind": "result"' in body,
              body[:400])
        check("stream ends with done", '"kind": "done"' in body, body[-400:])

        # 流式接口的空行处理必须与 /api/eval 一致，不能把整段输入重复成一条
        # Streaming must split blank lines like /api/eval, not replay the whole input.
        r = client.post("/api/eval/stream", json={"session": sid, "line": "a\n\nb"})
        frames = [json.loads(line[6:]) for line in
                  r.data.decode("utf-8", "replace").splitlines()
                  if line.startswith("data: ")]
        kinds = [f.get("kind") for f in frames]
        check("stream keeps blank line as one command",
              kinds.count("result") == 2 and kinds.count("error") == 1, str(kinds))
        r = client.post("/api/eval/stream", json={"session": sid, "line": ""})
        frames = [json.loads(line[6:]) for line in
                  r.data.decode("utf-8", "replace").splitlines()
                  if line.startswith("data: ")]
        check("stream empty line is a parse error",
              any(f.get("kind") == "error" for f in frames), str(frames)[:300])

        # 子进程退出后读线程必须把会话标记为失效，避免流式接口把截断当成 done
        # A child exit must mark the session dead so streaming cannot report a
        # truncated reply as done.
        sid2 = client.post("/api/session").get_json()["session"]
        try:
            entry = webapp._sessions[sid2]
            entry["interp"].proc.kill()
            entry["interp"]._reader.join(5)
            check("reader marks a dead session", not entry["interp"].alive,
                  str(entry["interp"].alive))
        finally:
            client.delete(f"/api/session/{sid2}")
        # 客户端中途关闭流式请求时必须终止解释器，不能留下仍在运行的命令
        # Closing a stream early must stop the interpreter, not leave a command running.
        sid3 = client.post("/api/session").get_json()["session"]
        try:
            interp3 = webapp._sessions[sid3]["interp"]
            gen = interp3.send_stream("PLUS ONE TWO")
            try:
                next(gen)
            except StopIteration:
                pass
            gen.close()
            check("early stream close kills session", not interp3.alive,
                  str(interp3.alive))
        finally:
            client.delete(f"/api/session/{sid3}")
    finally:
        client.delete(f"/api/session/{sid}")

    # Share persistence: switch to a temp file, store, clear memory, reload
    old_db = webapp.SHARE_DB
    with tempfile.TemporaryDirectory() as td:
        webapp.SHARE_DB = str(Path(td) / "shares.json")
        try:
            r = client.post("/api/share", json={"code": ["PLUS ONE TWO"]})
            sid_share = r.get_json()["id"]
            webapp._shares.clear()
            webapp._load_shares()
            check("share survives reload", sid_share in webapp._shares,
                  str(list(webapp._shares)))
            # 损坏或手动扩大的存储文件不能让启动时无限加载
            # A damaged or manually enlarged store must not load without bound.
            old_max = webapp.MAX_SHARES
            webapp.MAX_SHARES = 2
            try:
                now = webapp.time.time()
                db = Path(webapp.SHARE_DB)
                db.write_text(json.dumps({
                    "a": {"created": now - 3, "payload": {"code": ["A"]}},
                    "b": {"created": now - 2, "payload": {"code": ["B"]}},
                    "c": {"created": now - 1, "payload": {"code": ["C"]}},
                }), encoding="utf-8")
                webapp._shares.clear()
                webapp._load_shares()
                check("share store capped", set(webapp._shares) == {"b", "c"},
                      str(list(webapp._shares)))
            finally:
                webapp.MAX_SHARES = old_max
        finally:
            webapp.SHARE_DB = old_db

    # Rate limiter is off by default; enable briefly and check 429
    old_rate = webapp.RATE_LIMIT
    webapp.RATE_LIMIT = 1
    webapp._rate_buckets.clear()
    try:
        first = client.post("/api/eval", json={"line": "\\x.x"})
        second = client.post("/api/eval", json={"line": "\\x.x"})
        check("rate limit returns 429", first.status_code != 429
              and second.status_code == 429
              and second.get_json().get("code") == "rate_limited",
              f"{first.status_code}/{second.status_code}")
    finally:
        webapp.RATE_LIMIT = old_rate
        webapp._rate_buckets.clear()

    # 关闭服务器时必须回收所有解释器进程，不能让它们在后台继续运行
    # Shutting the server down must reap every interpreter process.
    sid4 = client.post("/api/session").get_json()["session"]
    interp4 = webapp._sessions[sid4]["interp"]
    webapp._kill_all_sessions()
    check("shutdown kills every interpreter",
          not interp4.alive and not webapp._sessions,
          f"alive={interp4.alive} sessions={len(webapp._sessions)}")


TESTS.append(test_web_stream_and_storage)


TESTS.append(test_property_extensions)


TESTS.append(test_new_features)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="λ calculus interpreter regression tests")
    ap.add_argument("--bin", default=None, help="extension 可执行文件路径 / path to extension")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    binary = find_binary(args.bin)
    print(f"interpreter: {binary}")
    for test in TESTS:
        before = len(FAILURES)
        try:
            if test is test_main_binary:
                test()
            else:
                test(binary)
        except Exception as exc:  # noqa: BLE001
            FAILURES.append(f"{test.__name__}: raised {type(exc).__name__}: {exc}")
        status = "PASS" if len(FAILURES) == before else "FAIL"
        print(f"  [{status}] {test.__name__}")

    print()
    if FAILURES:
        print(f"{len(FAILURES)} failure(s):")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print(f"All {len(TESTS)} test groups passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
