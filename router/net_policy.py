"""外网出口策略：默认直连，可选绑定物理网卡与沿用系统代理。"""
import json
import os
import subprocess
import urllib.parse
import urllib.request

import requests.adapters
import urllib3

CREATE_NO_WINDOW = 0x08000000
VIRTUAL_ADAPTER_HINTS = (
    "tap", "tun", "virtual", "vpn", "wireguard", "openvpn", "wintun",
    "hyper-v", "vmware", "virtualbox", "zerotier", "tailscale", "radmin",
    "loopback", "bluetooth",
)
DETECT_SCRIPT = (
    "Get-NetIPConfiguration | "
    "Where-Object { $_.NetAdapter.Status -eq 'Up' -and "
    "$_.IPv4DefaultGateway -ne $null -and $_.IPv4Address -ne $null } | "
    "Select-Object InterfaceAlias,InterfaceDescription,"
    "@{n='IPv4';e={$_.IPv4Address[0].IPAddress}} | "
    "ConvertTo-Json -Compress"
)

_use_system_proxy = False
_direct_interface = False
_interface_ip = ""
_source_address = ""


def configure(enabled: bool = False, direct_interface: bool = False,
              interface_ip: str = ""):
    """设置页保存后调用，让后续请求立即按新策略出网。"""
    global _use_system_proxy, _direct_interface, _interface_ip
    global _source_address
    _use_system_proxy = bool(enabled)
    _direct_interface = bool(direct_interface)
    _interface_ip = str(interface_ip or "").strip()
    _source_address = _resolve_source_address()


def use_system_proxy() -> bool:
    return _use_system_proxy


def direct_interface_enabled() -> bool:
    return _direct_interface


def source_address():
    """出网要绑定的本机地址；None 表示按系统默认路由走。"""
    return _source_address or None


def physical_ip() -> str:
    """当前选定的物理出口地址；未启用或探测失败时返回空串。"""
    return _source_address


def _resolve_source_address() -> str:
    """系统代理与绑定互斥：绑到物理网卡会让本机代理不可达。"""
    if _use_system_proxy or not _direct_interface:
        return ""
    if _interface_ip:
        return _interface_ip
    return detect_physical_ip()


def detect_physical_ip() -> str:
    """挑一个非虚拟网卡的 IPv4 作为出口地址；探测失败返回空串。"""
    try:
        interfaces = _query_interfaces()
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""
    for item in interfaces:
        description = "{} {}".format(
            item.get("InterfaceAlias") or "",
            item.get("InterfaceDescription") or "")
        if any(hint in description.lower() for hint in VIRTUAL_ADAPTER_HINTS):
            continue
        address = str(item.get("IPv4") or "")
        if address and not address.startswith(("127.", "169.254.")):
            return address
    return ""


def _query_interfaces() -> list:
    completed = subprocess.run(
        [_powershell_path(), "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-Command", DETECT_SCRIPT],
        timeout=20, creationflags=CREATE_NO_WINDOW,
        capture_output=True, text=True)
    data = json.loads(completed.stdout or "[]")
    if isinstance(data, dict):
        return [data]
    return [item for item in data if isinstance(item, dict)]


def _powershell_path() -> str:
    shell = os.path.join(
        os.environ.get("SystemRoot", r"C:\Windows"), "System32",
        "WindowsPowerShell", "v1.0", "powershell.exe")
    return shell if os.path.exists(shell) else "powershell.exe"


class BoundHTTPAdapter(requests.adapters.HTTPAdapter):
    """把连接 socket 绑到指定本机地址，强制走物理网卡出口。"""

    def __init__(self, bind_address: str, **kwargs):
        self._bind_address = bind_address
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        self.poolmanager = urllib3.PoolManager(
            num_pools=connections, maxsize=maxsize, block=block,
            source_address=(self._bind_address, 0), **kwargs)


def https_proxy_url():
    """系统 https 代理地址；开关关闭或系统未配置代理时返回 None。"""
    if not _use_system_proxy:
        return None
    try:
        proxies = urllib.request.getproxies()
    except OSError:
        return None
    return proxies.get("https") or proxies.get("all") or None


def split_proxy_url(proxy_url):
    """拆出 (host, port)；地址缺少端口时返回 None 表示不可用。"""
    if not proxy_url:
        return None
    text = str(proxy_url).strip()
    if "://" not in text:
        text = "http://" + text
    parsed = urllib.parse.urlsplit(text)
    if parsed.scheme not in ("http", "https"):
        return None
    if not parsed.hostname or not parsed.port:
        return None
    return parsed.hostname, parsed.port
