#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""共享核心一致性检查 / Shared-core consistency check.

`main.hs` 与 `extension.hs` 刻意各自独立编译，因此两者的核心实现是复制的。
复制最容易出现的故障是“只改了一边”。本脚本提取两边同名的顶层声明，
去掉注释与空白后逐字比对；同时确认新增语法片段在两边都存在。
它不依赖 Cabal，也不需要 GHC，CI 里直接 `python tools/check_core_sync.py`。

Both interpreters are deliberately standalone, so their core is duplicated.
The classic failure mode is a fix that lands in only one of them. This script
extracts same-named top-level declarations, strips comments and whitespace and
compares them verbatim; it also checks that the shared syntax fragments exist
in both files. No Cabal and no GHC needed: CI just runs this file.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECL_START = re.compile(r"^([A-Za-z_][A-Za-z0-9_']*)(?=\s|::|=|$)")

# 这些函数必须在两个文件里都存在；它们是语言语义的共同基础
# These must exist in both files: they are the shared semantic foundation.
MUST_EXIST = (
    "freeVars", "freshVar", "substRename", "orderOf", "stepOnce",
    "etaRoot", "etaStep", "stepFor", "isWHNF", "headSpine",
    "betaStep", "defaultLimit", "traceLimit",
    "cycleCheckLimit", "cycleTermLimit", "evalUntil", "evalWith",
    "parseExpr", "parseLam", "parseApp", "parseAtom", "parseParens",
    "parseLet", "parseIf", "notKeyword", "parseList", "typeTextP", "trim",
    "stripTrailingComment", "parenBalance", "readReplLine",
)

# 这些声明必须逐字一致；语义分叉（Env / JSON / fast 模式）不在此列
# These declarations must be textually identical; semantic differences
# (Env, JSON, fast mode) are intentionally excluded.
MUST_MATCH = (
    "freeVars", "freshVar", "substRename", "orderOf", "stepOnce",
    "etaRoot", "etaStep", "stepFor", "isWHNF", "headSpine",
    "betaStep", "defaultLimit", "traceLimit",
    "cycleCheckLimit", "cycleTermLimit",
    "parseLet", "notKeyword", "typeTextP", "parseParens", "trim",
    "parseIf", "parseList",
    "stripTrailingComment", "parenBalance", "readReplLine",
)


def declarations(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    starts = [(i, m.group(1)) for i, line in enumerate(lines)
              if (m := DECL_START.match(line))]
    found: dict[str, list[str]] = {}
    for k, (i, name) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
        block = "\n".join(lines[i:end]).rstrip()
        found.setdefault(name, []).append(block)
    return {name: "\n".join(parts) for name, parts in found.items()}


def declaration_spans(path: Path) -> dict[str, tuple[int, int]]:
    """Return name -> (start, end) zero-based line spans."""
    lines = path.read_text(encoding="utf-8").splitlines()
    starts = [(i, m.group(1)) for i, line in enumerate(lines)
              if (m := DECL_START.match(line))]
    spans: dict[str, tuple[int, int]] = {}
    for k, (i, name) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
        spans[name] = (i, end)
    return spans


def sync_from_extension(dst: Path, src: Path) -> int:
    """Copy shared declarations from extension.hs into main.hs.

    The extended interpreter is the single source of truth; the minimal file is
    kept standalone by copying the shared core into it. This replaces only the
    declarations listed in MUST_MATCH, leaving each file's own extras untouched.
    """
    src_text = src.read_text(encoding="utf-8")
    src_lines = src_text.splitlines(keepends=True)
    dst_text = dst.read_text(encoding="utf-8")
    dst_lines = dst_text.splitlines(keepends=True)
    src_decl = declarations(src)
    dst_decl = declarations(dst)
    src_span = declaration_spans(src)
    dst_span = declaration_spans(dst)
    changed = 0
    # 从后往前替换，避免行号偏移 / replace back to front so earlier spans stay valid
    targets = [n for n in MUST_MATCH if n in src_span and n in dst_span]
    for name in sorted(targets, key=lambda n: dst_span[n][0], reverse=True):
        if normalize(dst_decl.get(name, "")) == normalize(src_decl.get(name, "")):
            continue
        ds, de = dst_span[name]
        ss, se = src_span[name]
        block = "".join(src_lines[ss:se])
        dst_lines[ds:de] = [block if block.endswith("\n") else block + "\n"]
        changed += 1
    if changed:
        dst.write_text("".join(dst_lines), encoding="utf-8")
    return changed


def normalize(text: str) -> str:
    # 去掉整行注释与行尾空白；保留缩进，避免把不同结构抹平成一样
    # Drop whole-line comments and trailing whitespace; keep indentation so
    # structurally different code cannot collapse into the same text.
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        kept.append(line.rstrip())
    return "\n".join(kept)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check or sync the shared core")
    parser.add_argument("--fix", action="store_true",
                        help="copy differing shared declarations from extension.hs to main.hs")
    args = parser.parse_args(argv)

    if args.fix:
        changed = sync_from_extension(ROOT / "main.hs", ROOT / "extension.hs")
        print(f"synced {changed} declaration(s) from extension.hs to main.hs")

    a = declarations(ROOT / "main.hs")
    b = declarations(ROOT / "extension.hs")
    problems: list[str] = []

    for name in MUST_EXIST:
        if name not in a:
            problems.append(f"main.hs 缺少 {name} / main.hs is missing {name}")
        if name not in b:
            problems.append(f"extension.hs 缺少 {name} / extension.hs is missing {name}")

    for name in MUST_MATCH:
        if name not in a or name not in b:
            continue
        na, nb = normalize(a[name]), normalize(b[name])
        if na != nb:
            problems.append(
                f"{name} 在两份文件里不一致 / differs between the two files\n"
                f"    main.hs      : {na[:110]!r}\n"
                f"    extension.hs: {nb[:110]!r}"
            )

    if problems:
        for problem in problems:
            print("FAIL:", problem)
        print(f"\n{len(problems)} 处不一致 / {len(problems)} inconsistency(ies) found.")
        print("同步修改 main.hs 与 extension.hs 后重试")
        print("Apply the change to both files and retry.")
        return 1

    print(f"core sync ok: {len(MUST_EXIST)} shared names present, "
          f"{len(MUST_MATCH)} declarations identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
