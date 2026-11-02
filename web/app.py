#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lambda 演算 Web 计算器 — 后端 (Flask)。
Lambda calculus web calculator — backend (Flask).

计算引擎是本仓库的 Haskell 解释器 `extension.hs`（编译产物 `extension` /
`extension.exe`）。后端以 `--batch --json` 模式启动一个常驻进程，每条命令
写入一行并读取到记录分隔符 `\\x1e` 为止，因此：
The engine is the Haskell interpreter in this repo (`extension.hs`, compiled to
`extension`/`extension.exe`). The backend starts one persistent process in
`--batch --json` mode, writes one command per line and reads until the record
separator `\\x1e`, so:

* 定义、策略、步数上限等状态在会话内自然保持（不再整段重放）；
  definitions, strategy and step limits persist inside the session (no replay);
* 输出是结构化的 JSON，前端可直接渲染轨迹、语法树、类型；
  output is structured JSON, so the UI can render traces, ASTs and types;
* 超时会杀掉该会话并返回 408。
  a timeout kills the session and returns HTTP 408.

路由 / Routes:
  GET  /                    静态前端 index.html / static frontend
  GET  /fonts/<file>        APL385 字体 / font
  GET  /api/prelude         可用预定义名 / prelude names
  POST /api/session         创建会话 {lang?} -> {session} / create a session
  POST /api/eval            执行一行 {session, line} -> {outputs} / run one line
                            兼容旧接口：{code} 一次性执行 -> {results}
                            legacy: {code} runs one-shot -> {results}
  DELETE /api/session/<id>  主动结束会话 / end a session

解释器路径按以下顺序解析（可用环境变量覆盖）:
Interpreter lookup order (overridable by environment variables):
  LAMBDA_INTERP_BIN                 直接指定可执行文件 / explicit binary
  LAMBDA_INTERP_DIR/extension[.exe] 指定目录 / directory
  <repo>/extension[.exe]            仓库内本地运行 / inside the repo
  /opt/lambda-calculus-interpreter/ 线上部署 / production deployment
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

APP_DIR = Path(__file__).resolve().parent
RS = "\x1e"                     # 与前端的记录分隔符保持一致
EVAL_TIMEOUT = float(os.environ.get("LAMBDA_EVAL_TIMEOUT", "10"))
SESSION_IDLE = float(os.environ.get("LAMBDA_SESSION_IDLE", "1800"))
MAX_SESSIONS = int(os.environ.get("LAMBDA_MAX_SESSIONS", "32"))
ALLOWED_LANGS = {"zh", "en", "both"}


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


# ---------------------------------------------------------------------------
# 常驻解释器 / persistent interpreter
# ---------------------------------------------------------------------------
class Interpreter:
    """一个 `extension --batch --json` 子进程 + 一个读线程。"""

    def __init__(self, lang: str = "both"):
        self.alive = True
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        env = {**os.environ, "TERM": "dumb"}
        env.pop("LAMBDA_INTERP_BIN", None)
        self.proc = subprocess.Popen(
            [str(INTERP_BIN), "--batch", "--json", "--lang", lang],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=str(INTERP_DIR),
            env=env,
            bufsize=0,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        buf: list[dict] = []
        try:
            while True:
                raw = self.proc.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", "replace")
                if line.rstrip("\r\n") == RS:
                    self._q.put(buf)
                    buf = []
                elif line.strip():
                    try:
                        buf.append(json.loads(line))
                    except json.JSONDecodeError:
                        buf.append({"kind": "info", "text": line.rstrip()})
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._q.put(None)

    def send(self, line: str, timeout: float = EVAL_TIMEOUT) -> list[dict]:
        if not self.alive:
            raise TimeoutError("session is dead")
        with self._lock:
            try:
                self.proc.stdin.write((line + "\n").encode("utf-8"))
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self.kill()
                raise RuntimeError(f"interpreter pipe closed: {exc}") from exc
            try:
                outputs = self._q.get(timeout=timeout)
            except queue.Empty:
                self.kill()
                raise TimeoutError("evaluation timeout") from None
            if outputs is None:
                self.kill()
                raise RuntimeError("interpreter exited")
            return outputs

    def kill(self) -> None:
        self.alive = False
        try:
            self.proc.kill()
        except Exception:  # noqa: BLE001
            pass


_sessions: dict[str, dict] = {}
_sessions_lock = threading.Lock()


def _prune_sessions() -> None:
    now = time.time()
    with _sessions_lock:
        stale = [sid for sid, s in _sessions.items()
                 if now - s["used"] > SESSION_IDLE or not s["interp"].alive]
        for sid in stale:
            _sessions.pop(sid)["interp"].kill()
        # 超出上限时丢弃最久未使用的会话
        # Evict the least recently used session when over the limit.
        while len(_sessions) > MAX_SESSIONS:
            oldest = min(_sessions, key=lambda k: _sessions[k]["used"])
            _sessions.pop(oldest)["interp"].kill()


def get_session(sid: str | None, lang: str = "both") -> tuple[str, Interpreter]:
    _prune_sessions()
    with _sessions_lock:
        if sid and sid in _sessions:
            entry = _sessions[sid]
            entry["used"] = time.time()
            return sid, entry["interp"]
        sid = uuid.uuid4().hex
        interp = Interpreter(lang)
        _sessions[sid] = {"interp": interp, "used": time.time()}
        return sid, interp


# ---------------------------------------------------------------------------
# 一次性执行（旧接口 / 批量回放）/ one-shot legacy execution
# ---------------------------------------------------------------------------
def run_interpreter(code: str, lang: str = "both", timeout: float = EVAL_TIMEOUT):
    """把整段 code 喂给批处理解释器，返回全部输出对象。"""
    if not code.endswith("\n"):
        code += "\n"
    proc = subprocess.run(
        [str(INTERP_BIN), "--batch", "--json", "--lang", lang],
        input=code.encode("utf-8"),
        capture_output=True,
        timeout=timeout,
        cwd=str(INTERP_DIR),
        env={**os.environ, "TERM": "dumb"},
    )
    out = (proc.stdout or b"").decode("utf-8", "replace")
    results: list[dict] = []
    for chunk in out.split(RS)[:-1]:
        for line in chunk.splitlines():
            if line.strip():
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    results.append({"kind": "info", "text": line})
    if proc.returncode != 0 and not results:
        err = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        if err:
            results.append({"kind": "fail", "text": err[0]})
    return results


# ---------------------------------------------------------------------------
# 路由 / routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(str(APP_DIR), "index.html")


@app.route("/fonts/<path:filename>")
def fonts(filename):
    return send_from_directory(str(APP_DIR / "fonts"), filename)


@app.route("/api/prelude")
def prelude():
    return jsonify(PRELUDE)


@app.route("/api/session", methods=["POST"])
def api_session():
    data = request.get_json(force=True, silent=True) or {}
    lang = data.get("lang") if data.get("lang") in ALLOWED_LANGS else "both"
    sid, _ = get_session(None, lang)
    return jsonify({"ok": True, "session": sid})


@app.route("/api/session/<sid>", methods=["DELETE"])
def api_session_delete(sid):
    with _sessions_lock:
        entry = _sessions.pop(sid, None)
    if entry:
        entry["interp"].kill()
    return jsonify({"ok": True})


@app.route("/api/eval", methods=["POST"])
def api_eval():
    data = request.get_json(force=True, silent=True) or {}
    lang = data.get("lang") if data.get("lang") in ALLOWED_LANGS else "both"

    # 旧接口：{code} 一次性执行
    legacy = data.get("code") or data.get("expr")
    if legacy is not None:
        try:
            if not INTERP_BIN.is_file():
                return jsonify({"ok": False, "error": _missing_bin_msg()}), 500
            results = run_interpreter(str(legacy), lang)
            return jsonify({"ok": True, "results": results, "outputs": results})
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": _timeout_msg(lang)}), 408

    line = data.get("line")
    if line is None:
        # 兼容 {lines: [...]}：按顺序发送
        lines = data.get("lines") or []
        if not lines:
            return jsonify({"ok": False, "error": "empty request"}), 400
    else:
        lines = [line]

    try:
        sid, interp = get_session(data.get("session"), lang)
        outputs: list[dict] = []
        for ln in lines:
            outputs.extend(interp.send(str(ln)))
        with _sessions_lock:
            if sid in _sessions:
                _sessions[sid]["used"] = time.time()
        return jsonify({"ok": True, "session": sid, "outputs": outputs, "results": outputs})
    except TimeoutError:
        return jsonify({
            "ok": False,
            "error": _timeout_msg(lang),
            "timeout": True,
        }), 408
    except RuntimeError as exc:
        # 解释器进程已退出，前端应重建会话并回放历史。
        # The interpreter process is gone; the client should rebuild + replay.
        return jsonify({"ok": False, "error": str(exc), "restart": True}), 410
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 400


def _missing_bin_msg() -> str:
    return f"未找到解释器 Not found: {INTERP_BIN}。请先运行 build.bat / build.sh。Run build first."


def _timeout_msg(lang: str) -> str:
    if lang == "en":
        return "Evaluation timed out (>10s); the term may not terminate."
    if lang == "zh":
        return "计算超时（>10s），表达式可能陷入无限归约。"
    return "计算超时 / timed out (>10s)：表达式可能不终止 / the term may not terminate."


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8081")),
        threaded=True,
    )
