"""Run-scoped temporary workspace management."""
from __future__ import annotations

import atexit
import os
import re
from pathlib import Path
from typing import Any
from fet_analyzer.path_utils import (
    safe_mkdir, safe_path, safe_rmtree, unique_directory,
)


_RUN_DIRECTORY = re.compile(r"^run_(\d+)_")
_WORK_ROOT = ".fw"
_LEGACY_WORK_ROOT = ".fet_work"


def _process_is_running(pid: int) -> bool:
    if pid == os.getpid():
        return True
    if os.name == "nt":
        # ``os.kill(pid, 0)`` is not a portable existence probe on Windows.
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)  # query-limited-information
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return ctypes.get_last_error() == 5  # Access denied also means it exists.
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _remove_stale_runs(root: Path) -> None:
    """Remove abandoned run folders without touching a concurrent active run."""
    filesystem_root = safe_path(root)
    if not filesystem_root.exists():
        return
    for candidate in filesystem_root.iterdir():
        match = _RUN_DIRECTORY.match(candidate.name)
        if candidate.is_dir() and match and not _process_is_running(int(match.group(1))):
            safe_rmtree(candidate, ignore_errors=True)


def cleanup_stale_workspaces(output_root: Path) -> None:
    """Reclaim finished or abandoned runs and remove an empty work root."""
    for name in (_WORK_ROOT, _LEGACY_WORK_ROOT):
        root = output_root / name
        _remove_stale_runs(root)
        try:
            safe_path(root).rmdir()
        except OSError:
            pass


class RunWorkspace:
    """Own one run's transient images beneath a single hidden directory."""

    def __init__(self, output_root: Path):
        self.output_root = output_root
        self.root = output_root / _WORK_ROOT
        cleanup_stale_workspaces(output_root)
        safe_mkdir(self.root, parents=True, exist_ok=True)
        self.path, self.run_id = unique_directory(
            self.root, f"run_{os.getpid()}_",
        )
        self.temporary_ids: dict[Path, str] = {}
        self._closed = False
        atexit.register(self.cleanup)

    def temporary_directory(self, prefix: str) -> Path:
        path, identifier = unique_directory(self.path, prefix)
        self.temporary_ids[path] = identifier
        return path

    def cleanup(self) -> None:
        if self._closed:
            return
        self._closed = True
        safe_rmtree(self.path, ignore_errors=True)
        cleanup_stale_workspaces(self.output_root)
        atexit.unregister(self.cleanup)


def temporary_directory(
    config: dict[str, Any], prefix: str, fallback_parent: Path,
) -> Path:
    """Create a temporary directory inside the configured run workspace."""
    configured = config.get("execution", {}).get("temporary_root")
    parent = Path(configured) if configured else fallback_parent
    safe_mkdir(parent, parents=True, exist_ok=True)
    path, _ = unique_directory(parent, prefix)
    return path
