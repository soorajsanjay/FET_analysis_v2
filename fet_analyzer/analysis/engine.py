"""Numerical analysis boundary independent of plots and report formats."""
from __future__ import annotations

from typing import Any

from fet_analyzer.analysis.metric_summary import build_device_summary
from fet_analyzer.registry import ANALYZERS, register_analysis


def _transfer_handler(segments: list[Any], classification: dict[str, Any], config: dict[str, Any], device: dict[str, Any]) -> list[Any]:
    from fet_analyzer.analysis.transfer_sweep import analyze_transfer_sweeps
    return analyze_transfer_sweeps(segments, classification, config, device)


def _output_handler(segments: list[Any], classification: dict[str, Any], config: dict[str, Any], device: dict[str, Any]) -> list[Any]:
    from fet_analyzer.analysis.output_sweep import analyze_output_sweeps
    return analyze_output_sweeps(segments, classification, config)


register_analysis("transfer", _transfer_handler, name="canonical-transfer-engine")
register_analysis("output", _output_handler, name="canonical-output-engine")


def analyze_result_objects(segments: list[Any], classification: dict[str, Any], config: dict[str, Any], device: dict[str, Any]) -> list[Any]:
    sweep = str(classification.get("sweep_variable", "")).lower()
    measurement_type = "transfer" if sweep in {"vg", "vbg"} else "output"
    return ANALYZERS.get(measurement_type)(segments, classification, config, device)


def analyze_segments(segments: list[Any], classification: dict[str, Any], config: dict[str, Any], device: dict[str, Any]) -> dict[str, Any]:
    sweep = str(classification.get("sweep_variable", "")).lower()
    results = analyze_result_objects(segments, classification, config, device)
    metrics = {
        "measurement_type": "transfer" if sweep in {"vg", "vbg"} else "output",
        "classification": classification,
        "device_geometry": device,
        "sweep_results": [result.to_dict() for result in results],
    }
    metrics["device_summary"] = build_device_summary(metrics, config)
    return metrics
