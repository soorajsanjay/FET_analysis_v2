"""Public in-memory analysis API."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Sequence

from fet_analyzer.analysis.classifier import classify_measurement
from fet_analyzer.analysis.engine import analyze_segments
from fet_analyzer.analysis.segmentation import segment_sweeps
from fet_analyzer.config import DEFAULT_CONFIG, deep_merge
from fet_analyzer.schema import attach_canonical_result


def analyze_transfer(
    columns: dict[str, Sequence[float]],
    device: dict[str, Any],
    config: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    source_file: str = "in_memory",
) -> dict[str, Any]:
    """Analyze transfer data without filesystem, plotting, or report dependencies."""
    cfg = deep_merge(deepcopy(DEFAULT_CONFIG), config or {})
    parsed = {"metadata": metadata or {}, "columns": list(columns), "data": {key: list(value) for key, value in columns.items()}}
    classification = classify_measurement(
        parsed["metadata"], parsed["columns"], parsed["data"], filename=source_file,
        filename_patterns=cfg.get("filename_patterns"),
        lch_regex=cfg.get("tlm", {}).get("lch_regex"),
    )
    classification["source_filename"] = source_file
    segments = segment_sweeps(
        parsed, classification,
        vds_tolerance_v=float(
            cfg.get("transfer", {}).get("vds_segmentation_tolerance_v", 1e-6)
        ),
    )
    metrics = analyze_segments(segments, classification, cfg, device)
    metrics["source_file"] = source_file
    return attach_canonical_result(metrics)
