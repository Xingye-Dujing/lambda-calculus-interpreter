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
  GET  /api/health          会话数、解释器、版本与运行状态 / health, version, uptime
  POST /api/share           保存前端状态 -> {id} / store a share payload
  GET  /api/share/<id>      取回前端状态 / fetch a share payload
  POST /api/session         创建会话 {lang?} -> {session} / create a session
  POST /api/eval            执行一行 {session, line} -> {outputs} / run one line
                            兼容旧接口：{code} 一次性执行 -> {results}
                            legacy: {code} runs one-shot -> {results}
                            会话过期返回 410 + restart / expired -> 410 restart
  POST /api/session/<id>/lang    在同一进程内切换语言 / switch language in place
  POST /api/session/<id>/cancel  取消并移除会话 / cancel and drop a session
  DELETE /api/session/<id>      主动结束会话 / end a session

解释器路径按以下顺序解析（可用环境变量覆盖）:
Interpreter lookup order (overridable by environment variables):
  LAMBDA_INTERP_BIN                 直接指定可执行文件 / explicit binary
  LAMBDA_INTERP_DIR/extension[.exe] 指定目录 / directory
  <repo>/extension[.exe]            仓库内本地运行 / inside the repo
  /opt/lambda-calculus-interpreter/ 线上部署 / production deployment
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
from pathlib import Path

from flask import (Flask, Response, g, has_request_context, jsonify, request,
                   send_from_directory, stream_with_context)
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

APP_DIR = (Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "web"
           if getattr(sys, "frozen", False)
           else Path(__file__).resolve().parent)
RS = "\x1e"                     # 与前端的记录分隔符保持一致 / keep in sync with the frontend
# 环境变量可能是 0 或负数；统一夹到可用范围，避免 queue/sleep 收到非法值
# Env values may be zero or negative; clamp them so queue/sleep never see bad values.
EVAL_TIMEOUT = max(0.1, float(os.environ.get("LAMBDA_EVAL_TIMEOUT", "10")))
SESSION_IDLE = max(1.0, float(os.environ.get("LAMBDA_SESSION_IDLE", "1800")))
MAX_SESSIONS = max(0, int(os.environ.get("LAMBDA_MAX_SESSIONS", "32")))
ALLOWED_LANGS = {"zh", "en", "both"}
SHARE_TTL = max(0.0, float(os.environ.get("LAMBDA_SHARE_TTL", "604800")))   # 7 days
MAX_SHARES = max(0, int(os.environ.get("LAMBDA_MAX_SHARES", "500")))
MAX_SHARE_BYTES = 64 * 1024
# 分享短链的持久化文件；设为 off 可恢复纯内存模式
# Persistence file for short share links; set to off for memory-only mode.
SHARE_DB = os.environ.get("LAMBDA_SHARE_DB", str(APP_DIR / "shares.json"))
# 限制请求体大小，避免公开部署时一个巨大请求耗尽内存
# Cap the request body so a huge request cannot exhaust memory in production.
MAX_BODY = max(1024, int(os.environ.get("LAMBDA_MAX_BODY", str(1024 * 1024))))
# 可选的每 IP 每分钟请求上限；0 表示关闭（默认关闭，避免影响本地与测试）
# Optional per-IP requests/minute cap; 0 disables it (default, so local/tests are unaffected).
RATE_LIMIT = max(0, int(os.environ.get("LAMBDA_RATE_LIMIT", "0")))
# 可选的表达式节点上限，传给解释器的 --max-term-size
# Optional AST node cap forwarded to the interpreter as --max-term-size.
MAX_TERM_SIZE = os.environ.get("LAMBDA_MAX_TERM_SIZE", "").strip()

# 分享载荷 code 的行数上限，与字节上限一起约束短链状态的大小
# Line cap for share code; together with the byte cap it bounds short-link state.
MAX_SHARE_LINES = 200
# 后台回收线程的执行间隔（秒）
# Interval in seconds between background reaper sweeps.
REAPER_INTERVAL = 60.0
# 速率桶数量上限，避免大量来源 IP 让字典无限增长
# Cap the bucket map so many source IPs cannot grow it without bound.
RATE_BUCKET_MAX = 4096
RATE_BUCKET_IDLE = 120.0
# 进程启动时刻（单调时钟），用于 /api/health 的 uptime
# Process start on a monotonic clock, used for /api/health uptime.
_PROCESS_START = time.monotonic()
_rate_lock = threading.Lock()
_rate_buckets: dict[str, tuple[float, float]] = {}


def _rate_ok() -> bool:
    """Token bucket per client IP; disabled when RATE_LIMIT <= 0."""
    if RATE_LIMIT <= 0:
        return True
    ip = request.remote_addr or "unknown"
    now = time.monotonic()
    rate = RATE_LIMIT / 60.0
    with _rate_lock:
        if len(_rate_buckets) > RATE_BUCKET_MAX:
            cutoff = now - RATE_BUCKET_IDLE
            for key in [k for k, v in _rate_buckets.items() if v[1] < cutoff]:
                _rate_buckets.pop(key, None)
            while len(_rate_buckets) > RATE_BUCKET_MAX:
                oldest = min(_rate_buckets, key=lambda k: _rate_buckets[k][1])
                _rate_buckets.pop(oldest, None)
        tokens, last = _rate_buckets.get(ip, (float(RATE_LIMIT), now))
        tokens = min(float(RATE_LIMIT), tokens + (now - last) * rate)
        if tokens < 1.0:
            _rate_buckets[ip] = (tokens, now)
            return False
        _rate_buckets[ip] = (tokens - 1.0, now)
    return True
# 版本号来自仓库根目录的 VERSION 文件
# Version is read from the VERSION file at the repository root.
VERSION_FILE = APP_DIR.parent / "VERSION"

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
        return INTERP_CWD
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
                # 解释器以 INTERP_CWD 为工作目录，相对路径必须按它解析后再检查是否在 root 内
                # The interpreter runs with cwd=INTERP_CWD, so resolve relative paths
                # against that (not root) before checking confinement.
                target = INTERP_CWD / target
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
# 解释器的工作目录；桌面版指向可写的用户目录，普通 Web 部署仍是二进制所在目录
# Interpreter working directory; the desktop build points it at a writable user
# directory, while a normal web deployment keeps the binary's directory.
INTERP_CWD = Path(os.environ.get("LAMBDA_INTERP_CWD", str(INTERP_DIR))).expanduser()
try:
    INTERP_CWD.mkdir(parents=True, exist_ok=True)
except OSError:
    INTERP_CWD = INTERP_DIR

# 与 extension.hs 中 initEnv 保持一致
PRELUDE = [
    "TRUE", "FALSE", "NOT", "AND", "OR", "XOR", "NAND", "IF",
    "I", "K", "S", "B", "C", "W",
    "ZERO", "ONE", "TWO", "THREE", "SUCC", "PLUS", "MULT",
    "EXP", "PRED", "SUB", "ISZERO", "LEQ", "EQ",
    "MIN", "MAX", "DIV", "MOD",
    "PAIR", "FST", "SND", "NIL", "CONS", "HEAD", "TAIL",
    "APPEND", "REV", "LENGTH", "MAP", "FILTER", "FOLD", "RANGE", "ZIP", "Y",
]

app = Flask(__name__, static_folder=None, static_url_path=None)
app.config["MAX_CONTENT_LENGTH"] = MAX_BODY


# ---------------------------------------------------------------------------
# 轻量结构化日志 / lightweight structured logging
# ---------------------------------------------------------------------------
class _RequestIdFilter(logging.Filter):
    """把 flask.g 里的请求 id 注入每条日志
    Attach the request id from flask.g to every log record."""

    def filter(self, record):
        record.request_id = getattr(g, "request_id", "-") if has_request_context() else "-"
        return True


log = logging.getLogger("lambda.web")
if not log.handlers:
    _log_handler = logging.StreamHandler()
    _log_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] [rid=%(request_id)s] %(message)s"))
    _log_handler.addFilter(_RequestIdFilter())
    log.addHandler(_log_handler)
_log_level = os.environ.get("LAMBDA_LOG_LEVEL", "INFO").upper()
log.setLevel(_log_level if _log_level in (
    "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL") else "INFO")
log.propagate = False


@app.before_request
def _bind_request_id():
    # 继承上游的 X-Request-ID，缺失时生成一个短 id，并放入 flask.g 供日志使用
    # Inherit an upstream X-Request-ID or mint a short one, and store it in
    # flask.g so log records can carry it.
    rid = re.sub(r"[^A-Za-z0-9._:-]", "", request.headers.get("X-Request-ID") or "")[:64]
    g.request_id = rid or uuid.uuid4().hex[:12]


@app.after_request
def _echo_request_id(resp):
    # 把请求 id 写回响应头，便于前端与日志关联
    # Echo the request id back in the response for log correlation.
    rid = getattr(g, "request_id", "")
    if rid:
        resp.headers["X-Request-ID"] = rid
    return resp


# ---------------------------------------------------------------------------
# 统一 JSON 错误响应 / uniform JSON error responses
# ---------------------------------------------------------------------------
# code 词表与解释器侧保持一致；textZh / textEn 分别是中英文案
# The code vocabulary matches the interpreter; textZh / textEn are the locales.
_ERROR_TEXT = {
    "parse_error": ("语法解析失败，输入无法解析",
                    "Parse error: the input could not be parsed"),
    "unknown_command": ("未知命令，无法识别该指令",
                        "Unknown command: the command was not recognized"),
    "not_found": ("未找到请求的资源或会话",
                  "The requested resource or session was not found"),
    "load_error": ("加载失败，路径不合法或文件不可用",
                   "Load error: the path is invalid or the file is unavailable"),
    "timeout": ("计算超时，表达式可能不终止",
                "Evaluation timed out; the term may not terminate"),
    "session_expired": ("会话已过期，请重建会话并回放历史",
                        "Session expired; rebuild the session and replay history"),
    "bad_request": ("请求无效，参数不合法",
                    "Invalid request: the parameters are not valid"),
    "payload_too_large": ("请求体过大，超出允许的大小",
                          "Request payload too large"),
    "internal": ("服务器内部错误",
                 "Internal server error"),
    "cancelled": ("会话已取消",
                  "The session was cancelled"),
}

# 其余 HTTP 异常沿用原生状态码，映射到同一套 code 词表
# Other HTTP exceptions keep their native status and map to the same codes.
_HTTP_ERROR_CODE = {
    400: "bad_request",
    404: "not_found",
    405: "bad_request",
    408: "timeout",
    410: "session_expired",
    413: "payload_too_large",
    500: "internal",
}


def api_error(message, status, code, **extra):
    """返回统一 JSON 错误体，附带中英文案与可选的兼容字段
    Return a uniform JSON error body with bilingual text and optional fields."""
    text_zh, text_en = _ERROR_TEXT.get(code, (message, message))
    body = {
        "ok": False,
        "error": message,
        "code": code,
        "textZh": text_zh,
        "textEn": text_en,
    }
    body.update(extra)
    resp = jsonify(body)
    resp.status_code = status
    return resp


def _json_body():
    # 大小守卫复用 MAX_CONTENT_LENGTH（回退到 MAX_BODY），并保留 force/silent 的宽容解析
    # Reuse MAX_CONTENT_LENGTH (falling back to MAX_BODY) as the size guard while
    # keeping the tolerant force/silent JSON parsing.
    limit = app.config.get("MAX_CONTENT_LENGTH") or MAX_BODY
    if request.content_length is not None and request.content_length > limit:
        raise RequestEntityTooLarge()
    return request.get_json(force=True, silent=True)


@app.errorhandler(413)
def _err_413(exc):
    return api_error("请求体过大 / request payload too large", 413,
                     "payload_too_large")


@app.errorhandler(404)
def _err_404(exc):
    return api_error("未找到资源 / resource not found", 404, "not_found")


@app.errorhandler(Exception)
def _err_any(exc):
    # 让 413/404/500 等一律返回 JSON 而非 Flask 默认的 HTML 页面
    # Always answer with JSON instead of Flask's default HTML error pages.
    if isinstance(exc, HTTPException):
        status = exc.code or 500
        return api_error(exc.description or "", status,
                         _HTTP_ERROR_CODE.get(status, "internal"))
    log.exception("unhandled error / 未处理的服务器异常: %s", exc)
    return api_error("服务器内部错误 / internal server error", 500, "internal")


# ---------------------------------------------------------------------------
# 常驻解释器 / persistent interpreter
# ---------------------------------------------------------------------------
def _hidden_process_kwargs() -> dict:
    """Keep the bundled interpreter from opening a console window on Windows.

    PyInstaller's --windowed hides the desktop app's console, but the spawned
    `extension.exe` is a console-subsystem program and would otherwise flash a
    black window for every session.
    """
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }


class Interpreter:
    """一个 `extension --batch --json` 子进程 + 一个读线程"""

    def __init__(self, lang: str = "both"):
        self.alive = True
        self._q: queue.Queue = queue.Queue()
        # 流式求值的逐行通道：仅在 send_stream 激活时写入
        # Per-line channel used only while send_stream is active.
        self._stream_q: queue.Queue = queue.Queue()
        self._streaming = False
        self._lock = threading.Lock()
        env = {**os.environ, "TERM": "dumb"}
        env.pop("LAMBDA_INTERP_BIN", None)
        args = [str(INTERP_BIN), "--batch", "--json", "--lang", lang]
        if MAX_TERM_SIZE.isdigit() and int(MAX_TERM_SIZE) > 0:
            args += ["--max-term-size", MAX_TERM_SIZE]
        self.proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=str(INTERP_CWD),
            env=env,
            bufsize=0,
            **_hidden_process_kwargs(),
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
                    if self._streaming:
                        # 流式请求逐行接收；整批结果不再进入 _q
                        # A streaming request consumes lines; the batch skips _q.
                        self._stream_q.put(None)
                    else:
                        self._q.put(buf)
                    buf = []
                elif line.strip():
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        item = {"kind": "info", "text": line.rstrip()}
                    buf.append(item)
                    if self._streaming:
                        self._stream_q.put(item)
        except Exception:  # noqa: BLE001
            pass
        finally:
            if self._streaming:
                self._stream_q.put(None)
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

    def send_stream(self, line: str, timeout: float = EVAL_TIMEOUT):
        """Yield each output object as it arrives, with heartbeats.

        The outer lock is held for the whole evaluation, so one session still
        runs one command at a time. A heartbeat keeps the HTTP connection warm
        even when the reducer emits nothing until it finishes.
        """
        if not self.alive:
            raise TimeoutError("session is dead")
        with self._lock:
            # 丢弃上一次流式请求可能残留的对象 / drain stale stream objects
            while True:
                try:
                    self._stream_q.get_nowait()
                except queue.Empty:
                    break
            self._streaming = True
            started = time.monotonic()
            try:
                self.proc.stdin.write((line + "\n").encode("utf-8"))
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self._streaming = False
                self.kill()
                raise RuntimeError(f"interpreter pipe closed: {exc}") from exc
            try:
                while True:
                    try:
                        item = self._stream_q.get(timeout=5.0)
                    except queue.Empty:
                        elapsed = time.monotonic() - started
                        if elapsed > timeout:
                            self.kill()
                            raise TimeoutError("evaluation timeout") from None
                        yield {"kind": "heartbeat", "elapsedMs": int(elapsed * 1000)}
                        continue
                    if item is None:
                        if not self.alive:
                            raise RuntimeError("interpreter exited")
                        break
                    yield item
            finally:
                self._streaming = False

    def kill(self) -> None:
        # 先标记失效，再回收子进程，避免留下僵尸进程与泄漏的文件描述符；
        # 读线程仍是 daemon，不在此处 join
        # Mark the session dead first, then reap the child so no zombie process
        # or leaked file descriptor remains. The reader thread stays a daemon.
        self.alive = False
        try:
            self.proc.kill()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass
        # 逐个关闭管道，任一失败都不影响其余关闭
        # Close each pipe independently so one failure cannot skip the others.
        for pipe in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            try:
                if pipe is not None:
                    pipe.close()
            except Exception:  # noqa: BLE001
                pass
        log.debug("interpreter killed / 解释器进程已终止")


_sessions: dict[str, dict] = {}
_sessions_lock = threading.Lock()

# 短链分享：保存前端状态 JSON，返回一个短 id
# Short share links: keep the client state JSON server-side under a short id.
_shares: dict[str, dict] = {}
_shares_lock = threading.Lock()


def _share_db_path() -> Path | None:
    raw = (SHARE_DB or "").strip()
    if not raw or raw.lower() in ("off", "0", "none", "memory"):
        return None
    return Path(raw).expanduser()


def _load_shares() -> None:
    path = _share_db_path()
    if path is None or not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("share store unreadable / 分享存储无法读取: %s", exc)
        return
    if not isinstance(data, dict):
        return
    now = time.time()
    with _shares_lock:
        for sid, entry in data.items():
            if not isinstance(entry, dict):
                continue
            created = entry.get("created")
            payload = entry.get("payload")
            if isinstance(created, (int, float)) and isinstance(payload, dict):
                if now - created <= SHARE_TTL:
                    _shares[sid] = {"payload": payload, "created": float(created)}


def _save_shares_locked() -> None:
    path = _share_db_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(_shares, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("share store write failed / 分享存储写入失败: %s", exc)


_load_shares()


def _prune_shares() -> None:
    now = time.time()
    changed = False
    with _shares_lock:
        stale = [k for k, v in _shares.items() if now - v["created"] > SHARE_TTL]
        for k in stale:
            _shares.pop(k, None)
            changed = True
        while len(_shares) > MAX_SHARES:
            oldest = min(_shares, key=lambda k: _shares[k]["created"])
            _shares.pop(oldest, None)
            changed = True
        if changed:
            _save_shares_locked()


# code 会被前端逐条 exec，只放行无害内容：表达式、定义、注释与少量设置命令
# The client exec's code line by line, so allow only harmless content:
# expressions, definitions, comments and a few setting commands.
_SAFE_SHARE_SETTINGS = frozenset({":lang", ":strategy", ":steps", ":eta", ":fast"})

# 控制/格式/代理/私有/行段分隔符字符可能让 splitlines 拆行或绕过冒号检查
# Control, format, surrogate, private-use and line/paragraph separator
# characters can split lines or slip past the colon check, so reject them.
_UNSAFE_CHAR_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Zl", "Zp"})


def is_safe_share_command(line: str) -> bool:
    """校验分享 code 的单行，堵住命令注入面
    Validate one line of share code; close the command injection surface."""
    if not isinstance(line, str):
        return False
    # 拒绝控制字符、记录分隔符、BOM / 零宽字符与 Unicode 行段分隔符；制表符无害
    # Reject controls, the record separator, BOM/zero-width characters and
    # Unicode line/paragraph separators; a tab is harmless.
    for ch in line:
        if ch != "\t" and unicodedata.category(ch) in _UNSAFE_CHAR_CATEGORIES:
            return False
    stripped = line.strip()
    # 空行与 -- / # 注释行由解释器忽略，属于无害内容
    # Blank lines and -- / # comments are ignored by the interpreter.
    if not stripped or stripped.startswith("--") or stripped.startswith("#"):
        return True
    # 以 : 开头的命令只允许白名单里的无害设置项，其余一律拒绝，
    # 特别是 :load / :save / :reset / :q / :del / :begin / :step / :run /
    # :end / :env / :help / :let 等
    # Colon commands are allowed only from the harmless settings whitelist;
    # everything else (:load, :save, :reset, :q, :del, :begin, :step, :run,
    # :end, :env, :help, :let and so on) is rejected.
    if stripped.startswith(":"):
        head = stripped.split(None, 1)[0].lower()
        return head in _SAFE_SHARE_SETTINGS
    # 其余视为纯表达式或 name = expr / rec name = expr 定义
    # Everything else is a pure expression or a name = expr / rec name = expr
    # definition.
    return True


def _valid_share(payload) -> bool:
    if not isinstance(payload, dict):
        return False
    code = payload.get("code")
    if not isinstance(code, list) or not all(isinstance(x, str) for x in code):
        return False
    # 行数上限 + 逐行命令白名单，防止写入时可注入的载荷被后续 exec
    # Line cap plus a per-line whitelist stop an injectable payload at write time.
    if len(code) > MAX_SHARE_LINES:
        return False
    if not all(is_safe_share_command(x) for x in code):
        return False
    try:
        raw = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        return False
    return len(raw.encode("utf-8")) <= MAX_SHARE_BYTES


def _prune_sessions() -> None:
    now = time.time()
    doomed: list[tuple[str, dict]] = []
    with _sessions_lock:
        stale = [sid for sid, s in _sessions.items()
                 if now - s["used"] > SESSION_IDLE or not s["interp"].alive]
        for sid in stale:
            doomed.append((sid, _sessions.pop(sid)))
        # 超出上限时丢弃最久未使用的会话
        # Evict the least recently used session when over the limit.
        while len(_sessions) > MAX_SESSIONS:
            oldest = min(_sessions, key=lambda k: _sessions[k]["used"])
            doomed.append((oldest, _sessions.pop(oldest)))
    # kill 会等待子进程退出，放在锁外，避免阻塞其它会话
    # kill waits for the child process, so run it outside the lock.
    for sid, entry in doomed:
        entry["interp"].kill()
        log.info("session reaped (idle/dead) sid=%s / 空闲会话已回收", sid)


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
        log.info("session created sid=%s lang=%s / 会话已创建", new_sid, lang)
        return new_sid, interp


# ---------------------------------------------------------------------------
# 后台回收线程 / background reaper thread
# ---------------------------------------------------------------------------
def _reaper_loop() -> None:
    # 每 60 秒复用现有惰性清理：_prune_sessions 用 _sessions_lock 保护会话字典，
    # _prune_shares 用 _shares_lock 保护分享字典，两者都不改动惰性清理本身
    # Every 60 s reuse the existing lazy cleanup: _prune_sessions holds
    # _sessions_lock and _prune_shares holds _shares_lock; the lazy path stays.
    while True:
        time.sleep(REAPER_INTERVAL)
        try:
            _prune_sessions()
            _prune_shares()
        except Exception:  # noqa: BLE001
            log.exception("background reaper failed / 后台回收线程异常")


_reaper_lock = threading.Lock()
_reaper_started = False


def _start_reaper() -> None:
    # 模块内只启动一次，避免重复 import / reload 产生多个回收线程
    # Start only once per module so repeated imports do not spawn extra threads.
    global _reaper_started
    with _reaper_lock:
        if _reaper_started:
            return
        _reaper_started = True
        threading.Thread(target=_reaper_loop, name="session-reaper",
                         daemon=True).start()


_start_reaper()


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
        cwd=str(INTERP_CWD),
        env={**os.environ, "TERM": "dumb"},
        **_hidden_process_kwargs(),
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


def _read_version() -> str:
    # 版本取自仓库根目录的 VERSION 文件，缺失时返回 unknown
    # Version comes from the repo-root VERSION file; fall back to "unknown".
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


@app.route("/api/health")
def health():
    _prune_sessions()
    _prune_shares()
    with _sessions_lock:
        count = len(_sessions)
    with _shares_lock:
        share_count = len(_shares)
    # 原有键全部保留；interpreter 现为可执行文件名，完整路径另给 interpreterPath
    # Keep every original key; interpreter is now the executable name and the
    # full path is additionally exposed as interpreterPath.
    return jsonify({
        "ok": True,
        "sessions": count,
        "interpreter": INTERP_BIN.name,
        "available": INTERP_BIN.is_file(),
        "version": _read_version(),
        "uptime": max(0.0, time.monotonic() - _PROCESS_START),
        "shares": share_count,
        "sessionsMax": MAX_SESSIONS,
        "interpreterPath": str(INTERP_BIN),
    })


@app.route("/api/share", methods=["POST"])
def api_share():
    if not _rate_ok():
        return api_error("请求过于频繁 / rate limit exceeded", 429, "rate_limited")
    payload = _json_body()
    if not _valid_share(payload):
        log.warning("share rejected / 分享载荷被拒绝")
        return api_error("分享载荷无效或过大 / invalid or oversized share payload",
                         400, "bad_request")
    _prune_shares()
    sid = uuid.uuid4().hex[:10]
    with _shares_lock:
        _shares[sid] = {"payload": payload, "created": time.time()}
        _save_shares_locked()
    log.info("share stored sid=%s / 分享已保存", sid)
    return jsonify({"ok": True, "id": sid})


@app.route("/api/share/<sid>", methods=["GET"])
def api_share_get(sid):
    _prune_shares()
    with _shares_lock:
        entry = _shares.get(sid)
    if not entry:
        return api_error("分享不存在或已过期 / share not found", 404, "not_found")
    return jsonify({"ok": True, "state": entry["payload"]})


@app.route("/api/session", methods=["POST"])
def api_session():
    if not _rate_ok():
        return api_error("请求过于频繁 / rate limit exceeded", 429, "rate_limited")
    if not INTERP_BIN.is_file():
        log.error("interpreter missing / 解释器缺失: %s", INTERP_BIN)
        return api_error(_missing_bin_msg(), 500, "internal")
    data = _json_body() or {}
    lang = data.get("lang") if data.get("lang") in ALLOWED_LANGS else "both"
    sid, _ = get_session(None, lang)
    return jsonify({"ok": True, "session": sid})


@app.route("/api/session/<sid>/lang", methods=["POST"])
def api_session_lang(sid):
    """在同一个解释器进程内切换语言，避免重建会话
    Switch language inside the same interpreter process (no session rebuild)."""
    data = _json_body() or {}
    lang = data.get("lang") if data.get("lang") in ALLOWED_LANGS else "both"
    _prune_sessions()
    with _sessions_lock:
        entry = _sessions.get(sid)
        if entry:
            entry["used"] = time.time()
    if not entry:
        return api_error("session not found", 410, "session_expired", restart=True)
    try:
        outputs = entry["interp"].send(f":lang {lang}")
        return jsonify({"ok": True, "session": sid, "lang": lang, "outputs": outputs})
    except TimeoutError:
        log.warning("lang timeout sid=%s / 切换语言超时", sid)
        return api_error(_timeout_msg(lang), 408, "timeout", timeout=True)
    except RuntimeError as exc:
        log.warning("lang failed sid=%s: %s / 切换语言失败", sid, exc)
        return api_error(str(exc), 410, "session_expired", restart=True)


@app.route("/api/session/<sid>", methods=["DELETE"])
def api_session_delete(sid):
    with _sessions_lock:
        entry = _sessions.pop(sid, None)
    if entry:
        entry["interp"].kill()
        log.info("session deleted sid=%s / 会话已删除", sid)
    return jsonify({"ok": True})


@app.route("/api/session/<sid>/cancel", methods=["POST"])
def api_session_cancel(sid):
    # 取消会话：立即终止解释器并移除，供前端中止长时间求值
    # Cancel a session: stop its interpreter and drop it so the client can abort
    # a long-running evaluation.
    with _sessions_lock:
        entry = _sessions.pop(sid, None)
    if not entry:
        return api_error("会话不存在或已过期 / session not found or expired",
                         404, "not_found")
    entry["interp"].kill()
    log.info("session cancelled sid=%s / 会话已取消", sid)
    return jsonify({"ok": True, "cancelled": True})


@app.route("/api/eval", methods=["POST"])
def api_eval():
    if not _rate_ok():
        return api_error("请求过于频繁 / rate limit exceeded", 429, "rate_limited")
    data = _json_body() or {}
    lang = data.get("lang") if data.get("lang") in ALLOWED_LANGS else "both"

    # 旧接口：{code} 一次性执行
    legacy = data.get("code") or data.get("expr")
    if legacy is not None:
        try:
            for ln in str(legacy).splitlines():
                problem = validate_line(ln)
                if problem:
                    return api_error(problem, 400, "load_error")
            if not INTERP_BIN.is_file():
                return api_error(_missing_bin_msg(), 500, "internal")
            results = run_interpreter(str(legacy), lang)
            return jsonify({"ok": True, "results": results, "outputs": results})
        except subprocess.TimeoutExpired:
            log.warning("legacy eval timeout / 旧接口执行超时")
            return api_error(_timeout_msg(lang), 408, "timeout", timeout=True)

    line = data.get("line")
    if line is None:
        # 兼容 {lines: [...]}：按顺序发送
        raw_lines = data.get("lines") or []
        if not isinstance(raw_lines, list) or not raw_lines:
            return api_error("empty request", 400, "bad_request")
    else:
        raw_lines = [line]

    # 会话协议每行一个哨兵：必须把每个值拆成单行再逐条发送，
    # 否则多行输入会让后续请求读到上一条命令残留的输出
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
            return api_error(problem, 400, "load_error")

    if not INTERP_BIN.is_file():
        return api_error(_missing_bin_msg(), 500, "internal")

    sid_in = data.get("session")
    try:
        sid, interp = get_session(sid_in, lang, create=sid_in is None)
        if sid is None or interp is None:
            return api_error(
                "会话已过期，正在重建 / session expired; rebuilding",
                410, "session_expired", restart=True)
        outputs: list[dict] = []
        for ln in lines:
            outputs.extend(interp.send(ln))
        with _sessions_lock:
            if sid in _sessions:
                _sessions[sid]["used"] = time.time()
        return jsonify({"ok": True, "session": sid, "outputs": outputs, "results": outputs})
    except TimeoutError:
        log.warning("eval timeout sid=%s / 求值超时", sid_in)
        return api_error(_timeout_msg(lang), 408, "timeout", timeout=True)
    except RuntimeError as exc:
        # 解释器进程已退出，前端应重建会话并回放历史
        # The interpreter process is gone; the client should rebuild + replay.
        log.warning("eval session dead sid=%s: %s / 会话解释器已退出", sid_in, exc)
        return api_error(str(exc), 410, "session_expired", restart=True)
    except Exception as exc:  # noqa: BLE001
        log.exception("eval failed / 求值发生异常: %s", exc)
        return api_error(str(exc), 400, "bad_request")


@app.route("/api/eval/stream", methods=["POST"])
def api_eval_stream():
    """SSE variant of /api/eval.

    The response is a sequence of ``data: <json>`` frames. Reducer output is
    forwarded as soon as the interpreter emits it; a heartbeat every few seconds
    proves the connection is alive, and a final ``done`` frame closes the run.
    """
    if not _rate_ok():
        return api_error("请求过于频繁 / rate limit exceeded", 429, "rate_limited")
    data = _json_body() or {}
    lang = data.get("lang") if data.get("lang") in ALLOWED_LANGS else "both"
    line = data.get("line")
    if line is None:
        return api_error("empty request", 400, "bad_request")
    # 与 /api/eval 一致：空字符串仍然是一条命令，内部空行保留为空命令
    # Match /api/eval: an empty string is one command and inner blank lines stay blank.
    raw = str(line)
    parts = raw.splitlines()
    lines: list[str] = parts if parts else [raw]
    for ln in lines:
        problem = validate_line(ln)
        if problem:
            return api_error(problem, 400, "load_error")
    if not INTERP_BIN.is_file():
        return api_error(_missing_bin_msg(), 500, "internal")

    sid_in = data.get("session")
    sid, interp = get_session(sid_in, lang, create=sid_in is None)
    if sid is None or interp is None:
        return api_error(
            "会话已过期，正在重建 / session expired; rebuilding",
            410, "session_expired", restart=True)

    def sse(obj: dict) -> str:
        return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

    @stream_with_context
    def gen():
        yield sse({"kind": "start", "session": sid, "text": ""})
        try:
            for ln in lines:
                for obj in interp.send_stream(ln):
                    yield sse(obj)
            with _sessions_lock:
                if sid in _sessions:
                    _sessions[sid]["used"] = time.time()
            yield sse({"kind": "done", "ok": True, "session": sid})
        except TimeoutError:
            log.warning("stream eval timeout sid=%s / 流式求值超时", sid)
            yield sse({"kind": "timeout", "ok": False, "timeout": True,
                       "session": sid, "error": _timeout_msg(lang)})
        except RuntimeError as exc:
            log.warning("stream eval session dead sid=%s: %s", sid, exc)
            yield sse({"kind": "expired", "ok": False, "restart": True,
                       "session": sid, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            log.exception("stream eval failed / 流式求值异常: %s", exc)
            yield sse({"kind": "error", "ok": False, "error": str(exc)})

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


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
