"""
Build script — packaging DeepSeek Monitor into a single Windows executable.
Usage: python build.py
"""
import os
import subprocess
import sys

APP_VERSION = "1.0.6"
VERSION_FILE = "version_info.txt"
EXE_NAME = "DeepSeekMonitor-{}".format(APP_VERSION)


def _write_version_info(base):
    parts = APP_VERSION.split(".")
    while len(parts) < 4:
        parts.append("0")
    filevers = tuple(int(part) for part in parts[:4])
    version_text = ".".join(str(part) for part in filevers)
    path = os.path.join(base, VERSION_FILE)
    content = (
        "VSVersionInfo(\n"
        "  ffi=FixedFileInfo(\n"
        "    filevers={},\n"
        "    prodvers={},\n"
        "    mask=0x3f,\n"
        "    flags=0x0,\n"
        "    OS=0x40004,\n"
        "    fileType=0x1,\n"
        "    subtype=0x0,\n"
        "    date=(0, 0)\n"
        "  ),\n"
        "  kids=[\n"
        "    StringFileInfo([\n"
        "      StringTable(\n"
        "        '080404b0',\n"
        "        [StringStruct('CompanyName', 'DeepSeek Monitor'),\n"
        "         StringStruct('FileDescription', "
        "'DeepSeek Monitor Usage Monitor'),\n"
        "         StringStruct('FileVersion', '{}'),\n"
        "         StringStruct('InternalName', 'DeepSeekMonitor'),\n"
        "         StringStruct('OriginalFilename', '{}.exe'),\n"
        "         StringStruct('ProductName', 'DeepSeek Monitor'),\n"
        "         StringStruct('ProductVersion', '{}')])\n"
        "    ]),\n"
        "    VarFileInfo([VarStruct('Translation', [2052, 1200])])\n"
        "  ]\n"
        ")\n"
    ).format(filevers, filevers, version_text, EXE_NAME, version_text)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    return path


def build():
    base = os.path.dirname(os.path.abspath(__file__))
    version_info = _write_version_info(base)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile", "--windowed",
        "--name", EXE_NAME,
        "--version-file", version_info,
        "--add-data", f"{os.path.join(base, 'web')};web",
        "--hidden-import", "keyring.backends.Windows",
        "--hidden-import", "keyring.backends.win_cred",
        "--hidden-import", "pystray._win32",
        "--hidden-import", "ctypes",
        "--hidden-import", "_ctypes",
        "--hidden-import", "json",
        "--hidden-import", "requests",
        "--hidden-import", "webview",
        "--hidden-import", "PIL._imaging",
        "--hidden-import", "win32ctypes.core",
        "--hidden-import", "router.gateway",
        "--hidden-import", "router.sk_pool",
        "--hidden-import", "router.conversation",
        "--hidden-import", "router.usage_store",
        "--hidden-import", "router.notifier",
        "--hidden-import", "codex_integration",
        "--hidden-import", "sqlite3",
        os.path.join(base, "main.py"),
    ]

    print("Building DeepSeekMonitor.exe ...")
    subprocess.check_call(cmd)
    print("\nDone! Output: dist/{}.exe".format(EXE_NAME))

if __name__ == "__main__":
    build()
