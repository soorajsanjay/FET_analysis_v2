"""Reproducible machine-readable run manifest."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fet_analyzer.utils.logging import LOGGER
from fet_analyzer.path_utils import prepare_write_path, safe_path

def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with safe_path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def input_manifest_entry(path: Path) -> dict[str, Any]:
    """Describe an input without allowing cloud-file errors to abort a run."""
    entry: dict[str, Any] = {
        "path": str(path.resolve()),
        "size_bytes": None,
        "sha256": None,
    }
    try:
        entry["size_bytes"] = path.stat().st_size
        entry["sha256"] = file_sha256(path)
    except OSError as exc:
        entry["hash_status"] = "unavailable"
        entry["hash_error"] = f"{type(exc).__name__}: {exc}"
        LOGGER.warning(
            "Could not hash input for run manifest: %s (%s)",
            path,
            exc,
        )
    else:
        entry["hash_status"] = "verified"
    return entry

def write_run_manifest(output_root: Path, inputs: list[Path], config: dict[str, Any],
                       stats: dict[str, int], duplicate_info: list[dict[str, Any]],
                       errors: list[dict[str, Any]] | None = None) -> Path:
    failures = int(stats.get("error", 0))
    processed = sum(int(stats.get(key, 0)) for key in ("transfer", "output", "general_iv", "tlm"))
    status = "partial_failure" if failures and processed else "fatal_failure" if failures else "success"
    payload = {
        "schema_version": "2.0",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "statistics": stats,
        "processed_measurements": processed,
        "completion": {
            "successful": failures == 0,
            "per_file_analysis": True,
            "device_reports": True,
            "sample_comparisons": True,
            "tlm_analysis": True,
            "batch_summary": True,
            "html_index": False,
        },
        "configuration": config,
        "duplicates": duplicate_info,
        "inputs": [input_manifest_entry(path) for path in inputs],
        "device_parameters_file": str((Path(config["general"]["input_folder"]) / "device_parameters.txt").resolve()),
        "error_report": str((output_root / "errors" / "error_report.json").resolve()),
        "errors": list(errors or []),
    }
    from fet_analyzer.runtime import version_payload
    payload["versions"] = version_payload()
    path = output_root / "run_manifest.json"
    prepare_write_path(path).write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    return path


def mark_manifest_index_complete(path: Path) -> None:
    """Mark the final renderer complete only after the home page exists."""
    payload = json.loads(safe_path(path).read_text(encoding="utf-8"))
    payload.setdefault("completion", {})["html_index"] = True
    prepare_write_path(path).write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
