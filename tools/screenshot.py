#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为 README 生成浅色模式截图 / Capture light-mode screenshots for the README.

用法 / Usage
------------
    python tools/screenshot.py                 # 截三张：主界面、AST、环境
    python tools/screenshot.py --only main     # 只截一张
    python tools/screenshot.py --url http://127.0.0.1:8081/ --out docs/screenshots

依赖 / Requirements
-------------------
* 运行中的 Web 界面（`python web/app.py`）/ a running web UI
* Chrome 或 Edge / Chrome or Edge
* `pip install websocket-client`

原理 / How it works
-------------------
用 Chrome DevTools Protocol 驱动无头浏览器：真实执行命令、切换面板、
拖动轨迹进度，然后以 2x 像素密度截取整页 PNG。脚本不依赖页面暴露的
内部函数，只模拟点击与键盘输入，因此不要改动页面的 DOM id 约定
（`#cmd`、`#out`、`.tab`、`.steps-list`、`#clear`、`#theme-toggle`）。

It drives headless Chrome over CDP: it runs real commands, switches panels and
moves the trace slider, then captures a full-page PNG at 2x. It only simulates
clicks and keystrokes, so keep the DOM ids used below stable.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

try:
    import websocket
except ImportError:  # pragma: no cover
    sys.exit("需要 websocket-client / websocket-client is required:\n"
             "  pip install websocket-client")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_URL = "http://127.0.0.1:8081/"
DEFAULT_OUT = ROOT / "docs" / "screenshots"

# 各平台常见的 Chrome/Edge 位置 / common Chrome/Edge locations
CANDIDATES = [
    os.environ.get("CHROME_BIN", ""),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/microsoft-edge",
]


def find_chrome() -> str:
    for path in CANDIDATES:
        if path and Path(path).is_file():
            return path
    for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
        found = shutil.which(name)
        if found:
            return found
    sys.exit("找不到 Chrome/Edge，请设置 CHROME_BIN / Chrome or Edge not found; set CHROME_BIN")


class CDP:
    """极简 Chrome DevTools Protocol 客户端 / minimal CDP client."""

    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(ws_url, timeout=30)
        self._id = 0

    def call(self, method: str, **params):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def js(self, expression: str):
        result = self.call("Runtime.evaluate", expression=expression, returnByValue=True)
        return result.get("result", {}).get("value")


def wait_for_page(port: int, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            tabs = json.loads(urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/list", timeout=1).read())
            for tab in tabs:
                if tab.get("type") == "page" and tab.get("webSocketDebuggerUrl"):
                    return tab
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.15)
    raise RuntimeError("Chrome 没有就绪 / Chrome did not become ready")


def check_server(url: str) -> None:
    try:
        urllib.request.urlopen(url, timeout=3).read(1)
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"无法访问 {url} / cannot reach {url}: {exc}\n"
                 "请先启动 / start it first: python web/app.py")


class Shooter:
    def __init__(self, cdp: CDP, out: Path, width: int, height: int, scale: float):
        self.c = cdp
        self.out = out
        self.width = width
        self.height = height
        self.scale = scale

    # ---- 页面操作 / page actions -----------------------------------------
    def prepare(self, url: str) -> None:
        self.c.call("Page.enable")
        self.c.call("Runtime.enable")
        self.c.call("Emulation.setDeviceMetricsOverride",
                    width=self.width, height=self.height,
                    deviceScaleFactor=self.scale, mobile=False)
        self.c.call("Page.navigate", url=url)
        time.sleep(2.0)
        # 强制浅色 / force light mode regardless of stored preference
        self.c.js("localStorage.removeItem('lambda.ui.v2');"
                  "document.documentElement.setAttribute('data-theme','light');"
                  "document.getElementById('theme-toggle').textContent='深色 / Dark';")
        time.sleep(0.3)

    def _lines(self) -> int:
        return self.c.js("document.querySelectorAll('#out .line').length") or 0

    def run(self, command: str, settle: float = 0.35) -> None:
        before = self._lines()
        payload = json.dumps(command, ensure_ascii=False)
        self.c.js("(() => { const c=document.getElementById('cmd');"
                  f"c.value={payload};"
                  "c.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));"
                  "})()")
        for _ in range(60):
            if self._lines() != before:
                break
            time.sleep(0.1)
        time.sleep(settle)

    def clear(self) -> None:
        self.c.js("document.getElementById('clear').click()")
        time.sleep(1.0)

    def click_result(self) -> None:
        self.c.js("(() => { const r=document.querySelectorAll('#out .line.result');"
                  "if(r.length) r[r.length-1].click(); })()")
        time.sleep(0.35)

    def tab(self, name: str) -> None:
        self.c.js(f"document.querySelector('[data-tab=\"{name}\"]').click()")
        time.sleep(0.3)

    def step(self, index: int) -> None:
        self.c.js("(() => { const s=document.querySelectorAll('.steps-list .st');"
                  f"if(s.length>{index}) s[{index}].click(); }})()")
        time.sleep(0.3)

    def shot(self, name: str, clip_height: int | None = None) -> None:
        metrics = self.c.call("Page.getLayoutMetrics")
        height = metrics["cssContentSize"]["height"]
        if clip_height:
            height = min(height, clip_height)
        data = self.c.call("Page.captureScreenshot", format="png",
                           captureBeyondViewport=True,
                           clip={"x": 0, "y": 0, "width": self.width,
                                 "height": height, "scale": 1})
        self.out.mkdir(parents=True, exist_ok=True)
        path = self.out / name
        path.write_bytes(base64.b64decode(data["data"]))
        print(f"  {path.relative_to(ROOT)}  {path.stat().st_size // 1024} KB  "
              f"{self.width}x{int(height)}@{self.scale:g}x")


def capture(url: str, out: Path, only: str | None,
            width: int, height: int, scale: float) -> None:
    profile = tempfile.mkdtemp(prefix="lambda-shot-")
    port = 9333
    proc = subprocess.Popen(
        [find_chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--no-first-run", "--no-default-browser-check",
         "--force-prefers-color-scheme=light",
         f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
         "--remote-allow-origins=*",
         f"--window-size={width},{height}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        tab = wait_for_page(port)
        shooter = Shooter(CDP(tab["webSocketDebuggerUrl"]), out, width, height, scale)
        shooter.prepare(url)

        if only in (None, "main"):
            # 主界面：定义 + 结果 + 类型 + 归约轨迹
            shooter.clear()
            shooter.run("id = \\x.x")
            shooter.run("PLUS TWO THREE")
            shooter.run(":type \\f.\\x.f (f x)")
            shooter.click_result()
            shooter.step(4)
            shooter.shot("main.png")

        if only in (None, "ast"):
            # 语法树 + de Bruijn
            shooter.clear()
            shooter.run("id = \\x.x")
            shooter.run("PLUS TWO TWO")
            shooter.run(":type PLUS TWO TWO")
            shooter.click_result()
            shooter.tab("ast")
            shooter.shot("ast.png")

        if only in (None, "env"):
            # 环境面板
            shooter.clear()
            shooter.run("id = \\x.x")
            shooter.run("compose = \\f.\\g.\\x.f (g x)")
            shooter.run("twice = \\f.\\x.f (f x)")
            shooter.tab("env")
            shooter.shot("env.png")

        if only in (None, "guide"):
            # 使用指引（首次访问默认打开）
            shooter.clear()
            shooter.run("PLUS TWO THREE")
            shooter.tab("guide")
            shooter.shot("guide.png")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture light-mode screenshots of the web UI")
    parser.add_argument("--url", default=os.environ.get("LAMBDA_URL", DEFAULT_URL))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--only", choices=["main", "ast", "env", "guide"], default=None)
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=1100)
    parser.add_argument("--scale", type=float, default=2.0)
    args = parser.parse_args()

    check_server(args.url)
    print(f"capturing {args.url} -> {args.out}")
    capture(args.url, args.out, args.only, args.width, args.height, args.scale)
    return 0


if __name__ == "__main__":
    sys.exit(main())
