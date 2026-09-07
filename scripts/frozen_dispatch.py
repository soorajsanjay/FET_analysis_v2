"""Single analyzed PyInstaller entry point for all portable executables."""
import multiprocessing
import sys
from pathlib import Path


def main() -> int:
    multiprocessing.freeze_support()
    executable = Path(sys.executable).stem.casefold()
    if "worker" in executable:
        from fet_analyzer.cli import main as selected
    elif "browser" in executable:
        from fet_analyzer.dashboard.server import main as selected
    else:
        from fet_analyzer.native import main as selected
    return selected()


if __name__ == "__main__":
    raise SystemExit(main())
