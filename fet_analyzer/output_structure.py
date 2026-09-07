"""
Output folder structure creation for FET Analyzer.

Creates flat, collision-safe artifacts for each processed file:
    <output>/
      <normalized_file_id>.xlsx
      <normalized_file_id>_report.html
      <normalized_file_id>_metadata.json
      <normalized_file_id>_metrics.json
      <normalized_file_id>_plots/  (optional)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fet_analyzer.utils.logging import LOGGER
from fet_analyzer.path_utils import (
    prepare_write_path, safe_mkdir, safe_path, safe_rmtree, safe_unlink,
)


def normalise_file_id(name: str) -> str:
    """Create a clean folder-safe identifier from a filename.

    Removes extensions and UUID suffixes from Telegram media uploads.
    """
    # Strip media UUID suffix: "file---uuid.ext" → "file"
    stem = Path(name).stem
    if "---" in stem:
        stem = stem.split("---")[0]
    # Remove unsafe characters
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in stem)
    # Collapse multiple underscores
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_")


def create_output_structure(
    base_output: Path,
    file_id: str,
    file_path: Path,
    overwrite: bool = False,
    keep_plots: bool = False,
) -> dict[str, Path]:
    """Create flat per-file output paths without a device subdirectory.

    Returns:
        dict mapping logical name → Path for each output component.
    """
    norm_id = normalise_file_id(file_id)
    safe_mkdir(base_output, parents=True, exist_ok=True)
    analysis_path = base_output / f"{norm_id}.xlsx"
    report_path = base_output / f"{norm_id}_report.html"
    metadata_path = base_output / f"{norm_id}_metadata.json"
    metrics_path = base_output / f"{norm_id}_metrics.json"
    plot_path = base_output / f"{norm_id}_plots"
    existing = [
        path for path in (analysis_path, report_path, metadata_path, metrics_path)
        if safe_path(path).exists()
    ]
    if existing:
        if not overwrite:
            LOGGER.info("Output exists, skipping: %s", existing[0])
            return {}
        for path in existing:
            safe_unlink(path)
    if safe_path(plot_path).exists() and overwrite:
        safe_rmtree(plot_path)
    if keep_plots:
        safe_mkdir(plot_path, parents=True, exist_ok=True)

    # Do NOT copy raw source file — user already has the original

    return {
        "root": base_output,
        "plots": plot_path,
        "report": report_path,
        "analysis_xlsx": analysis_path,
        "metadata_json": metadata_path,
        "metrics_json": metrics_path,
    }


def save_metadata_json(path: Path, metadata: dict[str, Any]):
    """Save extracted metadata as JSON."""
    with open(prepare_write_path(path), "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, default=str, ensure_ascii=False)
    LOGGER.debug("Saved metadata: %s", path)


def save_metrics_json(path: Path, metrics: dict[str, Any]):
    """Save extracted metrics as JSON."""
    from fet_analyzer.schema import attach_canonical_result, validate_metrics_consistency
    attach_canonical_result(metrics)
    consistency_errors = validate_metrics_consistency(metrics)
    metrics["renderer_consistency"] = {
        "status": "error" if consistency_errors else "pass",
        "issues": consistency_errors,
    }
    for issue in consistency_errors:
        LOGGER.warning("Canonical renderer consistency: %s", issue)
    with open(prepare_write_path(path), "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, default=str, ensure_ascii=False)
    LOGGER.debug("Saved metrics: %s", path)


def save_intermediate_data(
    intermediate_dir: Path,
    segments: list[Any],
    metrics: dict[str, Any],
    classification: dict[str, Any],
) -> None:
    """Populate intermediate/ folder with per-segment CSVs for inspection.

    Writes:
      - segments.csv: cleaned segment data (Vg, Id, direction, bias)
      - gm_data.csv: Vg, gm per segment (from plots)
      - ss_data.csv: SS sweep data per segment
      - extracted_summary.csv: one-row summary of key metrics
    """
    import csv

    drain_col = classification.get("drain_current_raw_column", "Id")
    sweep_var = classification.get("sweep_variable", "Vg")

    # ── 1. Cleaned segment data ───────────────────────────────────
    seg_path = intermediate_dir / "segments.csv"
    with open(prepare_write_path(seg_path), "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["segment_index", "direction", "bias_variable", "bias_level",
                          sweep_var, drain_col])
        for i, seg in enumerate(segments):
            vg = seg.data.get(sweep_var, [])
            idd = seg.data.get(drain_col, [])
            for j in range(min(len(vg), len(idd))):
                writer.writerow([
                    i, seg.direction,
                    seg.bias_variable or "", seg.bias_level,
                    vg[j], idd[j],
                ])
    LOGGER.debug("  → Intermediate: %s", seg_path)

    # ── 2. gm data per segment ────────────────────────────────────
    gm_path = intermediate_dir / "gm_data.csv"
    with open(prepare_write_path(gm_path), "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["segment_index", "direction", "bias_key", sweep_var, "gm"])
        seg_metrics = metrics.get("segments", {})
        for bias_key in sorted(seg_metrics.keys()):
            seg = seg_metrics[bias_key]
            gm_val = seg.get("gm_max_s")
            gm_vg = seg.get("gm_max_vg")
            # We don't have per-point gm in metrics, but we have peak
            # For full gm curve we need the plot function output — store peak as summary
            writer.writerow(["", "forward", bias_key, gm_vg, gm_val])
    LOGGER.debug("  → Intermediate: %s", gm_path)

    # ── 3. SS data per segment ────────────────────────────────────
    ss_path = intermediate_dir / "ss_data.csv"
    with open(prepare_write_path(ss_path), "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["bias_key", "ss_mv_dec", "ss_vg", "ion_ioff", "ion_ioff_log10"])
        for bias_key in sorted(seg_metrics.keys()):
            seg = seg_metrics[bias_key]
            writer.writerow([
                bias_key,
                seg.get("ss_mv_dec"),
                seg.get("ss_at_vg"),
                seg.get("ion_ioff"),
                seg.get("ion_ioff_log10"),
            ])
    LOGGER.debug("  → Intermediate: %s", ss_path)

    # ── 4. Extracted summary ──────────────────────────────────────
    summary_path = intermediate_dir / "extracted_summary.csv"
    summary = metrics.get("summary", {})
    with open(prepare_write_path(summary_path), "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value"])
        for key in ["vth_v_mean", "mobility_cm2_vs_max", "ss_mv_dec_min",
                     "hysteresis_v_max", "dibl_mv_v"]:
            writer.writerow([key, summary.get(key)])
        writer.writerow(["gm_max_s", metrics.get("gm_max_s")])
        writer.writerow(["ion_ioff_log10", metrics.get("ion_ioff_log10")])
        writer.writerow(["ss_min_mv_dec", metrics.get("ss_min_mv_dec")])
    LOGGER.debug("  → Intermediate: %s", summary_path)
