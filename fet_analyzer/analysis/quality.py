"""Data-quality checks shared by reports, JSON, and Excel exports."""
from __future__ import annotations

from typing import Any

import numpy as np


def _column(data: dict[str, Any], names: tuple[str, ...]) -> list[float] | None:
    columns = {str(key).lower(): key for key in data}
    key = next((columns[name] for name in names if name in columns), None)
    return data.get(key) if key is not None else None


def _finite_abs(values: list[float] | None) -> np.ndarray:
    array = np.abs(np.asarray(values or [], dtype=float))
    return array[np.isfinite(array)]


def assess_quality(clean_results: list[dict[str, Any]], metrics: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Return auditable warning-only quality flags without suppressing data."""
    total_before = sum(len(result.get("indices_kept", [])) + result.get("n_removed_nan", 0) + result.get("n_removed_noise", 0) + result.get("n_removed_compliance", 0) for result in clean_results)
    removed_nan = sum(result.get("n_removed_nan", 0) for result in clean_results)
    removed_noise = sum(result.get("n_removed_noise", 0) for result in clean_results)
    removed_compliance = sum(result.get("n_removed_compliance", 0) for result in clean_results)
    flags: list[dict[str, str]] = []
    if removed_compliance:
        flags.append({"level": "warning", "code": "compliance_clipped", "message": f"{removed_compliance} compliance-plateau points removed"})
    if total_before and (removed_nan + removed_noise + removed_compliance) / total_before > 0.2:
        flags.append({"level": "warning", "code": "high_data_removal", "message": "More than 20% of measurement points were removed during cleaning"})

    advanced = config.get("advanced", {})
    leakage_required = float(advanced.get("gate_leakage_id_dominance_fraction", 0.90))
    leakage_valid = leakage_passing = 0
    maximum_ratio = None
    for result in clean_results:
        data = result.get("cleaned", {})
        drain = _column(data, ("id", "absid", "abs_id", "is"))
        gate = _column(data, ("ig", "absig", "abs_ig", "ibg", "absibg", "abs_ibg"))
        if drain is None or gate is None:
            continue
        count = min(len(drain), len(gate))
        id_values = np.abs(np.asarray(drain[:count], dtype=float))
        ig_values = np.abs(np.asarray(gate[:count], dtype=float))
        valid = np.isfinite(id_values) & np.isfinite(ig_values)
        leakage_valid += int(np.sum(valid))
        leakage_passing += int(np.sum(valid & (id_values > ig_values)))
        ratio_mask = valid & (id_values > 0)
        if ratio_mask.any():
            candidate = float(np.max(ig_values[ratio_mask] / id_values[ratio_mask]))
            maximum_ratio = candidate if maximum_ratio is None else max(maximum_ratio, candidate)
    leakage_fraction = leakage_passing / leakage_valid if leakage_valid else None
    if leakage_fraction is not None and leakage_fraction < leakage_required:
        flags.append({
            "level": "warning", "code": "gate_leakage_dominance",
            "message": f"|Id| exceeded |Ig| at {100 * leakage_fraction:.1f}% of {leakage_valid} valid points; required {100 * leakage_required:.1f}%",
        })

    is_transfer = any(
        str(item.get("identity", {}).get("measurement_type", "")).lower() == "transfer"
        for item in metrics.get("sweep_results", []) if isinstance(item, dict)
    )
    sanity: dict[str, Any] = {"eligible_sweeps": 0, "open_candidates": [], "short_candidates": []}
    if is_transfer:
        minimum_points = int(advanced.get("sanity_min_points", 10))
        noise_floor = float((metrics.get("analysis_settings") or {}).get("noise_floor_a", config.get("transfer", {}).get("noise_floor_a", 1e-13)))
        open_limit = max(float(advanced.get("open_p95_current_a", 1e-11)), float(advanced.get("open_noise_floor_factor", 10.0)) * noise_floor)
        short_limit = float(advanced.get("short_p10_ua_per_um", 100.0))
        flatness_limit = float(advanced.get("short_flatness_ratio", 3.0))
        sweep_fraction = float(advanced.get("sanity_sweep_fraction", 0.90))
        width = (metrics.get("device_geometry") or {}).get("channel_width_um")
        diagnostics = []
        for index, result in enumerate(clean_results):
            drain = _finite_abs(_column(result.get("cleaned", {}), ("id", "absid", "abs_id", "is")))
            if len(drain) < minimum_points:
                continue
            p5, p10, p95 = (float(value) for value in np.percentile(drain, [5, 10, 95]))
            flatness = p95 / p5 if p5 > 0 else float("inf")
            normalized_p10 = p10 * 1e6 / float(width) if isinstance(width, (int, float)) and width > 0 else None
            open_candidate = p95 < open_limit
            short_candidate = normalized_p10 is not None and normalized_p10 > short_limit and flatness < flatness_limit
            diagnostics.append({
                "sweep_index": index, "n_points": len(drain), "p5_id_a": p5, "p10_id_a": p10,
                "p95_id_a": p95, "p10_ua_per_um": normalized_p10, "flatness_ratio": flatness,
                "open_candidate": open_candidate, "short_candidate": short_candidate,
            })
            if open_candidate:
                sanity["open_candidates"].append(index)
            if short_candidate:
                sanity["short_candidates"].append(index)
        sanity.update({
            "eligible_sweeps": len(diagnostics), "sweeps": diagnostics, "required_sweep_fraction": sweep_fraction,
            "open_p95_limit_a": open_limit, "short_p10_limit_ua_per_um": short_limit,
            "short_flatness_ratio_limit": flatness_limit,
        })
        eligible = len(diagnostics)
        if eligible and len(sanity["open_candidates"]) / eligible >= sweep_fraction:
            flags.append({"level": "warning", "code": "possible_open", "message": f"Possible open: {len(sanity['open_candidates'])}/{eligible} eligible transfer sweeps remain in the fA-to-pA current range"})
        if eligible and len(sanity["short_candidates"]) / eligible >= sweep_fraction:
            flags.append({"level": "warning", "code": "possible_short", "message": f"Possible short: {len(sanity['short_candidates'])}/{eligible} eligible transfer sweeps are flat above {short_limit:g} µA/µm"})

    ss = (metrics.get("summary") or {}).get("ss_mv_dec_min", metrics.get("ss_min_mv_dec"))
    ss_limit = advanced.get("min_subthreshold_slope_mv_dec", 60)
    if ss is not None and ss < ss_limit:
        flags.append({"level": "warning", "code": "subthermal_ss", "message": f"SS={ss:.1f} mV/dec is below the configured physical check of {ss_limit:.1f} mV/dec"})
    return {
        "points_before_cleaning": total_before, "removed_nan": removed_nan, "removed_noise": removed_noise,
        "removed_compliance": removed_compliance,
        "gate_leakage": {"valid_points": leakage_valid, "passing_points": leakage_passing, "passing_fraction": leakage_fraction, "required_fraction": leakage_required, "maximum_abs_ig_over_id": maximum_ratio},
        "electrical_sanity": sanity, "flags": flags, "status": "warning" if flags else "pass",
    }
