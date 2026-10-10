"""启动接管：结束运行中的旧版本，让新版本接管自启动会话。"""
import ctypes
import os
import re
import sys
from ctypes import wintypes

TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = -1
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000
WAIT_TIMEOUT = 0x00000102
MAX_PATH = 260
APP_IMAGE_PREFIX = "deepseekmonitor"
VERSION_PATTERN = re.compile(r"-(\d+(?:\.\d+)*)\.exe$", re.IGNORECASE)


class _ProcessEntry32W(ctypes.Structure):
    """PROCESSENTRY32W 的最小可用定义。"""

    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * MAX_PATH),
    ]


def other_instances() -> list:
    """需要接管的旧实例进程 (pid, 可执行文件名)。"""
    return select_instances(_snapshot_entries(), os.getpid())


def _snapshot_entries() -> list:
    """当前进程快照的 (pid, 父 pid, 可执行文件名)。"""
    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        return []
    entry = _ProcessEntry32W()
    entry.dwSize = ctypes.sizeof(_ProcessEntry32W)
    entries = []
    try:
        has_entry = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while has_entry:
            entries.append((entry.th32ProcessID,
                            entry.th32ParentProcessID,
                            entry.szExeFile))
            has_entry = kernel32.Process32NextW(
                snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return entries


def select_instances(entries: list, own_pid: int) -> list:
    """挑出要结束的旧实例进程。

    单文件打包会同时出现引导父进程与应用子进程（同名），只结束应用本体，
    让引导进程正常回收临时解包目录；自身进程与自己的引导父进程都要排除。
    """
    skipped = {own_pid, _parent_of(entries, own_pid)}
    candidates = [
        (pid, parent, name)
        for pid, parent, name in entries
        if _is_app_process(name, pid, skipped)
    ]
    launcher_pids = {parent for _pid, parent, _name in candidates}
    return [(pid, name) for pid, _parent, name in candidates
            if pid not in launcher_pids]


def _parent_of(entries: list, pid: int) -> int:
    for entry_pid, parent_pid, _name in entries:
        if entry_pid == pid:
            return parent_pid
    return 0


def _is_app_process(file_name: str, pid: int, skipped_pids) -> bool:
    if pid in skipped_pids:
        return False
    lowered = file_name.lower()
    return lowered.startswith(APP_IMAGE_PREFIX) and lowered.endswith(".exe")


def version_key(path) -> tuple:
    """从文件名解析版本号；解析不出来时返回空元组。"""
    match = VERSION_PATTERN.search(os.path.basename(path or ""))
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def should_replace(other_exe, own_exe=None) -> bool:
    """只在自身版本不低于对方时接管，避免旧快捷方式顶掉新版。"""
    own = version_key(own_exe or sys.executable)
    other = version_key(other_exe)
    if not own or not other:
        return True
    return own >= other


def terminate_process(pid: int, timeout_ms: int = 5000) -> bool:
    """结束指定进程并等待其退出，确认互斥锁已释放。"""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, pid)
    if not handle:
        return False
    try:
        if not kernel32.TerminateProcess(handle, 1):
            return False
        return kernel32.WaitForSingleObject(handle, timeout_ms) != WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(handle)


def take_over(log=None, own_exe=None) -> bool:
    """结束旧版本进程；仍有更新版本在运行时返回 False。"""
    newer_running = False
    for pid, file_name in other_instances():
        if not should_replace(file_name, own_exe):
            newer_running = True
            continue
        if log:
            log("Closing {} (pid={})".format(file_name, pid))
        terminate_process(pid)
    return not newer_running
