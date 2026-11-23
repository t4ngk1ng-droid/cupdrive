#!/usr/bin/env python3
"""
webapp.py — cupdrive 桌面版（浏览器壳）

Python 只做两件事：BLE 和曲线加工。界面是本地网页，
由内置 HTTP 服务提供，用 Edge/Chrome 的 --app 模式打开成独立窗口。

为什么不用 pywebview
──────────────────────────────────────────────────────────────
pywebview 在 Windows 上依赖 pythonnet + WinForms，PyInstaller
打包后 pythonnet 加载失败（Failed to resolve
Python.Runtime.Loader.Initialize），分发版本跑不起来。
换成 HTTP + 浏览器后，打包只依赖 bleak / numpy，能稳定出 exe。

用法
──────────────────────────────────────────────────────────────
    python webapp.py                 启动并打开窗口
    python webapp.py --check         后端自检，不启动服务
    python webapp.py --selftest      启动服务 → 调 API → 退出
    python webapp.py --no-browser    只启动服务，不开浏览器
    python webapp.py --port 8123     固定端口
"""

import os
import sys
import json
import time
import glob
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# ── 路径 ───────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    RES_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    APP_DIR = os.path.dirname(sys.executable)
    if sys.stdout is None:
        _log = open(os.path.join(APP_DIR, "cupdrive.log"), "a",
                    encoding="utf-8", buffering=1)
        sys.stdout = _log
        sys.stderr = _log
else:
    RES_DIR = APP_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, RES_DIR)
os.chdir(APP_DIR)

from cupdrive.service import Core, DEFAULT_CHANS, SLEW
from cupdrive import ble as BLE

CURVES_DIR = os.path.join(APP_DIR, "curves")
EXAMPLES_DIR = os.path.join(RES_DIR, "examples")
UI_DIR = os.path.join(RES_DIR, "ui")
WEB_DIR = os.path.join(RES_DIR, "web")

# 只允许这些方法被 HTTP 调用。import_script 之类涉及任意路径的
# 方法不开放。
ALLOWED = {
    "scan", "connect", "mock", "disconnect", "status", "set_params",
    "send", "stop", "panic", "list_curves", "load_curve", "import_data",
}


# ══════════════════════════════════════════════════════════════
#  HTTP
# ══════════════════════════════════════════════════════════════
def make_handler(core: Core, debug=False):
    class Handler(BaseHTTPRequestHandler):
        server_version = "cupdrive"

        def log_message(self, fmt, *args):
            if debug:
                sys.stdout.write("[http] " + (fmt % args) + "\n")

        def _raw(self, body, ctype, code=200):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionAbortedError):
                pass

        def _json(self, obj, code=200):
            self._raw(json.dumps(obj, ensure_ascii=False),
                      "application/json; charset=utf-8", code)

        def _file(self, path, ctype):
            try:
                with open(path, "rb") as f:
                    self._raw(f.read(), ctype)
            except OSError:
                self._json({"ok": False, "error": "not found"}, 404)

        def do_GET(self):
            core.touch()
            p = urlparse(self.path).path
            if p == "/api/status":
                self._json(core.status())
            elif p == "/api/list_curves":
                self._json(core.list_curves())
            elif p in ("/", "/index.html"):
                self._file(os.path.join(UI_DIR, "app.html"), "text/html; charset=utf-8")
            elif p in ("/marker", "/marker/"):
                self._file(os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8")
            elif p == "/favicon.ico":
                self._raw(b"", "image/x-icon", 204)
            else:
                self._json({"ok": False, "error": "not found"}, 404)

        def do_POST(self):
            core.touch()
            p = urlparse(self.path).path
            if p == "/api/quit":
                self._json({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return

            if not p.startswith("/api/"):
                self._json({"ok": False, "error": "not found"}, 404)
                return

            method = p[5:]
            if method not in ALLOWED:
                self._json({"ok": False, "error": "unknown method"}, 404)
                return

            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    body = {}
            except Exception:
                body = {}

            fn = getattr(core, method)
            try:
                self._json(fn(**body))
            except TypeError as e:
                self._json({"ok": False, "error": str(e)}, 400)
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, 500)

    return Handler


# ══════════════════════════════════════════════════════════════
#  浏览器
# ══════════════════════════════════════════════════════════════
def find_browser():
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    pf_local = os.environ.get("LOCALAPPDATA", "")
    for p in (
        os.path.join(pf86, r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(pf, r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(pf, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(pf86, r"Google\Chrome\Application\chrome.exe"),
        os.path.join(pf_local, r"Google\Chrome\Application\chrome.exe"),
    ):
        if os.path.isfile(p):
            return p
    return None


def launch_ui(url):
    """用 ShellExecute 打开浏览器窗口。

    直接 subprocess.Popen 一个 Edge 在 PyInstaller --noconsole 的 exe 里
    不会建窗口（进程起来又退出）；ShellExecute 经过 Explorer，和双击
    快捷方式等价，窗口一定出现。
    """
    browser = find_browser()
    if browser:
        try:
            import ctypes
            r = ctypes.windll.shell32.ShellExecuteW(
                None, "open", browser,
                f"--app={url} --window-size=1300,880", None, 1)
            if r > 32:
                return True
            print("[launch] ShellExecute returned", r)
        except Exception as e:
            print("[launch] ShellExecute failed:", e)
    try:
        os.startfile(url)
        return True
    except Exception as e:
        print("[launch] startfile failed:", e)
        return False


def idle_watch(server, core, seconds=120):
    """浏览器关掉后前端不再轮询，空闲超时就退出进程。"""
    while True:
        time.sleep(5)
        if time.time() - core.last_request > seconds:
            try:
                server.shutdown()
            except Exception:
                pass
            return


# ══════════════════════════════════════════════════════════════
#  自检
# ══════════════════════════════════════════════════════════════
def check():
    print("=" * 64)
    print("cupdrive · 后端自检")
    print("=" * 64)
    print(f"\n[1] Python {sys.version.split()[0]}")
    print(f"    {sys.executable}")
    print(f"    frozen={getattr(sys, 'frozen', False)}")

    print("\n[2] 依赖")
    for mod in ("bleak", "numpy"):
        try:
            __import__(mod)
            print(f"    {mod:8s} OK")
        except Exception as e:
            print(f"    {mod:8s} FAIL {e}")

    core = Core(CURVES_DIR, EXAMPLES_DIR)
    core.ensure_example()

    print("\n[3] 曲线")
    cs = core.list_curves()
    for c in cs[:10]:
        print(f"    {c['name']:28s} {c['points']:5d} 点  "
              f"{c['hz']}Hz  {c['duration']:7.1f}s")
    if not cs:
        print("    （空）")

    print("\n[4] 安全护栏 + Mock")
    core.mock()
    print("    ", core.set_params("0,1,2", 1e9))
    for vals in ((0, 0, 0, 0), (100, 100, 100, 0)):
        core.send(*vals)
        st = core.status()
        print(f"    请求 {vals} → 实际 {st['last']}  "
              f"帧 {st['frame'][:24]}…")
    print("    上限:", {BLE.CH_NAMES.get(int(k), k): v
                        for k, v in core.status()["caps"].items()})

    if cs:
        d = core.load_curve(cs[0]["path"])
        print(f"\n[5] 载入 {d['name']}: {len(d['b'])} 点, 首值 {d['b'][:3]}")

    core.shutdown()
    print("\n" + "=" * 64)
    print("自检完成。启动:  python webapp.py")
    return 0


def _post(url, method, **kw):
    req = urllib.request.Request(
        f"{url}api/{method}",
        data=json.dumps(kw).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _get(url, path):
    with urllib.request.urlopen(url + path.lstrip("/"), timeout=30) as r:
        return r.status, r.read()


def selftest(url):
    ok = True

    def step(name, cond, extra=""):
        nonlocal ok
        print(f"[selftest] {name}: {'OK' if cond else 'FAIL'} {extra}")
        ok = ok and bool(cond)

    status_, html = _get(url, "/")
    step("page", status_ == 200 and b"cupdrive" in html, f"{len(html)} bytes")

    curves = json.loads(_get(url, "/api/list_curves")[1])
    step("curves", len(curves) > 0, str([c["name"] for c in curves]))

    step("mock", _post(url, "mock").get("ok"))
    step("params", _post(url, "set_params", chans="0,1,2", slew=1e9).get("ok"))
    _post(url, "send", v0=100, v1=100, v2=100, v3=0)
    st = _post(url, "status")
    step("hard caps", st["last"] == [40, 55, 35, 0], str(st["last"]))
    _post(url, "panic")
    st = _post(url, "status")
    step("panic", st["last"] == [0, 0, 0, 0], str(st["last"]))

    print("[selftest] OK" if ok else "[selftest] FAIL")
    return ok


# ══════════════════════════════════════════════════════════════
#  主入口
# ══════════════════════════════════════════════════════════════
def main():
    if "--check" in sys.argv:
        return check()

    core = Core(CURVES_DIR, EXAMPLES_DIR)
    core.ensure_example()

    port = 0
    if "--port" in sys.argv:
        i = sys.argv.index("--port")
        if i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])

    httpd = ThreadingHTTPServer(("127.0.0.1", port),
                                make_handler(core, "--debug" in sys.argv))
    httpd.daemon_threads = True
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"

    print("=" * 64)
    print(f"cupdrive  http://127.0.0.1:{httpd.server_address[1]}/")
    print(f"曲线目录  {CURVES_DIR}")
    print("=" * 64)

    if "--selftest" in sys.argv:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        ok = selftest(url)
        httpd.shutdown()
        core.shutdown()
        return 0 if ok else 1

    if "--no-browser" not in sys.argv:
        launch_ui(url)

    threading.Thread(target=idle_watch, args=(httpd, core, 120),
                     daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        core.shutdown()
        print("cupdrive 退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
