"""
DeepSeek API Usage Monitor — system tray + dual-theme popup.
"""
import json, os, sys, threading, ctypes, datetime
from ctypes import wintypes

import webview, pystray
from PIL import Image, ImageDraw

from config.settings import Settings
from api.deepseek import DeepSeekPlatform

# ---------------------------------------------------------------------------
# Logging (no sensitive data)
# ---------------------------------------------------------------------------
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.log")

def log(msg: str):
    now = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{now}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except:
        pass

log("=== App started ===")

# ---------------------------------------------------------------------------
# Win32
# ---------------------------------------------------------------------------
class _Accent(ctypes.Structure):
    _fields_ = [("s", ctypes.c_uint), ("f", ctypes.c_uint),
                ("c", ctypes.c_uint), ("a", ctypes.c_uint)]

class _Wca(ctypes.Structure):
    _fields_ = [("a", ctypes.c_int), ("d", ctypes.POINTER(_Accent)),
                ("s", ctypes.c_size_t)]

u32 = ctypes.windll.user32


def find_hwnd():
    return u32.FindWindowW(None, "DeepSeek Monitor")


def apply_acrylic():
    hwnd = find_hwnd()
    if not hwnd:
        return
    try:
        a = _Accent(); a.s = 4; a.f = 2
        d = _Wca(); d.a = 19; d.s = ctypes.sizeof(a); d.d = ctypes.pointer(a)
        u32.SetWindowCompositionAttribute(wintypes.HWND(hwnd), ctypes.pointer(d))
    except Exception as e:
        log(f"Acrylic error: {e}")


def apply_shadow():
    """Enable native drop shadow on the window."""
    hwnd = find_hwnd()
    if not hwnd:
        return
    try:
        # Get current GWL_STYLE
        style = u32.GetWindowLongW(wintypes.HWND(hwnd), -20)  # GWL_EXSTYLE
        # Add WS_EX_NOREDIRECTIONBITMAP for layered windows
        style |= 0x00080000  # CS_DROPSHADOW
        u32.SetClassLongW(wintypes.HWND(hwnd), -26, style)  # GCL_STYLE
    except Exception:
        pass  # Non-critical


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_settings = Settings()
_api = None
_window = None
_visible = True


def _get_platform():
    global _api
    token = (_settings.get_platform_token() or "").replace("Bearer ", "").strip()
    cookie = _settings.get_platform_cookie()
    if token and (_api is None or getattr(_api, 'token', None) != token):
        _api = DeepSeekPlatform(token, cookie)
    return _api if token else None


def _make_icon():
    s = 64
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([4, 4, s - 4, s - 4], fill="#4F6BED")
    d.ellipse([15, 15, s - 15, s - 15], outline="#FFFFFF", width=3)
    d.ellipse([24, 24, s - 24, s - 24], fill="#FFFFFF")
    return img


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------
class Bridge:

    def get_usage_data(self):
        platform = _get_platform()
        if not platform:
            return {"error": "no_token"}
        try:
            result = platform.get_all_usage()
            u = result.get("usage", {})
            log(f"Data OK: models={list(u.get('models',{}).keys())}, days={len(u.get('daily_breakdown',[]))}")
            return result
        except Exception as e:
            log(f"Data error: {e}")
            return {"error": str(e)}

    def get_settings(self):
        return _settings.get_all()

    def save_settings(self, raw: str):
        data = json.loads(raw)
        _settings.save_all(data)
        if _window:
            _window.evaluate_js(
                "try{if(window._onCfg)window._onCfg("
                + json.dumps(data) + ")}catch(e){}")
        return {"success": True}

    def test_platform_token(self, token: str, cookie: str = ""):
        try:
            t = token.replace("Bearer ", "").strip()
            return {"valid": DeepSeekPlatform(t, cookie).test_connection()}
        except Exception:
            return {"valid": False}

    def open_settings(self):
        if _window:
            _window.evaluate_js("if(window.showPanel)showPanel('settings')")

    def hide_window(self):
        global _visible
        if _window:
            _window.hide()
            _visible = False

    def move_to(self, x: int, y: int):
        if _window:
            _window.move(x, y)
            now = datetime.datetime.now()
            if not hasattr(self, '_last_save') or (now - self._last_save).total_seconds() > 1:
                self._last_save = now
                _settings.set("window_x", x)
                _settings.set("window_y", y)

    def get_window_pos(self):
        sx = _settings.get("window_x") or 100
        sy = _settings.get("window_y") or 100
        return {"x": sx, "y": sy}

    def go_back_to_main(self):
        if _window:
            _window.evaluate_js("if(window.showPanel)showPanel('main')")

    def refresh_main(self):
        if _window:
            _window.evaluate_js(
                "if(window.showPanel)showPanel('main');"
                "if(window.refreshData)refreshData()")


# ---------------------------------------------------------------------------
# Tray
# ---------------------------------------------------------------------------
def _on_toggle(icon, item):
    global _visible
    if _visible:
        _window.hide(); _visible = False
    else:
        _window.show(); _visible = True
        threading.Timer(0.3, apply_acrylic).start()

def _on_refresh(icon, item):
    if _window:
        _window.evaluate_js("if(window.refreshData)refreshData()")

def _on_settings(icon, item):
    if _window:
        _window.evaluate_js("if(window.showPanel)showPanel('settings')")

def _on_quit(icon, item):
    icon.stop()
    try: _window.destroy()
    except: pass
    os._exit(0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global _window

    base = os.path.dirname(os.path.abspath(__file__))
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS

    index_html = os.path.join(base, "web", "index.html")
    if not os.path.exists(index_html):
        index_html = os.path.abspath("web/index.html")

    # Tray
    tray = pystray.Icon("dsmon", _make_icon(), "DeepSeek Monitor",
        pystray.Menu(
            pystray.MenuItem("显示/隐藏", _on_toggle, default=True),
            pystray.MenuItem("设置", _on_settings),
            pystray.MenuItem("刷新", _on_refresh),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", _on_quit),
        ))
    threading.Thread(target=tray.run, daemon=True).start()
    log("Tray started")

    # Window
    _window = webview.create_window(
        title="DeepSeek Monitor",
        url=index_html,
        width=400, height=750,
        frameless=True, on_top=True, easy_drag=False,
        js_api=Bridge(),
    )
    log("Window created")

    def on_loaded():
        log("Page loaded")
        # Restore saved position or use default
        sx = _settings.get("window_x") or 100
        sy = _settings.get("window_y") or 100
        _window.move(sx, sy)
        threading.Timer(0.5, apply_acrylic).start()
        threading.Timer(0.8, apply_shadow).start()

    _window.events.loaded += on_loaded

    log("Starting event loop...")
    try:
        webview.start(gui="edgechromium", http_server=True, debug=False)
    except Exception as e:
        log(f"start crashed: {e}")
        import traceback; log(traceback.format_exc())
    log("Event loop ended")


if __name__ == "__main__":
    main()
