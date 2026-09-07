"""
FET parameter extraction: threshold voltage, mobility, subthreshold swing,
Ion/Ioff, hysteresis, and DIBL.

All methods operate on cleaned sweep segment data and return structured
metrics with units, method, and confidence annotations.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from fet_analyzer.utils.logging import LOGGER

# Physical constants
EPSILON_0_F_PER_CM = 8.854187817e-14  # vacuum permittivity in F/cm
C = EPSILON_0_F_PER_CM  # alias


# ═══════════════════════════════════════════════════════════════════════════════
# Threshold Voltage — Peak-gm Tangent (Linear Extrapolation)
# ═══════════════════════════════════════════════════════════════════════════════

def extract_vth_peak_gm_tangent(
    vg: list[float],
    id_raw: list[float],
    gm: list[float] | None = None,
    vg_gm: list[float] | None = None,
    tangent_window_v: float = 2.0,
    tangent_min_points: int = 5,
    vds: float = 0.0,
    vds_correction: bool = True,
    use_abs: bool = True,
) -> dict[str, Any]:
    """Extract Vth using peak-gm tangent / linear extrapolation.

    Algorithm:
      1. Find Vg where |gm| is maximum
      2. Linear fit Id vs Vg in ±tangent_window_v around that point
      3. Extrapolate to Id = 0 → Vg_intercept
      4. Vth = Vg_intercept − Vds/2 (if correction enabled)

    The tangent window is auto-scaled: capped at 25% of the Vg sweep span
    but never smaller than (tangent_min_points × estimated Vg step).
    """
    warnings: list[str] = []

    vg_arr = np.array(vg, dtype=float)
    id_arr = np.array(id_raw, dtype=float)
    if use_abs:
        id_arr = np.abs(id_arr)

    # Filter NaNs
    mask = np.isfinite(vg_arr) & np.isfinite(id_arr)
    vg_arr = vg_arr[mask]
    id_arr = id_arr[mask]

    if len(vg_arr) < tangent_min_points:
        return _vth_fail("insufficient_points", warnings, len(vg_arr), tangent_min_points)

    # ── Compute gm if not provided ─────────────────────────────────────────
    if gm is None or vg_gm is None:
        gm_arr = np.zeros(len(vg_arr))
        for i in range(1, len(vg_arr) - 1):
            dvg = vg_arr[i + 1] - vg_arr[i - 1]
            if abs(dvg) > 1e-15:
                gm_arr[i] = (id_arr[i + 1] - id_arr[i - 1]) / dvg
        vg_gm_arr = vg_arr
    else:
        gm_arr = np.array(gm, dtype=float)
        vg_gm_arr = np.array(vg_gm, dtype=float)

    gm_mask = np.isfinite(gm_arr) & np.isfinite(vg_gm_arr)
    gm_arr, vg_gm_arr = gm_arr[gm_mask], vg_gm_arr[gm_mask]
    if len(gm_arr) == 0:
        return _vth_fail("no_finite_gm", warnings, 0, tangent_min_points)

    # Use |gm| for peak finding (handles both n- and p-type)
    gm_abs = np.abs(gm_arr)
    peak_idx = int(np.nanargmax(gm_abs))
    gm_peak_vg = float(vg_gm_arr[peak_idx])
    gm_peak_value = float(gm_arr[peak_idx])

    # ── Auto-scale tangent window ──────────────────────────────────────────
    vg_span = float(vg_arr[-1] - vg_arr[0]) if len(vg_arr) > 1 else 0
    vg_step = float(np.mean(np.diff(vg_arr))) if len(vg_arr) > 2 else 0.01
    # Cap at 25% of sweep span, floor at tangent_min_points × Vg_step
    window_max = max(abs(vg_span) * 0.25, tangent_min_points * abs(vg_step) * 2)
    window = min(abs(tangent_window_v), window_max)
    window = max(window, tangent_min_points * abs(vg_step))

    if abs(window - abs(tangent_window_v)) > 0.001:
        LOGGER.debug(
            "Tangent window auto-scaled: %.3f → %.3f V (Vg span=%.3f V)",
            tangent_window_v, window, vg_span,
        )

    vg_center = gm_peak_vg
    win_indices = np.where(
        (vg_arr >= vg_center - window) & (vg_arr <= vg_center + window)
    )[0]

    if len(win_indices) == 0:
        return _vth_fail("empty_tangent_window", warnings, 0, tangent_min_points)

    win_start = int(win_indices[0])
    win_end = int(win_indices[-1]) + 1

    if win_end - win_start < tangent_min_points:
        return _vth_fail("insufficient_window_points", warnings,
                         win_end - win_start, tangent_min_points)

    vg_win = vg_arr[win_start:win_end]
    id_win = id_arr[win_start:win_end]

    # ── Linear fit: Id = slope × Vg + intercept ────────────────────────────
    A = np.vstack([vg_win, np.ones_like(vg_win)]).T
    slope, intercept = np.linalg.lstsq(A, id_win, rcond=None)[0]

    # R²
    id_pred = slope * vg_win + intercept
    ss_res = np.sum((id_win - id_pred) ** 2)
    ss_tot = np.sum((id_win - np.mean(id_win)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 1e-30 else 0.0

    # Extrapolate to Id = 0
    if abs(slope) < 1e-30:
        return _vth_fail("zero_slope", warnings, len(vg_win), tangent_min_points)

    vg_intercept = -intercept / slope

    # Vds/2 correction
    vth = vg_intercept
    if vds_correction and abs(vds) > 1e-9:
        vth = vg_intercept - vds / 2.0

    return {
        "vth_v": float(vth),
        "vth_method": "peak_gm_tangent",
        "vg_intercept_v": float(vg_intercept),
        "tangent_slope_a_per_v": float(slope),
        "tangent_r2": float(r2),
        "tangent_n_points": len(vg_win),
        "tangent_vg_range": (float(vg_win[0]), float(vg_win[-1])),
        "gm_peak_vg": gm_peak_vg,
        "gm_peak_value_s": gm_peak_value,
        "vds_corrected": vds_correction,
        "warnings": warnings,
    }


def extract_vth_constant_current(
    vg: list[float],
    id_raw: list[float],
    i_target_a_per_um: float = 1e-7,
    width_um: float = 100.0,
    use_abs: bool = True,
) -> dict[str, Any]:
    """Extract Vth via constant-current method.

    Find Vg where |Id|/W crosses the target current density.
    Uses linear interpolation between bracketing points.

    Returns same structure as extract_vth_peak_gm_tangent.
    """
    warnings: list[str] = []
    i_target = i_target_a_per_um * width_um  # target in A

    vg_arr = np.array(vg, dtype=float)
    id_arr = np.array(id_raw, dtype=float)
    if use_abs:
        id_arr = np.abs(id_arr)

    mask = np.isfinite(vg_arr) & np.isfinite(id_arr)
    vg_arr = vg_arr[mask]
    id_arr = id_arr[mask]

    if len(vg_arr) < 2:
        return _vth_fail("insufficient_points_cc", warnings, len(vg_arr), 2)

    # Find where current crosses target
    diff = id_arr - i_target
    crossing_indices = np.where(np.diff(np.signbit(diff)))[0]

    if len(crossing_indices) == 0:
        warnings.append(
            f"Constant-current target {i_target:.2e} A not reached "
            f"(|Id| range: {np.min(id_arr):.2e}–{np.max(id_arr):.2e} A)"
        )
        return {
            "vth_v": None,
            "vth_method": "constant_current",
            "i_target_a": float(i_target),
            "i_target_a_per_um": i_target_a_per_um,
            "warnings": warnings,
        }

    # Interpolate at first crossing
    i = int(crossing_indices[0])
    if i + 1 >= len(vg_arr):
        i = len(vg_arr) - 2

    # Linear interpolation between (vg[i], id[i]) and (vg[i+1], id[i+1])
    frac = (i_target - id_arr[i]) / (id_arr[i + 1] - id_arr[i])
    vth_interp = vg_arr[i] + frac * (vg_arr[i + 1] - vg_arr[i])

    return {
        "vth_v": float(vth_interp),
        "vth_method": "constant_current",
        "i_target_a": float(i_target),
        "i_target_a_per_um": float(i_target_a_per_um),
        "crossing_vg_range": (float(vg_arr[i]), float(vg_arr[i + 1])),
        "warnings": warnings,
    }


def _vth_fail(
    reason: str,
    warnings: list[str],
    n_points: int,
    min_points: int,
) -> dict[str, Any]:
    """Build a Vth failure result."""
    warnings.append(
        f"Vth extraction failed ({reason}): "
        f"{n_points} points available, {min_points} required"
    )
    return {
        "vth_v": None,
        "vth_method": "peak_gm_tangent",
        "warnings": warnings,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Mobility Extraction
# ═══════════════════════════════════════════════════════════════════════════════

def extract_field_effect_mobility(
    gm_max_s: float,
    cox_f_per_cm2: float,
    width_um: float,
    length_um: float,
    vds: float,
) -> dict[str, Any]:
    """Compute field-effect mobility from peak gm.

    μ_FE = gm_max × L / (Cox × W × Vds)

    All inputs in SI: gm (S), Cox (F/cm²), W/L (μm), Vds (V).
    Returns μ in cm²/V·s.
    """
    warnings: list[str] = []

    if cox_f_per_cm2 is None or cox_f_per_cm2 <= 0:
        return {"mobility_cm2_vs": None, "method": "field_effect", "warnings": ["Cox not available"]}
    if length_um is None or length_um <= 0:
        return {"mobility_cm2_vs": None, "method": "field_effect", "warnings": ["Lch not available"]}
    if abs(vds) < 1e-9:
        return {"mobility_cm2_vs": None, "method": "field_effect", "warnings": ["Vds ≈ 0"]}

    # gm × L / (Cox × W × Vds)
    # Units: (A/V) × (μm) / (F/cm² × μm × V) = cm²/V·s
    # Convert: 1 F/cm² = 1 C/(V·cm²) → numerator in (A·μm)/(V) = (C·μm)/(s·V)
    # Cox in F/cm² → multiply by 1e-8 to get F/μm², then:
    # μ = gm × L / (Cox × 1e-8 × W × Vds) in cm²/V·s? No...

    # Let me do this carefully:
    # gm [S] = [A/V]
    # Cox [F/cm²] × W [μm] × L [μm]:
    #   Cox × (W × 1e-4 cm) × (L × 1e-4 cm) = Cox × W × L × 1e-8 [F]
    # μ = gm × L [μm] / (Cox [F/cm²] × W [μm] × Vds [V])
    #   = gm [A/V] × L [μm] / (Cox [F/cm²] × W [μm] × Vds [V])
    #   = gm × L / (Cox × W × Vds)  [μm/F → convert]

    # More carefully:
    # gm = ∂Id/∂Vg [A/V]
    # Id = (W/L) × μ × Cox' × (Vg-Vth) × Vds
    #   where Cox' is F/cm²
    # ∂Id/∂Vg = (W/L) × μ × Cox' × Vds
    # μ = gm × L / (W × Cox' × Vds)
    #
    # Units check: gm [A/V] × L [cm] / (W [cm] × Cox' [F/cm²] × Vds [V])
    # = (A/V) × (cm) / (cm × F/cm² × V) = (A/V) × (cm) / (cm × (A·s/V) · (1/cm²) × V)
    # That's getting messy. Let me just convert everything to SI:
    # Cox' in F/cm² = Cox' × 1e4 F/m²
    # W, L in m
    # Then μ = gm × L / (W × Cox' × 1e4 × Vds) [m²/V·s]
    # To get cm²/V·s: multiply by 1e4
    # μ [cm²/V·s] = gm × L / (W × Cox' × Vds) with L, W in cm

    w_cm = width_um * 1e-4
    l_cm = length_um * 1e-4

    denominator = w_cm * cox_f_per_cm2 * abs(vds)
    if denominator < 1e-30:
        return {"mobility_cm2_vs": None, "method": "field_effect", "warnings": ["Denominator ≈ 0"]}

    mu = abs(gm_max_s) * l_cm / denominator

    return {
        "mobility_cm2_vs": float(mu),
        "method": "field_effect",
        "warnings": warnings,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Hysteresis
# ═══════════════════════════════════════════════════════════════════════════════

def extract_hysteresis(
    seg_forward: Any,  # SweepSegment
    seg_reverse: Any,  # SweepSegment
    method: str = "midpoint_overlap",
    midpoint_fraction: float = 0.5,
) -> dict[str, Any]:
    """Extract hysteresis between forward and reverse sweeps.

    Method 'midpoint_overlap': Find Vg where Id crosses the midpoint of the log-current overlap range,
    compute ΔV = Vg_reverse - Vg_forward at that current.

    Returns:
        {
            delta_v: float | None,    # Vhyst in volts
            method: str,
            vg_forward: float | None,
            vg_reverse: float | None,
            i_at_hysteresis: float | None,
        }
    """
    vg_fwd = np.array(seg_forward.sweep_values, dtype=float)
    id_fwd = np.abs(np.array(seg_forward.data.get("Id", seg_forward.data.get("Is", [])), dtype=float))
    vg_rev = np.array(seg_reverse.sweep_values, dtype=float)
    id_rev = np.abs(np.array(seg_reverse.data.get("Id", seg_reverse.data.get("Is", [])), dtype=float))

    # Filter NaN
    fwd_mask = np.isfinite(vg_fwd) & np.isfinite(id_fwd)
    rev_mask = np.isfinite(vg_rev) & np.isfinite(id_rev)
    vg_fwd = vg_fwd[fwd_mask]
    id_fwd = id_fwd[fwd_mask]
    vg_rev = vg_rev[rev_mask]
    id_rev = id_rev[rev_mask]

    if len(vg_fwd) < 3 or len(vg_rev) < 3:
        return {"delta_v": None, "method": method, "warnings": ["Insufficient points for hysteresis"]}

    # Current range overlap
    i_min = max(np.min(id_fwd), np.min(id_rev))
    i_max = min(np.max(id_fwd), np.max(id_rev))

    if i_min >= i_max:
        return {"delta_v": None, "method": method, "warnings": ["No current overlap between sweeps"]}

    # Target current at Cox/2 = midpoint of log overlap
    if method == "midpoint_overlap":
        i_target = 10 ** ((np.log10(i_min) + np.log10(i_max)) / 2)
    else:
        i_target = i_min + midpoint_fraction * (i_max - i_min)

    def interpolate_vg(vg_values: np.ndarray, current_values: np.ndarray) -> float | None:
        log_i = np.log10(np.maximum(current_values, np.finfo(float).tiny))
        order = np.argsort(log_i)
        log_i, vg_values = log_i[order], vg_values[order]
        unique_i, inverse = np.unique(log_i, return_inverse=True)
        unique_vg = np.array([np.median(vg_values[inverse == idx]) for idx in range(len(unique_i))])
        target = np.log10(i_target)
        if target < unique_i[0] or target > unique_i[-1]:
            return None
        return float(np.interp(target, unique_i, unique_vg))

    vg_f = interpolate_vg(vg_fwd, id_fwd)
    vg_r = interpolate_vg(vg_rev, id_rev)
    if vg_f is None or vg_r is None:
        return {"delta_v": None, "method": method,
                "warnings": ["Hysteresis interpolation target lies outside a sweep"]}

    return {
        "delta_v": float(vg_r - vg_f),
        "delta_v_abs": float(abs(vg_r - vg_f)),
        "method": method,
        "vg_forward_v": vg_f,
        "vg_reverse_v": vg_r,
        "i_at_hysteresis_a": float(i_target),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# DIBL (Drain-Induced Barrier Lowering)
# ═══════════════════════════════════════════════════════════════════════════════

def extract_dibl(
    segments: list[Any],
    vth_results: dict[float, dict[str, Any]],
    polarity: str = "p",
) -> dict[str, Any]:
    """Compute DIBL from Vth at two or more Vd levels.

    DIBL = −ΔVth / ΔVds  [mV/V]

    Requires at least 2 forward sweep segments with different Vd values.
    """
    if len(vth_results) < 2:
        return {"dibl_mv_v": None, "warnings": ["Need ≥2 Vds levels for DIBL"]}

    # Compare drain-field magnitude; retain signed Vds separately for provenance.
    sorted_items = sorted(vth_results.items(), key=lambda x: abs(x[0]))
    vd_vals = []
    signed_vd_vals = []
    vth_vals = []

    for vd, result in sorted_items:
        if result.get("vth_v") is not None:
            vd_vals.append(abs(vd))
            signed_vd_vals.append(float(vd))
            vth_vals.append(result["vth_v"])

    if len(vd_vals) < 2:
        return {"dibl_mv_v": None, "warnings": ["Insufficient valid Vth values"]}

    x = np.asarray(vd_vals, dtype=float)
    y = np.asarray(vth_vals, dtype=float)
    if np.ptp(x) < 1e-15:
        return {"dibl_mv_v": None, "warnings": ["Vds magnitudes are not distinct"]}
    slope, intercept = np.polyfit(x, y, 1)
    predicted = slope * x + intercept
    residuals = y - predicted
    total = float(np.sum((y - np.mean(y)) ** 2))
    r2 = float(1 - np.sum(residuals ** 2) / total) if total > 1e-30 else None
    slope_std = None
    if len(x) > 2:
        slope_std = float(np.sqrt(np.sum(residuals ** 2) / (len(x) - 2) / np.sum((x - np.mean(x)) ** 2)))
    # Conventional positive DIBL means threshold magnitude decreases with drain field.
    sign = -1.0 if polarity.lower() == "n" else 1.0
    dibl = sign * 1000.0 * slope

    return {
        "dibl_mv_v": float(dibl),
        "dibl_v_v": float(dibl / 1000),
        "vd_pairs": list(zip(vd_vals, vth_vals)),
        "fit_points": [
            {"measured_vds_v": signed, "abs_vds_v": magnitude, "vth_v": vth}
            for signed, magnitude, vth in zip(signed_vd_vals, vd_vals, vth_vals)
        ],
        "raw_vth_slope_v_v": float(slope),
        "intercept_v": float(intercept),
        "polarity_multiplier": sign,
        "slope_std_v_v": slope_std,
        "ci95_mv_v": float(1.96 * 1000 * slope_std) if slope_std is not None else None,
        "r2": r2,
        "polarity": polarity.lower(),
        "method": "linear_fit_vth_vs_abs_vds",
        "warnings": [],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Bulk extraction runner
# ═══════════════════════════════════════════════════════════════════════════════

def extract_all_transfer_metrics(
    segments: list[Any],
    classification: dict[str, Any],
    config: dict[str, Any],
    device_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run all transfer parameter extraction on a set of forward segments.

    Returns complete extracted metrics dictionary.
    """
    transfer_cfg = config.get("transfer", {})
    device_cfg = device_params or config.get("device_defaults", {})

    vth_method = transfer_cfg.get("vth_method", "peak_gm_tangent")
    vds_correction = transfer_cfg.get("vth_vds_correction", True)
    tangent_window = transfer_cfg.get("tangent_window_v", 2.0)
    tangent_min = transfer_cfg.get("tangent_min_points", 5)
    w = device_cfg.get("channel_width_um", 100.0)
    l = device_cfg.get("channel_length_um")
    tox_nm = device_cfg.get("oxide_thickness_nm", 90.0)
    eps_r = device_cfg.get("dielectric_constant", 3.9)
    cox = device_cfg.get("cox_f_per_cm2")
    if cox is None:
        tox_cm = tox_nm * 1e-7
        cox = C * eps_r / tox_cm  # F/cm²

    results: dict[str, Any] = {
        "device_params": {
            "width_um": w,
            "length_um": l,
            "tox_nm": tox_nm,
            "epsilon_r": eps_r,
            "cox_f_per_cm2": cox,
        },
        "vth": {},
        "mobility": {},
        "hysteresis": {},
        "dibl": None,
        "ss": {},
    }

    # ── Vth extraction per bias ───────────────────────────────────────────
    from fet_analyzer.analysis.segmentation import group_by_bias
    bias_groups = group_by_bias(segments)

    vth_results = {}
    for bias_key, segs in sorted(bias_groups.items()):
        fwd = [s for s in segs if s.direction == "forward"]
        if not fwd:
            continue
        seg = fwd[0]
        vg = seg.sweep_values
        id_data = seg.data.get(
            classification.get("drain_current_raw_column", "Id"), []
        )
        vds = seg.bias_level if seg.bias_variable and seg.bias_variable.lower() in ("vd", "vs") else 0.1

        # Compute gm only within this already split (bias, direction) segment.
        from fet_analyzer.analysis.numerics import compute_gm_with_diagnostics
        gm_result = compute_gm_with_diagnostics(vg, id_data, transfer_cfg)
        vg_gm, gm_values = gm_result["vg"], gm_result["gm_for_metrics"]

        if vth_method == "peak_gm_tangent" and gm_result["smoothing"]["metric_eligible"]:
            vth_result = extract_vth_peak_gm_tangent(
                vg, id_data,
                gm=gm_values or None, vg_gm=vg_gm or None,
                tangent_window_v=tangent_window,
                tangent_min_points=tangent_min,
                vds=vds if vds != 0 else 0.1,
                vds_correction=vds_correction,
            )
        elif vth_method == "constant_current":
            cc = transfer_cfg.get("constant_current_value", 1e-7)
            vth_result = extract_vth_constant_current(
                vg, id_data,
                i_target_a_per_um=cc,
                width_um=w,
            )
        elif vth_method == "peak_gm_tangent":
            vth_result = {"vth_v": None, "vth_method": vth_method,
                          "warnings": ["gm-dependent Vth suppressed because adaptive smoothing was unavailable"]}
        else:
            vth_result = {"vth_v": None, "vth_method": vth_method, "warnings": [f"Unknown method: {vth_method}"]}

        vth_result["vds_v"] = vds
        results["vth"][str(bias_key)] = vth_result
        vth_results[bias_key] = vth_result

        # ── Mobility ───────────────────────────────────────────────────
        gm_max = abs(vth_result.get("gm_peak_value_s", 0))
        if gm_max > 0 and l is not None:
            mob = extract_field_effect_mobility(
                gm_max_s=gm_max,
                cox_f_per_cm2=cox,
                width_um=w,
                length_um=l,
                vds=vds,
            )
        else:
            mob = {"mobility_cm2_vs": None, "method": "field_effect", "warnings": []}
        results["mobility"][str(bias_key)] = mob

        # ── SS ──────────────────────────────────────────────────────────
        from fet_analyzer.analysis.numerics import compute_ss
        gate_col = classification.get("gate_leakage_column")
        gate_leakage = seg.data.get(gate_col, []) if gate_col else None
        ss = compute_ss(
            vg, id_data,
            noise_floor_a=float(transfer_cfg.get("noise_floor_a", 1e-13)),
            vg_range_v=tuple(transfer_cfg["ss_vg_range_v"])
            if transfer_cfg.get("ss_vg_range_v") else None,
            gate_leakage_values=gate_leakage,
            leakage_factor=float(transfer_cfg.get("ss_leakage_factor", 1.0)),
            require_above_gate_leakage=bool(
                transfer_cfg.get("ss_require_above_gate_leakage", True)
            ),
            polarity=device_cfg.get("polarity"),
        )
        results["ss"][str(bias_key)] = ss

    # ── Hysteresis — pair forward/reverse per bias ────────────────────────
    for bias_key, segs in sorted(bias_groups.items()):
        fwd = [s for s in segs if s.direction == "forward"]
        rev = [s for s in segs if s.direction == "reverse"]
        if fwd and rev:
            hyst = extract_hysteresis(fwd[0], rev[0])
            results["hysteresis"][str(bias_key)] = hyst

    # ── DIBL ──────────────────────────────────────────────────────────────
    results["dibl"] = extract_dibl(segments, vth_results, polarity=device_cfg.get("polarity", "p"))

    # ── Global summaries ──────────────────────────────────────────────────
    vth_vals = [r["vth_v"] for r in results["vth"].values() if r.get("vth_v") is not None]
    mob_vals = [r["mobility_cm2_vs"] for r in results["mobility"].values() if r.get("mobility_cm2_vs") is not None]
    hyst_vals = [r["delta_v_abs"] for r in results["hysteresis"].values() if r.get("delta_v_abs") is not None]
    ss_vals = [r["ss_mv_dec"] for r in results["ss"].values() if r.get("ss_mv_dec") is not None]

    results["summary"] = {
        "vth_v_mean": float(np.mean(vth_vals)) if vth_vals else None,
        "vth_v_std": float(np.std(vth_vals, ddof=1)) if len(vth_vals) > 1 else None,
        "vth_v_range": (float(min(vth_vals)), float(max(vth_vals))) if vth_vals else None,
        "mobility_cm2_vs_max": float(max(mob_vals)) if mob_vals else None,
        "mobility_cm2_vs_mean": float(np.mean(mob_vals)) if mob_vals else None,
        "mobility_cm2_vs_std": float(np.std(mob_vals, ddof=1)) if len(mob_vals) > 1 else None,
        "hysteresis_v_max": float(max(hyst_vals)) if hyst_vals else None,
        "ss_mv_dec_min": float(min(ss_vals)) if ss_vals else None,
        "ss_mv_dec_mean": float(np.mean(ss_vals)) if ss_vals else None,
        "ss_mv_dec_std": float(np.std(ss_vals, ddof=1)) if len(ss_vals) > 1 else None,
        "dibl_mv_v": results["dibl"].get("dibl_mv_v"),
    }

    return results
