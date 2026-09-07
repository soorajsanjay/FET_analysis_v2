"""Durable machine- and human-readable error reporting for pipeline runs."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fet_analyzer.reports.html_report import write_html_report
from fet_analyzer.path_utils import prepare_write_path, safe_mkdir, safe_path, safe_unlink


def error_entry(stage: str, exc: BaseException, source_file: str = "") -> dict[str, Any]:
    import traceback
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_file": source_file,
        "stage": stage,
        "exception_type": type(exc).__name__,
        "message": str(exc),
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    }


def write_error_reports(output_root: Path, errors: list[dict[str, Any]]) -> dict[str, Path]:
    """Always write an auditable error summary, including a clean-run report."""
    report_dir = output_root / "errors"
    safe_mkdir(report_dir, parents=True, exist_ok=True)
    generated = datetime.now(timezone.utc).isoformat()
    payload = {
        "schema_version": "1.0",
        "generated_utc": generated,
        "status": "errors" if errors else "clean",
        "error_count": len(errors),
        "errors": errors,
    }
    json_path = report_dir / "error_report.json"
    csv_path = report_dir / "error_report.csv"
    html_path = report_dir / "error_report.html"
    legacy_markdown = report_dir / "error_report.md"
    if safe_path(legacy_markdown).exists():
        safe_unlink(legacy_markdown)
    prepare_write_path(json_path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    fields = ["timestamp_utc", "source_file", "stage", "exception_type", "message", "traceback"]
    with prepare_write_path(csv_path).open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in fields} for row in errors)
    lines = ["# FET Analyzer Error Report", "", f"Generated: `{generated}`", "", f"Errors: **{len(errors)}**", ""]
    if not errors:
        lines.append("No errors were recorded during this run.")
    for index, row in enumerate(errors, 1):
        lines.extend([
            f"## {index}. {row.get('exception_type', 'Error')} during {row.get('stage', 'unknown')}", "",
            f"- Source: `{row.get('source_file') or 'run-level'}`",
            f"- Message: {row.get('message', '')}", "", "```text", row.get("traceback", "").rstrip(), "```", "",
        ])
    write_html_report(html_path, "FET Analyzer Error Report", lines)
    return {"json": json_path, "csv": csv_path, "html": html_path}
