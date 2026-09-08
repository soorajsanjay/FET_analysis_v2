"""Runtime helpers shared by source installs and frozen Windows launchers."""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fet_analyzer import __version__
from fet_analyzer.path_utils import prepare_write_path, safe_mkdir


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def application_data_dir() -> Path:
    """Return a stable per-user directory for logs and lightweight GUI state."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    target = base / "FET Analyzer"
    safe_mkdir(target, parents=True, exist_ok=True)
    return target


def runtime_log_path(component: str) -> Path:
    log_dir = application_data_dir() / "logs"
    safe_mkdir(log_dir, parents=True, exist_ok=True)
    return log_dir / f"{component}.log"


def append_runtime_log(component: str, message: str) -> Path:
    path = runtime_log_path(component)
    timestamp = datetime.now(timezone.utc).isoformat()
    with prepare_write_path(path).open("a", encoding="utf-8") as handle:
        handle.write(f"{timestamp} {message}\n")
    return path


def frozen_distribution_dir() -> Path:
    return Path(sys.executable).resolve().parent


def resolve_worker_command() -> list[str]:
    """Resolve the analysis worker; frozen GUIs relaunch the primary EXE."""
    if not is_frozen():
        return [sys.executable, "-m", "fet_analyzer"]
    primary = frozen_distribution_dir() / "FET-Analyzer-v2.exe"
    if not primary.is_file():
        raise FileNotFoundError(
            f"Primary analysis executable is missing: {primary}. Reinstall the complete portable "
            "FET Analyzer folder; do not move an executable out of that folder by itself."
        )
    return [str(primary), "--worker"]


def worker_launch_error(exc: BaseException, command: list[str]) -> str:
    executable = command[0] if command else "unknown"
    winerror = getattr(exc, "winerror", None)
    detail = f"{type(exc).__name__}: {exc}"
    if winerror is not None:
        detail += f" (Windows error {winerror})"
    return (
        f"Windows could not start the analysis worker at {executable}. {detail}. "
        "Extract the complete portable ZIP to an approved local folder; if this copy is in "
        "OneDrive, try an approved folder outside OneDrive. Check the downloaded ZIP or EXE "
        "Properties for an Unblock option if your organization permits it. If Windows application "
        "control still blocks execution, send the diagnostic bundle to IT."
    )


def probe_worker(timeout: float = 10.0) -> dict[str, Any]:
    """Launch a harmless frozen/source worker probe and report the exact outcome."""
    try:
        command = ([sys.executable, "-c", "import fet_analyzer; print('worker-ready')"]
                   if not is_frozen() else [*resolve_worker_command(), "--worker-probe"])
    except Exception as exc:
        return {"status": "missing", "command": [], "error": str(exc)}
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as exc:
        return {"status": "timeout", "command": command, "error": f"Timed out after {exc.timeout} seconds"}
    except PermissionError as exc:
        return {"status": "blocked", "command": command, "error": worker_launch_error(exc, command)}
    except OSError as exc:
        return {"status": "launch_error", "command": command, "error": worker_launch_error(exc, command)}
    output = (completed.stdout or completed.stderr or "").strip()
    return {"status": "responded" if completed.returncode == 0 and "worker-ready" in output else "failed",
            "command": command, "return_code": completed.returncode, "output": output}


def version_payload() -> dict[str, Any]:
    from fet_analyzer.schema import SCHEMA_VERSION
    return {
        "application": __version__,
        "result_schema": SCHEMA_VERSION,
        "manifest_schema": "2.0",
        "parser_api": "1",
        "analysis_api": "1",
        "creator": "Sooraj Sanjay",
        "python": platform.python_version(),
        "frozen": is_frozen(),
    }


def write_diagnostic_bundle(payload: dict[str, Any]) -> Path:
    target = application_data_dir() / "diagnostics"
    safe_mkdir(target, parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = target / f"fet-analyzer-diagnostics-{stamp}.json"
    prepare_write_path(path).write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    return path
