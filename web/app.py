#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lambda 演算 Web 计算器 — 后端 (Flask)。

计算引擎是本仓库的 Haskell 解释器 `extension.hs`（编译产物 `extension` /
`extension.exe`）。后端把多行代码经 stdin 喂给解释器，捕获其 REPL 输出
（⇒ 结果 / defined / 解析错误）并清洗后返回。

路由:
  GET  /                    静态前端 index.html
  GET  /fonts/<file>        APL385 字体
  GET  /api/prelude         可用预定义名
  POST /api/eval  {code}    运行解释器，返回逐行结果

解释器路径按以下顺序解析（可用环境变量覆盖）:
  LAMBDA_INTERP_BIN                 直接指定可执行文件
  LAMBDA_INTERP_DIR/extension[.exe] 指定目录
  <repo>/extension[.exe]            仓库内本地运行
  /opt/lambda-calculus-interpreter/ 线上部署（/opt/lambda-app）
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

APP_DIR = Path(__file__).resolve().parent


def _resolve_interp() -> Path:
    env_bin = os.environ.get("LAMBDA_INTERP_BIN")
    if env_bin:
        return Path(env_bin)

    dirs = []
    if os.environ.get("LAMBDA_INTERP_DIR"):
        dirs.append(Path(os.environ["LAMBDA_INTERP_DIR"]))
    dirs.extend([APP_DIR.parent, Path("/opt/lambda-calculus-interpreter")])

    for directory in dirs:
        for name in ("extension.exe", "extension"):
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return dirs[-1] / "extension"


INTERP_BIN = _resolve_interp()
INTERP_DIR = INTERP_BIN.parent

# 与 extension.hs 中 initEnv 保持一致
PRELUDE = [
    "TRUE", "FALSE", "NOT", "AND", "OR", "IF",
    "ZERO", "ONE", "TWO", "THREE", "SUCC", "PLUS", "MULT",
]

app = Flask(__name__, static_folder=None, static_url_path=None)


_console_ready = False


def interpreter_command():
    """Windows 下 GHC 默认按本地代码页（如 GBK）读写，⇒ 无法编码会崩溃；
    先把控制台代码页切到 UTF-8。Linux 无此问题。"""
    global _console_ready
    if os.name == "nt" and not _console_ready:
        _console_ready = True
        try:
            subprocess.run(
                "chcp 65001", shell=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
            )
        except Exception:  # noqa: BLE001
            pass
    return [str(INTERP_BIN)]


def run_interpreter(code: str, timeout: float = 10.0):
    """把 code 喂给 Haskell 解释器，返回已去掉 REPL 提示符 'λ> ' 的输出行。"""
    if os.name == "nt":
        # Windows 下解释器按本地代码页读 stdin，非 ASCII 的 λ 会被错误解码；
        # 它等价于反斜杠，替换后不影响语义。
        code = code.replace("λ", "\\")
    if not code.endswith("\n"):
        code += "\n"
    proc = subprocess.run(
        interpreter_command(),
        input=code.encode("utf-8"),
        capture_output=True,
        timeout=timeout,
        cwd=str(INTERP_DIR),
        env={**os.environ, "TERM": "dumb"},
    )
    out = (proc.stdout or b"").decode("utf-8", "replace")
    lines = []
    for raw in out.splitlines():
        line = raw
        if line.startswith("λ> "):
            line = line[3:]
        elif line == "λ>":
            line = ""
        if line == "":
            continue
        lines.append(line)
    if proc.returncode != 0 and not lines:
        err = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        if err:
            lines.append("运行错误: " + err[0])
    return lines


def classify(lines):
    results = []
    for line in lines:
        if line.startswith("⇒"):
            results.append({"kind": "result", "text": line[1:].strip()})
        elif line.startswith("defined "):
            results.append({"kind": "define", "text": line[len("defined "):].strip()})
        elif "错误" in line:
            results.append({"kind": "error", "text": line})
        else:
            results.append({"kind": "info", "text": line})
    return results


@app.route("/")
def index():
    return send_from_directory(str(APP_DIR), "index.html")


@app.route("/fonts/<path:filename>")
def fonts(filename):
    return send_from_directory(str(APP_DIR / "fonts"), filename)


@app.route("/api/prelude")
def prelude():
    return jsonify(PRELUDE)


@app.route("/api/eval", methods=["POST"])
def api_eval():
    try:
        data = request.get_json(force=True, silent=True) or {}
        code = data.get("code") or data.get("expr") or ""
        code = code.strip()
        if not code:
            return jsonify({"ok": False, "error": "请输入表达式或定义"}), 400
        if not INTERP_BIN.is_file():
            return jsonify({
                "ok": False,
                "error": f"未找到解释器：{INTERP_BIN}。请先运行 build.bat / build.sh 编译。",
            }), 500
        lines = run_interpreter(code)
        return jsonify({"ok": True, "results": classify(lines), "raw": lines})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "计算超时（>10s），表达式可能陷入无限归约。"}), 408
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(e)}), 400


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8081")),
    )
