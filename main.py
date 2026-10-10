"""
DeepSeek API Usage Monitor — system tray + dual-theme popup.
"""
import json, os, sys, threading, ctypes, datetime, time
from ctypes import wintypes

import webview, pystray
from PIL import Image, ImageDraw

import app_lifecycle
from config.settings import APP_NAME
from config.settings import Settings
from config.settings import SK_KEY_MASK
from api.deepseek import DeepSeekPlatform
from api.deepseek import fetch_balance
import codex_integration
from router import conversation, gateway as gateway_mod, notifier
from router import net_policy, sk_pool, usage_store

# ---------------------------------------------------------------------------
# Logging (no sensitive data)
# ---------------------------------------------------------------------------
def _log_path() -> str:
    """Keep logs beside the config so they survive temp-dir cleanup."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    directory = os.path.join(base, APP_NAME)
    try:
        os.makedirs(directory, exist_ok=True)
        return os.path.join(directory, "app.log")
    except OSError:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "app.log")


LOG_PATH = _log_path()


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


_singleton_handle = None


def _acquire_single_instance() -> bool:
    """Hold a session mutex so duplicated logon triggers cannot stack."""
    global _singleton_handle
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False,
                                   "Local\\DeepSeekMonitor.Singleton")
    if not handle:
        return True
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False
    _singleton_handle = handle
    return True


def _wait_for_singleton(timeout_seconds: float = 8.0) -> bool:
    """Retry because a just terminated build may still hold the mutex."""
    deadline = time.time() + timeout_seconds
    while True:
        if _acquire_single_instance():
            return True
        if time.time() >= deadline:
            return False
        time.sleep(0.2)

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
_gateway = None
_pool = None
_conversations = None
_usage_store = None
_notifier = notifier.Notifier()
_balances = {}
_balance_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Multi-SK gateway
# ---------------------------------------------------------------------------
def _get_price_table():
    return _settings.get("price_table") or usage_store.DEFAULT_PRICE_TABLE


def _apply_net_policy():
    """Apply the saved egress policy and log the chosen source address."""
    net_policy.configure(
        enabled=bool(_settings.get("use_system_proxy")),
        direct_interface=bool(_settings.get("direct_interface")),
        interface_ip=_settings.get("direct_interface_ip") or "",
    )
    log("Egress: system_proxy={} direct_interface={} source={}".format(
        net_policy.use_system_proxy(),
        net_policy.direct_interface_enabled(),
        net_policy.physical_ip() or "system-default"))


def _rebuild_pool():
    global _pool
    entries = _settings.get_sk_pool()
    configs = []
    keys = {}
    for entry in entries:
        sk_id = entry.get("id", "")
        if not sk_id:
            continue
        configs.append(sk_pool.SKConfig(
            id=sk_id,
            name=entry.get("name", sk_id),
            weight=max(int(entry.get("weight", 1) or 1), 1),
            daily_cost_cap=float(entry.get("daily_cost_cap", 0) or 0),
            monthly_cost_cap=float(entry.get("monthly_cost_cap", 0) or 0),
            time_windows=list(entry.get("time_windows") or []),
            is_default=bool(entry.get("is_default", False)),
            is_platform=bool(entry.get("is_platform", False)),
            enabled=bool(entry.get("enabled", True)),
        ))
        keys[sk_id] = entry.get("api_key", "")
    _pool = sk_pool.SKPool(configs, _usage_store)
    for sk in _pool.all():
        sk.api_key = keys.get(sk.cfg.id, "")
        cached = _balances.get(sk.cfg.id)
        if cached is not None:
            sk.balance = cached["balance"]
            sk.is_available = cached["is_available"]


def _build_state():
    global _conversations
    _rebuild_pool()
    if _conversations is None:
        _conversations = conversation.ConversationStore(_pool, _usage_store)
    else:
        _conversations.set_pool(_pool)
    return gateway_mod.GatewayState(
        pool=_pool,
        conversations=_conversations,
        usage=_usage_store,
        notifier=_notifier,
        conversation_cost_limit=float(
            _settings.get("conversation_cost_limit") or 5.0),
    )


def _start_gateway():
    global _gateway, _usage_store
    if _gateway is not None:
        return
    _usage_store = usage_store.UsageStore(price_table=_get_price_table())
    state = _build_state()
    base_port = int(_settings.get("gateway_port") or 8787)
    last_error = None
    for port in range(base_port, base_port + 10):
        try:
            _gateway = gateway_mod.Gateway(state, port=port)
            _gateway.start()
            log(f"Gateway started on 127.0.0.1:{_gateway.port}")
            return
        except OSError as exc:
            last_error = exc
            continue
    log(f"Gateway start failed: {last_error}")


def _refresh_balances():
    if _pool is None:
        return
    for sk in _pool.all():
        if not sk.api_key:
            continue
        try:
            result = fetch_balance(sk.api_key)
        except Exception as exc:
            log(f"Balance fetch error for {sk.cfg.id}: {exc}")
            continue
        if result is None:
            log(f"Balance fetch failed for {sk.cfg.id}")
            continue
        with _balance_lock:
            _balances[sk.cfg.id] = result
            _pool.set_balance(
                sk.cfg.id, result["balance"], result["is_available"])


def _balance_worker():
    while True:
        _refresh_balances()
        interval_minutes = max(
            int(_settings.get("balance_poll_minutes") or 10), 1)
        time.sleep(interval_minutes * 60)


def _kick_balance_refresh():
    thread = threading.Thread(target=_refresh_balances, daemon=True)
    thread.start()


def _register_notifier(tray_icon):
    def tray_sink(kind, message, sk_id):
        try:
            tray_icon.notify(message, title="DeepSeek Monitor")
        except Exception as exc:
            log(f"Tray notify error: {exc}")

    def panel_sink(kind, message, sk_id):
        if _window is None:
            return
        try:
            _window.evaluate_js(
                "try{if(window._onNotify)_onNotify("
                + json.dumps({"kind": kind, "message": message,
                              "sk_id": sk_id})
                + ")}catch(e){}")
        except Exception:
            pass

    _notifier.add_sink(tray_sink)
    _notifier.add_sink(panel_sink)


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

    def log_js(self, message):
        log("JS: {}".format(message))
        return True

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
        global _api
        data = json.loads(raw)
        saved = _settings.save_all(data)
        _apply_net_policy()
        # 出口策略可能变化，丢弃缓存的平台客户端并刷新网关状态
        _api = None
        if _gateway is not None:
            _gateway.set_state(_build_state())
        result = {"success": bool(saved),
                  "auto_start": _settings.auto_start_status()}
        if not saved:
            log("Auto-start entry write failed")
            result["error"] = "开机自启写入失败"
        if _window:
            _window.evaluate_js(
                "try{if(window._onCfg)window._onCfg("
                + json.dumps(data) + ")}catch(e){}")
        return result

    def get_autostart_status(self):
        return _settings.auto_start_status()

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

    def get_gateway_status(self):
        return {
            "running": _gateway is not None,
            "port": _gateway.port if _gateway else None,
            "gateway_port": _settings.get("gateway_port"),
            "conversation_cost_limit": _settings.get(
                "conversation_cost_limit"),
            "balance_poll_minutes": _settings.get("balance_poll_minutes"),
            "price_table": _get_price_table(),
            "codex": codex_integration.status(),
        }

    def get_egress_status(self):
        return {
            "use_system_proxy": net_policy.use_system_proxy(),
            "direct_interface": net_policy.direct_interface_enabled(),
            "source_address": net_policy.physical_ip(),
            "system_proxy": net_policy.https_proxy_url() or "",
        }

    def get_sk_pool(self):
        try:
            result = []
            for entry in _settings.get_sk_pool():
                item = dict(entry)
                item["api_key"] = SK_KEY_MASK if item.get("api_key") else ""
                sk = _pool.get(item["id"]) if _pool else None
                item["balance"] = sk.balance if sk else None
                item["is_available"] = sk.is_available if sk else True
                item["suspended"] = bool(
                    sk and sk.suspended_until > time.time())
                item["is_platform"] = bool(item.get("is_platform", False))
                if _usage_store is not None:
                    item["today_cost"] = _usage_store.today_cost(item["id"])
                    item["month_cost"] = _usage_store.month_cost(item["id"])
                    daily = _usage_store.daily_stats(item["id"])
                    item["today_tokens"] = daily["tokens"]
                    item["today_requests"] = daily["requests"]
                else:
                    item["today_cost"] = 0
                    item["month_cost"] = 0
                    item["today_tokens"] = 0
                    item["today_requests"] = 0
                result.append(item)
            return result
        except Exception as exc:
            import traceback
            log("get_sk_pool error: {}\n{}".format(
                exc, traceback.format_exc()))
            raise

    def get_sk_daily_series(self, sk_id):
        if _usage_store is None:
            return []
        return _usage_store.daily_cost_series(sk_id, days=7)

    def get_sk_detail(self, sk_id):
        if _usage_store is None:
            return {}
        with _balance_lock:
            balance = dict(_balances.get(sk_id) or {})
        return {
            "balance": balance,
            "model_today": _usage_store.model_breakdown(sk_id, month=False),
            "model_month": _usage_store.model_breakdown(sk_id, month=True),
            "token_series": _usage_store.daily_token_series(sk_id, days=7),
            "conversations": _usage_store.conversations_by_sk(
                sk_id, limit=10),
        }

    def save_sk_pool(self, raw):
        entries = json.loads(raw)
        _settings.save_sk_pool(entries)
        if _gateway is not None:
            _gateway.set_state(_build_state())
        _kick_balance_refresh()
        return {"success": True}

    def test_sk(self, api_key):
        try:
            result = fetch_balance(api_key.strip())
            return {
                "valid": result is not None,
                "balance": result["balance"] if result else None,
            }
        except Exception:
            return {"valid": False, "balance": None}

    def get_sk_usage(self):
        totals = _usage_store.sk_totals() if _usage_store else []
        return {"totals": totals}

    def get_conversations(self):
        return _usage_store.conversations(limit=50) if _usage_store else []

    def clear_conversations(self):
        if _usage_store is None:
            return {"cleared": 0}
        return {"cleared": _usage_store.clear_conversations()}

    def get_events(self, limit=50):
        return _usage_store.events(limit=limit) if _usage_store else []

    def apply_codex_gateway(self):
        port = int(_settings.get("gateway_port") or 8787)
        return codex_integration.apply_gateway(port=port)

    def restore_codex_config(self):
        return {"restored": codex_integration.restore()}

    def reload_gateway_config(self):
        if _gateway is not None:
            _gateway.set_state(_build_state())
        return {"success": True}


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
        _window.evaluate_js(
            "if(window.manualRefresh)manualRefresh() "
            "else if(window.refreshData)refreshData()")

def _on_settings(icon, item):
    if _window:
        _window.evaluate_js("if(window.showPanel)showPanel('settings')")

def _on_quit(icon, item):
    global _gateway
    if _gateway is not None:
        try:
            _gateway.stop()
        except Exception:
            pass
    icon.stop()
    try: _window.destroy()
    except: pass
    os._exit(0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global _window

    if not app_lifecycle.take_over(log):
        log("A newer build is already running; exiting")
        return
    if not _wait_for_singleton():
        log("Another instance is already running; exiting")
        return
    _apply_net_policy()
    log("Executable: {} (frozen={})".format(
        sys.executable, getattr(sys, "frozen", False)))
    try:
        if _settings.sync_auto_start():
            log("Auto-start triggers repointed to current executable")
    except OSError as exc:
        log(f"Auto-start sync failed: {exc}")
    status = _settings.auto_start_status()
    log("Auto-start enabled={} registry_ok={} shortcut_ok={}".format(
        status["enabled"], status["registry_ok"], status["shortcut_ok"]))

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
    _register_notifier(tray)
    _start_gateway()
    threading.Thread(target=_balance_worker, daemon=True).start()

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
        _window.show()
        # Restore saved position or use default
        sx = _settings.get("window_x") or 100
        sy = _settings.get("window_y") or 100
        _window.move(sx, sy)
        threading.Timer(0.5, apply_acrylic).start()
        threading.Timer(0.8, apply_shadow).start()

    _window.events.loaded += on_loaded

    log("Starting event loop...")
    _run_ui()


def _run_ui():
    """Retry the UI because WebView2 can still be warming up after logon."""
    for attempt, delay in enumerate((0, 20, 45), start=1):
        if delay:
            log(f"UI retry {attempt} in {delay}s")
            time.sleep(delay)
        try:
            webview.start(gui="edgechromium", http_server=True, debug=False)
            log("Event loop ended")
            return True
        except Exception as exc:
            log(f"start crashed: {exc}")
            import traceback
            log(traceback.format_exc())
    return False


if __name__ == "__main__":
    main()
