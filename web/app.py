#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lambda 演算 Web 计算器 — 后端 (Flask)
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
* 超时会杀掉该会话并返回 408
  a timeout kills the session and returns HTTP 408.

路由 / Routes:
  GET  /                    静态前端 index.html / static frontend
  GET  /fonts/<file>        APL385 字体 / font
  GET  /icon.svg            站点图标 / favicon
  GET  /api/prelude         可用预定义名 / prelude names
  GET  /api/health          会话数与解释器状态 / health and session count
  POST /api/share           保存前端状态 -> {id} / store a share payload
  GET  /api/share/<id>      取回前端状态 / fetch a share payload
  POST /api/session         创建会话 {lang?} -> {session} / create a session
  POST /api/eval            执行一行 {session, line} -> {outputs} / run one line
                            兼容旧接口：{code} 一次性执行 -> {results}
                            legacy: {code} runs one-shot -> {results}
                            会话过期返回 410 + restart / expired -> 410 restart
  POST /api/session/<id>/lang  在同一进程内切换语言 / switch language in place
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
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

APP_DIR = Path(__file__).resolve().parent
RS = "\x1e"                     # 与前端的记录分隔符保持一致 / keep in sync with the frontend
EVAL_TIMEOUT = float(os.environ.get("LAMBDA_EVAL_TIMEOUT", "10"))
SESSION_IDLE = float(os.environ.get("LAMBDA_SESSION_IDLE", "1800"))
MAX_SESSIONS = int(os.environ.get("LAMBDA_MAX_SESSIONS", "32"))
ALLOWED_LANGS = {"zh", "en", "both"}
SHARE_TTL = float(os.environ.get("LAMBDA_SHARE_TTL", "604800"))   # 7 days
MAX_SHARES = int(os.environ.get("LAMBDA_MAX_SHARES", "500"))
MAX_SHARE_BYTES = 64 * 1024

# `:load` 默认只允许解释器目录内的文件，防止 Web 用户读取服务器任意路径；
# 设为 `*` 可关闭限制（仅建议在本地使用）
# `:load` is restricted to the interpreter directory by default so web users
# cannot read arbitrary server files; set LAMBDA_LOAD_ROOT=* to disable.
LOAD_RE = re.compile(r"^:load\s+(.+)$")
SAVE_RE = re.compile(r"^:save\s+(.+)$")

# 写文件在 Web 端默认关闭，避免公开部署时任意覆盖服务器文件
# Writing files over the web is disabled by default; enable only for local use.
ALLOW_SAVE = os.environ.get("LAMBDA_ALLOW_SAVE", "0").strip().lower() in (
    "1", "true", "yes", "on",
)


def load_root() -> Path | None:
    raw = os.environ.get("LAMBDA_LOAD_ROOT")
    if raw is None:
        return INTERP_DIR
    if raw.strip() in ("", "*"):
        return None
    return Path(raw).expanduser().resolve()


def _check_path(line: str) -> str | None:
    for regex, verb in ((LOAD_RE, "load"), (SAVE_RE, "save")):
        match = regex.match(line.strip())
        if not match:
            continue
        if verb == "save" and not ALLOW_SAVE:
            return (":save 在 Web 端默认关闭 / :save is disabled over the web "
                    "(set LAMBDA_ALLOW_SAVE=1 for local use)")
        root = load_root()
        if root is None:
            return None
        raw = match.group(1).strip().strip('"').strip("'")
        try:
            target = Path(raw)
            if not target.is_absolute():
                # 解释器以 INTERP_DIR 为工作目录，相对路径必须按它解析后再检查是否在 root 内
                # The interpreter runs with cwd=INTERP_DIR, so resolve relative paths
                # against that (not root) before checking confinement.
                target = INTERP_DIR / target
            target.resolve().relative_to(root)
        except (ValueError, OSError):
            return (f":{verb} 仅允许解释器目录内的路径 / :{verb} is restricted to {root} "
                    "(set LAMBDA_LOAD_ROOT=* to allow any path)")
        return None
    return None


def validate_line(line: str) -> str | None:
    return _check_path(line)


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
    "EXP", "PRED", "SUB", "ISZERO", "LEQ", "EQ",
    "PAIR", "FST", "SND", "NIL", "CONS", "HEAD", "TAIL", "Y",
]

app = Flask(__name__, static_folder=None, static_url_path=None)


# ---------------------------------------------------------------------------
# 常驻解释器 / persistent interpreter
# ---------------------------------------------------------------------------
class Interpreter:
    """一个 `extension --batch --json` 子进程 + 一个读线程"""

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

# 短链分享：保存前端状态 JSON，返回一个短 id
# Short share links: keep the client state JSON server-side under a short id.
_shares: dict[str, dict] = {}
_shares_lock = threading.Lock()


def _prune_shares() -> None:
    now = time.time()
    with _shares_lock:
        stale = [k for k, v in _shares.items() if now - v["created"] > SHARE_TTL]
        for k in stale:
            _shares.pop(k, None)
        while len(_shares) > MAX_SHARES:
            oldest = min(_shares, key=lambda k: _shares[k]["created"])
            _shares.pop(oldest, None)


def _valid_share(payload) -> bool:
    if not isinstance(payload, dict):
        return False
    code = payload.get("code")
    if not isinstance(code, list) or not all(isinstance(x, str) for x in code):
        return False
    try:
        raw = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        return False
    return len(raw.encode("utf-8")) <= MAX_SHARE_BYTES


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


def get_session(sid: str | None, lang: str = "both",
                *, create: bool = True) -> tuple[str, Interpreter] | tuple[None, None]:
    """Look up or create a session.

    With ``create=False`` an unknown id returns ``(None, None)`` instead of
    silently starting a fresh environment, so the client can replay history.
    """
    _prune_sessions()
    with _sessions_lock:
        if sid and sid in _sessions:
            entry = _sessions[sid]
            entry["used"] = time.time()
            return sid, entry["interp"]
        if not create:
            return None, None
        new_sid = uuid.uuid4().hex
        interp = Interpreter(lang)
        _sessions[new_sid] = {"interp": interp, "used": time.time()}
        return new_sid, interp


# ---------------------------------------------------------------------------
# 一次性执行（旧接口 / 批量回放）/ one-shot legacy execution
# ---------------------------------------------------------------------------
def run_interpreter(code: str, lang: str = "both", timeout: float = EVAL_TIMEOUT):
    """把整段 code 喂给批处理解释器，返回全部输出对象"""
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


@app.route("/icon.svg")
def icon():
    return send_from_directory(str(APP_DIR), "icon.svg", mimetype="image/svg+xml")


@app.route("/api/prelude")
def prelude():
    return jsonify(PRELUDE)


@app.route("/api/health")
def health():
    _prune_sessions()
    with _sessions_lock:
        count = len(_sessions)
    return jsonify({
        "ok": True,
        "sessions": count,
        "interpreter": str(INTERP_BIN),
        "available": INTERP_BIN.is_file(),
    })


@app.route("/api/share", methods=["POST"])
def api_share():
    payload = request.get_json(force=True, silent=True)
    if not _valid_share(payload):
        return jsonify({"ok": False, "error": "invalid or oversized share payload"}), 400
    _prune_shares()
    sid = uuid.uuid4().hex[:10]
    with _shares_lock:
        _shares[sid] = {"payload": payload, "created": time.time()}
    return jsonify({"ok": True, "id": sid})


@app.route("/api/share/<sid>", methods=["GET"])
def api_share_get(sid):
    _prune_shares()
    with _shares_lock:
        entry = _shares.get(sid)
    if not entry:
        return jsonify({"ok": False, "error": "share not found"}), 404
    return jsonify({"ok": True, "state": entry["payload"]})


@app.route("/api/session", methods=["POST"])
def api_session():
    data = request.get_json(force=True, silent=True) or {}
    lang = data.get("lang") if data.get("lang") in ALLOWED_LANGS else "both"
    sid, _ = get_session(None, lang)
    return jsonify({"ok": True, "session": sid})


@app.route("/api/session/<sid>/lang", methods=["POST"])
def api_session_lang(sid):
    """在同一个解释器进程内切换语言，避免重建会话
    Switch language inside the same interpreter process (no session rebuild)."""
    data = request.get_json(force=True, silent=True) or {}
    lang = data.get("lang") if data.get("lang") in ALLOWED_LANGS else "both"
    _prune_sessions()
    with _sessions_lock:
        entry = _sessions.get(sid)
        if entry:
            entry["used"] = time.time()
    if not entry:
        return jsonify({"ok": False, "error": "session not found", "restart": True}), 410
    try:
        outputs = entry["interp"].send(f":lang {lang}")
        return jsonify({"ok": True, "session": sid, "lang": lang, "outputs": outputs})
    except TimeoutError:
        return jsonify({"ok": False, "error": _timeout_msg(lang), "timeout": True}), 408
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc), "restart": True}), 410


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
            for ln in str(legacy).splitlines():
                problem = validate_line(ln)
                if problem:
                    return jsonify({"ok": False, "error": problem}), 400
            if not INTERP_BIN.is_file():
                return jsonify({"ok": False, "error": _missing_bin_msg()}), 500
            results = run_interpreter(str(legacy), lang)
            return jsonify({"ok": True, "results": results, "outputs": results})
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": _timeout_msg(lang)}), 408

    line = data.get("line")
    if line is None:
        # 兼容 {lines: [...]}：按顺序发送
        raw_lines = data.get("lines") or []
        if not isinstance(raw_lines, list) or not raw_lines:
            return jsonify({"ok": False, "error": "empty request"}), 400
    else:
        raw_lines = [line]

    # 会话协议每行一个哨兵：必须把每个值拆成单行再逐条发送，
    # 否则多行输入会让后续请求读到上一条命令残留的输出。
    # The session protocol emits one sentinel per line, so split every value
    # into single lines; otherwise a multi-line value leaves stale output queued.
    lines: list[str] = []
    for ln in raw_lines:
        text = str(ln)
        parts = text.splitlines()
        lines.extend(parts if parts else [text])

    for ln in lines:
        problem = validate_line(ln)
        if problem:
            return jsonify({"ok": False, "error": problem}), 400

    sid_in = data.get("session")
    try:
        sid, interp = get_session(sid_in, lang, create=sid_in is None)
        if sid is None or interp is None:
            return jsonify({
                "ok": False,
                "error": "会话已过期，正在重建 / session expired; rebuilding",
                "restart": True,
            }), 410
        outputs: list[dict] = []
        for ln in lines:
            outputs.extend(interp.send(ln))
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
        # 解释器进程已退出，前端应重建会话并回放历史
        # The interpreter process is gone; the client should rebuild + replay.
        return jsonify({"ok": False, "error": str(exc), "restart": True}), 410
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 400


def _missing_bin_msg() -> str:
    return f"未找到解释器 Not found: {INTERP_BIN}。请先运行 build.bat / build.sh。Run build first."


def _timeout_msg(lang: str) -> str:
    secs = f"{EVAL_TIMEOUT:g}"
    if lang == "en":
        return f"Evaluation timed out (>{secs}s); the term may not terminate."
    if lang == "zh":
        return f"计算超时（>{secs}s），表达式可能陷入无限归约。"
    return (f"计算超时 / timed out (>{secs}s)："
            "表达式可能不终止 / the term may not terminate.")


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8081")),
        threaded=True,
    )
