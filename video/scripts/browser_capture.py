#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实机浏览器截图与录屏 / Real-browser screenshot and screencast capture.

为宣传片采集真实素材，不重绘界面。统一驱动本机 Chrome + ChromeDriver，
通过 CDP 的 Page.startScreencast 抓帧，再用 ffmpeg 编码为定帧率 MP4。
Capture real assets for the promo film instead of redrawing the UI. It drives
the local Chrome + ChromeDriver, grabs frames through CDP Page.startScreencast
and encodes them into a constant-frame-rate MP4 with ffmpeg.

用法 / Usage
------------
    # 采集两套素材（B 站横屏 + 抖音竖屏），自动启动 Web 服务
    python video/scripts/browser_capture.py --profile both --start-server

    # 只截 B 站主界面静帧 / only the Bilibili main still
    python video/scripts/browser_capture.py --profile bili --only cover --kind shot

    # 抖音竖屏，只录 trace 片段，保留原始帧用于调试
    python video/scripts/browser_capture.py --profile douyin --only trace --keep-frames

依赖 / Requirements
-------------------
    pip install selenium websocket-client
    本机 Chrome 与 chromedriver.exe；ffmpeg 在 PATH 中
    Local Chrome + chromedriver.exe; ffmpeg on PATH

输出 / Output
-------------
    video/public/real/bili/{cover.png, clip-*.mp4, manifest.json}
    video/public/real/douyin/{cover.png, clip-*.mp4, manifest.json}

取景 / Framing
--------------
B 站 profile 用 1920x1080 CSS 像素，完整显示终端 + 检查器
Douyin profile 用 540x960 CSS 像素 @2x，得到 1080x1920 的竖屏素材；
窄屏下页面变成单列并整体滚动，所以每个场景可以指定滚动位置
（top / inspector / deep），让终端或检查器落在安全区内
The Bilibili profile uses 1920x1080 CSS px and shows the full app. The Douyin
profile uses 540x960 CSS px at 2x to produce 1080x1920 vertical footage. On
narrow screens the page becomes a single scrolling column, so each scene can
request a scroll position, keeping the terminal or inspector inside the safe area.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable

try:
    import websocket
except ImportError:  # pragma: no cover
    sys.exit("需要 websocket-client / websocket-client is required:\n"
             "  pip install websocket-client")

ROOT = Path(__file__).resolve().parents[2]
VIDEO = ROOT / "video"
DEFAULT_OUT = VIDEO / "public" / "real"
DEFAULT_URL = "http://127.0.0.1:8081/"

# profile -> 视口与输出尺寸 / viewport and output size
PROFILES = {
    "bili": {
        # Web UI 的实际内容宽约 1140 CSS px，1280 视口刚好填满画面
        # The app caps its content near 1140 CSS px; a 1280 viewport fills the frame.
        "width": 1280,
        "height": 720,
        "scale": 1.5,
        "label": "Bilibili 16:9 landscape",
    },
    "douyin": {
        "width": 540,
        "height": 960,
        "scale": 2,
        "label": "Douyin 9:16 vertical",
    },
}

CANDIDATES = [
    os.environ.get("CHROME_BIN", ""),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
]

DRIVER_CANDIDATES = [
    os.environ.get("CHROMEDRIVER_BIN", ""),
    r"C:\Program Files\Google\Chrome\Application\chromedriver.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chromedriver.exe",
    "/usr/local/bin/chromedriver",
    "/usr/bin/chromedriver",
]


# --------------------------------------------------------------------------
# 环境探测 / environment discovery
# --------------------------------------------------------------------------
def find_binary(candidates: list[str], names: tuple[str, ...], what: str) -> str:
    for path in candidates:
        if path and Path(path).is_file():
            return path
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    sys.exit(f"找不到 {what} / {what} not found; set "
             f"{'CHROME_BIN' if what == 'Chrome' else 'CHROMEDRIVER_BIN'}")


def find_chrome() -> str:
    return find_binary(CANDIDATES, ("google-chrome", "chromium", "microsoft-edge"), "Chrome")


def find_driver() -> str:
    return find_binary(DRIVER_CANDIDATES, ("chromedriver",), "ChromeDriver")


def check_server(url: str) -> bool:
    try:
        urllib.request.urlopen(url + "api/health", timeout=2).read(1)
        return True
    except Exception:  # noqa: BLE001
        return False


def start_server(url: str) -> subprocess.Popen | None:
    """按需要拉起 Flask 服务，返回进程句柄以便退出时清理"""
    if check_server(url):
        return None
    log_path = Path(tempfile.mkstemp(prefix="lambda-web-", suffix=".log")[1])
    log = open(log_path, "ab")
    env = dict(os.environ)
    env["PORT"] = "8081"
    env["HOST"] = "127.0.0.1"
    proc = subprocess.Popen([sys.executable, "web/app.py"], cwd=str(ROOT),
                            env=env, stdout=log, stderr=subprocess.STDOUT)
    log.close()
    deadline = time.time() + 30
    while time.time() < deadline:
        if check_server(url):
            print(f"  web server ready ({url})")
            return proc
        if proc.poll() is not None:
            break
        time.sleep(0.25)
    proc.terminate()
    sys.exit(f"Web 服务启动失败，日志见 {log_path} / web server failed, see {log_path}")


def devtools_port(profile: Path, timeout: float = 25.0) -> int:
    marker = profile / "DevToolsActivePort"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if marker.is_file():
            try:
                return int(marker.read_text(encoding="utf-8").splitlines()[0].strip())
            except (OSError, ValueError, IndexError):
                pass
        time.sleep(0.1)
    raise RuntimeError("Chrome 没有写入调试端口 / Chrome did not publish a DevTools port")


def wait_for_page(port: int, timeout: float = 25.0) -> dict:
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


# --------------------------------------------------------------------------
# 线程化 CDP 客户端 / threaded CDP client
# --------------------------------------------------------------------------
class _Pending:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.msg: dict = {}


class CDP:
    """读取事件与命令响应共用一个线程，录屏时仍可持续 screencastFrameAck"""

    def __init__(self, ws_url: str) -> None:
        self.ws = websocket.create_connection(ws_url, timeout=60,
                                              suppress_origin=True)
        self._send_lock = threading.Lock()
        self._lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self._id = 0
        self._stop = threading.Event()
        self._capture = False
        self.frames: list[tuple[float, str]] = []
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _send(self, obj: dict) -> None:
        with self._send_lock:
            self.ws.send(json.dumps(obj))

    def _read(self) -> None:
        while not self._stop.is_set():
            try:
                raw = self.ws.recv()
            except Exception:  # noqa: BLE001
                break
            if not raw:
                break
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if "id" in msg:
                with self._lock:
                    pending = self._pending.pop(msg["id"], None)
                if pending is not None:
                    pending.msg = msg
                    pending.event.set()
            elif msg.get("method") == "Page.screencastFrame":
                params = msg["params"]
                self._send({"id": -1, "method": "Page.screencastFrameAck",
                            "params": {"sessionId": params["sessionId"]}})
                if self._capture:
                    self.frames.append((time.monotonic(), params["data"]))

    def call(self, method: str, **params):
        self._id += 1
        mid = self._id
        pending = _Pending()
        with self._lock:
            self._pending[mid] = pending
        self._send({"id": mid, "method": method, "params": params})
        if not pending.event.wait(timeout=45):
            raise RuntimeError(f"CDP 超时 / CDP timeout: {method}")
        msg = pending.msg
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg.get("result", {})

    def js(self, expression: str):
        result = self.call("Runtime.evaluate", expression=expression,
                           returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in result:
            detail = result["exceptionDetails"]
            text = detail.get("text", "")
            desc = (detail.get("exception") or {}).get("description", "")
            raise RuntimeError(f"JS 异常 / JS exception: {text} {desc}\n"
                               f"  expression: {expression[:300]}")
        return result.get("result", {}).get("value")

    def close(self) -> None:
        self._stop.set()
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------
# 浏览器封装 / browser wrapper
# --------------------------------------------------------------------------
class Browser:
    def __init__(self, url: str, profile: str, out: Path,
                 headless: bool = True, use_driver: bool = True) -> None:
        self.url = url
        self.profile = profile
        self.meta = PROFILES[profile]
        self.width = self.meta["width"]
        self.height = self.meta["height"]
        self.scale = self.meta["scale"]
        self.out = out
        self.driver = None
        self.proc = None
        self.profile_dir = Path(tempfile.mkdtemp(prefix="lambda-capture-"))
        self.temp_logs: list[Path] = []

        chrome = find_chrome()
        driver = find_driver() if use_driver else ""
        args = [
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            "--force-prefers-color-scheme=light",
            "--remote-debugging-port=0",
            f"--user-data-dir={self.profile_dir}",
            f"--window-size={self.width},{self.height}",
            "--remote-allow-origins=*",
            "about:blank",
        ]
        if headless:
            args.insert(0, "--headless=new")

        try:
            if use_driver and driver:
                from selenium import webdriver
                from selenium.webdriver.chrome.service import Service

                options = webdriver.ChromeOptions()
                options.binary_location = chrome
                for arg in args:
                    options.add_argument(arg)
                service = Service(executable_path=driver)
                service.log_path = str(self.profile_dir / "driver.log")
                self.driver = webdriver.Chrome(service=service, options=options)
                mode = "ChromeDriver"
            else:
                self.proc = subprocess.Popen([chrome] + args,
                                             stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL)
                mode = "CDP"
        except Exception as exc:  # noqa: BLE001
            print(f"  ChromeDriver 启动失败，改用 CDP / driver failed, falling back to CDP: {exc}")
            if self.driver is not None:
                try:
                    self.driver.quit()
                except Exception:  # noqa: BLE001
                    pass
                self.driver = None
            self.proc = subprocess.Popen([chrome] + args,
                                         stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
            mode = "CDP (fallback)"

        port = devtools_port(self.profile_dir)
        tab = wait_for_page(port)
        self.cdp = CDP(tab["webSocketDebuggerUrl"])
        self.cdp.call("Page.enable")
        self.cdp.call("Runtime.enable")
        self.set_viewport(self.width, self.height)
        self.open(url)
        self.prepare_ui()
        print(f"  browser ready via {mode}: {self.width}x{self.height} "
              f"@{self.scale}x -> {self.out_w}x{self.out_h}")

    @property
    def out_w(self) -> int:
        return int(self.width * self.scale)

    @property
    def out_h(self) -> int:
        return int(self.height * self.scale)

    # ---- 页面准备 / page setup -------------------------------------------
    def set_viewport(self, width: int, height: int) -> None:
        self.width, self.height = width, height
        self.cdp.call("Emulation.setDeviceMetricsOverride", width=width,
                      height=height, deviceScaleFactor=self.scale, mobile=False)

    def _wait_ready(self) -> None:
        deadline = time.time() + 20
        while time.time() < deadline:
            if self.cdp.js("document.readyState") == "complete":
                break
            time.sleep(0.2)
        time.sleep(1.2)

    def open(self, url: str) -> None:
        if self.driver is not None:
            self.driver.get(url)
        else:
            self.cdp.call("Page.navigate", url=url)
        self._wait_ready()

    def prepare_ui(self) -> None:
        """中文界面 + 浅色 + 去掉与叙事无关的控件 / Chinese, light, minimal chrome

        发布到中文社区，录屏里只保留中文文本；页脚示例、语言/编码选择、
        分享导出等按钮与画面无关，隐藏后终端与检查器更突出
        For a Chinese-speaking audience the recording shows Chinese only, and
        hiding the example footer and unrelated controls keeps the frame calm.
        """
        self.js("localStorage.setItem('lambda.ui.v2', JSON.stringify("
                "{lang:'zh', theme:'light'}));")
        if self.driver is not None:
            self.driver.refresh()
        else:
            self.cdp.call("Page.reload")
        self._wait_ready()

        self.js("document.documentElement.setAttribute('data-theme','light');"
                "(() => { const s=document.querySelector('header h1 span[style]');"
                "if(s) s.remove(); })()")
        style = (
            "footer, #sel-lang, #sel-encoding, #share, #export, "
            "#static-page, #import, #theme-toggle, #subline "
            "{display:none !important;}"
        )
        self.js("(() => { const s=document.createElement('style');"
                "s.textContent=" + json.dumps(style) + ";"
                "document.head.appendChild(s); })()")
        time.sleep(0.5)

    # ---- 交互 / interactions ---------------------------------------------
    def js(self, expression: str):
        return self.cdp.js(expression)

    def line_count(self) -> int:
        return self.js("document.querySelectorAll('#out .line').length") or 0

    def wait_lines(self, before: int, timeout: float = 15.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.line_count() != before:
                return
            time.sleep(0.1)

    def _dismiss_autocomplete(self, el) -> None:
        """输入后按 Enter 前关掉补全弹窗，否则会被 acceptAc 吃掉

        The app binds Enter to acceptAc while its autocomplete popup is open,
        which silently replaces the typed command with a completion. Escape
        closes the popup first; the global Escape handler only fires when no
        popup is open, so this is safe either way.
        """
        from selenium.webdriver.common.keys import Keys

        el.send_keys(Keys.ESCAPE)

    def cmd(self, text: str, settle: float = 0.45) -> None:
        """真实键盘输入并回车 / type with real keystrokes, then press Enter"""
        before = self.line_count()
        if self.driver is not None:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.common.keys import Keys

            el = self.driver.find_element(By.ID, "cmd")
            el.clear()
            el.send_keys(text)
            self._dismiss_autocomplete(el)
            el.send_keys(Keys.ENTER)
        else:
            payload = json.dumps(text, ensure_ascii=False)
            self.js("(() => { const c=document.getElementById('cmd');"
                    f"c.value={payload};"
                    "c.dispatchEvent(new KeyboardEvent('keydown',"
                    "{key:'Enter',bubbles:true}));})()")
        self.wait_lines(before)
        time.sleep(settle)

    def typed_cmd(self, text: str, char_delay: float = 0.055,
                  settle: float = 0.55) -> None:
        """逐字输入，用于录屏里可见的打字过程 / visible typing for the recording"""
        before = self.line_count()
        if self.driver is not None:
            from selenium.webdriver.common.by import By
            from selenium.webdriver.common.keys import Keys

            el = self.driver.find_element(By.ID, "cmd")
            el.clear()
            for ch in text:
                el.send_keys(ch)
                time.sleep(char_delay)
            self._dismiss_autocomplete(el)
            el.send_keys(Keys.ENTER)
        else:
            payload = json.dumps(text, ensure_ascii=False)
            self.js("(() => { const c=document.getElementById('cmd');"
                    "c.value=''; window.__typing=setInterval(() => {"
                    f"const t={payload}; if(c.value.length>=t.length)"
                    "{clearInterval(window.__typing);return;}"
                    "c.value+=t[c.value.length];"
                    "c.dispatchEvent(new Event('input',{bubbles:true}));"
                    f"}}, {int(char_delay * 1000)});}})()")
            time.sleep(len(text) * char_delay + 0.2)
            self.js("(() => { const c=document.getElementById('cmd');"
                    "c.dispatchEvent(new KeyboardEvent('keydown',"
                    "{key:'Enter',bubbles:true}));})()")
        self.wait_lines(before)
        time.sleep(settle)

    def click(self, selector: str, settle: float = 0.35) -> None:
        """点击控件；控件不存在时只警告，不让整场采集失败

        Click a control; warn instead of aborting the run when it is absent.
        """
        try:
            if self.driver is not None:
                from selenium.webdriver.common.by import By

                self.driver.find_element(By.CSS_SELECTOR, selector).click()
            else:
                self.js(f"document.querySelector({json.dumps(selector)}).click()")
        except Exception:  # noqa: BLE001
            # Selenium 可能被遮挡层拦住，退回 JS 点击
            # Selenium can be blocked by an overlay; fall back to a JS click.
            try:
                self.js(f"(() => {{ const e=document.querySelector("
                        f"{json.dumps(selector)}); if(e) e.click(); }})()")
            except Exception as exc:  # noqa: BLE001
                print(f"    ! 跳过缺失控件 / skipping missing control: {selector} "
                      f"({type(exc).__name__})")
        time.sleep(settle)

    def tab(self, name: str, settle: float = 0.45) -> None:
        self.click(f'[data-tab="{name}"]', settle)

    def click_result(self) -> None:
        self.js("(() => { const r=document.querySelectorAll('#out .line.result');"
                "if(r.length) r[r.length-1].click(); })()")
        time.sleep(0.4)

    def step(self, index: int) -> None:
        self.js("(() => { const s=document.querySelectorAll('.steps-list .st');"
                f"if(s.length>{index}) s[{index}].click(); }})()")
        time.sleep(0.35)

    def clear(self) -> None:
        self.click("#clear", 0.7)

    def frame(self, where: str) -> None:
        """竖屏取景：滚动页面，让终端或检查器进入画面"""
        if self.profile != "douyin":
            return
        offsets = {"top": 0, "terminal": 0, "inspector": 650, "deep": 1150}
        y = offsets.get(where, 0)
        self.js(f"window.scrollTo(0,{y})")
        time.sleep(0.35)

    def close_modal(self) -> None:
        """关闭可能残留的对话框 / close any leftover dialog"""
        self.js("(() => { const m=document.getElementById('modal');"
                "if(m && m.classList.contains('open')){"
                "const c=document.getElementById('modal-cancel');"
                "if(c) c.click();} })()")
        time.sleep(0.25)

    def modal_input(self, text: str) -> None:
        """等待工具对话框出现，填入表达式并确认 / wait for the Tools dialog, fill and accept"""
        deadline = time.time() + 10
        while time.time() < deadline:
            if self.js("(() => { const m=document.getElementById('modal');"
                       "return !!(m && m.classList.contains('open')); })()"):
                break
            time.sleep(0.2)
        expr = (
            "(() => {"
            "const i = document.getElementById('modal-input');"
            "if (i) {"
            "i.value = " + json.dumps(text, ensure_ascii=False) + ";"
            "i.dispatchEvent(new Event('input', {bubbles: true}));"
            "document.getElementById('modal-ok').click();"
            "}"
            "})()"
        )
        self.js(expr)
        deadline = time.time() + 10
        while time.time() < deadline:
            if not self.js("(() => { const m=document.getElementById('modal');"
                           "return !!(m && m.classList.contains('open')); })()"):
                break
            time.sleep(0.2)
        time.sleep(0.4)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    # ---- 采集 / capture ---------------------------------------------------
    def shot(self, name: str) -> Path:
        data = self.cdp.call("Page.captureScreenshot", format="png",
                             captureBeyondViewport=False,
                             clip={"x": 0, "y": 0, "width": self.width,
                                   "height": self.height, "scale": self.scale})
        self.out.mkdir(parents=True, exist_ok=True)
        path = self.out / name
        path.write_bytes(base64.b64decode(data["data"]))
        print(f"    {path.relative_to(ROOT)}  "
              f"{path.stat().st_size // 1024} KB  {self.out_w}x{self.out_h}")
        return path

    def record(self, name: str, actions: Callable[["Browser"], None],
               fps: int = 30, keep_frames: bool = False) -> Path:
        frames = Path(tempfile.mkdtemp(prefix="lambda-frames-"))
        self.cdp.frames.clear()
        self.cdp._capture = True
        try:
            self.cdp.call("Page.startScreencast", format="jpeg", quality=88,
                          everyNthFrame=1, maxWidth=self.out_w,
                          maxHeight=self.out_h)
            t0 = time.monotonic()
            actions(self)
            # 让最后一帧到达 / let the final frames arrive
            time.sleep(0.4)
            self.cdp.call("Page.stopScreencast")
            self.cdp._capture = False
            time.sleep(0.2)
            frames_got = sorted(self.cdp.frames)
        except Exception:
            self.cdp._capture = False
            raise

        if len(frames_got) < 2:
            raise RuntimeError(f"录屏只拿到 {len(frames_got)} 帧 / only got "
                               f"{len(frames_got)} frames for {name}")

        # 用真实到达时间写 concat 列表，避免帧率抖动导致快放
        # Write the concat list with real arrival times so variable screencast
        # cadence does not speed up the result.
        lines: list[str] = []
        for i, (ts, data) in enumerate(frames_got):
            (frames / f"frame-{i:05d}.jpg").write_bytes(base64.b64decode(data))
            if i + 1 < len(frames_got):
                dur = frames_got[i + 1][0] - ts
            else:
                dur = 0.6
            # 不要压缩长间隔，否则静态片段会被快放
            # Never cap short: doing so would fast-forward through static holds.
            dur = max(0.01, min(dur, 30.0))
            lines.append(f"file 'frame-{i:05d}.jpg'\nduration {dur:.4f}")
        lines.append(f"file 'frame-{len(frames_got) - 1:05d}.jpg'")
        (frames / "list.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

        self.out.mkdir(parents=True, exist_ok=True)
        target = self.out / name
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat",
               "-safe", "0", "-i", "list.txt",
               # screencast 以 CSS 像素出帧，需要放大到目标分辨率
               # Screencast frames arrive at CSS resolution; upscale to target.
               "-vf", f"fps={fps},scale={self.out_w}:{self.out_h},format=yuv420p",
               "-c:v", "libx264", "-preset", "medium", "-crf", "20",
               "-movflags", "+faststart", str(target)]
        subprocess.run(cmd, cwd=str(frames), check=True)
        duration = max(ts - t0 for ts, _ in frames_got)
        print(f"    {target.relative_to(ROOT)}  "
              f"{target.stat().st_size // 1024} KB  {self.out_w}x{self.out_h}  "
              f"~{duration:.1f}s  {len(frames_got)} frames")
        if keep_frames:
            kept = self.out / (Path(name).stem + "-frames")
            if kept.exists():
                shutil.rmtree(kept)
            shutil.move(str(frames), str(kept))
        else:
            shutil.rmtree(frames, ignore_errors=True)
        return target

    def close(self) -> None:
        try:
            self.cdp.close()
        except Exception:  # noqa: BLE001
            pass
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:  # noqa: BLE001
                pass
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                self.proc.kill()
        shutil.rmtree(self.profile_dir, ignore_errors=True)


# --------------------------------------------------------------------------
# 场景 / scenes
# --------------------------------------------------------------------------
def s_cover(b: Browser) -> None:
    b.clear()
    b.cmd("PLUS TWO THREE")
    b.click_result()
    b.step(4)
    b.frame("top")


def s_intro(b: Browser) -> None:
    b.clear()
    b.frame("top")
    b.typed_cmd("id = \\x.x")
    b.typed_cmd("PLUS TWO THREE")
    b.click_result()
    b.sleep(0.8)


def s_trace(b: Browser) -> None:
    b.clear()
    b.cmd("PLUS TWO THREE")
    b.click_result()
    b.frame("inspector" if b.profile == "douyin" else "top")
    total = b.js("(() => { const r=document.querySelector('#tr-range');"
                 "return r ? Number(r.max) : 0; })()") or 0
    for i in range(int(total) + 1):
        b.js(f"(() => {{ const r=document.querySelector('#tr-range');"
             f"if(r){{ r.value={i};"
             "r.dispatchEvent(new Event('input',{bubbles:true})); } })()")
        b.sleep(0.55)


def s_manual(b: Browser) -> None:
    b.clear()
    b.cmd(":begin (\\x.x) ((\\y.y) z)")
    b.frame("inspector" if b.profile == "douyin" else "top")
    b.sleep(0.5)
    b.click("#m-step", 0.8)
    b.click(".redex-btn", 0.8)
    b.click("#m-step", 0.8)
    b.sleep(0.6)


def s_ast(b: Browser) -> None:
    b.clear()
    b.cmd("PLUS TWO TWO")
    b.click_result()
    b.tab("ast")
    b.frame("inspector" if b.profile == "douyin" else "top")
    b.sleep(1.0)


def s_type(b: Browser) -> None:
    b.clear()
    b.cmd(":type \\f.\\x.f (f x)")
    b.tab("type")
    b.frame("inspector" if b.profile == "douyin" else "top")
    b.sleep(1.0)


def s_env(b: Browser) -> None:
    b.clear()
    b.cmd("compose = \\f.\\g.\\x.f (g x)")
    b.cmd("twice = \\f.\\x.f (f x)")
    b.cmd("id = \\x.x")
    b.tab("env")
    b.frame("inspector" if b.profile == "douyin" else "top")
    b.sleep(0.9)


def s_race(b: Browser) -> None:
    b.clear()
    b.tab("tools")
    b.click('[data-tool="race"]', 0.5)
    b.modal_input("PLUS TWO THREE")
    b.tab("race")
    b.frame("inspector" if b.profile == "douyin" else "top")
    b.sleep(1.0)


def s_fast(b: Browser) -> None:
    b.clear()
    b.cmd(":fast on")
    b.typed_cmd("MULT FIVE SIX")
    b.frame("top")
    b.sleep(0.8)


def s_guide(b: Browser) -> None:
    b.clear()
    b.tab("guide")
    b.frame("inspector" if b.profile == "douyin" else "top")
    for _ in range(2 if b.profile == "douyin" else 3):
        b.js("(() => { const p=document.getElementById('panel');"
             "if(p) p.scrollTop += Math.round(p.clientHeight * 0.8); })()")
        b.sleep(0.7)


# key -> (kind, profiles, action)
SCENES: dict[str, tuple[str, tuple[str, ...], Callable[[Browser], None]]] = {
    "cover":  ("shot", ("bili", "douyin"), s_cover),
    "intro":  ("clip", ("bili", "douyin"), s_intro),
    "trace":  ("clip", ("bili", "douyin"), s_trace),
    "manual": ("clip", ("bili",), s_manual),
    "ast":    ("clip", ("bili", "douyin"), s_ast),
    "type":   ("clip", ("bili", "douyin"), s_type),
    "env":    ("clip", ("bili",), s_env),
    "race":   ("clip", ("bili", "douyin"), s_race),
    "fast":   ("clip", ("bili",), s_fast),
    "guide":  ("clip", ("bili", "douyin"), s_guide),
}


def capture_profile(url: str, out: Path, profile: str, only: list[str] | None,
                    kind: str | None, headless: bool, use_driver: bool,
                    keep_frames: bool, fps: int) -> None:
    dest = out / profile
    dest.mkdir(parents=True, exist_ok=True)
    selected = [k for k in SCENES
                if (only is None or k in only)
                and profile in SCENES[k][1]
                and (kind is None or SCENES[k][0] == kind)]
    if not selected:
        print(f"  [{profile}] 没有匹配场景 / no matching scenes")
        return

    print(f"[{profile}] {PROFILES[profile]['label']} -> {dest}")
    browser = Browser(url, profile, dest, headless=headless, use_driver=use_driver)
    manifest: dict = {
        "profile": profile,
        "width": browser.out_w,
        "height": browser.out_h,
        "scenes": [],
    }
    try:
        for key in selected:
            scene_kind, _, action = SCENES[key]
            print(f"  scene: {key} ({scene_kind})")
            browser.close_modal()
            action_start = time.monotonic()
            if scene_kind == "shot":
                # 静帧场景也要先摆好画面，但不要占用录屏
                action(browser)
                path = browser.shot("cover.png")
            else:
                path = browser.record(f"clip-{key}.mp4", action, fps=fps,
                                      keep_frames=keep_frames)
            manifest["scenes"].append({
                "key": key,
                "kind": scene_kind,
                "file": path.name,
                "seconds": round(time.monotonic() - action_start, 2),
            })
    finally:
        browser.close()

    (dest / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture real browser screenshots and screencasts for the promo")
    parser.add_argument("--url", default=os.environ.get("LAMBDA_URL", DEFAULT_URL))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--profile", choices=["bili", "douyin", "both"], default="both")
    parser.add_argument("--only", default=None,
                        help="逗号分隔的场景名 / comma-separated scene keys")
    parser.add_argument("--kind", choices=["shot", "clip"], default=None)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--start-server", action="store_true",
                        help="未启动时自动运行 web/app.py")
    parser.add_argument("--headed", action="store_true",
                        help="显示浏览器窗口 / show the browser window")
    parser.add_argument("--no-driver", action="store_true",
                        help="跳过 ChromeDriver，直接用 CDP 启动 Chrome")
    parser.add_argument("--keep-frames", action="store_true",
                        help="保留录屏原始帧 / keep raw screencast frames")
    parser.add_argument("--list", action="store_true", help="列出场景并退出")
    args = parser.parse_args()

    if args.list:
        for key, (kind, profiles, _) in SCENES.items():
            print(f"{key:8s} {kind:4s} {', '.join(profiles)}")
        return 0

    url = args.url.rstrip("/") + "/"
    server = start_server(url) if args.start_server else None
    if not check_server(url):
        sys.exit(f"无法访问 {url} / cannot reach {url}; "
                 "先运行 python web/app.py 或加 --start-server")

    profiles = ["bili", "douyin"] if args.profile == "both" else [args.profile]
    only = [s.strip() for s in args.only.split(",")] if args.only else None
    try:
        for profile in profiles:
            capture_profile(url, args.out, profile, only, args.kind,
                            not args.headed, not args.no_driver,
                            args.keep_frames, args.fps)
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except Exception:  # noqa: BLE001
                server.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
