#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Benchmark runner and trend chart for the interpreter.

运行一组 :bench 基准并把结果存入带时间戳的 JSON，也可生成 HTML 趋势图。
Run a small :bench suite into a timestamped JSON log and render an HTML chart.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = ("PLUS 40 40", "MULT 20 20", "FACT 6", "(\\x.x x) (\\y.y)")
DEFAULT_DB = ROOT / "web" / "benchmarks.json"


def find_binary(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("LAMBDA_INTERP_BIN")
    if env and Path(env).is_file():
        return Path(env)
    dirs = []
    d = os.environ.get("LAMBDA_INTERP_DIR")
    if d:
        dirs.append(Path(d))
    dirs += [ROOT, Path("/opt/lambda-calculus-interpreter")]
    for base in dirs:
        for name in ("extension.exe", "extension"):
            p = base / name
            if p.is_file():
                return p
    raise SystemExit("extension binary not found / 未找到 extension")


def run_case(binary: Path, expr: str, runs: int = 5) -> dict:
    # 先加载 prelude：FACT 等名字只定义在 lib/prelude.lam，否则会被当成自由变量，
    # 基准实际测的是 0 步的规范化空转
    # Load the prelude first: FACT etc. live only in lib/prelude.lam; without it the
    # "benchmark" measures a free variable in normal form (zero beta steps).
    line = f":load lib/prelude.lam\n:bench {runs} {expr}\n"
    try:
        proc = subprocess.run([str(binary), "--batch", "--json", "--lang", "en"],
                              input=line.encode("utf-8"), capture_output=True,
                              cwd=ROOT, timeout=120)
    except subprocess.TimeoutExpired:
        return {"expr": expr, "meanMs": None, "kind": "timeout",
                "text": "benchmark timed out / 基准超时"}
    except OSError as exc:
        return {"expr": expr, "meanMs": None, "kind": "error",
                "text": str(exc)[:200]}
    results: dict = {}
    for chunk in proc.stdout.decode("utf-8", "replace").split("\x1e"):
        for part in chunk.splitlines():
            if part.strip():
                try:
                    obj = json.loads(part)
                except ValueError:
                    continue
                results = obj
                break
    return {"expr": expr, "meanMs": results.get("elapsedMs", results.get("mean")),
            "kind": results.get("kind"), "text": results.get("text", "")[:200]}


def read_db(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def write_db(path: Path, data: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def chart(entries: list[dict]) -> str:
    flat: list[dict] = []
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("cases"), list):
            flat.extend(entry["cases"])
        elif isinstance(entry, dict) and "expr" in entry:
            flat.append(entry)
    entries = flat
    exprs = list(dict.fromkeys(e.get("expr", "") for e in entries))
    colors = ("#2f6f4f", "#b23c2c", "#3b5ea8", "#a06a1f")
    # Legends stack 14px apart starting at y=344; grow the canvas so the last
    # label is never clipped by the fixed 360px viewBox.
    height = max(360, 344 + len(exprs) * 14 + 10)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="{height}" '
             f'viewBox="0 0 900 {height}">']
    parts.append('<text x="20" y="26" font-size="16">lambda benchmark trend</text>')
    for i, expr in enumerate(exprs):
        pts = [(j, e.get("meanMs") or 0) for j, e in
               enumerate(x for x in entries if x.get("expr", "") == expr)]
        if not pts:
            continue
        mx = max(1.0, max(p[1] for p in pts))
        y0 = 320
        coords = " ".join(f"{60 + j * 26},{y0 - (v / mx) * 260:.1f}" for j, v in pts)
        parts.append(f'<polyline fill="none" stroke="{colors[i % len(colors)]}" '
                     f'stroke-width="2" points="{coords}"/>')
        parts.append(f'<text x="60" y="{344 + i * 14}" font-size="11" '
                     f'fill="{colors[i % len(colors)]}">{html.escape(expr)}</text>')
    parts.append('</svg>')
    return ("<!doctype html><html><head><meta charset=\"utf-8\"><title>benchmarks</title>"
            "</head><body style=\"background:#fbfaf7;font-family:monospace;padding:20px\">"
            + "".join(parts) + "</body></html>")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", default=None)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--chart", default=None, help="write an HTML chart to this path")
    ap.add_argument("--runs", type=int, default=5)
    args = ap.parse_args()
    binary = find_binary(args.bin)
    db = Path(args.db)
    if args.chart:
        Path(args.chart).write_text(chart(read_db(db)), encoding="utf-8")
        print(f"chart written / 图表已写入: {args.chart}")
        return 0
    entry = {"ts": time.time(), "version": (ROOT / "VERSION").read_text().strip(),
             "cases": [run_case(binary, c, args.runs) for c in CASES]}
    data = read_db(db)
    data.append(entry)
    write_db(db, data[-100:])
    print(json.dumps(entry, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
