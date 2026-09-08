"""Single analyzed PyInstaller entry point for all portable executables."""
import multiprocessing
import os
import sys
from pathlib import Path


def main() -> int:
    multiprocessing.freeze_support()
    executable = Path(sys.executable).stem.casefold()
    force_worker = "--worker" in sys.argv
    if force_worker:
        sys.argv.remove("--worker")
    if "--worker-probe" in sys.argv:
        print("worker-ready", flush=True)
        return 0
    if "worker" in executable or force_worker:
        if "worker" in executable and len(sys.argv) == 1:
            print("FET Analyzer Worker is a command-line helper. Open FET-Analyzer-v2.exe for the dashboard, or run this file with --help.")
            if os.name == "nt" and sys.stdin is not None and sys.stdin.isatty():
                input("Press Enter to close...")
            return 0
        from fet_analyzer.cli import main as selected
    elif "browser" in executable:
        from fet_analyzer.dashboard.server import main as selected
    else:
        # The primary build is console-capable so it can relaunch itself as a
        # piped worker. Hide that console for ordinary native desktop use.
        if os.name == "nt":
            try:
                import ctypes
                ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
            except Exception:
                pass
        from fet_analyzer.native import main as selected
    return selected()


if __name__ == "__main__":
    raise SystemExit(main())
