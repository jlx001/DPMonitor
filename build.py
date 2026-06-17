"""
Build script — packaging DeepSeek Monitor into a single Windows executable.
Usage: python build.py
"""
import subprocess, os, sys

def build():
    base = os.path.dirname(os.path.abspath(__file__))

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile", "--windowed",
        "--name", "DeepSeekMonitor",
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
        os.path.join(base, "main.py"),
    ]

    print("Building DeepSeekMonitor.exe ...")
    subprocess.check_call(cmd)
    print("\nDone! Output: dist/DeepSeekMonitor.exe")

if __name__ == "__main__":
    build()
