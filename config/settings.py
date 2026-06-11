import json
import os
import sys

import keyring
import keyring.errors

APP_NAME = "DeepSeekMonitor"
KEYRING_SERVICE = "DeepSeekMonitor"

DEFAULT_CONFIG = {
    "refresh_interval_minutes": 10,
    "auto_start": False,
    "alert_enabled": False,
    "alert_balance_threshold": 10.0,
    "alert_daily_threshold": 50.0,
    "visible_models": ["deepseek-v4-flash", "deepseek-v4-pro"],
    "_version": 2,
    "theme": "glass",
    "window_width": 400,
    "window_height": 680,
    "window_x": None,
    "window_y": None,
}


def _config_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.path.expanduser("~/.config")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def _config_path():
    return os.path.join(_config_dir(), "config.json")


def _get_cred(username: str) -> str:
    try:
        cred = keyring.get_credential(KEYRING_SERVICE, username)
        return cred.password if cred else ""
    except keyring.errors.KeyringError:
        return ""


class Settings:

    def __init__(self):
        self._path = _config_path()
        self._ensure_defaults()

    def _ensure_defaults(self):
        if not os.path.exists(self._path):
            self._write(DEFAULT_CONFIG.copy())

    def _read(self):
        with open(self._path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data):
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # --- API Key ---
    def get_api_key(self):
        return _get_cred("api_key")

    def set_api_key(self, key: str):
        if key:
            keyring.set_password(KEYRING_SERVICE, "api_key", key)
        else:
            try: keyring.delete_password(KEYRING_SERVICE, "api_key")
            except keyring.errors.PasswordDeleteError: pass

    # --- Platform Token ---
    def get_platform_token(self):
        return _get_cred("platform_token")

    def set_platform_token(self, token: str):
        if token:
            keyring.set_password(KEYRING_SERVICE, "platform_token", token)
        else:
            try: keyring.delete_password(KEYRING_SERVICE, "platform_token")
            except keyring.errors.PasswordDeleteError: pass

    # --- Platform Cookie ---
    def get_platform_cookie(self):
        return _get_cred("platform_cookie")

    def set_platform_cookie(self, cookie: str):
        if cookie:
            keyring.set_password(KEYRING_SERVICE, "platform_cookie", cookie)
        else:
            try: keyring.delete_password(KEYRING_SERVICE, "platform_cookie")
            except keyring.errors.PasswordDeleteError: pass

    # --- General settings ---
    def get(self, key: str):
        data = self._read()
        return data.get(key, DEFAULT_CONFIG.get(key))

    def set(self, key: str, value):
        data = self._read()
        data[key] = value
        self._write(data)

    def get_all(self):
        data = self._read()
        data["api_key"] = self.get_api_key()
        data["platform_token"] = self.get_platform_token()
        data["platform_cookie"] = self.get_platform_cookie()
        return data

    def save_all(self, new_data: dict):
        api_key = new_data.pop("api_key", None)
        platform_token = new_data.pop("platform_token", None)
        platform_cookie = new_data.pop("platform_cookie", None)
        if api_key is not None:
            self.set_api_key(api_key)
        if platform_token is not None:
            self.set_platform_token(platform_token)
        if platform_cookie is not None:
            self.set_platform_cookie(platform_cookie)
        auto_start = new_data.pop("auto_start", None)
        current = self._read()
        current.update(new_data)
        self._write(current)
        if auto_start is not None:
            self.set_auto_start(auto_start)

    # --- Auto-start ---
    def set_auto_start(self, enable: bool):
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        if enable:
            app_path = sys.argv[0] if getattr(sys, 'frozen', False) else sys.executable
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{app_path}"')
        else:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE) as key:
                    winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        self.set("auto_start", enable)
