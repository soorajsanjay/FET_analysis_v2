"""Runtime helpers shared by source installs and frozen Windows launchers."""
from __future__ import annotations

import json
import os
import platform
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
    """Resolve the CLI worker without recursively invoking a frozen GUI."""
    if not is_frozen():
        return [sys.executable, "-m", "fet_analyzer"]
    worker = frozen_distribution_dir() / "FET-Analyzer-Worker.exe"
    if not worker.is_file():
        raise FileNotFoundError(
            f"Analysis worker is missing: {worker}. Reinstall the complete portable "
            "FET Analyzer folder; do not move an executable out of that folder by itself."
        )
    return [str(worker)]


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
