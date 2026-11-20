#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A minimal JSON-RPC language server for .lam files.

为 .lam 文件提供最小可用的 JSON-RPC 语言服务器，走 stdio。
Supports initialize, didOpen/didChange diagnostics, completion and hover.
支持初始化、打开/修改时的诊断、补全与悬停。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
_DOCS: dict[str, str] = {}
_CACHE: dict[tuple[str, str], tuple[list[dict], str]] = {}


def find_binary() -> Path | None:
    """Locate the compiled extension binary, mirroring web/app.py.

    按与 web/app.py 相同的顺序查找编译好的 extension。
    """
    env = os.environ.get("LAMBDA_INTERP_BIN")
    if env and Path(env).is_file():
        return Path(env)
    roots = []
    d = os.environ.get("LAMBDA_INTERP_DIR")
    if d:
        roots.append(Path(d))
    roots += [ROOT, Path("/opt/lambda-calculus-interpreter")]
    for base in roots:
        for name in ("extension.exe", "extension"):
            p = base / name
            if p.is_file():
                return p
    return None


def run_extension(lines: list[str]) -> list[list[dict]]:
    """Run a batch of commands and group JSON objects per input line.

    批量运行命令并按输入行分组返回 JSON 对象。
    """
    binary = find_binary()
    if binary is None or not lines:
        return []
    try:
        proc = subprocess.run([str(binary), "--batch", "--json", "--lang", "both"],
                              input=("\n".join(lines) + "\n").encode("utf-8"),
                              capture_output=True, cwd=ROOT, timeout=30)
    except subprocess.TimeoutExpired:
        # A slow/hung command must not take down the JSON-RPC server; an empty
        # result makes callers fall back to their offline/static answers.
        return []
    except OSError:
        return []
    out: list[list[dict]] = []
    for chunk in proc.stdout.decode("utf-8", "replace").split("\x1e"):
        objects = []
        for part in chunk.splitlines():
            if not part.strip():
                continue
            try:
                objects.append(json.loads(part))
            except ValueError:
                continue
        out.append(objects)
    while out and not out[-1]:
        out.pop()
    return out

PRELUDE = (
    "TRUE FALSE NOT AND OR XOR NAND IF I K S B C W ZERO ONE TWO THREE SUCC "
    "PLUS MULT EXP PRED SUB ISZERO LEQ EQ MIN MAX DIV MOD PAIR FST SND NIL "
    "CONS HEAD TAIL APPEND REV LENGTH MAP FILTER FOLD RANGE ZIP Y"
).split()

COMMANDS = (
    ":help :load :save :let :env :del :reset :strategy :steps :eta :fast "
    ":encoding :trace :machine :stats :par :ftype :ast :db :type :eq :conv "
    ":prove :nf :whnf :int :church :begin :step :run :end :back :forward "
    ":goto :def :search :reload :edit :lang :time :bench :growth :shortest :q"
).split()

KNOWN = set(PRELUDE) | set(COMMANDS) | {"rec", "let", "in", "if", "then", "else"}

# 标识符/命令字符：\w 覆盖字母数字下划线与 Unicode 字母，另加冒号与撇号
# Identifier/command characters: \w covers alphanumerics and Unicode letters,
# plus the colon for commands and apostrophes for primed names.
_WORD_CHARS = re.compile(r"[:'’\w]+", re.UNICODE)


def word_at(text: str, line: int, character: int) -> str:
    """Return the identifier at a zero-based (line, character) position.

    标准 LSP 客户端只发送 line/character，需从文档文本中取出该位置的词。
    Standard LSP clients send only line/character; recover the word from the
    document text at that position.
    """
    if line < 0 or character < 0:
        return ""
    rows = text.splitlines()
    if line >= len(rows):
        return ""
    row = rows[line]
    if character > len(row):
        return ""
    for match in _WORD_CHARS.finditer(row):
        if match.start() <= character <= match.end():
            return match.group(0)
    return ""


def diagnostics(text: str) -> list[dict]:
    """Return real line diagnostics from the interpreter, with a static fallback.

    优先用解释器给出真实诊断，失败时退回静态检查。
    """
    lines = text.splitlines()
    batches = run_extension(lines)
    out: list[dict] = []
    if batches:
        for n, objects in enumerate(batches[:len(lines)]):
            bad = [o for o in objects if o.get("kind") in ("error", "fail")]
            if not bad:
                continue
            msg = bad[0].get("textZh") or bad[0].get("textEn") or bad[0].get("text", "")
            pos = bad[0].get("pos")
            start = max(0, (pos - 1) if isinstance(pos, int) else 0)
            out.append({"range": {"start": {"line": n, "character": start},
                                  "end": {"line": n, "character": len(lines[n])}},
                        "severity": 1,
                        "source": "lambda-interpreter",
                        "message": str(msg)})
        return out
    # 静态回退 / static fallback
    for n, line in enumerate(lines):
        s = line.strip()
        if not s or s.startswith("--") or s.startswith("#"):
            continue
        if s.startswith(":") and s.split()[0] not in KNOWN:
            out.append({"range": {"start": {"line": n, "character": 0},
                                  "end": {"line": n, "character": len(line)}},
                        "severity": 2,
                        "message": f"unknown command / 未知命令: {s.split()[0]}"})
    return out


def real_hover(word: str, text: str) -> str:
    """Ask the interpreter for the type of a word in the document.

    向解释器询问文档中某个名字的真实类型。
    """
    key = (word, text)
    if key in _CACHE:
        return _CACHE[key][1]
    defs = [ln for ln in text.splitlines()
            if ln.strip() and not ln.strip().startswith(("--", "#")) and "=" in ln]
    result = ""
    batches = run_extension(defs + [f":type {word}"])
    if batches:
        objs = batches[-1]
        typed = next((o for o in objs if o.get("kind") == "type"), None)
        if typed:
            zh = typed.get("typeZh") or typed.get("type", "")
            en = typed.get("typeEn") or typed.get("type", "")
            prop = typed.get("propositionZh") or ""
            result = f"**{word}** : `{zh}`\n\n{en}\n\n{prop}".strip()
        else:
            bad = next((o for o in objs if o.get("kind") in ("error", "fail")), None)
            if bad:
                result = str(bad.get("textZh") or bad.get("text", ""))
    if not result:
        kind = "command" if word.startswith(":") else ("prelude" if word in PRELUDE else "name")
        result = f"`{word}` — {kind} (offline / 离线)"
    _CACHE[key] = ([], result)
    return result


def handle(msg: dict) -> dict | None:
    method = msg.get("method")
    params = msg.get("params") or {}
    rid = msg.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "capabilities": {"hoverProvider": True, "completionProvider": {}},
            "serverInfo": {"name": "lambda-lsp", "version": "1.0"}}}
    if method in ("initialized", "shutdown", "exit"):
        return None
    if method in ("textDocument/didOpen", "textDocument/didChange"):
        uri = (params.get("textDocument") or {}).get("uri", "")
        if method == "textDocument/didOpen":
            text = ((params.get("textDocument") or {}).get("text") or "")
        else:
            changes = params.get("contentChanges") or []
            text = changes[-1].get("text", "") if changes else ""
        _DOCS[uri] = text
        _CACHE.clear()
        return {"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
                "params": {"uri": (params.get("textDocument") or {}).get("uri", ""),
                           "diagnostics": diagnostics(text)}}
    if method == "textDocument/completion" and rid is not None:
        items = [{"label": x, "kind": 14 if x.startswith(":") else 6} for x in COMMANDS + PRELUDE]
        return {"jsonrpc": "2.0", "id": rid, "result": items}
    if method == "textDocument/hover" and rid is not None:
        pos = params.get("position") or {}
        uri = (params.get("textDocument") or {}).get("uri", "")
        text = _DOCS.get(uri, "")
        word = str(pos.get("word", ""))
        if not word:
            line, char = pos.get("line"), pos.get("character")
            if isinstance(line, int) and isinstance(char, int):
                word = word_at(text, line, char)
        value = real_hover(word, text) if word else ""
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "contents": {"kind": "markdown", "value": value}}}
    if rid is not None:
        return {"jsonrpc": "2.0", "id": rid,
                "error": {"code": -32601, "message": "method not found"}}
    return None


class MalformedMessage(Exception):
    """A malformed LSP frame that main() can skip without stopping the server."""


def read_message(stream) -> dict | None:
    """Read one LSP frame, returning None on EOF and raising on bad input.

    读取一帧 LSP 消息：EOF 返回 None，畸形帧抛出受控异常。
    """
    length = 0
    while True:
        line = stream.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        if line.lower().startswith(b"content-length:"):
            try:
                length = int(line.split(b":", 1)[1].strip())
            except (ValueError, IndexError) as exc:
                raise MalformedMessage("invalid Content-Length") from exc
    if length <= 0:
        raise MalformedMessage("missing or invalid Content-Length")
    body = stream.read(length)
    if len(body) != length:
        raise MalformedMessage("short read of message body")
    try:
        obj = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise MalformedMessage("invalid JSON body") from exc
    if not isinstance(obj, dict):
        raise MalformedMessage("message body is not a JSON object")
    return obj


def write_message(obj: dict) -> None:
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode() + data)
    sys.stdout.buffer.flush()


def main() -> int:
    while True:
        try:
            msg = read_message(sys.stdin.buffer)
        except MalformedMessage:
            # Skip a single bad frame and keep serving; only EOF ends the loop.
            continue
        if msg is None:
            return 0
        try:
            reply = handle(msg)
        except Exception:  # noqa: BLE001 - never let bad input kill the server
            rid = msg.get("id")
            reply = ({"jsonrpc": "2.0", "id": rid,
                      "error": {"code": -32603, "message": "internal error"}}
                     if rid is not None else None)
        if reply is not None:
            write_message(reply)


if __name__ == "__main__":
    raise SystemExit(main())
