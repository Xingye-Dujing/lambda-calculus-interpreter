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
  类型推断、环境操作、手动归约、语法树、de Bruijn、双语输出、JSON 协议
  Covers parse positions, β-reduction results, strategies, step limits,
  Church hints, type inference, environment commands, manual reduction,
  syntax trees, de Bruijn view, bilingual output and the JSON protocol.

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
    """运行一组命令，返回「每条命令的输出对象列表」

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
    finally:
        client.delete(f"/api/session/{sid}")


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
