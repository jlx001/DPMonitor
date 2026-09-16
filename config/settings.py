import json
import os
import subprocess
import sys

import keyring
import keyring.errors

from router.usage_store import DEFAULT_PRICE_TABLE

APP_NAME = "DeepSeekMonitor"
KEYRING_SERVICE = "DeepSeekMonitor"
SK_KEY_MASK = "********"
AUTOSTART_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_SHORTCUT = APP_NAME + ".lnk"
CREATE_NO_WINDOW = 0x08000000
CONFIG_VERSION = 3

DEFAULT_CONFIG = {
    "refresh_interval_minutes": 10,
    "auto_start": False,
    "alert_enabled": False,
    "alert_balance_threshold": 10.0,
    "alert_daily_threshold": 50.0,
    "hidden_models": [],
    "_version": CONFIG_VERSION,
    "theme": "glass",
    "window_width": 400,
    "window_height": 680,
    "window_x": None,
    "window_y": None,
    "gateway_port": 8787,
    "conversation_cost_limit": 5.0,
    "balance_poll_minutes": 10,
    "sk_pool": [],
    "price_table": DEFAULT_PRICE_TABLE,
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


def _set_cred(username: str, password: str):
    try:
        keyring.set_password(KEYRING_SERVICE, username, password)
    except keyring.errors.KeyringError:
        pass


def _delete_cred(username: str):
    try:
        keyring.delete_password(KEYRING_SERVICE, username)
    except keyring.errors.PasswordDeleteError:
        pass


class Settings:

    def __init__(self):
        self._path = _config_path()
        self._ensure_defaults()
        self._migrate()

    def _ensure_defaults(self):
        if not os.path.exists(self._path):
            self._write(DEFAULT_CONFIG.copy())

    def _migrate(self):
        """Adopt the per-model price list and drop the old flat one."""
        data = self._read()
        if data.get("_version", 0) >= CONFIG_VERSION:
            return
        data["price_table"] = DEFAULT_PRICE_TABLE
        data["_version"] = CONFIG_VERSION
        self._write(data)

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

    # --- SK pool ---
    def get_sk_pool(self):
        pool = self.get("sk_pool") or []
        result = []
        for entry in pool:
            item = dict(entry)
            item["api_key"] = _get_cred("sk_pool:{}".format(item.get("id", "")))
            result.append(item)
        return result

    def save_sk_pool(self, entries):
        previous_ids = {
            entry.get("id")
            for entry in (self.get("sk_pool") or [])
        }
        safe = []
        for entry in entries:
            item = dict(entry)
            raw_key = item.pop("api_key", "") or ""
            sk_id = item.get("id", "")
            if raw_key and raw_key != SK_KEY_MASK:
                _set_cred("sk_pool:{}".format(sk_id), raw_key)
            safe.append(item)
        current_ids = {entry.get("id") for entry in safe}
        for removed_id in previous_ids - current_ids:
            _delete_cred("sk_pool:{}".format(removed_id))
        self.set("sk_pool", safe)

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
            try:
                self.set_auto_start(auto_start)
            except OSError:
                return False
        return True

    # --- Auto-start ---
    @staticmethod
    def _auto_start_target():
        """Executable and arguments that launch this build."""
        if getattr(sys, "frozen", False):
            return sys.executable, ""
        project_root = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))
        return sys.executable, os.path.join(project_root, "main.py")

    @classmethod
    def _auto_start_command(cls):
        target, arguments = cls._auto_start_target()
        if arguments:
            return '"{}" "{}"'.format(target, arguments)
        return '"{}"'.format(target)

    @staticmethod
    def _startup_shortcut_path():
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        folder = os.path.join(base, "Microsoft", "Windows", "Start Menu",
                              "Programs", "Startup")
        return os.path.join(folder, AUTOSTART_SHORTCUT)

    @staticmethod
    def _powershell_quote(text: str) -> str:
        return "'" + str(text).replace("'", "''") + "'"

    def _write_startup_shortcut(self) -> bool:
        """Mirror the logon trigger into the Startup folder."""
        target, arguments = self._auto_start_target()
        shortcut = self._startup_shortcut_path()
        folder = os.path.dirname(shortcut)
        if not os.path.isdir(folder):
            return False
        shell = os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"), "System32",
            "WindowsPowerShell", "v1.0", "powershell.exe")
        if not os.path.exists(shell):
            shell = "powershell.exe"
        script = (
            "$ws = New-Object -ComObject WScript.Shell;"
            "$lnk = $ws.CreateShortcut({shortcut});"
            "$lnk.TargetPath = {target};"
            "$lnk.Arguments = {arguments};"
            "$lnk.WorkingDirectory = {workdir};"
            "$lnk.Save()"
        ).format(
            shortcut=self._powershell_quote(shortcut),
            target=self._powershell_quote(target),
            arguments=self._powershell_quote(arguments),
            workdir=self._powershell_quote(
                os.path.dirname(arguments or target)),
        )
        try:
            subprocess.run(
                [shell, "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-Command", script],
                timeout=30, creationflags=CREATE_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            return False
        return os.path.exists(shortcut)

    def _remove_startup_shortcut(self):
        try:
            os.remove(self._startup_shortcut_path())
        except OSError:
            pass

    @staticmethod
    def _read_auto_start():
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                AUTOSTART_KEY_PATH, 0,
                                winreg.KEY_READ) as key:
                value, _ = winreg.QueryValueEx(key, APP_NAME)
                return value
        except FileNotFoundError:
            return None

    @staticmethod
    def _write_auto_start(command: str):
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,
                                AUTOSTART_KEY_PATH, 0,
                                winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)

    @staticmethod
    def _remove_auto_start():
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                AUTOSTART_KEY_PATH, 0,
                                winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, APP_NAME)
        except FileNotFoundError:
            pass

    def sync_auto_start(self):
        """Repoint both logon triggers at this build's executable."""
        if not self.get("auto_start"):
            return False
        command = self._auto_start_command()
        changed = False
        # A source-tree run must not replace a working frozen entry, so only
        # a frozen build or a dangling entry rewrites the Run value.
        try:
            current = self._read_auto_start()
            if current != command and (
                    getattr(sys, "frozen", False)
                    or self._is_dangling_command(current)):
                self._write_auto_start(command)
                current = command
                changed = True
        except OSError:
            return changed
        if current == command and not os.path.exists(
                self._startup_shortcut_path()):
            if self._write_startup_shortcut():
                changed = True
        return changed

    @staticmethod
    def _is_dangling_command(command) -> bool:
        """True when a registered command points at a deleted file."""
        if not command:
            return True
        text = str(command).strip()
        if text.startswith('"'):
            target = text[1:].split('"', 1)[0]
        else:
            target = text.split(" ", 1)[0]
        return not os.path.exists(target)

    def auto_start_status(self) -> dict:
        """Current logon-trigger state, for the settings panel."""
        command = self._auto_start_command()
        target, _ = self._auto_start_target()
        try:
            registry_command = self._read_auto_start()
        except OSError:
            registry_command = None
        shortcut = self._startup_shortcut_path()
        return {
            "enabled": bool(self.get("auto_start")),
            "command": command,
            "target_exists": os.path.exists(target),
            "registry_command": registry_command,
            "registry_ok": registry_command == command,
            "shortcut_path": shortcut,
            "shortcut_ok": os.path.exists(shortcut),
        }

    def set_auto_start(self, enable: bool):
        """Register or remove both logon triggers, verifying the write."""
        if enable:
            command = self._auto_start_command()
            self._write_auto_start(command)
            if self._read_auto_start() == command:
                self._write_startup_shortcut()
        else:
            self._remove_auto_start()
            self._remove_startup_shortcut()
        self.set("auto_start", enable)
        return self.auto_start_status()
