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
import subprocess
import sys
import tempfile
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

    # 重新定义为不可类型化的项后，旧类型方案必须被清除，不能残留
    # Redefining to an untypable term must drop the stale type scheme.
    outs = run(["f = \\x.x", ":type f", "f = \\x.x x", ":type f"], b)
    check("first type", outs[1][0].get("type") == "t0 → t0 (polymorphic)", str(outs[1]))
    check("stale type dropped", outs[3][0].get("type") != "t0 → t0 (polymorphic)", str(outs[3]))
    check("second kind", outs[3][0].get("kind") == "type", str(outs[3]))

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
        check("load redef stale dropped", outs[3][0].get("type") != "t0 → t0 (polymorphic)", str(outs[3]))


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
    # 否则校验与解释器实际打开的文件不一致，可绕过路径限制。
    # With a custom LAMBDA_LOAD_ROOT, relative paths must resolve against the
    # interpreter's cwd (INTERP_DIR); resolving against root lets the real open
    # land outside the configured root.
    saved_root = os.environ.get("LAMBDA_LOAD_ROOT")
    with tempfile.TemporaryDirectory() as td:
        os.environ["LAMBDA_LOAD_ROOT"] = td
        try:
            err = webapp.validate_line(":load test.lam")
            check("web load custom root relative confined",
                  err is not None and "restricted" in err, str(err))
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


def test_normal_forms_and_eta(b: Path) -> None:
    r = one([":nf (\\x.\\y.x) a b"], b)
    check("nf term", r.get("term") == "a" and r.get("steps") == 2, str(r))
    r = one([":whnf (\\x.\\y.x) (\\x.x)"], b)
    check("whnf stops early", r.get("term") == "λy → λx → x" and r.get("steps") == 1, str(r))

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


# ---------------------------------------------------------------------------
# CLI 选项与轨迹上限 / CLI options and the trace cap
# ---------------------------------------------------------------------------

def test_cli_options(b: Path) -> None:
    p = subprocess.run([str(b), "--version"], capture_output=True, timeout=30)
    check("version", "2.0.0" in p.stdout.decode("utf-8", "replace"), p.stdout.decode("utf-8", "replace"))
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
    check("prelude extended", "Y" in client.get("/api/prelude").get_json(), "")
    icon = client.get("/icon.svg")
    check("icon served", icon.status_code == 200 and "svg" in icon.content_type, icon.content_type)

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
    test_main_binary,
]


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
