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


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


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
        # The desktop build is local, so file loading/saving is allowed.
        os.environ.setdefault("LAMBDA_LOAD_ROOT", "*")
        os.environ.setdefault("LAMBDA_ALLOW_SAVE", "1")
    return data_dir


def _wait_for_server(url: str, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    health = url + "api/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:  # noqa: BLE001
            time.sleep(0.1)
    raise RuntimeError("web UI did not start / 网页界面未能启动")


def main() -> int:
    multiprocessing.freeze_support()
    _prepare_environment()

    import webview
    from web.app import app

    port = _free_port()
    url = f"http://127.0.0.1:{port}/"

    def serve() -> None:
        app.run(host="127.0.0.1", port=port, threaded=True,
                debug=False, use_reloader=False)

    threading.Thread(target=serve, daemon=True, name="lambda-web").start()
    _wait_for_server(url)

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
