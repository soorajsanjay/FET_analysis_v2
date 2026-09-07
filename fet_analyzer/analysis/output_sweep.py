"""Standalone output-sweep analysis, including resistance at each gate bias."""
from __future__ import annotations

from typing import Any
from collections import defaultdict

import numpy as np

from fet_analyzer.analysis.numerics import compute_gds
from fet_analyzer.analysis.sweep_models import OutputSweepResult, SweepIdentity


def analyze_output_sweep(
    segment: Any,
    classification: dict[str, Any],
    config: dict[str, Any],
    *,
    source_filename: str = "",
    sweep_index: int = 0,
) -> OutputSweepResult:
    """Analyze one Id-Vd sweep at one Vg, or with no gate bias."""
    sweep_var = segment.sweep_variable
    drain_col = classification.get("drain_current_raw_column", "Id")
    vd = np.asarray(segment.data.get(sweep_var, segment.sweep_values), dtype=float)
    current = np.asarray(segment.data.get(drain_col, []), dtype=float)
    finite = np.isfinite(vd) & np.isfinite(current)
    vd, current = vd[finite], current[finite]
    warnings: list[str] = []
    point_mask = (np.abs(vd) > 1e-12) & (np.abs(current) > 1e-15)
    point_resistance = np.abs(vd[point_mask] / current[point_mask])
    average = float(np.mean(point_resistance)) if len(point_resistance) else None
    median = float(np.median(point_resistance)) if len(point_resistance) else None
    fit_resistance = None
    fit_r2 = None
    vd_limit = float(config.get("tlm", {}).get("tlm_output_vd_max", 0.1))
    linear = np.abs(vd) <= vd_limit
    if linear.sum() >= 3:
        slope, intercept = np.polyfit(vd[linear], current[linear], 1)
        prediction = slope * vd[linear] + intercept
        total = np.sum((current[linear] - np.mean(current[linear])) ** 2)
        fit_r2 = (
            float(1 - np.sum((current[linear] - prediction) ** 2) / total)
            if total > 1e-30 else None
        )
        if abs(slope) > 1e-15:
            fit_resistance = 1.0 / abs(float(slope))
    else:
        warnings.append("Insufficient low-Vd points for linear resistance fit")
    _, gds = compute_gds(vd.tolist(), current.tolist())
    finite_gds = np.asarray(gds, dtype=float)
    gds_max = (
        float(np.nanmax(np.abs(finite_gds)))
        if len(finite_gds) and np.isfinite(finite_gds).any() else None
    )
    no_gate_bias = segment.bias_variable is None or segment.bias_level is None
    identity = SweepIdentity(
        source_filename=source_filename,
        sweep_index=sweep_index,
        measurement_type="output",
        direction=segment.direction,
        sweep_variable=sweep_var,
        bias_variable=segment.bias_variable,
        bias_value_v=segment.bias_level,
    )
    return OutputSweepResult(
        identity=identity,
        n_points=len(vd),
        gate_bias_v=None if no_gate_bias else float(segment.bias_level),
        no_gate_bias=no_gate_bias,
        resistance_avg_ohm=average,
        resistance_median_ohm=median,
        resistance_linear_fit_ohm=fit_resistance,
        linear_fit_r2=fit_r2,
        gds_max_s=gds_max,
        warnings=warnings,
    )


def analyze_output_sweeps(
    segments: list[Any],
    classification: dict[str, Any],
    config: dict[str, Any],
) -> list[OutputSweepResult]:
    source = str(classification.get("source_filename", ""))
    return [
        analyze_output_sweep(
            segment,
            classification,
            config,
            source_filename=source,
            sweep_index=index,
        )
        for index, segment in enumerate(segments)
    ]


def summarize_resistance_by_gate_bias(
    results: list[OutputSweepResult],
) -> dict[str, dict[str, Any]]:
    """Average resistance results across repeated directions at each Vg."""
    grouped: dict[str, list[OutputSweepResult]] = defaultdict(list)
    for result in results:
        key = "no_gate_bias" if result.no_gate_bias else str(result.gate_bias_v)
        grouped[key].append(result)

    def average(items: list[float | None]) -> float | None:
        valid = [float(item) for item in items if item is not None and np.isfinite(item)]
        return float(np.mean(valid)) if valid else None

    return {
        key: {
            "gate_bias_v": None if key == "no_gate_bias" else members[0].gate_bias_v,
            "no_gate_bias": key == "no_gate_bias",
            "n_sweeps": len(members),
            "directions": sorted({member.identity.direction for member in members}),
            "resistance_avg_ohm": average([
                member.resistance_avg_ohm for member in members
            ]),
            "resistance_median_ohm": average([
                member.resistance_median_ohm for member in members
            ]),
            "resistance_linear_fit_ohm": average([
                member.resistance_linear_fit_ohm for member in members
            ]),
            "linear_fit_r2": average([member.linear_fit_r2 for member in members]),
        }
        for key, members in sorted(grouped.items())
    }
