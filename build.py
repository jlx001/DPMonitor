"""
Build script — packaging DeepSeek Monitor into a single Windows executable.
Usage: python build.py
"""
import subprocess
import os
import sys


def build():
    base = os.path.dirname(os.path.abspath(__file__))

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "DeepSeekMonitor",
        "--add-data", f"{os.path.join(base, 'web')};web",
        "--hidden-import", "keyring.backends.Windows",
        "--hidden-import", "keyring.backends.win_cred",
        "--hidden-import", "pystray._win32",
        "--icon", os.path.join(base, "assets", "tray_icon.ico") if os.path.exists(os.path.join(base, "assets", "tray_icon.ico")) else "",
        os.path.join(base, "main.py"),
    ]

    # Remove empty --icon if no ico file
    if not os.path.exists(os.path.join(base, "assets", "tray_icon.ico")):
        cmd.remove("")

    print("Building DeepSeekMonitor.exe ...")
    subprocess.check_call([a for a in cmd if a])

    print("\nDone! Output: dist/DeepSeekMonitor.exe")


if __name__ == "__main__":
    build()
