"""Reusable numerical primitives shared by analysis and plotting."""
from __future__ import annotations

from typing import Any

import numpy as np

from fet_analyzer.utils.logging import LOGGER


def interpolate_abs_current_at_voltage(
    voltage: list[float], current: list[float], target_v: float | None,
) -> float | None:
    """Interpolate |current| at a voltage without extrapolating."""
    if target_v is None:
        return None
    x = np.asarray(voltage, dtype=float)
    y = np.abs(np.asarray(current, dtype=float))
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if len(x) < 2:
        return None
    order = np.argsort(x)
    x, y = x[order], y[order]
    unique_x, inverse = np.unique(x, return_inverse=True)
    unique_y = np.asarray([np.median(y[inverse == i]) for i in range(len(unique_x))])
    target = float(target_v)
    if target < unique_x[0] or target > unique_x[-1]:
        return None
    return float(np.interp(target, unique_x, unique_y))


def nearest_abs_current_at_voltage(
    voltage: list[float], current: list[float], target_v: float | None,
) -> dict[str, Any]:
    """Read |current| at a closest measured voltage and retain provenance.

    If two or more measured voltages are exactly equidistant from the target,
    choose the candidate with the lowest median |current|.  This is a
    conservative Ion estimate and, importantly, always reports a voltage that
    was actually measured instead of averaging voltage coordinates.
    """
    empty = {
        "current_a": None, "requested_v": target_v, "actual_v": None,
        "delta_v": None, "exact": False, "equidistant_tie": False,
        "candidate_voltages_v": [], "selection_reason": None,
    }
    if target_v is None:
        return empty
    x = np.asarray(voltage, dtype=float)
    y = np.abs(np.asarray(current, dtype=float))
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if not len(x):
        return empty
    target = float(target_v)
    distance = np.abs(x - target)
    minimum = float(np.min(distance))
    nearest = np.isclose(distance, minimum, rtol=0.0, atol=1e-12)
    candidate_voltages = np.unique(x[nearest])
    candidate_values = []
    for candidate in candidate_voltages:
        same_candidate = np.isclose(x, candidate, rtol=0.0, atol=1e-12)
        candidate_values.append((
            float(np.median(y[same_candidate])),
            abs(float(candidate)),
            float(candidate),
        ))
    # Lowest |Id| is conservative.  If currents are identical, prefer the
    # smaller |Vg| and finally numeric voltage for deterministic behavior.
    value, _, actual = min(candidate_values)
    same_voltage = np.isclose(x, actual, rtol=0.0, atol=1e-12)
    value = float(np.median(y[same_voltage]))
    delta = actual - target
    tied = len(candidate_voltages) > 1
    return {
        "current_a": value, "requested_v": target, "actual_v": actual,
        "delta_v": delta, "exact": abs(delta) <= 1e-12,
        "equidistant_tie": tied,
        "candidate_voltages_v": [float(item) for item in candidate_voltages],
        "selection_reason": (
            "equidistant candidates; selected lowest median |Id|"
            if tied else "nearest measured voltage"
        ),
    }


def compute_gm(
    vg: list[float],
    id_values: list[float],
    smooth_window: int = 0,
    smooth_order: int = 1,
) -> tuple[list[float], list[float]]:
    """Compatibility wrapper returning the historical ``(Vg, gm)`` tuple."""
    method = "savgol" if smooth_window >= 3 else "none"
    result = compute_gm_with_diagnostics(
        vg, id_values,
        {"smooth_method": method, "savgol_window": smooth_window,
         "savgol_order": smooth_order},
    )
    return result["vg"], result["gm"]


def _odd_ceiling(value: float) -> int:
    integer = int(np.ceil(value))
    return integer if integer % 2 else integer + 1


def _largest_odd_below(value: float) -> int:
    integer = int(np.ceil(value)) - 1
    return integer if integer % 2 else integer - 1


def _finite_runs(values: np.ndarray) -> list[np.ndarray]:
    indices = np.flatnonzero(np.isfinite(values))
    if not len(indices):
        return []
    cuts = np.where(np.diff(indices) > 1)[0] + 1
    return [part for part in np.split(indices, cuts) if len(part)]


def _roughness_noise(values: np.ndarray) -> float:
    if len(values) < 3:
        return float("nan")
    second = np.diff(values, n=2)
    center = float(np.median(second))
    mad = float(np.median(np.abs(second - center)))
    return 1.4826 * mad / np.sqrt(6.0)


def _candidate_metrics(
    smoothed: np.ndarray,
    vg: np.ndarray,
    window: int,
    order: int,
) -> dict[str, Any]:
    peak_index = int(np.argmax(np.abs(smoothed)))
    peak = abs(float(smoothed[peak_index]))
    noise = _roughness_noise(smoothed)
    scale = max(peak, float(np.max(np.abs(smoothed))), 1.0) * np.finfo(float).eps
    denominator = max(noise, scale) if np.isfinite(noise) else scale
    return {
        "window_points": window,
        "polynomial_order": order,
        "gm_peak_s": peak,
        "gm_peak_vg": float(vg[peak_index]),
        "noise_sigma_s": noise if np.isfinite(noise) else None,
        "snr": float(peak / denominator),
        "relative_peak_change": None,
        "peak_shift_steps": None,
        "snr_improvement_fraction": None,
        "peak_stable": None,
        "shift_stable": None,
        "snr_plateau": None,
        "transition_stable": None,
        "selected": False,
    }


def _adaptive_region(
    vg: np.ndarray,
    gm_raw: np.ndarray,
    config: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    count = len(gm_raw)
    order = max(1, int(config.get("savgol_order", 1)))
    minimum_fraction = float(config.get("adaptive_gm_min_fraction", 0.05))
    maximum_fraction = float(config.get("adaptive_gm_max_fraction", 0.10))
    peak_tolerance = float(config.get("adaptive_gm_peak_tolerance", 0.05))
    peak_shift_limit = float(config.get("adaptive_gm_peak_shift_steps", 1.0))
    snr_tolerance = float(config.get("adaptive_gm_snr_plateau_tolerance", 0.10))
    required_transitions = max(1, int(config.get("adaptive_gm_stable_transitions", 2)))
    minimum = max(5, _odd_ceiling(minimum_fraction * count), _odd_ceiling(order + 1))
    maximum = min(count if count % 2 else count - 1, _largest_odd_below(maximum_fraction * count))
    windows = list(range(minimum, maximum + 1, 2)) if maximum >= minimum else []
    audit: dict[str, Any] = {
        "n_usable_points": count,
        "minimum_window_points": minimum,
        "maximum_window_points": maximum,
        "candidate_windows": windows,
        "selected_window_points": None,
        "selection_status": "unavailable",
        "selection_reason": "",
        "metric_eligible": False,
        "candidates": [],
        "warnings": [],
    }
    if not windows:
        message = (
            "Adaptive gm smoothing unavailable: no odd window satisfies the "
            "five-point minimum and strict <10% region-length cap"
        )
        audit["selection_reason"] = "no_legal_window"
        audit["warnings"].append(message)
        return gm_raw.copy(), np.full(count, np.nan), audit
    try:
        from scipy.signal import savgol_filter
    except ImportError:
        message = "Adaptive gm smoothing unavailable because SciPy is not installed"
        audit["selection_reason"] = "scipy_unavailable"
        audit["warnings"].append(message)
        return gm_raw.copy(), np.full(count, np.nan), audit

    smoothed_values: list[np.ndarray] = []
    candidates: list[dict[str, Any]] = []
    step_values = np.diff(vg)
    positive_steps = step_values[step_values > 0]
    typical_step = float(np.median(positive_steps)) if len(positive_steps) else 1.0
    for window in windows:
        smoothed = savgol_filter(
            gm_raw, window_length=window, polyorder=min(order, window - 1)
        )
        smoothed_values.append(np.asarray(smoothed, dtype=float))
        candidate = _candidate_metrics(smoothed_values[-1], vg, window, order)
        if candidates:
            previous = candidates[-1]
            peak_scale = max(abs(float(previous["gm_peak_s"])), np.finfo(float).tiny)
            snr_scale = max(abs(float(previous["snr"])), np.finfo(float).tiny)
            candidate["relative_peak_change"] = abs(
                float(candidate["gm_peak_s"]) - float(previous["gm_peak_s"])
            ) / peak_scale
            candidate["peak_shift_steps"] = abs(
                float(candidate["gm_peak_vg"]) - float(previous["gm_peak_vg"])
            ) / typical_step
            candidate["snr_improvement_fraction"] = (
                float(candidate["snr"]) - float(previous["snr"])
            ) / snr_scale
            candidate["peak_stable"] = bool(
                candidate["relative_peak_change"] <= peak_tolerance
            )
            candidate["shift_stable"] = bool(
                candidate["peak_shift_steps"] <= peak_shift_limit
            )
            candidate["snr_plateau"] = bool(
                candidate["snr_improvement_fraction"] <= snr_tolerance
            )
            candidate["transition_stable"] = bool(
                candidate["peak_stable"]
                and candidate["shift_stable"]
                and candidate["snr_plateau"]
            )
        candidates.append(candidate)

    selected_index: int | None = None
    reason = ""
    status = "accepted"
    if len(candidates) == 1:
        selected_index = 0
        reason = "only_legal_candidate"
        status = "review"
        audit["warnings"].append(
            "Adaptive gm smoothing has only one legal window; stability could not be confirmed"
        )
    else:
        transitions_needed = min(required_transitions, len(candidates) - 1)
        stable = [bool(item["transition_stable"]) for item in candidates[1:]]
        for start in range(0, len(stable) - transitions_needed + 1):
            if all(stable[start:start + transitions_needed]):
                selected_index = start
                reason = f"stable_plateau_{transitions_needed}_transition"
                break
        if selected_index is None:
            base = candidates[0]
            guarded = [
                index for index, item in enumerate(candidates)
                if abs(float(item["gm_peak_s"]) - float(base["gm_peak_s"]))
                / max(abs(float(base["gm_peak_s"])), np.finfo(float).tiny) <= peak_tolerance
                and abs(float(item["gm_peak_vg"]) - float(base["gm_peak_vg"]))
                / typical_step <= peak_shift_limit
            ]
            pool = guarded or list(range(len(candidates)))
            selected_index = max(pool, key=lambda index: (float(candidates[index]["snr"]), -windows[index]))
            reason = "best_snr_no_stable_plateau"
            status = "review"
            audit["warnings"].append(
                "Adaptive gm peak did not stabilize before the <10% window cap; best allowed SNR was used"
            )
    candidates[selected_index]["selected"] = True
    audit.update({
        "selected_window_points": windows[selected_index],
        "selection_status": status,
        "selection_reason": reason,
        "metric_eligible": True,
        "candidates": candidates,
    })
    selected = smoothed_values[selected_index]
    return selected, selected.copy(), audit


def compute_gm_with_diagnostics(
    vg: list[float],
    id_values: list[float],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute derivative-first gm and return smoothing provenance."""
    cfg = config or {}
    vg_arr = np.asarray(vg, dtype=float)
    id_arr = np.asarray(id_values, dtype=float)
    mask = np.isfinite(vg_arr) & np.isfinite(id_arr)
    vg_arr, id_arr = vg_arr[mask], id_arr[mask]
    empty = {
        "vg": [], "gm": [], "gm_for_metrics": [],
        "smoothing": {"mode": str(cfg.get("smooth_method", "none")),
                      "selected_window_points": None, "regions": [],
                      "metric_eligible": False, "warnings": []},
    }
    if len(vg_arr) < 5:
        return empty
    order = np.argsort(vg_arr)
    vg_arr, id_arr = vg_arr[order], id_arr[order]
    unique_vg, inverse = np.unique(vg_arr, return_inverse=True)
    if len(unique_vg) < 5:
        return empty
    id_unique = np.asarray([
        np.median(id_arr[inverse == index]) for index in range(len(unique_vg))
    ])
    steps = np.diff(unique_vg)
    positive_steps = steps[steps > 0]
    if not len(positive_steps):
        return empty
    typical_step = float(np.median(positive_steps))
    gm = np.full(len(unique_vg), np.nan)
    max_gap = 2.5 * typical_step
    for index in range(1, len(unique_vg) - 1):
        left_gap = unique_vg[index] - unique_vg[index - 1]
        right_gap = unique_vg[index + 1] - unique_vg[index]
        if left_gap <= max_gap and right_gap <= max_gap:
            gm[index] = (
                (id_unique[index + 1] - id_unique[index - 1])
                / (unique_vg[index + 1] - unique_vg[index - 1])
            )
    mode = str(cfg.get("smooth_method", "none")).lower()
    smooth_window = int(cfg.get("savgol_window", 0) or 0)
    smooth_order = int(cfg.get("savgol_order", 1) or 1)
    gm_for_metrics = gm.copy()
    regions: list[dict[str, Any]] = []
    warnings: list[str] = []
    if mode == "adaptive_savgol":
        gm_for_metrics[:] = np.nan
        for region_index, indices in enumerate(_finite_runs(gm)):
            displayed, eligible, audit = _adaptive_region(
                unique_vg[indices], gm[indices], cfg
            )
            gm[indices] = displayed
            gm_for_metrics[indices] = eligible
            audit["region_index"] = region_index
            audit["vg_min"] = float(unique_vg[indices[0]])
            audit["vg_max"] = float(unique_vg[indices[-1]])
            regions.append(audit)
            warnings.extend(audit["warnings"])
    elif smooth_window >= 3 and smooth_window % 2 == 1:
        try:
            from scipy.signal import savgol_filter
            finite = np.isfinite(gm)
            if finite.sum() >= smooth_window:
                gm[finite] = savgol_filter(
                    gm[finite],
                    window_length=smooth_window,
                    polyorder=min(smooth_order, smooth_window - 1),
                )
                gm_for_metrics = gm.copy()
        except ImportError:
            LOGGER.warning("SciPy unavailable: gm smoothing skipped")
            warnings.append("SciPy unavailable: fixed gm smoothing skipped")
    selected_windows = [
        item["selected_window_points"] for item in regions
        if item.get("selected_window_points") is not None
    ]
    smoothing = {
        "mode": mode,
        "polynomial_order": smooth_order,
        "selected_window_points": (
            selected_windows[0] if len(set(selected_windows)) == 1 and selected_windows else None
        ),
        "selected_windows_points": selected_windows,
        "regions": regions,
        "metric_eligible": bool(np.isfinite(gm_for_metrics).any()),
        "warnings": warnings,
    }
    finite_metric = np.flatnonzero(np.isfinite(gm_for_metrics))
    if finite_metric.size:
        peak_index = int(finite_metric[np.argmax(np.abs(gm_for_metrics[finite_metric]))])
        peak_region = next((
            item for item in regions
            if item.get("vg_min") <= unique_vg[peak_index] <= item.get("vg_max")
        ), None)
        smoothing["peak_region_index"] = (
            peak_region.get("region_index") if peak_region else None
        )
        smoothing["peak_window_points"] = (
            peak_region.get("selected_window_points") if peak_region else
            (smooth_window if mode == "savgol" and smooth_window >= 3 else None)
        )
        smoothing["peak_selection_status"] = (
            peak_region.get("selection_status") if peak_region else "configured"
        )
    else:
        smoothing.update({
            "peak_region_index": None, "peak_window_points": None,
            "peak_selection_status": "unavailable",
        })
    return {
        "vg": unique_vg.tolist(), "gm": gm.tolist(),
        "gm_for_metrics": gm_for_metrics.tolist(), "smoothing": smoothing,
    }


def compute_ss(
    vg: list[float],
    id_values: list[float],
    noise_floor_a: float = 1e-13,
    vg_range_v: tuple[float, float] | None = None,
    min_decades: float = 1.0,
    avg_decades: float = 2.0,
    gate_leakage_values: list[float] | None = None,
    leakage_factor: float = 1.0,
    require_above_gate_leakage: bool = False,
    polarity: str | None = None,
) -> dict[str, Any]:
    """Compute SS from leakage-qualified Id data.

    The dVg/d(log10|Id|) slope is fitted in V/dec and converted exactly once
    to mV/dec. With leakage data, only |Id| > factor x |Ig| is eligible.
    """
    count = min(len(vg), len(id_values))
    vg_arr = np.asarray(vg[:count], dtype=float)
    id_arr = np.abs(np.asarray(id_values[:count], dtype=float))
    original_indices = np.arange(count)
    mask = np.isfinite(vg_arr) & np.isfinite(id_arr) & (id_arr > noise_floor_a)
    leakage_available = bool(gate_leakage_values)
    excluded_below_ig = 0
    warnings: list[str] = []
    if leakage_available:
        ig_arr = np.full(count, np.nan, dtype=float)
        leakage_count = min(count, len(gate_leakage_values or []))
        if leakage_count:
            ig_arr[:leakage_count] = np.abs(np.asarray(
                (gate_leakage_values or [])[:leakage_count], dtype=float
            ))
        leakage_mask = np.isfinite(ig_arr) & (id_arr > leakage_factor * ig_arr)
        excluded_below_ig = int(np.count_nonzero(mask & ~leakage_mask))
        mask &= leakage_mask
    elif require_above_gate_leakage:
        warnings.append(
            "SS unavailable: gate leakage was not measured, so |Id| > |Ig| "
            "cannot be verified"
        )
        mask &= False
    if vg_range_v is not None:
        mask &= (vg_arr >= vg_range_v[0]) & (vg_arr <= vg_range_v[1])
    polarity_key = str(polarity or "").strip().lower()
    ioff_vg = None
    ioff_index = None
    eligible_indices = np.flatnonzero(mask)
    if len(eligible_indices):
        ioff_index = int(eligible_indices[np.argmin(id_arr[eligible_indices])])
        ioff_vg = float(vg_arr[ioff_index])
        if polarity_key in {"p", "pfet", "p-type", "ptype"}:
            mask &= vg_arr <= ioff_vg
        elif polarity_key in {"n", "nfet", "n-type", "ntype"}:
            mask &= vg_arr >= ioff_vg
    vg_arr, id_arr, original_indices = vg_arr[mask], id_arr[mask], original_indices[mask]
    empty = {
        "ss_mv_dec": None, "ss_vg": None, "ss_region": None,
        "ss_decades": 0.0, "ss_avg_mv_dec": None, "ss_avg_decades": 0.0,
        "ss_fit_slope_v_dec": None, "ss_fit_indices": [],
        "ss_unit": "mV/dec", "ss_leakage_qualified": leakage_available,
        "ss_leakage_factor": leakage_factor if leakage_available else None,
        "ss_candidate_points": int(len(vg_arr)),
        "ss_excluded_below_ig": excluded_below_ig, "warnings": warnings,
        "ss_ioff_vg": ioff_vg,
        "ss_ioff_index": ioff_index,
        "ss_polarity": polarity_key or None,
    }
    if len(vg_arr) < 5:
        return empty
    log_id = np.log10(id_arr)
    # Evaluate the same contiguous windows as the original implementation, but
    # use running regression sums instead of calling np.polyfit/std for every
    # candidate.  This preserves the extraction method while avoiding tens of
    # thousands of tiny least-squares allocations per device.
    best: dict[str, Any] | None = None
    for start in range(len(vg_arr) - 2):
        count = 0
        sum_x = sum_y = sum_xx = sum_xy = 0.0
        min_x = float("inf")
        max_x = float("-inf")
        monotonic_up = True
        monotonic_down = True
        for end in range(start + 2, len(vg_arr)):
            # Leakage qualification must not turn separated measurements into
            # one artificial fit window. Once a gap is reached, every longer
            # candidate from this start is also discontinuous.
            if np.any(np.diff(original_indices[start:end + 1]) != 1):
                break
            if end == start + 2:
                window_start = start
            else:
                window_start = end
            for index in range(window_start, end + 1):
                x = float(log_id[index])
                y = float(vg_arr[index])
                count += 1
                sum_x += x
                sum_y += y
                sum_xx += x * x
                sum_xy += x * y
                min_x = min(min_x, x)
                max_x = max(max_x, x)
            differences = np.diff(log_id[start:end + 1])
            monotonic_up = bool(np.all(differences >= -1e-12))
            monotonic_down = bool(np.all(differences <= 1e-12))
            decades = max_x - min_x
            denominator = count * sum_xx - sum_x * sum_x
            # np.std(window) <= 1e-15 is equivalent to a vanishing regression
            # denominator at the precision relevant to measured voltage data.
            if (decades < min_decades or abs(denominator) <= 1e-24
                    or not (monotonic_up or monotonic_down)):
                continue
            slope = (count * sum_xy - sum_x * sum_y) / denominator
            value = abs(slope) * 1000.0
            if best is None or value < best["ss_mv_dec"]:
                best = {
                    "ss_mv_dec": value,
                    "ss_fit_slope_v_dec": abs(float(slope)),
                    "ss_vg": float(np.mean(vg_arr[start:end + 1])),
                    "ss_region": (float(vg_arr[start]), float(vg_arr[end])),
                    "ss_decades": decades,
                    "ss_n_points": end - start + 1,
                    "ss_fit_indices": original_indices[start:end + 1].tolist(),
                }
    total_decades = float(np.max(log_id) - np.min(log_id))
    avg_value = None
    avg_region = None
    if total_decades >= avg_decades and np.std(log_id) > 1e-15:
        slope, _ = np.polyfit(log_id, vg_arr, 1)
        avg_value = abs(float(slope)) * 1000.0
        avg_region = (float(vg_arr[0]), float(vg_arr[-1]))
    if best is None:
        best = {**empty, "ss_decades": total_decades}
    return {
        **empty,
        **best,
        "ss_avg_mv_dec": avg_value,
        "ss_avg_region": avg_region,
        "ss_avg_decades": total_decades if avg_value is not None else 0.0,
    }


def compute_on_off(
    id_values: list[float],
    gate_leakage_values: list[float] | None = None,
    leakage_factor: float = 3.0,
) -> dict[str, Any]:
    """Compute Ion/Ioff using the existing gate-leakage qualification."""
    pairs: list[tuple[float, float | None]] = []
    for index, value in enumerate(id_values):
        if not np.isfinite(value):
            continue
        leakage = None
        if gate_leakage_values is not None and index < len(gate_leakage_values):
            candidate = gate_leakage_values[index]
            if np.isfinite(candidate):
                leakage = abs(float(candidate))
        pairs.append((abs(float(value)), leakage))
    values = [value for value, _ in pairs]
    if len(values) < 2:
        return {"ion_ioff": None, "ion_ioff_log10": None}
    sorted_values = sorted(values)
    valid = [
        value for value in sorted_values
        if value > sorted_values[max(0, len(sorted_values) // 20)] * 0.01
    ] or sorted_values
    qualified = [
        value for value, leakage in pairs
        if value > 0 and (leakage is None or value > leakage_factor * leakage)
    ]
    if not qualified:
        return {
            "ion_ioff": None, "ion_ioff_log10": None, "ion_a": max(valid),
            "ioff_a": None, "ioff_method": "minimum_above_gate_leakage",
            "leakage_factor": leakage_factor,
            "warnings": ["No measured drain-current point exceeds the gate-leakage criterion"],
        }
    ion, ioff = max(valid), min(qualified)
    if ion <= 0 or ioff <= 0:
        return {"ion_ioff": None, "ion_ioff_log10": None}
    ratio = ion / ioff
    return {
        "ion_ioff": ratio,
        "ion_ioff_log10": float(np.log10(ratio)),
        "ion_a": ion,
        "ioff_a": ioff,
        "ioff_method": (
            "minimum_above_gate_leakage"
            if gate_leakage_values is not None else "minimum_measured"
        ),
        "leakage_factor": leakage_factor,
        "warnings": [],
    }


def compute_gds(vd: list[float], id_values: list[float]) -> tuple[list[float], list[float]]:
    """Compute output conductance within one already-split sweep."""
    vd_arr = np.asarray(vd, dtype=float)
    id_arr = np.asarray(id_values, dtype=float)
    mask = np.isfinite(vd_arr) & np.isfinite(id_arr)
    vd_arr, id_arr = vd_arr[mask], id_arr[mask]
    if len(vd_arr) < 2:
        return [], []
    gds = np.full(len(vd_arr), np.nan)
    first = vd_arr[1] - vd_arr[0]
    last = vd_arr[-1] - vd_arr[-2]
    if abs(first) > 1e-15:
        gds[0] = abs((id_arr[1] - id_arr[0]) / first)
    if abs(last) > 1e-15:
        gds[-1] = abs((id_arr[-1] - id_arr[-2]) / last)
    for index in range(1, len(vd_arr) - 1):
        delta = vd_arr[index + 1] - vd_arr[index - 1]
        if abs(delta) > 1e-15:
            gds[index] = abs((id_arr[index + 1] - id_arr[index - 1]) / delta)
    return vd_arr.tolist(), gds.tolist()
