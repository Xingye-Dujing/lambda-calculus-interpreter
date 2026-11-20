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

import atexit
import html
import json
from contextlib import contextmanager
import logging
import os
import queue
import re
import signal
import sqlite3
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
# 流式输出队列上限：慢消费者不能让读线程无界堆积对象
# Bound the streaming queue so a slow consumer cannot grow memory without limit.
STREAM_QUEUE_MAX = max(64, int(os.environ.get("LAMBDA_STREAM_QUEUE_MAX", "10000")))
SESSION_IDLE = max(1.0, float(os.environ.get("LAMBDA_SESSION_IDLE", "1800")))
MAX_SESSIONS = max(0, int(os.environ.get("LAMBDA_MAX_SESSIONS", "32")))
ALLOWED_LANGS = {"zh", "en", "both"}
SHARE_TTL = max(0.0, float(os.environ.get("LAMBDA_SHARE_TTL", "604800")))   # 7 days
MAX_SHARES = max(0, int(os.environ.get("LAMBDA_MAX_SHARES", "500")))
MAX_SHARE_BYTES = 64 * 1024
# 分享短链的持久化文件；设为 off 可恢复纯内存模式
# Persistence file for short share links; set to off for memory-only mode.
SHARE_DB = os.environ.get("LAMBDA_SHARE_DB", str(APP_DIR / "shares.json"))
# 会话快照：把回放历史落到磁盘，过期或进程重启后可恢复
# Session snapshots: persist replay history so a session survives expiry/restarts.
SNAPSHOT_TTL = max(0.0, float(os.environ.get("LAMBDA_SNAPSHOT_TTL", str(SESSION_IDLE))))
MAX_SNAPSHOTS = max(0, int(os.environ.get("LAMBDA_MAX_SNAPSHOTS", str(MAX_SESSIONS))))
MAX_SNAPSHOT_LINES = 200
SNAPSHOT_DB = os.environ.get("LAMBDA_SNAPSHOT_DB", str(APP_DIR / "sessions.json"))
# 静态分享页：把一段对话渲染成自包含 HTML
# Static share pages: render a transcript as a self-contained HTML document.
PAGE_DB = os.environ.get("LAMBDA_PAGE_DB", str(APP_DIR / "sharepages.json"))
MAX_PAGES = max(0, int(os.environ.get("LAMBDA_MAX_PAGES", "100")))
MAX_PAGE_LINES = 300
# 策展示例与轻量 token / curated gallery and lightweight tokens
TOKEN_DB = os.environ.get("LAMBDA_TOKEN_DB", str(APP_DIR / "tokens.json"))
GALLERY = [
    {"id": "church", "zh": "邱奇算术", "en": "Church arithmetic",
     "code": "PLUS TWO THREE"},
    {"id": "fixed", "zh": "不动点与递归", "en": "Fixpoint and recursion",
     "code": "Y (\\f.\\n. ISZERO n THEN ONE ELSE MULT n (f (PRED n)))"},
    {"id": "alpha", "zh": "α 等价", "en": "Alpha equivalence",
     "code": ":eq \\a.a , \\b.b"},
    {"id": "convert", "zh": "β 可转换性证明", "en": "Beta-convertibility proof",
     "code": ":prove PLUS ONE TWO , THREE"},
    {"id": "scott", "zh": "Scott 惰性列表", "en": "Scott lazy lists",
     "code": ":encoding scott"},
]
# 策略竞速使用的四种策略，顺序与前端展示一致
# The four strategies used by the race endpoint, in display order.
STRATEGIES = ("applicative", "normal", "cbn", "cbv")
# 限制请求体大小，避免公开部署时一个巨大请求耗尽内存
# Cap the request body so a huge request cannot exhaust memory in production.
MAX_BODY = max(1024, int(os.environ.get("LAMBDA_MAX_BODY", str(1024 * 1024))))
# 可选的每 IP 每分钟请求上限；0 表示关闭（默认关闭，避免影响本地与测试）
# Optional per-IP requests/minute cap; 0 disables it (default, so local/tests are unaffected).
RATE_LIMIT = max(0, int(os.environ.get("LAMBDA_RATE_LIMIT", "0")))
# 是否信任来自回环代理的 X-Forwarded-For；默认关闭，需显式 opt-in
# Whether to trust X-Forwarded-For from a loopback proxy; off by default, opt in explicitly.
TRUST_XFF = os.environ.get("LAMBDA_TRUST_XFF", "").strip().lower() in ("1", "true", "yes", "on")
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
# token 数量上限与空闲时间：/api/token 无需认证，必须限制其增长
# Cap and idle TTL for the unauthenticated /api/token endpoint.
MAX_TOKENS = 4096
TOKEN_IDLE = 24 * 3600.0
# 进程启动时刻（单调时钟），用于 /api/health 的 uptime
# Process start on a monotonic clock, used for /api/health uptime.
_PROCESS_START = time.monotonic()
_rate_lock = threading.Lock()
_rate_buckets: dict[str, tuple[float, float]] = {}


def _client_ip() -> str:
    """Best-effort real client IP, optionally trusting a loopback reverse proxy.

    生产部署经 Caddy(handle_path) 转发时 remote_addr 是 127.0.0.1，所有浏览器
    会共用一个限流桶。只有显式设置 LAMBDA_TRUST_XFF=1 时，才信任来自回环地址的
    X-Forwarded-For。代理通常在已有链尾追加真实客户端地址，因此取最后一段：
    取第一段会被客户端伪造的值控制，从而绕过限流。
    Behind a loopback reverse proxy remote_addr is the proxy and every browser
    would share one bucket. Only when LAMBDA_TRUST_XFF=1 do we trust X-Forwarded-For
    from a loopback peer. Proxies normally append the real client to the chain, so
    use the LAST value; trusting the first lets a client spoof its own bucket key.
    """
    remote = request.remote_addr or "unknown"
    if TRUST_XFF and remote in ("127.0.0.1", "::1"):
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            last = forwarded.rsplit(",", 1)[-1].strip()
            if last:
                return last
    return remote


def _rate_ok(cost: int = 1) -> bool:
    """Token bucket per client IP; disabled when RATE_LIMIT <= 0."""
    if RATE_LIMIT <= 0:
        return True
    cost = max(1, int(cost))
    ip = _client_ip()
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
        if tokens < cost:
            _rate_buckets[ip] = (tokens, now)
            return False
        _rate_buckets[ip] = (tokens - float(cost), now)
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
EDIT_RE = re.compile(r"^:edit(\s|$)")

# 写文件在 Web 端默认关闭，避免公开部署时任意覆盖服务器文件
# Writing files over the web is disabled by default; enable only for local use.
ALLOW_SAVE = os.environ.get("LAMBDA_ALLOW_SAVE", "0").strip().lower() in (
    "1", "true", "yes", "on",
)


def load_root() -> Path | None:
    raw = os.environ.get("LAMBDA_LOAD_ROOT")
    if raw is None:
        return INTERP_CWD.resolve()
    if raw.strip() in ("", "*"):
        return None
    return Path(raw).expanduser().resolve()


def _strip_trailing_comment(text: str) -> str:
    """去掉行尾 -- / # 注释，与解释器的 stripTrailingComment 保持一致
    Strip a trailing -- / # comment, matching the interpreter's rules: the
    marker only starts a comment at the beginning or after whitespace."""
    out = []
    for i, c in enumerate(text):
        if c == "-" and i + 1 < len(text) and text[i + 1] == "-" and (not out or out[-1].isspace()):
            break
        if c == "#" and (not out or out[-1].isspace()):
            break
        out.append(c)
    return "".join(out)


def _check_path(line: str) -> str | None:
    for regex, verb in ((LOAD_RE, "load"), (SAVE_RE, "save")):
        match = regex.match(_strip_trailing_comment(line.strip()))
        if not match:
            continue
        if verb == "save" and not ALLOW_SAVE:
            return (":save 在 Web 端默认关闭 / :save is disabled over the web "
                    "(set LAMBDA_ALLOW_SAVE=1 for local use)")
        root = load_root()
        if root is None:
            return None
        raw = match.group(1).strip().strip('"').strip("'")
        # 拒绝隐藏路径段（.git/.env 等）与非 .lam 文件：加载失败行会回显源文本，
        # 公开部署下读取仓库内任意文件会造成信息泄露
        # Reject hidden segments and non-.lam files: failed loads echo source lines,
        # so reading arbitrary repo files would leak information.
        parts = [p for p in Path(raw).parts if p not in (".", "..")]
        if any(p.startswith(".") for p in parts):
            return (f":{verb} 仅允许非隐藏路径 / :{verb} is restricted "
                    "to paths without hidden segments")
        if Path(raw).suffix.lower() != ".lam":
            return (f":{verb} 仅允许 .lam 文件 / :{verb} is restricted to .lam files")
        try:
            target = Path(raw)
            if not target.is_absolute():
                # 解释器以 INTERP_CWD 为工作目录，相对路径必须按它解析后再检查是否在 root 内
                # The interpreter runs with cwd=INTERP_CWD, so resolve relative paths
                # against that (not root) before checking confinement.
                target = INTERP_CWD / target
            resolved = target.resolve()
            # 用相对 root 的路径再校验隐藏段与后缀：符号链接可以指向 root 内的
            # 隐藏文件（如 .git/config），仅检查原始路径会漏掉这种情况.
            # Re-check on the resolved path relative to root: a symlink could
            # point at a hidden file inside root while the raw path looks clean.
            rel = resolved.relative_to(root)
        except (ValueError, OSError):
            return (f":{verb} 仅允许解释器目录内的路径 / :{verb} is restricted to {root} "
                    "(set LAMBDA_LOAD_ROOT=* to allow any path)")
        if (any(p.startswith(".") for p in rel.parts)
                or resolved.suffix.lower() != ".lam"):
            return (f":{verb} 仅允许非隐藏 .lam 路径 / :{verb} is restricted "
                    "to non-hidden .lam paths")
        return None
    return None


_CLI_ONLY_TEXT = "该命令仅在命令行可用 / this command is only available in the CLI"


def validate_line(line: str) -> tuple[str, str] | None:
    """Validate one web command; returns an error code and message."""
    # 命令必须是真正的单行：换行、回车和 \x1e 哨兵都会破坏“每行一个回复”的协议，
    # 还可能把后半段当成未校验的新命令注入解释器（例如 "1\n:load /etc/passwd"）
    # A command must be a single line: newlines, CR and the \x1e sentinel break the
    # one-reply-per-line protocol and can inject an unverified command (e.g.
    # "1\n:load /etc/passwd" bypasses the :load path check).
    if any(ord(c) < 32 and c != "\t" or c == "\x7f" for c in line):
        return ("bad_request", "命令含非法控制字符 / command contains control characters")
    # Web 会话必须保持存活，且不能让 API 直接拉起服务器上的编辑器
    # A web session must stay alive, and the API must not launch a server editor.
    # 解释器会先剥掉行尾注释再解析命令；这里也必须这么做，否则
    # ":quit -- bye" 会绕过检查并让持久化解释器进程退出.
    # The interpreter strips trailing comments before dispatch; do the same here,
    # otherwise ":quit -- bye" bypasses the check and kills the shared process.
    text = _strip_trailing_comment(line.strip()).strip()
    if text in (":q", ":quit") or EDIT_RE.match(text):
        return ("cli_only", _CLI_ONLY_TEXT)
    problem = _check_path(line)
    if problem:
        return ("load_error", problem)
    return None


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
    "cli_only": ("该命令仅在命令行可用",
                 "This command is only available in the command line"),
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
    "rate_limited": ("请求过于频繁，请稍后再试",
                     "Too many requests; please retry shortly"),
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
    429: "rate_limited",
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


class BadJSONBody(Exception):
    """The request body is valid JSON but not an object."""


@app.errorhandler(BadJSONBody)
def _err_bad_json(exc):
    return api_error("请求体必须是 JSON 对象 / JSON body must be an object",
                     400, "bad_request")


def _json_body():
    # 大小守卫复用 MAX_CONTENT_LENGTH（回退到 MAX_BODY），并保留 force/silent 的宽容解析
    # Reuse MAX_CONTENT_LENGTH (falling back to MAX_BODY) as the size guard while
    # keeping the tolerant force/silent JSON parsing.
    limit = app.config.get("MAX_CONTENT_LENGTH") or MAX_BODY
    if request.content_length is not None and request.content_length > limit:
        raise RequestEntityTooLarge()
    body = request.get_json(force=True, silent=True)
    # 畸形/空 JSON 仍按空对象宽容处理；但列表/数字等合法非对象会让 .get 抛
    # AttributeError 变成 500，这里统一改为 400 bad_request.
    # Malformed/empty JSON stays lenient; a valid non-object would otherwise
    # raise AttributeError and surface as a 500.
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise BadJSONBody()
    return body


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


def _write_all(stream, data: bytes) -> None:
    """Write every byte to a raw (unbuffered) pipe; a single write may be short.

    bufsize=0 makes stdin a raw FileIO whose write() is one os.write() and may
    return a partial count. Large commands (> PIPE_BUF) would otherwise be
    truncated and desynchronise the one-sentinel-per-line protocol.
    """
    view = memoryview(data)
    while view:
        written = stream.write(view)
        if not written:
            raise OSError("short write to interpreter stdin")
        view = view[written:]
    stream.flush()


class Interpreter:
    """一个 `extension --batch --json` 子进程 + 一个读线程"""

    def __init__(self, lang: str = "both"):
        self.alive = True
        self._q: queue.Queue = queue.Queue()
        # 流式求值的逐行通道：仅在 send_stream 激活时写入
        # Per-line channel used only while send_stream is active.
        self._stream_q: queue.Queue = queue.Queue(maxsize=STREAM_QUEUE_MAX)
        self._stream_overflow = False
        self._streaming = False
        # 命令槽用 Condition 做有界等待：流式生成器在 yield 之间不再持有锁，
        # 慢消费者最多让同会话的其他请求等待一个 EVAL_TIMEOUT，之后会话被回收
        # A Condition-based command slot with a bounded wait: the streaming generator
        # no longer holds a lock across yields, so a slow consumer can pin a session
        # for at most one EVAL_TIMEOUT instead of forever.
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._busy = False
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

    def _stream_put(self, item) -> None:
        """Queue a stream item; kill the child on overflow instead of growing forever."""
        try:
            self._stream_q.put_nowait(item)
        except queue.Full:
            self._stream_overflow = True
            log.warning("stream queue overflow, killing interpreter / 流式队列溢出，终止解释器")
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass

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
                        self._stream_put(None)
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
                        self._stream_put(item)
        except Exception:  # noqa: BLE001
            pass
        finally:
            # 读线程结束说明子进程已退出；标记会话不可用，流式请求不会把截断当成成功
            # The reader ending means the child is gone; mark the session dead so a
            # streaming request cannot mistake a truncated reply for success.
            self.alive = False
            if self._streaming:
                self._stream_put(None)
            self._q.put(None)

    def _begin_command(self, timeout: float) -> None:
        """Acquire the command slot, waiting at most ``timeout`` for a stream to end."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._busy:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    # 卡住的流不能无限拖住其他请求：终止会话并让等待者按过期处理
                    # A stuck stream must not block other requests forever: kill the
                    # session so waiters get the normal 410 restart path.
                    self.kill()
                    raise TimeoutError("session busy")
                self._cond.wait(remaining)
            self._busy = True

    def _end_command(self) -> None:
        with self._cond:
            self._busy = False
            self._cond.notify_all()

    def _send_unlocked(self, line: str, timeout: float = EVAL_TIMEOUT) -> list[dict]:
        """Write one command and collect its reply; the caller holds the command slot."""
        try:
            _write_all(self.proc.stdin, (line + "\n").encode("utf-8"))
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

    def send(self, line: str, timeout: float = EVAL_TIMEOUT) -> list[dict]:
        if not self.alive:
            # 已死亡会话不是超时，而是需要重建；用 RuntimeError 映射到 410+restart
            # A dead session is not a timeout but a rebuild signal (410 + restart).
            raise RuntimeError("session is dead")
        self._begin_command(timeout)
        try:
            return self._send_unlocked(line, timeout)
        finally:
            self._end_command()

    def send_many(self, lines: list[str], timeout: float = EVAL_TIMEOUT) -> list[list[dict]]:
        """Send several commands atomically under a single lock acquisition.

        多命令序列（如策略竞速）必须一次持锁发完，避免与同会话的其它请求交错.
        A multi-command sequence (e.g. the strategy race) must hold the lock for
        the whole batch so a concurrent request on the same session cannot splice
        commands in between and desynchronise the replies.
        """
        if not self.alive:
            raise RuntimeError("session is dead")
        self._begin_command(timeout)
        try:
            return [self._send_unlocked(ln, timeout) for ln in lines]
        finally:
            self._end_command()

    def send_stream(self, line: str, timeout: float = EVAL_TIMEOUT):
        """Yield each output object as it arrives, with heartbeats.

        The command slot is held only between yields, and other callers wait with
        a bounded timeout, so one stalled HTTP consumer cannot pin the session.
        """
        if not self.alive:
            raise RuntimeError("session is dead")
        self._begin_command(timeout)
        try:
            # 丢弃上一次流式请求可能残留的对象 / drain stale stream objects
            while True:
                try:
                    self._stream_q.get_nowait()
                except queue.Empty:
                    break
            self._streaming = True
            self._stream_overflow = False
            completed = False
            started = time.monotonic()
            try:
                _write_all(self.proc.stdin, (line + "\n").encode("utf-8"))
            except (BrokenPipeError, OSError) as exc:
                self._streaming = False
                self.kill()
                raise RuntimeError(f"interpreter pipe closed: {exc}") from exc
            try:
                while True:
                    # 即使输出持续不断也要检查总超时，不能只在 queue.Empty 分支检查
                    # Enforce the wall-clock deadline on every iteration, not only
                    # when no output arrives; a chatty command must not run forever.
                    if time.monotonic() - started > timeout:
                        self.kill()
                        raise TimeoutError("evaluation timeout")
                    try:
                        # 心跳间隔不超过剩余超时，避免长命令超过 EVAL_TIMEOUT 才被中止
                        # Never wait past the deadline; a heartbeat must not overshoot.
                        remaining = timeout - (time.monotonic() - started)
                        item = self._stream_q.get(timeout=max(0.05, min(5.0, remaining)))
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
                        completed = True
                        break
                    yield item
            finally:
                self._streaming = False
                # 客户端中途断开时命令仍在运行，输出无法再对齐；直接回收会话
                # On an early client disconnect kill the session instead of letting
                # the next command read stale results or burn CPU.
                if not completed and self.alive:
                    self.kill()
        finally:
            self._end_command()

    def kill(self) -> None:
        # 先标记失效并释放命令槽，等待中的请求能立刻走 410，而不是一直卡在这里
        # Mark dead and release the command slot so waiters take the 410 path at once.
        with self._cond:
            self.alive = False
            self._busy = False
            self._cond.notify_all()
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


def _kill_all_sessions() -> None:
    """Stop every interpreter process; used when the server shuts down."""
    with _sessions_lock:
        entries = list(_sessions.values())
        _sessions.clear()
    for entry in entries:
        try:
            entry["interp"].kill()
        except Exception:  # noqa: BLE001
            pass


def _on_shutdown_signal(signum, frame):  # noqa: ANN001
    # 退出前先回收子进程，否则解释器会在后台继续跑到步数上限
    # Reap the children first; otherwise an interpreter keeps running in the
    # background until it hits its step limit.
    _kill_all_sessions()
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


atexit.register(_kill_all_sessions)
for _sig_name in ("SIGTERM", "SIGINT"):
    _sig = getattr(signal, _sig_name, None)
    if _sig is None:
        continue
    try:
        signal.signal(_sig, _on_shutdown_signal)
    except (ValueError, OSError):
        pass  # 只能在主线程安装信号处理器 / only the main thread may install one

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
    # 文件可能被手工改大；只保留未过期的最新若干条，避免启动时无限增长
    # The file may be edited by hand; keep only the newest unexpired entries so
    # startup memory stays bounded.
    candidates: list[tuple[float, str, dict]] = []
    for sid, entry in data.items():
        if not isinstance(entry, dict) or not isinstance(sid, str):
            continue
        created = entry.get("created")
        payload = entry.get("payload")
        if (isinstance(created, (int, float)) and isinstance(payload, dict)
                and now - created <= SHARE_TTL and _valid_share(payload)):
            candidates.append((float(created), sid, payload))
    candidates.sort(key=lambda item: item[0], reverse=True)
    with _shares_lock:
        for created, sid, payload in candidates[:MAX_SHARES]:
            _shares[sid] = {"payload": payload, "created": created}


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


# 会话快照与分享短链使用同样的原子落盘方式，但存的是命令回放历史
# Session snapshots use the same atomic write as shares, but store replay history.
_snapshots: dict[str, dict] = {}
_snapshots_lock = threading.Lock()
# 串行化快照的读-改-写序列，避免并发 eval 互相覆盖历史
# Serialize snapshot read-modify-write sequences so concurrent evals cannot overwrite each other.
_snapshot_rmw_lock = threading.RLock()


def _snapshot_db_path() -> Path | None:
    raw = (SNAPSHOT_DB or "").strip()
    if not raw or raw.lower() in ("off", "0", "none", "memory"):
        return None
    return Path(raw).expanduser()


def _use_sqlite() -> bool:
    raw = (SNAPSHOT_DB or "").strip().lower()
    return raw.endswith((".sqlite", ".sqlite3", ".db"))


@contextmanager
def _sql_conn():
    # 每次调用都提交并关闭连接，避免长驻服务累积文件描述符
    # Commit and close on every use so a long-running server cannot leak handles.
    path = _snapshot_db_path()
    assert path is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS snapshots ("
            "id TEXT PRIMARY KEY, code TEXT NOT NULL, lang TEXT NOT NULL, "
            "created REAL NOT NULL, used REAL NOT NULL, name TEXT NOT NULL DEFAULT '', "
            "owner TEXT)"
        )
        # 旧库可能还没有 owner 列；补齐后旧行保持 ownerless（向后兼容）
        # Older databases may lack the owner column; add it and leave old rows
        # ownerless for backwards compatibility.
        cols = {row[1] for row in conn.execute("PRAGMA table_info(snapshots)").fetchall()}
        if "owner" not in cols:
            conn.execute("ALTER TABLE snapshots ADD COLUMN owner TEXT")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _sql_get(sid: str) -> dict | None:
    try:
        with _sql_conn() as conn:
            row = conn.execute(
                "SELECT code, lang, created, used, name, owner FROM snapshots WHERE id=?",
                (sid,),
            ).fetchone()
    except sqlite3.Error as exc:
        log.warning("snapshot sqlite read failed / SQLite 快照读取失败: %s", exc)
        return None
    if not row:
        return None
    try:
        code = json.loads(row[0])
    except (TypeError, ValueError):
        return None
    if not isinstance(code, list) or not all(isinstance(x, str) for x in code):
        return None
    return {"code": code[-MAX_SNAPSHOT_LINES:], "lang": row[1],
            "created": float(row[2]), "used": float(row[3]), "name": row[4] or "",
            "owner": row[5] or None}


def _sql_put(sid: str, entry: dict) -> bool:
    try:
        with _sql_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO snapshots (id, code, lang, created, used, name, owner) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (sid, json.dumps(entry["code"], ensure_ascii=False), entry["lang"],
                 entry["created"], entry["used"], entry.get("name", ""),
                 entry.get("owner") or None),
            )
        return True
    except sqlite3.Error as exc:
        log.warning("snapshot sqlite write failed / SQLite 快照写入失败: %s", exc)
        return False


def _sql_all() -> dict[str, dict]:
    try:
        with _sql_conn() as conn:
            rows = conn.execute(
                "SELECT id, code, lang, created, used, name, owner FROM snapshots"
            ).fetchall()
    except sqlite3.Error as exc:
        log.warning("snapshot sqlite scan failed / SQLite 快照扫描失败: %s", exc)
        return {}
    out: dict[str, dict] = {}
    for sid, raw, lang, created, used, name, owner in rows:
        try:
            code = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(code, list) and all(isinstance(x, str) for x in code):
            out[sid] = {"code": code[-MAX_SNAPSHOT_LINES:], "lang": lang,
                        "created": float(created), "used": float(used), "name": name or "",
                        "owner": owner or None}
    return out


def _owner_sql(owner: str | None) -> tuple[str, tuple]:
    """SQL 谓词：旧的无主快照对所有客户端可见，其余只匹配自己的 owner
    SQL predicate mirroring _owner_allowed for cross-process updates.
    """
    if owner is None:
        return "owner IS NULL", ()
    return "(owner IS NULL OR owner=?)", (owner,)


def _sql_rename(sid: str, name: str, owner: str | None, used: float) -> bool:
    clause, args = _owner_sql(owner)
    try:
        with _sql_conn() as conn:
            cur = conn.execute(
                f"UPDATE snapshots SET name=?, used=? WHERE id=? AND {clause}",
                (name, used, sid, *args),
            )
            return cur.rowcount > 0
    except sqlite3.Error as exc:
        log.warning("snapshot sqlite rename failed / SQLite 快照重命名失败: %s", exc)
        return False


def _sql_delete(sid: str, owner: str | None = None) -> None:
    clause, args = _owner_sql(owner)
    try:
        with _sql_conn() as conn:
            conn.execute(f"DELETE FROM snapshots WHERE id=? AND {clause}", (sid, *args))
    except sqlite3.Error as exc:
        log.warning("snapshot sqlite delete failed / SQLite 快照删除失败: %s", exc)


def _load_snapshots() -> None:
    if _use_sqlite():
        with _sql_conn():
            pass
        return
    path = _snapshot_db_path()
    if path is None or not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("snapshot store unreadable / 快照存储无法读取: %s", exc)
        return
    if not isinstance(data, dict):
        return
    now = time.time()
    candidates: list[tuple[float, str, dict]] = []
    for sid, entry in data.items():
        if not isinstance(sid, str) or not isinstance(entry, dict):
            continue
        code = entry.get("code")
        used = entry.get("used")
        created = entry.get("created")
        lang = entry.get("lang")
        if (not isinstance(code, list) or not all(isinstance(x, str) for x in code)
                or not isinstance(used, (int, float)) or not isinstance(created, (int, float))
                or not isinstance(lang, str) or lang not in ALLOWED_LANGS
                or now - used > SNAPSHOT_TTL):
            continue
        name = entry.get("name", "")
        if not isinstance(name, str):
            name = ""
        # owner 也必须持久化，否则重启后所有快照都变成公开可见
        # Persist the owner too, or every snapshot becomes public after a restart.
        owner = entry.get("owner")
        if not isinstance(owner, str):
            owner = None
        candidates.append((float(used), sid,
                           {"code": code[-MAX_SNAPSHOT_LINES:], "lang": lang,
                            "created": float(created), "used": float(used), "name": name,
                            "owner": owner}))
    candidates.sort(key=lambda item: item[0], reverse=True)
    with _snapshots_lock:
        for _, sid, entry in candidates[:MAX_SNAPSHOTS]:
            _snapshots[sid] = entry


def _save_snapshots_locked() -> bool:
    path = _snapshot_db_path()
    if path is None:
        return True
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(_snapshots, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError as exc:
        log.warning("snapshot store write failed / 快照存储写入失败: %s", exc)
        return False


_load_snapshots()


def _snapshot_all() -> dict[str, dict]:
    if _use_sqlite():
        return _sql_all()
    with _snapshots_lock:
        return {k: dict(v) for k, v in _snapshots.items()}


def _snapshot_get(sid: str) -> dict | None:
    if _use_sqlite():
        return _sql_get(sid)
    with _snapshots_lock:
        entry = _snapshots.get(sid)
        return dict(entry) if entry else None


def _snapshot_put(sid: str, entry: dict) -> bool:
    if _use_sqlite():
        return _sql_put(sid, entry)
    with _snapshots_lock:
        _snapshots[sid] = entry
        return _save_snapshots_locked()


def _snapshot_remove(sid: str, owner: str | None = None) -> None:
    if _use_sqlite():
        _sql_delete(sid, owner)
        return
    with _snapshots_lock:
        entry = _snapshots.get(sid)
        if entry is not None and _owner_allowed(entry, owner):
            _snapshots.pop(sid, None)
            _save_snapshots_locked()


def _snapshot_rename(sid: str, name: str, owner: str | None) -> bool:
    """改名：SQLite 下用带 owner 条件的单条 UPDATE，跨进程也安全
    Rename atomically; the SQLite path carries the owner in the UPDATE.
    """
    used = time.time()
    if _use_sqlite():
        return _sql_rename(sid, name, owner, used)
    with _snapshot_rmw_lock:
        entry = _snapshot_get(sid)
        if not _owner_allowed(entry, owner):
            return False
        entry["name"] = name
        entry["used"] = used
        return _snapshot_put(sid, entry)


def _prune_snapshots() -> None:
    now = time.time()
    entries = _snapshot_all()
    stale = [k for k, v in entries.items() if now - v["used"] > SNAPSHOT_TTL]
    while len(entries) - len(stale) > MAX_SNAPSHOTS:
        candidates = [k for k in entries if k not in stale]
        if not candidates:
            break
        stale.append(min(candidates, key=lambda k: entries[k]["used"]))
    for sid in stale:
        _snapshot_remove(sid)


def _snapshot_record(sid: str, lines, lang: str, set_lang: bool = True,
                     owner: str | None = None) -> None:
    """Append successfully evaluated lines to a persistent replay snapshot.

    把成功执行的行追加到可持久化的回放快照中。set_lang=False 用于请求未显式带
    lang 的情况：不能把快照里已有的 en/zh 悄悄改回默认的 both。
    owner 取自会话，写进快照供管理器鉴权；已有快照的所有者不被覆盖。
    """
    if _snapshot_db_path() is None or not isinstance(sid, str):
        return
    if not isinstance(lang, str) or lang not in ALLOWED_LANGS:
        lang = "both"
    if owner is None:
        with _sessions_lock:
            session = _sessions.get(sid)
            owner = session.get("owner") if session else None
    # 整个读-改-写必须持锁，否则两个并发 eval 会基于同一旧快照各自追加，
    # 后写者覆盖先写者
    # RLock 不与 _snapshots_lock 形成环：get/put 各自获取后即释放
    # Hold the whole read-modify-write so two concurrent evals cannot both read the
    # same old snapshot and let the later write clobber the earlier one. RLock does
    # not cycle with _snapshots_lock: get/put each acquire and release it separately.
    with _snapshot_rmw_lock:
        now = time.time()
        entry = _snapshot_get(sid) or {
            "code": [], "lang": lang if lang in ALLOWED_LANGS else "both",
            "created": now, "used": now, "name": "", "owner": owner}
        code = list(entry.get("code", []))
        for ln in lines:
            text = str(ln).strip()
            if text:
                code.append(text)
        # 语言切换要写回已有快照，否则恢复时会沿用旧语言
        # Persist a language switch onto an existing snapshot, or restore uses the
        # stale language. Invalid values leave the stored language untouched.
        if set_lang and lang in ALLOWED_LANGS:
            entry["lang"] = lang
        entry.update({"code": code[-MAX_SNAPSHOT_LINES:], "used": now,
                      "name": entry.get("name", "")})
        _snapshot_put(sid, entry)


# 静态分享页存储 / static share-page storage
_pages: dict[str, dict] = {}
_pages_lock = threading.Lock()


def _page_db_path() -> Path | None:
    raw = (PAGE_DB or "").strip()
    if not raw or raw.lower() in ("off", "0", "none", "memory"):
        return None
    return Path(raw).expanduser()


def _load_pages() -> None:
    path = _page_db_path()
    if path is None or not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("page store unreadable / 页面存储无法读取: %s", exc)
        return
    if not isinstance(data, dict):
        return
    with _pages_lock:
        for pid, entry in data.items():
            if (isinstance(pid, str) and isinstance(entry, dict)
                    and isinstance(entry.get("html"), str)
                    and isinstance(entry.get("created"), (int, float))):
                _pages[pid] = {"html": entry["html"], "created": float(entry["created"])}


def _save_pages_locked() -> None:
    path = _page_db_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(_pages, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("page store write failed / 页面存储写入失败: %s", exc)


_load_pages()


def _prune_pages() -> None:
    now = time.time()
    changed = False
    with _pages_lock:
        stale = [k for k, v in _pages.items() if now - v["created"] > SHARE_TTL]
        for k in stale:
            _pages.pop(k, None)
            changed = True
        while len(_pages) > MAX_PAGES:
            oldest = min(_pages, key=lambda k: _pages[k]["created"])
            _pages.pop(oldest, None)
            changed = True
        if changed:
            _save_pages_locked()


def _render_page(title: str, lines: list[dict], trace: list[dict] | None = None) -> str:
    """Render a bilingual transcript as a self-contained HTML page.
    把双语对话渲染成不依赖外部资源的 HTML 页面。
    """
    esc = html.escape
    rows = []
    for item in lines:
        zh = esc(str(item.get("zh", "")))
        en = esc(str(item.get("en", "")))
        term = item.get("term")
        extra = ("<pre>" + esc(str(term)) + "</pre>") if term else ""
        rows.append(
            '<div class="row"><div class="mark">λ&gt;</div>'
            '<div class="body"><div class="zh">' + zh + '</div>'
            '<div class="en">' + en + '</div>' + extra + '</div></div>'
        )
    body = "\n".join(rows)
    player = ""
    player_script = ""
    if isinstance(trace, list) and trace:
        frames = []
        for s in trace[:500]:
            if not isinstance(s, dict):
                continue
            frames.append(
                '<section class="frame"><h2>' + esc(str(s.get("n", ""))) + ' · ' +
                esc(str(s.get("rule", "β"))) + '</h2><pre>' +
                esc(str(s.get("before", ""))) + '</pre><pre class="after">' +
                esc(str(s.get("after", ""))) + '</pre></section>'
            )
        if frames:
            player = (
                '<section class="trace-player"><h2>Reduction trace / 归约轨迹</h2>'
                '<div class="controls"><button type="button" id="tp-prev">←</button>'
                '<button type="button" id="tp-play">play</button>'
                '<button type="button" id="tp-next">→</button>'
                '<span id="tp-count"></span></div>' +
                '<div id="tp-frames">' + "".join(frames) + '</div></section>'
            )
            player_script = (
                "var f=[].slice.call(document.querySelectorAll('#tp-frames .frame')),i=0,t=null;"
                "function show(){f.forEach(function(x,j){x.classList.toggle('on',j===i)});"
                "document.getElementById('tp-count').textContent=(i+1)+' / '+f.length}show();"
                "document.getElementById('tp-next').onclick=function(){i=(i+1)%f.length;show()};"
                "document.getElementById('tp-prev').onclick=function(){i=(i-1+f.length)%f.length;show()};"
                "document.getElementById('tp-play').onclick=function(){"
                "if(t){clearInterval(t);t=null;this.textContent='play'}else{"
                "var self=this;t=setInterval(function(){i=(i+1)%f.length;show()},1200);"
                "self.textContent='pause'}};"
            )
    return (
        "<!doctype html><html lang=\"zh\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>" + esc(title) + "</title><style>"
        ":root{--bg:#fbfaf7;--fg:#1d1d1b;--dim:#666;--bd:#ddd;--ac:#2f6f4f}"
        "*{box-sizing:border-box}body{margin:0;padding:28px 18px;background:var(--bg);"
        "color:var(--fg);font-family:ui-monospace,Consolas,monospace;line-height:1.65}"
        "main{max-width:860px;margin:auto}h1{font-weight:400;font-size:20px;margin:0 0 6px}"
        ".sub{color:var(--dim);font-size:12px;margin-bottom:20px}"
        ".row{border-bottom:1px dashed var(--bd);padding:10px 0;display:flex;gap:10px}"
        ".mark{color:var(--ac)}.body{white-space:pre-wrap;word-break:break-word;min-width:0}"
        ".en{color:var(--dim);margin-top:4px}.zh+.en{margin-top:4px}"
        "pre{white-space:pre-wrap;word-break:break-word;color:var(--ac);font-size:12px}"
        "body[data-lang=zh] .en,body[data-lang=en] .zh{display:none}"
        "button{background:transparent;border:1px solid var(--bd);border-radius:5px;"
        "color:var(--fg);padding:4px 10px;cursor:pointer;font:inherit}"
        ".trace-player{margin-top:28px;border-top:1px solid var(--bd);padding-top:14px}"
        ".trace-player h2{font-size:14px;font-weight:400}"
        ".trace-player .controls{display:flex;gap:6px;align-items:center;margin-bottom:10px}"
        ".trace-player .frame{display:none}"
        ".trace-player .frame.on{display:block}"
        ".trace-player .frame h2{font-size:12px;color:var(--ac)}"
        ".trace-player .after{border-color:var(--ac)}"
        "#tp-count{color:var(--dim);font-size:12px}"
        "</style></head><body data-lang=\"both\"><main>"
        "<h1>" + esc(title) + "</h1>"
        "<div class=\"sub\">Lambda calculus · <button id=\"lg\" type=\"button\">中 / EN / 双语</button></div>"
        + body + player +
        "</main><script>(function(){var b=document.body,btn=document.getElementById('lg'),"
        "ls=['both','zh','en'],i=0;btn.addEventListener('click',function(){i=(i+1)%3;"
        "b.dataset.lang=ls[i];});" + player_script +
        "})();</script></body></html>"
    )


# 轻量 token 归属与用量 / lightweight token ownership and usage
_tokens: dict[str, dict] = {}
_tokens_lock = threading.Lock()


def _token_db_path() -> Path | None:
    raw = (TOKEN_DB or "").strip()
    if not raw or raw.lower() in ("off", "0", "none", "memory"):
        return None
    return Path(raw).expanduser()


def _load_tokens() -> None:
    path = _token_db_path()
    if path is None or not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("token store unreadable / token 存储无法读取: %s", exc)
        return
    if isinstance(data, dict):
        with _tokens_lock:
            for k, v in data.items():
                if isinstance(k, str) and isinstance(v, dict) and isinstance(v.get("used"), int):
                    _tokens[k] = v


def _prune_tokens_locked() -> bool:
    """在 _tokens_lock 内回收过期/超额 token，返回是否有改动
    Prune stale/overflow tokens under _tokens_lock; report whether we changed it.
    """
    now = time.time()
    before = len(_tokens)
    stale = [k for k, v in _tokens.items()
             if now - v.get("created", 0) > TOKEN_IDLE]
    for k in stale:
        _tokens.pop(k, None)
    while len(_tokens) > MAX_TOKENS:
        oldest = min(_tokens, key=lambda k: _tokens[k].get("created", 0))
        _tokens.pop(oldest, None)
    return len(_tokens) != before


def _prune_tokens() -> None:
    with _tokens_lock:
        if _prune_tokens_locked():
            _save_tokens_locked()


def _save_tokens_locked() -> None:
    path = _token_db_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(_tokens, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("token store write failed / token 存储写入失败: %s", exc)


_load_tokens()


def _token_used(token) -> None:
    if not isinstance(token, str) or _token_db_path() is None:
        return
    with _tokens_lock:
        entry = _tokens.get(token)
        if entry:
            entry["used"] += 1
            _save_tokens_locked()


# 会话所有权：owner 是客户端自己生成并保存在 localStorage 的随机串
# 它把快照绑定到浏览器，避免 /api/snapshots 列举所有人的会话或被任意删除
# 旧数据（无 owner）只给同样不带 owner 的旧客户端访问，保持向后兼容
# Session ownership: a random client-generated token stored in localStorage binds
# snapshots to one browser, so /api/snapshots cannot enumerate or delete other
# users' sessions. Legacy ownerless entries stay visible to ownerless clients.
def _req_lang(data: dict | None = None) -> str:
    """语言字段必须先判类型：数组/对象不可哈希，直接 in set 会抛 500
    Check the type first: unhashable JSON values would raise a 500.
    """
    value = data.get("lang") if data else None
    return value if isinstance(value, str) and value in ALLOWED_LANGS else "both"


def _req_owner(data: dict | None = None) -> str | None:
    candidates = []
    if data:
        candidates.append(data.get("owner"))
    candidates.append(request.args.get("owner"))
    for value in candidates:
        if (isinstance(value, str) and 8 <= len(value) <= 128
                and value.isalnum()):
            return value
    return None


def _owner_allowed(entry: dict | None, owner: str | None) -> bool:
    """Matching owners may access their snapshots; legacy ownerless ones stay visible.

    旧版无 owner 的快照对所有客户端可见，避免升级后历史会话“消失”；
    新快照只属于各自的 owner。
    """
    if entry is None:
        return False
    stored = entry.get("owner")
    return stored is None or stored == owner


# code 会被前端逐条 exec，只放行无害内容：表达式、定义、注释与少量设置命令
# The client exec's code line by line, so allow only harmless content:
# expressions, definitions, comments and a few setting commands.
# 只读查询与定义可以分享；会读文件、改环境或操纵会话的命令不行
# Read-only queries and definitions may be shared; commands that touch files,
# change the environment or drive the session may not.
_SAFE_SHARE_SETTINGS = frozenset({
    # 设置 / settings
    ":lang", ":strategy", ":steps", ":eta", ":fast", ":encoding",
    # 只读查询 / read-only queries
    ":type", ":trace", ":ast", ":db", ":eq", ":conv", ":nf", ":whnf",
    ":int", ":church", ":env", ":help", ":def", ":search", ":prove",
    # 定义 / definitions
    ":let",
    # 手动归约（只影响回放者自己的会话）/ manual reduction (session-local only)
    # :undo/:redo are the interpreter's aliases for :back/:forward.
    ":begin", ":step", ":back", ":undo", ":forward", ":redo", ":goto", ":run", ":end",
})

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
    # 以 : 开头的命令只允许白名单里的无害命令；文件、编辑与会话操纵类命令拒绝
    # 手动归约命令只影响回放者自己的会话，因此在白名单内
    # Colon commands must be on the harmless whitelist; file, editor and
    # session commands are rejected. Manual reduction is session-local, so it
    # is allowed.
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
    doomed: list[tuple[str, dict, str]] = []
    with _sessions_lock:
        # 正在执行命令的会话占用 interp._busy 命令槽，不能因“空闲超时”回收它
        # A session with a command in flight occupies _busy; never reap it as idle.
        stale = [sid for sid, s in _sessions.items()
                 if (not s["interp"]._busy
                     and (now - s["used"] > SESSION_IDLE or not s["interp"].alive))]
        for sid in stale:
            doomed.append((sid, _sessions.pop(sid), "idle/dead"))
        # 超出上限时只淘汰空闲会话；若都忙则暂时超限，留待下次清理
        # Evict only idle sessions when over the limit; tolerate a temporary
        # over-limit until the next sweep if all are busy.
        while len(_sessions) > MAX_SESSIONS:
            candidates = [sid for sid in _sessions
                          if not _sessions[sid]["interp"]._busy]
            if not candidates:
                break
            oldest = min(candidates, key=lambda k: _sessions[k]["used"])
            doomed.append((oldest, _sessions.pop(oldest), "limit"))
    # kill 会等待子进程退出，放在锁外，避免阻塞其它会话
    # kill waits for the child process, so run it outside the lock.
    for sid, entry, reason in doomed:
        entry["interp"].kill()
        if reason == "limit":
            log.info("session evicted (limit) sid=%s / 超限会话已淘汰", sid)
        else:
            log.info("session reaped (idle/dead) sid=%s / 空闲会话已回收", sid)


def get_session(sid: str | None, lang: str = "both",
                *, create: bool = True, owner: str | None = None
                ) -> tuple[str, Interpreter] | tuple[None, None]:
    """Look up or create a session.

    With ``create=False`` an unknown id returns ``(None, None)`` instead of
    silently starting a fresh environment, so the client can replay history.
    """
    _prune_sessions()
    with _sessions_lock:
        if sid and isinstance(sid, str) and sid in _sessions:
            entry = _sessions[sid]
            entry["used"] = time.time()
            return sid, entry["interp"]
        if not create:
            return None, None
        new_sid = uuid.uuid4().hex
    # 启动子进程（Popen + 读线程）放在全局锁外，避免阻塞其他会话与 health 检查
    # Start the child process outside the global lock so other sessions and the
    # health endpoint are not blocked by a slow Popen.
    interp = Interpreter(lang)
    with _sessions_lock:
        _sessions[new_sid] = {"interp": interp, "used": time.time(), "owner": owner}
    log.info("session created sid=%s lang=%s / 会话已创建", new_sid, lang)
    return new_sid, interp


def _drop_session(sid: str | None) -> None:
    """移除并终止一个会话，失败路径上不能留下孤儿解释器进程
    Drop a session and kill its interpreter so failed operations leave no
    orphaned process behind.
    """
    if not isinstance(sid, str):
        return
    with _sessions_lock:
        entry = _sessions.pop(sid, None)
    if entry:
        entry["interp"].kill()


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
            _prune_snapshots()
            _prune_pages()
            _prune_tokens()
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
    args = [str(INTERP_BIN), "--batch", "--json", "--lang", lang]
    # 旧接口也要遵守同一表达式上限，否则可绕过会话接口的大小保护
    # The legacy endpoint must honour the same term cap as the session path.
    if MAX_TERM_SIZE.isdigit() and int(MAX_TERM_SIZE) > 0:
        args += ["--max-term-size", MAX_TERM_SIZE]
    proc = subprocess.run(
        args,
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
    _prune_snapshots()
    _prune_pages()
    with _sessions_lock:
        count = len(_sessions)
    with _shares_lock:
        share_count = len(_shares)
    with _pages_lock:
        page_count = len(_pages)
    with _tokens_lock:
        token_count = len(_tokens)
    snapshot_count = len(_snapshot_all())
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
        "snapshots": snapshot_count,
        "pages": page_count,
        "tokens": token_count,
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
    if not _rate_ok():
        return api_error("请求过于频繁 / rate limit exceeded", 429, "rate_limited")
    _prune_shares()
    with _shares_lock:
        entry = _shares.get(sid)
    if not entry:
        return api_error("分享不存在或已过期 / share not found", 404, "not_found")
    return jsonify({"ok": True, "state": entry["payload"]})


@app.route("/api/share/page", methods=["POST"])
def api_share_page():
    if not _rate_ok():
        return api_error("请求过于频繁 / rate limit exceeded", 429, "rate_limited")
    data = _json_body()
    if not isinstance(data, dict):
        return api_error("bad request", 400, "bad_request")
    lines = data.get("lines")
    title = data.get("title", "Lambda calculus")
    if (not isinstance(lines, list) or not isinstance(title, str)
            or len(lines) > MAX_PAGE_LINES):
        return api_error("页面载荷无效 / invalid page payload", 400, "bad_request")
    for item in lines:
        if not isinstance(item, dict) or not isinstance(item.get("zh"), str) \
                or not isinstance(item.get("en"), str):
            return api_error("页面载荷无效 / invalid page payload", 400, "bad_request")
    trace = data.get("trace") or []
    if (not isinstance(trace, list) or len(trace) > 500
            or any(not isinstance(s, dict) for s in trace)):
        return api_error("轨迹载荷无效 / invalid trace payload", 400, "bad_request")
    page = _render_page(title[:120], lines, trace)
    if len(page.encode("utf-8")) > 512 * 1024:
        return api_error("页面过大 / page too large", 413, "payload_too_large")
    _prune_pages()
    pid = uuid.uuid4().hex[:10]
    with _pages_lock:
        _pages[pid] = {"html": page, "created": time.time()}
        _save_pages_locked()
    return jsonify({"ok": True, "id": pid})


@app.route("/api/share/page/<pid>", methods=["GET"])
def api_share_page_get(pid):
    if not _rate_ok():
        return api_error("请求过于频繁 / rate limit exceeded", 429, "rate_limited")
    _prune_pages()
    with _pages_lock:
        entry = _pages.get(pid)
    if entry is None:
        return api_error("页面不存在 / page not found", 404, "not_found")
    return Response(entry["html"], mimetype="text/html; charset=utf-8")


@app.route("/api/gallery", methods=["GET"])
def api_gallery():
    if not _rate_ok():
        return api_error("请求过于频繁 / rate limit exceeded", 429, "rate_limited")
    return jsonify({"ok": True, "examples": GALLERY})


@app.route("/api/token", methods=["POST"])
def api_token():
    if not _rate_ok():
        return api_error("请求过于频繁 / rate limit exceeded", 429, "rate_limited")
    token = uuid.uuid4().hex[:16]
    with _tokens_lock:
        _tokens[token] = {"used": 0, "created": time.time()}
        # 先加入再回收，保证写入后也不超过上限
        # Prune after insertion so the store is bounded on return as well.
        _prune_tokens_locked()
        _save_tokens_locked()
    return jsonify({"ok": True, "token": token})


@app.route("/api/session", methods=["POST"])
def api_session():
    if not _rate_ok():
        return api_error("请求过于频繁 / rate limit exceeded", 429, "rate_limited")
    if not INTERP_BIN.is_file():
        log.error("interpreter missing / 解释器缺失: %s", INTERP_BIN)
        return api_error(_missing_bin_msg(), 500, "internal")
    data = _json_body() or {}
    lang = _req_lang(data)
    sid, _ = get_session(None, lang, owner=_req_owner(data))
    return jsonify({"ok": True, "session": sid})


@app.route("/api/session/<sid>/restore", methods=["POST"])
def api_session_restore(sid):
    """Rebuild a dead session from its persisted replay snapshot.

    从持久化的回放快照重建已失效的会话，避免重复执行客户端历史。
    """
    if not _rate_ok():
        return api_error("请求过于频繁 / rate limit exceeded", 429, "rate_limited")
    data = _json_body() or {}
    lang = _req_lang(data)
    owner = _req_owner(data)
    _prune_snapshots()
    # 只在读取/校验和最终提交时持锁：回放最多 200 行、每行可能耗满超时，
    # 全程持锁会让所有并发 eval 与快照管理请求一起阻塞
    # Hold the lock only to read and to commit: replaying up to 200 lines while
    # holding it would block every concurrent eval and snapshot request.
    with _snapshot_rmw_lock:
        entry = _snapshot_get(sid)
        if not _owner_allowed(entry, owner):
            return api_error("快照不存在或已过期 / snapshot not found", 404, "not_found")
        code = list(entry["code"])
        saved_lang = entry["lang"]
        saved_name = entry.get("name", "")
        saved_owner = entry.get("owner")
        for ln in code:
            problem = validate_line(ln)
            if problem:
                return api_error(problem[1], 400, problem[0])
        if not INTERP_BIN.is_file():
            return api_error(_missing_bin_msg(), 500, "internal")
    new_sid, interp = get_session(None, saved_lang, owner=saved_owner)
    try:
        interp.send(":lang " + saved_lang)
        for ln in code:
            interp.send(ln)
    except TimeoutError:
        _drop_session(new_sid)
        log.warning("snapshot restore timeout sid=%s / 快照恢复超时", sid)
        return api_error(_timeout_msg(lang), 408, "timeout", timeout=True)
    except RuntimeError as exc:
        _drop_session(new_sid)
        log.warning("snapshot restore failed sid=%s: %s / 快照恢复失败", sid, exc)
        return api_error(str(exc), 410, "session_expired", restart=True)
    new_entry = {"code": code, "lang": saved_lang, "name": saved_name,
                 "owner": saved_owner,
                 "created": time.time(), "used": time.time()}
    # 提交时重新校验归属，并先写新快照再删旧快照：SQLite 写入失败会被吞掉，
    # 若先删就再也找不回原快照
    # Recheck ownership at commit time, and write the new snapshot before
    # removing the old one: SQLite _sql_put swallows write errors.
    with _snapshot_rmw_lock:
        current = _snapshot_get(sid)
        if not _owner_allowed(current, owner):
            _drop_session(new_sid)
            return api_error("快照不存在或已过期 / snapshot not found", 404, "not_found")
        if not _snapshot_put(new_sid, new_entry):
            _drop_session(new_sid)
            return api_error("快照写入失败 / snapshot write failed", 500, "internal")
        _snapshot_remove(sid, owner)
    log.info("session restored from snapshot %s -> %s / 会话已从快照恢复", sid, new_sid)
    return jsonify({"ok": True, "session": new_sid, "code": code, "lang": saved_lang})


@app.route("/api/snapshots", methods=["GET"])
def api_snapshots():
    """List persisted sessions for the session manager.

    为会话管理器列出持久化的会话。
    """
    if not _rate_ok():
        return api_error("请求过于频繁 / rate limit exceeded", 429, "rate_limited")
    _prune_snapshots()
    owner = _req_owner()
    items = []
    for sid, entry in _snapshot_all().items():
        if not _owner_allowed(entry, owner):
            continue
        items.append({"id": sid, "lines": len(entry["code"]), "lang": entry["lang"],
                      "created": entry["created"], "used": entry["used"],
                      "name": entry.get("name", "")})
    items.sort(key=lambda x: x["used"], reverse=True)
    return jsonify({"ok": True, "snapshots": items, "storage":
                    "sqlite" if _use_sqlite() else ("off" if _snapshot_db_path() is None else "file")})


@app.route("/api/snapshot/<sid>/name", methods=["POST"])
def api_snapshot_name(sid):
    if not _rate_ok():
        return api_error("请求过于频繁 / rate limit exceeded", 429, "rate_limited")
    data = _json_body() or {}
    name = data.get("name")
    if not isinstance(name, str) or len(name) > 80:
        return api_error("名称无效 / invalid name", 400, "bad_request")
    owner = _req_owner(data)
    # SQLite 下用带 owner 条件的单条 UPDATE，避免跨 worker 的读-改-写竞态
    # A single owner-conditional UPDATE also closes the cross-worker RMW race.
    clean = name.strip()
    if not _snapshot_rename(sid, clean, owner):
        return api_error("快照不存在 / snapshot not found", 404, "not_found")
    return jsonify({"ok": True, "id": sid, "name": clean})


@app.route("/api/snapshot/<sid>", methods=["DELETE"])
def api_snapshot_delete(sid):
    if not _rate_ok():
        return api_error("请求过于频繁 / rate limit exceeded", 429, "rate_limited")
    data = _json_body() or {}
    owner = _req_owner(data)
    with _snapshot_rmw_lock:
        entry = _snapshot_get(sid)
        if not _owner_allowed(entry, owner):
            return api_error("快照不存在 / snapshot not found", 404, "not_found")
        _snapshot_remove(sid, owner)
    return jsonify({"ok": True, "id": sid})


@app.route("/api/session/<sid>/lang", methods=["POST"])
def api_session_lang(sid):
    """在同一个解释器进程内切换语言，避免重建会话
    Switch language inside the same interpreter process (no session rebuild)."""
    if not _rate_ok():
        return api_error("请求过于频繁 / rate limit exceeded", 429, "rate_limited")
    data = _json_body() or {}
    lang = _req_lang(data)
    _prune_sessions()
    with _sessions_lock:
        entry = _sessions.get(sid)
        if entry:
            entry["used"] = time.time()
    if not entry:
        return api_error("session not found", 410, "session_expired", restart=True)
    try:
        outputs = entry["interp"].send(f":lang {lang}")
        _snapshot_record(sid, [f":lang {lang}"], lang)
        return jsonify({"ok": True, "session": sid, "lang": lang, "outputs": outputs})
    except TimeoutError:
        log.warning("lang timeout sid=%s / 切换语言超时", sid)
        return api_error(_timeout_msg(lang), 408, "timeout", timeout=True)
    except RuntimeError as exc:
        log.warning("lang failed sid=%s: %s / 切换语言失败", sid, exc)
        return api_error(str(exc), 410, "session_expired", restart=True)


@app.route("/api/session/<sid>", methods=["DELETE"])
def api_session_delete(sid):
    if not _rate_ok():
        return api_error("请求过于频繁 / rate limit exceeded", 429, "rate_limited")
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
    if not _rate_ok():
        return api_error("请求过于频繁 / rate limit exceeded", 429, "rate_limited")
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
    lang = _req_lang(data)

    # 旧接口：{code} 一次性执行
    legacy = data.get("code") or data.get("expr")
    if legacy is not None:
        try:
            for ln in str(legacy).splitlines():
                problem = validate_line(ln)
                if problem:
                    return api_error(problem[1], 400, problem[0])
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
            return api_error(problem[1], 400, problem[0])

    # 批量请求按命令数计费，避免一次 lines 数组绕过按请求的限流
    # Charge per command so a single lines[] array cannot bypass the rate limit.
    if len(lines) > 1 and not _rate_ok(len(lines) - 1):
        return api_error("请求过于频繁 / rate limit exceeded", 429, "rate_limited")

    if not INTERP_BIN.is_file():
        return api_error(_missing_bin_msg(), 500, "internal")

    sid_in = data.get("session")
    owner = _req_owner(data)
    try:
        sid, interp = get_session(sid_in, lang, create=sid_in is None, owner=owner)
        if sid is None or interp is None:
            return api_error(
                "会话已过期，正在重建 / session expired; rebuilding",
                410, "session_expired", restart=True)
        outputs: list[dict] = []
        done = 0
        try:
            for ln in lines:
                outputs.extend(interp.send(ln))
                done += 1
        finally:
            # 多行请求中途超时时，已执行的行仍要落盘，否则恢复后的会话缺少
            # 这些定义，与超时前的真实状态不一致
            # Record the successfully executed prefix even if a later line times
            # out, so a restored session still contains earlier definitions.
            if done:
                _snapshot_record(sid, lines[:done], lang, set_lang=("lang" in data))
        _token_used(data.get("token"))
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


def _pick_race_result(outputs: list[dict]) -> dict:
    """Pick the meaningful JSON object from one strategy's output.
    从某个策略的输出里挑出有实际意义的结果对象。
    """
    wanted = {"result", "warn", "error", "fail", "type", "proof", "trace"}
    for obj in reversed(outputs):
        if isinstance(obj, dict) and obj.get("kind") in wanted:
            return obj
    return outputs[-1] if outputs else {}


@app.route("/api/race", methods=["POST"])
def api_race():
    """Run one expression under all four strategies in the same session.

    在同一个会话里用四种策略归约同一个表达式，供前端并排展示。
    The original strategy is restored at the end.
    """
    if not _rate_ok():
        return api_error("请求过于频繁 / rate limit exceeded", 429, "rate_limited")
    data = _json_body() or {}
    lang = _req_lang(data)
    line = data.get("line")
    if not isinstance(line, str) or not line.strip():
        return api_error("表达式为空 / empty expression", 400, "bad_request")
    # 必须逐行拆分并只接受单行：整段字符串直接拼进 ":trace …" 会让换行变成
    # 一条未经校验的新命令，绕过 :load 路径检查和 :quit 拦截
    # Split into lines and accept exactly one: embedding a multi-line string in
    # ":trace …" turns the second line into an unverified command, bypassing the
    # :load path check and the :quit refusal.
    parts = [p for p in line.splitlines() if p.strip()]
    if len(parts) != 1:
        return api_error("竞速只接受单个表达式 / race accepts a single expression",
                         400, "bad_request")
    expr = parts[0].strip()
    # 竞速只接受表达式，不接受命令：每条策略都要用 :trace 收集步骤
    # The race accepts expressions only; each strategy is measured with :trace.
    if expr.startswith(":"):
        return api_error("请输入表达式而不是命令 / enter an expression, not a command",
                         400, "bad_request")
    problem = validate_line(expr)
    if problem:
        return api_error(problem[1], 400, problem[0])
    if not INTERP_BIN.is_file():
        return api_error(_missing_bin_msg(), 500, "internal")
    sid_in = data.get("session")
    # need 不在竞速的四种策略里，但界面可能正选用它：恢复时必须原样保留，
    # 否则竞速结束后会话策略被悄悄改成 applicative
    # need is not raced, but the UI may be using it: preserve it on restore so a
    # race does not silently switch the session to applicative order.
    restore_strategy = data.get("strategy")
    strategy = restore_strategy if restore_strategy in STRATEGIES + ("need",) else "applicative"
    sid, interp = get_session(sid_in, lang, create=sid_in is None,
                              owner=_req_owner(data))
    if sid is None or interp is None:
        return api_error(
            "会话已过期，正在重建 / session expired; rebuilding",
            410, "session_expired", restart=True)
    results: dict[str, dict] = {}
    try:
        # 整段“设策略 -> :trace -> 恢复策略”必须在同一把锁内发完，否则并发的
        # /api/eval 会插进中间，让竞速结果属于错误的策略或读串输出.
        # The whole set-strategy / :trace / restore batch must go out under one
        # lock; otherwise a concurrent /api/eval can interleave and misalign the
        # strategy or the replies.
        batch: list[str] = []
        for name in STRATEGIES:
            batch.append(":strategy " + name)
            batch.append(":trace " + expr)
        batch.append(":strategy " + strategy)
        outputs = interp.send_many(batch)
        for i, name in enumerate(STRATEGIES):
            results[name] = _pick_race_result(outputs[2 * i + 1])
    except TimeoutError:
        log.warning("race timeout sid=%s / 策略竞速超时", sid_in)
        return api_error(_timeout_msg(lang), 408, "timeout", timeout=True)
    except RuntimeError as exc:
        log.warning("race session dead sid=%s: %s / 策略竞速会话已退出", sid_in, exc)
        return api_error(str(exc), 410, "session_expired", restart=True)
    _snapshot_record(sid, [expr], lang, set_lang=("lang" in data))
    with _sessions_lock:
        if sid in _sessions:
            _sessions[sid]["used"] = time.time()
    return jsonify({"ok": True, "session": sid, "line": expr,
                    "strategy": strategy, "results": results})


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
    lang = _req_lang(data)
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
            return api_error(problem[1], 400, problem[0])
    if len(lines) > 1 and not _rate_ok(len(lines) - 1):
        return api_error("请求过于频繁 / rate limit exceeded", 429, "rate_limited")
    if not INTERP_BIN.is_file():
        return api_error(_missing_bin_msg(), 500, "internal")

    sid_in = data.get("session")
    # 非字符串会话 id 会在 _sessions 字典查找时抛 TypeError（500）；
    # 在这里就拒绝，和 /api/eval 的错误格式保持一致.
    # A non-string session id would raise TypeError on the dict lookup (500);
    # reject it here with the same 400 shape as /api/eval.
    if sid_in is not None and not isinstance(sid_in, str):
        return api_error("invalid session id", 400, "bad_request")
    sid, interp = get_session(sid_in, lang, create=sid_in is None,
                              owner=_req_owner(data))
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
                # 逐行落盘：中途超时也能保住已执行的定义
                # Persist each completed line so a later timeout keeps earlier definitions.
                _snapshot_record(sid, [ln], lang, set_lang=("lang" in data))
            with _sessions_lock:
                if sid in _sessions:
                    _sessions[sid]["used"] = time.time()
            yield sse({"kind": "done", "ok": True, "session": sid})
        except TimeoutError:
            log.warning("stream eval timeout sid=%s / 流式求值超时", sid)
            yield sse({"kind": "timeout", "ok": False, "timeout": True,
                       "session": sid, "error": _timeout_msg(lang),
                       "code": "timeout"})
        except RuntimeError as exc:
            log.warning("stream eval session dead sid=%s: %s", sid, exc)
            yield sse({"kind": "expired", "ok": False, "restart": True,
                       "session": sid, "error": str(exc),
                       "code": "session_expired"})
        except Exception as exc:  # noqa: BLE001
            log.exception("stream eval failed / 流式求值异常: %s", exc)
            yield sse({"kind": "error", "ok": False, "error": str(exc),
                       "code": "internal"})

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
