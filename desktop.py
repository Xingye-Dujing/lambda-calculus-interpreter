#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Desktop wrapper for the lambda-calculus web UI.

Starts the existing Flask app on a loopback port and opens it in a native
pywebview window. PyInstaller bundles this file together with `web/`, `lib/`,
`VERSION` and the `extension` binary into a single desktop application.

桌面版入口：在本地回环端口启动现有 Flask 应用，用 pywebview 原生窗口打开。
PyInstaller 会把本文件与 `web/`、`lib/`、`VERSION` 和 `extension` 一起打包。
"""
from __future__ import annotations

import multiprocessing
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path


def _bind_port() -> tuple[int, socket.socket]:
    """Bind an ephemeral loopback port and keep the socket listening.

    Holding the socket until the server takes over removes the race between
    choosing a port and binding it (a classic TOCTOU bug on busy machines).
    绑定回环端口后保持监听，直到服务器接管该套接字，避免选端口与绑定之间被抢占。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    return int(sock.getsockname()[1]), sock


def _free_port() -> int:
    port, sock = _bind_port()
    sock.close()
    return port


def _prepare_environment() -> Path:
    """Point the backend at bundled resources and a writable user directory."""
    frozen = bool(getattr(sys, "frozen", False))
    bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    data_dir = Path.home() / ".lambda-calculus-interpreter"

    if frozen:
        data_dir.mkdir(parents=True, exist_ok=True)
        # app.py resolves `extension` from APP_DIR.parent (the PyInstaller root).
        os.environ.setdefault("LAMBDA_INTERP_DIR", str(bundle))
        os.environ.setdefault("LAMBDA_INTERP_CWD", str(data_dir))
        os.environ.setdefault("LAMBDA_SHARE_DB", str(data_dir / "shares.json"))
        os.environ.setdefault("LAMBDA_SNAPSHOT_DB", str(data_dir / "sessions.json"))
        os.environ.setdefault("LAMBDA_PAGE_DB", str(data_dir / "sharepages.json"))
        os.environ.setdefault("LAMBDA_TOKEN_DB", str(data_dir / "tokens.json"))
        # The desktop build is local, so file loading/saving is allowed.
        os.environ.setdefault("LAMBDA_LOAD_ROOT", "*")
        os.environ.setdefault("LAMBDA_ALLOW_SAVE", "1")
    return data_dir


def _wait_for_server(url: str, timeout: float = 15.0,
                     server_error: list[BaseException] | None = None) -> None:
    deadline = time.monotonic() + timeout
    health = url + "api/health"

    def fail() -> None:
        # 服务器线程若已抛异常，把它带进错误信息，避免隐藏真正的启动失败原因
        # Surface the server thread's exception instead of hiding the root cause
        # behind a generic "did not start" timeout.
        if server_error:
            exc = server_error[0]
            raise RuntimeError(
                f"web UI server thread failed / 网页服务器线程出错: {exc!r}"
            ) from exc

    while time.monotonic() < deadline:
        fail()
        try:
            with urllib.request.urlopen(health, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:  # noqa: BLE001
            time.sleep(0.1)
    fail()
    raise RuntimeError("web UI did not start / 网页界面未能启动")


def main() -> int:
    multiprocessing.freeze_support()
    _prepare_environment()

    import webview
    from web.app import app

    # 选端口时就绑定并监听，把已打开的套接字交给 Werkzeug，杜绝端口被抢占
    # Bind and listen when picking the port, then hand the open socket to Werkzeug.
    port, sock = _bind_port()
    url = f"http://127.0.0.1:{port}/"

    # 守护线程里的启动异常主听不到，收集到共享列表由 _wait_for_server 上报
    # Exceptions raised in the daemon server thread are invisible to the main
    # thread; collect them in a shared holder so _wait_for_server can report them.
    server_error: list[BaseException] = []

    def serve() -> None:
        try:
            from werkzeug.serving import make_server
            server = make_server("127.0.0.1", port, app, threaded=True,
                                 fd=sock.fileno())
            server.serve_forever()
        except BaseException as exc:  # noqa: BLE001
            server_error.append(exc)

    threading.Thread(target=serve, daemon=True, name="lambda-web").start()
    _wait_for_server(url, server_error=server_error)

    webview.create_window(
        "λ 演算解释器 / Lambda Calculus Interpreter",
        url,
        width=1280,
        height=860,
        min_size=(900, 600),
        confirm_close=False,
    )
    webview.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
