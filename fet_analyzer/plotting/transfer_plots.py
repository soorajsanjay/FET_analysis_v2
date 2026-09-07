"""
Transfer curve plotting: Id-Vg (linear + log), gm, subthreshold swing,
and gate leakage comparison for FET transfer characteristics.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from fet_analyzer.analysis.ion_bias import resolve_ion_bias
from fet_analyzer.analysis.numerics import (
    compute_gm, compute_gm_with_diagnostics, nearest_abs_current_at_voltage,
)
from fet_analyzer.path_utils import prepare_write_path
from fet_analyzer.utils.logging import LOGGER
from fet_analyzer.utils.units import format_eng, width_normalize_id

# Try to import matplotlib, gracefully degrade if not available
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


# ── Plot styling ────────────────────────────────────────────────────────────

def _setup_style(config: dict[str, Any] | None = None):
    """Apply publication-quality plot styling."""
    if not HAS_MPL:
        return
    plot_cfg = (config or {}).get("plots", {})
    plt.rcParams.update({
        "font.size": plot_cfg.get("font_size", 11),
        "font.family": plot_cfg.get("font_family", "sans-serif"),
        "axes.grid": plot_cfg.get("show_grid", True),
        "figure.dpi": plot_cfg.get("dpi", 150),
        "savefig.dpi": plot_cfg.get("dpi", 150),
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.1,
    })


def _get_colors(config: dict[str, Any] | None = None) -> list[str]:
    """Return color palette from config."""
    return (config or {}).get("plots", {}).get("palette", [
        "#0072B2", "#E69F00", "#009E73", "#F0E442", "#56B4E9",
        "#D55E00", "#CC79A7", "#000000", "#999999", "#882255",
    ])


def _analysis_settings(
    config: dict[str, Any] | None,
    device_params: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return the effective transfer settings used by extraction and plots."""
    cfg = config or {}
    transfer = cfg.get("transfer", {})
    device = device_params or cfg.get("device_defaults", {})
    ion_bias = resolve_ion_bias(cfg, device)
    ss_noise_floor = transfer.get("noise_floor_a", 1e-13)
    cleaning_noise_floor = device.get("noise_floor_a", ss_noise_floor)
    return {
        "ion_method_used": transfer.get("ion_method", "fixed_vg"),
        "ion_method_configured": transfer.get("ion_method", "fixed_vg"),
        "ion_method_note": "Primary Ion/Ioff uses the configured method; optional fixed-gate and fixed-overdrive checkboxes may report either or both additional reads.",
        "report_ion_at_fixed_vg": bool(transfer.get("report_ion_at_fixed_vg", False)),
        "report_ion_at_fixed_overdrive": bool(transfer.get("report_ion_at_fixed_overdrive", False)) or any(
            transfer.get(key) is not None for key in ("ion_overdrive_v", "overdrive_v", "ion_overdrive_field_mv_cm")
        ),
        "ion_constant_vg_v": ion_bias["fixed_vg_v"],
        "ion_fixed_vg_v": ion_bias["fixed_vg_v"],
        "ion_fixed_vg_input_v": ion_bias["fixed_vg_input_v"],
        "ion_gate_field_mv_cm": ion_bias["gate_field_mv_cm"],
        "ion_fixed_vg_source": ion_bias["fixed_vg_source"],
        "ion_overdrive_v": ion_bias["overdrive_v"],
        "ion_overdrive_input_v": ion_bias["overdrive_input_v"],
        "ion_overdrive_field_mv_cm": ion_bias["overdrive_field_mv_cm"],
        "ion_overdrive_source": ion_bias["overdrive_source"],
        "ion_oxide_thickness_nm": ion_bias["oxide_thickness_nm"],
        "ion_bias_warnings": ion_bias["warnings"],
        "ioff_method_used": "minimum_abs_id_above_gate_leakage",
        "ioff_method_configured": transfer.get("ioff_method", "minimum_above_ig"),
        "ioff_leakage_factor": float(transfer.get("ioff_leakage_factor", 3.0)),
        "vth_method": transfer.get("vth_method", "peak_gm_tangent"),
        "vth_tangent_window_v": float(transfer.get("tangent_window_v", 2.0)),
        "vth_tangent_min_points": int(transfer.get("tangent_min_points", 5)),
        "vth_constant_current_a_per_um": (
            float(transfer["constant_current_value"])
            if transfer.get("constant_current_value") is not None else None
        ),
        "vth_vds_correction": bool(transfer.get("vth_vds_correction", True)),
        "ss_method_used": "minimum_fit_over_at_least_1_current_decade",
        "ss_average_min_decades": 2.0,
        "ss_require_above_gate_leakage": bool(
            transfer.get("ss_require_above_gate_leakage", True)
        ),
        "ss_leakage_factor": float(transfer.get("ss_leakage_factor", 1.0)),
        "ss_unit_conversion": "mV/dec = 1000 x |dVg/d(log10|Id|)| in V/dec",
        "noise_floor_a": float(ss_noise_floor),
        "summary_config": cfg.get("summary", {}),
        "cleaning_noise_floor_a": float(cleaning_noise_floor),
        "gm_savgol_window": int(transfer.get("savgol_window", 0)),
        "gm_savgol_order": int(transfer.get("savgol_order", 1)),
        "gm_smoothing_mode": transfer.get("smooth_method", "savgol"),
        "gm_adaptive_min_fraction": float(transfer.get("adaptive_gm_min_fraction", 0.05)),
        "gm_adaptive_max_fraction": float(transfer.get("adaptive_gm_max_fraction", 0.10)),
        "gm_adaptive_peak_tolerance": float(transfer.get("adaptive_gm_peak_tolerance", 0.05)),
        "gm_adaptive_peak_shift_steps": float(transfer.get("adaptive_gm_peak_shift_steps", 1.0)),
        "gm_adaptive_snr_plateau_tolerance": float(transfer.get("adaptive_gm_snr_plateau_tolerance", 0.10)),
        "gm_adaptive_stable_transitions": int(transfer.get("adaptive_gm_stable_transitions", 2)),
        "normalize_by_width": bool(transfer.get("normalize_by_width", True)),
        "channel_width_um": device.get("channel_width_um", 100.0),
    }


# ── Data helpers ────────────────────────────────────────────────────────────

def _ss_fit_window_bounds(
    fit_vg: np.ndarray,
    fit_id: np.ndarray,
    padding_decades: float = 0.08,
) -> tuple[float, float, float, float] | None:
    """Return a finite data-space box around SS points for a logarithmic axis."""
    vg_values = np.asarray(fit_vg, dtype=float)
    id_values = np.asarray(fit_id, dtype=float)
    valid = np.isfinite(vg_values) & np.isfinite(id_values) & (id_values > 0)
    if not np.any(valid):
        return None

    x_min = float(np.min(vg_values[valid]))
    x_max = float(np.max(vg_values[valid]))
    log_id = np.log10(id_values[valid])
    y_min = float(10 ** (np.min(log_id) - padding_decades))
    y_max = float(10 ** (np.max(log_id) + padding_decades))
    return x_min, x_max, y_min, y_max


def _compute_gm(
    vg: list[float],
    id_vals: list[float],
    smooth_window: int = 0,
    smooth_order: int = 1,
) -> tuple[list[float], list[float]]:
    """Compatibility wrapper around the shared numerical gm implementation."""
    return compute_gm(vg, id_vals, smooth_window, smooth_order)

def _compute_ss(
    vg: list[float],
    id_vals: list[float],
    noise_floor_a: float = 1e-13,
    vg_range_v: tuple[float, float] | None = None,
    min_decades: float = 1.0,
    avg_decades: float = 2.0,
) -> dict[str, Any]:
    """Compute subthreshold swing SS = dVg/d(log10|Id|).

    Returns {
        ss_mv_dec: minimum SS in mV/decade
        ss_vg: Vg at SS minimum
        ss_region: (vg_min, vg_max) of subthreshold region
    }
    """
    vg_arr = np.array(vg, dtype=float)
    id_arr = np.array(id_vals, dtype=float)

    # Use abs Id, filter noise
    id_abs = np.abs(id_arr)
    mask = np.isfinite(vg_arr) & np.isfinite(id_arr) & (id_abs > noise_floor_a)

    if vg_range_v is not None:
        mask &= (vg_arr >= vg_range_v[0]) & (vg_arr <= vg_range_v[1])

    vg_arr = vg_arr[mask]
    id_arr = id_abs[mask]

    if len(vg_arr) < 5:
        return {
            "ss_mv_dec": None,
            "ss_vg": None,
            "ss_region": None,
            "ss_decades": 0.0,
            "ss_avg_mv_dec": None,
            "ss_avg_decades": 0.0,
        }

    # SS = dVg / d(log10 |Id|).  Use finite contiguous windows and require
    # enough current span so a single noisy point cannot define "minimum SS".
    log_id = np.log10(id_arr)

    best: dict[str, Any] | None = None
    for start in range(0, len(vg_arr) - 2):
        for end in range(start + 2, len(vg_arr)):
            log_window = log_id[start:end + 1]
            decades = float(np.max(log_window) - np.min(log_window))
            if decades < min_decades:
                continue
            if np.std(log_window) <= 1e-15:
                continue
            slope, _ = np.polyfit(log_window, vg_arr[start:end + 1], 1)
            ss_val = abs(float(slope)) * 1000.0
            if best is None or ss_val < best["ss_mv_dec"]:
                best = {
                    "ss_mv_dec": ss_val,
                    "ss_vg": float(np.mean(vg_arr[start:end + 1])),
                    "ss_region": (float(vg_arr[start]), float(vg_arr[end])),
                    "ss_decades": decades,
                    "ss_n_points": end - start + 1,
                }

    total_decades = float(np.max(log_id) - np.min(log_id))
    ss_avg_mv_dec = None
    ss_avg_region = None
    if total_decades >= avg_decades and np.std(log_id) > 1e-15:
        avg_slope, _ = np.polyfit(log_id, vg_arr, 1)
        ss_avg_mv_dec = abs(float(avg_slope)) * 1000.0
        ss_avg_region = (float(vg_arr[0]), float(vg_arr[-1]))

    if best is None:
        return {
            "ss_mv_dec": None,
            "ss_vg": None,
            "ss_region": None,
            "ss_decades": total_decades,
            "ss_avg_mv_dec": ss_avg_mv_dec,
            "ss_avg_region": ss_avg_region,
            "ss_avg_decades": total_decades if ss_avg_mv_dec is not None else 0.0,
        }

    return {
        **best,
        "ss_avg_mv_dec": ss_avg_mv_dec,
        "ss_avg_region": ss_avg_region,
        "ss_avg_decades": total_decades if ss_avg_mv_dec is not None else 0.0,
    }


def _compute_on_off(
    id_values: list[float], gate_values: list[float] | None = None,
    leakage_factor: float = 3.0,
) -> dict[str, Any]:
    """Compute Ion/Ioff ratio from a list of drain current values.

    Uses max(|Id|) / min(|Id|) — direction-agnostic.
    Excludes noise floor points.
    """
    pairs = []
    for index, value in enumerate(id_values):
        if value != value:
            continue
        gate = None
        if gate_values is not None and index < len(gate_values) and gate_values[index] == gate_values[index]:
            gate = abs(gate_values[index])
        pairs.append((abs(value), gate))
    abs_vals = [value for value, _ in pairs]
    if len(abs_vals) < 2:
        return {"ion_ioff": None, "ion_ioff_log10": None}

    # Filter noise floor
    sorted_vals = sorted(abs_vals)
    # Use 5th percentile as noise floor estimate if no explicit floor
    valid = [v for v in sorted_vals if v > sorted_vals[max(0, len(sorted_vals)//20)] * 0.01]
    if not valid:
        valid = sorted_vals

    leakage_qualified = [value for value, gate in pairs
                         if value > 0 and (gate is None or value > leakage_factor * gate)]
    if not leakage_qualified:
        return {"ion_ioff": None, "ion_ioff_log10": None, "ion_a": max(valid),
                "ioff_a": None, "ioff_method": "minimum_above_gate_leakage",
                "leakage_factor": leakage_factor,
                "warnings": ["No measured drain-current point exceeds the gate-leakage criterion"]}
    i_off = min(leakage_qualified)
    i_on = max(valid)
    if i_off <= 0 or i_on <= 0:
        return {"ion_ioff": None, "ion_ioff_log10": None}

    ratio = i_on / i_off
    return {
        "ion_ioff": ratio,
        "ion_ioff_log10": float(np.log10(ratio)),
        "ion_a": i_on,
        "ioff_a": i_off,
        "ioff_method": "minimum_above_gate_leakage" if gate_values is not None else "minimum_measured",
        "leakage_factor": leakage_factor,
        "warnings": [],
    }


# Keep plotting and standalone sweep analysis on the same numerical
# implementations.  The local definitions above are retained for compatibility
# with older callers, but these shared aliases are authoritative.
from fet_analyzer.analysis.numerics import (
    compute_gm as _compute_gm,
    compute_on_off as _compute_on_off,
    compute_ss as _compute_ss,
)


def _ss_fit_coordinates(
    vg: list[float],
    id_values: list[float],
    ss_result: dict[str, Any],
    noise_floor_a: float,
    width_um: float,
    normalize: bool,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Return the fitted SS line in the transfer-log plot coordinates."""
    fit_indices = ss_result.get("ss_fit_indices") or []
    if not fit_indices or ss_result.get("ss_mv_dec") is None:
        return None

    vg_arr = np.asarray(vg, dtype=float)
    id_arr = np.abs(np.asarray(id_values, dtype=float))
    valid_indices = [i for i in fit_indices if i < len(vg_arr) and i < len(id_arr)]
    vg_fit, id_fit = vg_arr[valid_indices], id_arr[valid_indices]
    if len(vg_fit) < 3:
        return None

    log_id = np.log10(id_fit)
    if np.std(log_id) <= 1e-15:
        return None
    slope, intercept = np.polyfit(log_id, vg_fit, 1)
    if abs(slope) <= 1e-15:
        return None

    # Parameterize the fitted segment in log-current space. Inverting a nearly
    # horizontal regression over the Vg extrema can overflow and autoscale the
    # image far away from the measured currents.
    log_id_line = np.linspace(float(np.min(log_id)), float(np.max(log_id)), 100)
    vg_line = slope * log_id_line + intercept
    id_line = 10 ** log_id_line
    if normalize and width_um:
        id_line = id_line / width_um
    return vg_line, id_line


# ── Main transfer plot function ─────────────────────────────────────────────

def plot_transfer_curves(
    segments: list[Any],
    classification: dict[str, Any],
    output_dir: Path,
    config: dict[str, Any] | None = None,
    device_params: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate publication-quality transfer curve plots.

    Creates:
      1. Id-Vg linear scale (all bias levels, forward sweep)
      2. |Id|-Vg log scale
      3. gm-Vg with peak annotation
      4. |Id| vs |Ig| leakage comparison

    Returns dict of extracted metrics.
    """
    if not HAS_MPL:
        # Plotting is optional; extraction must still work in a headless environment.
        LOGGER.warning("matplotlib not available - calculating transfer metrics without plots")
        cfg = config or {}
        sweep_var = classification.get("sweep_variable", "Vg")
        drain_raw = classification.get("drain_current_raw_column", "Id")
        noise_floor = cfg.get("transfer", {}).get("noise_floor_a", 1e-13)
        metrics: dict[str, Any] = {"segments": {}, "ss_min_mv_dec": None,
                                   "gm_max_s": None, "gm_max_vg": None,
                                   "ion_ioff": None, "ion_ioff_log10": None,
                                   "analysis_settings": _analysis_settings(config, device_params)}
        for index, seg in enumerate(segments):
            if seg.direction != "forward":
                continue
            vg, current = seg.data.get(sweep_var, []), seg.data.get(drain_raw, [])
            gm_result = compute_gm_with_diagnostics(vg, current, cfg.get("transfer", {}))
            gm_vg = np.asarray(gm_result["vg"], dtype=float)
            gm = np.asarray(gm_result["gm_for_metrics"], dtype=float)
            finite = np.isfinite(gm)
            peak = int(np.nanargmax(np.abs(gm))) if finite.any() else None
            gate_col = classification.get("gate_leakage_column")
            gate_raw = seg.data.get(gate_col, []) if gate_col else None
            ss = _compute_ss(
                vg, current, noise_floor_a=noise_floor,
                gate_leakage_values=gate_raw,
                leakage_factor=float(cfg.get("transfer", {}).get("ss_leakage_factor", 1.0)),
                require_above_gate_leakage=bool(
                    cfg.get("transfer", {}).get("ss_require_above_gate_leakage", True)
                ),
                polarity=(device_params or cfg.get("device_defaults", {})).get("polarity"),
            )
            on_off = _compute_on_off(current)
            bias_key = str(round(seg.bias_level, 6) if seg.bias_level is not None else index)
            metrics["segments"][bias_key] = {"n_points": len(vg), **ss, **on_off,
                "gm_max_s": float(abs(gm[peak])) if peak is not None else None,
                "gm_max_vg": float(gm_vg[peak]) if peak is not None else None,
                "gm_smoothing": gm_result["smoothing"]}
        from fet_analyzer.analysis.extraction import extract_all_transfer_metrics
        extracted = extract_all_transfer_metrics(segments, classification, cfg, device_params=device_params)
        summary = extracted.get("summary", {})
        metrics.update({"summary": summary, "per_bias_vth": extracted.get("vth", {}),
            "per_bias_ss": extracted.get("ss", {}), "per_bias_mobility": extracted.get("mobility", {}),
            "per_bias_hysteresis": extracted.get("hysteresis", {}),
            "mobility_cm2_vs_max": summary.get("mobility_cm2_vs_max"),
            "vth_v_mean": summary.get("vth_v_mean"), "ss_min_mv_dec": summary.get("ss_mv_dec_min")})
        for item in metrics["segments"].values():
            if item.get("gm_max_s") is not None and (metrics["gm_max_s"] is None or item["gm_max_s"] > metrics["gm_max_s"]):
                metrics["gm_max_s"], metrics["gm_max_vg"] = item["gm_max_s"], item["gm_max_vg"]
            if item.get("ion_ioff_log10") is not None and (metrics["ion_ioff_log10"] is None or item["ion_ioff_log10"] > metrics["ion_ioff_log10"]):
                metrics["ion_ioff"], metrics["ion_ioff_log10"] = item["ion_ioff"], item["ion_ioff_log10"]
        metrics["sample_id"] = classification.get("filename_info", {}).get("sample_label", "unknown")
        metrics["measurement_type"] = classification.get("filename_info", {}).get("measurement_type", "transfer")
        import json
        with open(prepare_write_path(output_dir / "transfer_metrics.json"), "w", encoding="utf-8") as handle:
            json.dump(metrics, handle, indent=2, default=str)
        return metrics

    _setup_style(config)
    colors = _get_colors(config)
    cfg = config or {}
    transfer_cfg = cfg.get("transfer", {})
    plot_cfg = cfg.get("plots", {})
    device_cfg = (device_params or {}) or cfg.get("device_defaults", {})

    sweep_var = classification.get("sweep_variable", "Vg")
    drain_col = classification.get("drain_current_column", "Id")
    drain_raw = classification.get("drain_current_raw_column", "Id")
    gate_col = classification.get("gate_current_column")
    gate_leak_col = classification.get("gate_leakage_column")
    noise_floor = transfer_cfg.get("noise_floor_a", 1e-13)
    normalize = transfer_cfg.get("normalize_by_width", True)
    width_um = device_cfg.get("channel_width_um", 100.0)

    metrics: dict[str, Any] = {
        "segments": {},
        "ss_min_mv_dec": None,
        "gm_max_s": None,  # raw S (unnormalized)
        "gm_max_vg": None,
        "gm_smoothing": {},
        "ion_ioff": None,
        "ion_ioff_log10": None,
        "leakage_ratio_max": None,
        "analysis_settings": _analysis_settings(config, device_params),
    }

    # Group segments by bias level
    from fet_analyzer.analysis.segmentation import group_by_bias
    bias_groups = group_by_bias(segments)

    # Filter to forward sweep only for extractable metrics
    forward_segs = [s for s in segments if s.direction == "forward"]
    # SS window search is intentionally exhaustive; calculate it once per
    # segment and reuse it in both plots and exported metrics.
    ss_results_by_segment: dict[int, dict[str, Any]] = {}
    for seg in forward_segs:
        vg = seg.data.get(sweep_var, [])
        id_raw = seg.data.get(drain_raw, [])
        gate_raw = seg.data.get(gate_leak_col, []) if gate_leak_col else None
        ss_results_by_segment[id(seg)] = _compute_ss(
            vg, id_raw, noise_floor_a=noise_floor,
            vg_range_v=tuple(transfer_cfg["ss_vg_range_v"])
            if transfer_cfg.get("ss_vg_range_v") else None,
            gate_leakage_values=gate_raw,
            leakage_factor=float(transfer_cfg.get("ss_leakage_factor", 1.0)),
            require_above_gate_leakage=bool(
                transfer_cfg.get("ss_require_above_gate_leakage", True)
            ),
            polarity=(device_params or {}).get("polarity"),
        )

    # ── Build descriptive title from filename info ──────────────────
    finfo = classification.get("filename_info", {})
    meas_type = finfo.get("measurement_type", "Transfer")
    sample = finfo.get("sample_label", "")
    device = finfo.get("device_name", "")
    dev_type = finfo.get("device_type", "")
    source_filename = classification.get("source_filename", "")
    title_parts = [source_filename or f"{meas_type} — {sample}".strip(" —")]
    if source_filename and (meas_type or sample):
        parsed_label = " — ".join(part for part in (meas_type, sample) if part)
        title_parts.append(f"\n{parsed_label}")
    if dev_type:
        title_parts.append(f"({dev_type})")
    if device:
        title_parts.append(f" — {device}")
    base_title = " ".join(title_parts)

    # ── 1. |Id|-Vg Linear Scale ────────────────────────────────────
    fig1, ax1 = plt.subplots(figsize=plot_cfg.get("figsize", [8, 6]))
    is_p = classification.get("polarity") and "P_TYPE" in str(classification["polarity"])
    ylabel = f"|{drain_col}|/W (A/μm)" if (normalize and width_um) else f"|{drain_col}| (A)"
    for idx, (bias_key, segs) in enumerate(sorted(bias_groups.items())):
        for seg in segs:
            if seg.direction != "forward":
                continue
            color = colors[idx % len(colors)]
            vg = seg.data.get(sweep_var, [])
            id_raw = [abs(v) for v in seg.data.get(drain_raw, [])]
            label = f"{seg.bias_variable or 'Bias'} = {bias_key:.3g} V" if bias_key != "unbiased" else "Sweep"

            id_norm = [v / width_um for v in id_raw] if (normalize and width_um) else id_raw
            ax1.plot(vg, id_norm, color=color, linewidth=1.2, label=label)

    ax1.set_xlabel(f"{sweep_var} (V)")
    ax1.set_ylabel(ylabel)
    pol_note = " (p-type, |Id| shown)" if is_p else ""
    ax1.set_title(f"{base_title} — Linear Scale{pol_note}")
    if len(bias_groups) <= 5:
        ax1.legend(fontsize=9, loc="best")
    ax1.grid(True, alpha=0.3)
    fig1.tight_layout()
    fig1.savefig(prepare_write_path(output_dir / "transfer_linear.png"))
    plt.close(fig1)

    # ── 2. |Id|-Vg Log Scale ─────────────────────────────────────────
    fig2, ax2 = plt.subplots(figsize=plot_cfg.get("figsize", [8, 6]))
    for idx, (bias_key, segs) in enumerate(sorted(bias_groups.items())):
        for seg in segs:
            color = colors[idx % len(colors)]
            vg = seg.data.get(sweep_var, [])
            id_raw = seg.data.get(drain_raw, [])
            id_abs = [abs(v) for v in id_raw]
            label = f"{seg.bias_variable or 'Bias'} = {bias_key:.3g} V" if bias_key != "unbiased" else None

            # Normalize if requested
            if normalize and width_um:
                id_plot = width_normalize_id(id_abs, width_um)
            else:
                id_plot = id_abs

            ax2.semilogy(vg, id_plot, color=color, linewidth=1.2, label=label)

            # Explain the minimum-SS extraction directly on the log plot.
            # SS is dVg/d(log10|Id|), evaluated on the selected >=1-decade
            # window. The legacy average-SS value remains in JSON for
            # compatibility but is intentionally not used or displayed here.
            if seg.direction == "forward":
                gate_raw = seg.data.get(gate_leak_col, []) if gate_leak_col else None
                ss_result = ss_results_by_segment[id(seg)]
                min_fit = _ss_fit_coordinates(
                    vg, id_raw, ss_result, noise_floor, width_um, normalize
                )
                if min_fit is not None:
                    ax2.semilogy(
                        min_fit[0], min_fit[1], color=color,
                        linewidth=1.8, linestyle=":",
                        label=(
                            f"SSmin={ss_result['ss_mv_dec']:.0f} mV/dec "
                            f"({ss_result.get('ss_decades', 0.0):.2g} dec)"
                        ),
                    )

    ax2.set_xlabel(f"{sweep_var} (V)")
    if normalize:
        ax2.set_ylabel(f"|{drain_col}|/W (A/μm)")
    else:
        ax2.set_ylabel(f"|{drain_col}| (A)")
    ax2.set_title(f"{base_title} — Log Scale")
    if len(bias_groups) <= 5:
        ax2.legend(fontsize=9, loc="best")
    ax2.grid(True, alpha=0.3, which="both")
    fig2.tight_layout()
    fig2.savefig(prepare_write_path(output_dir / "transfer_log.png"))
    plt.close(fig2)

    # Dedicated SS diagnostic: measured Id/Ig, accepted fit points, and fit line.
    configured_size = plot_cfg.get("figsize", [8, 6])
    fig_ss, (ax_ss, ax_ss_zoom) = plt.subplots(
        1, 2,
        figsize=[max(12, float(configured_size[0]) * 1.7), configured_size[1]],
    )
    ss_axes = (ax_ss, ax_ss_zoom)
    fit_windows: list[tuple[float, float, float, float]] = []
    valid_fit_count = 0
    for idx, seg in enumerate(forward_segs):
        color = colors[idx % len(colors)]
        vg = seg.data.get(sweep_var, [])
        id_raw = seg.data.get(drain_raw, [])
        gate_raw = seg.data.get(gate_leak_col, []) if gate_leak_col else None
        bias_label = (
            f"{seg.bias_variable or 'Bias'} = {seg.bias_level:.3g} V"
            if seg.bias_level is not None else "Sweep"
        )
        scale = width_um if normalize and width_um else 1.0
        id_plot = np.abs(np.asarray(id_raw, dtype=float)) / scale
        for axis in ss_axes:
            axis.semilogy(vg, id_plot, color=color, linewidth=1.2,
                           label=f"|Id|, {bias_label}")
        if gate_raw:
            count = min(len(vg), len(gate_raw))
            ig_plot = np.abs(np.asarray(gate_raw[:count], dtype=float)) / scale
            for axis in ss_axes:
                axis.semilogy(vg[:count], ig_plot, color=color, linewidth=0.9,
                               linestyle="--", alpha=0.7,
                               label=f"|Ig|, {bias_label}")
        ss_result = ss_results_by_segment[id(seg)]
        fit = _ss_fit_coordinates(vg, id_raw, ss_result, noise_floor, width_um, normalize)
        indices = ss_result.get("ss_fit_indices") or []
        if fit is not None and indices:
            valid_fit_count += 1
            fit_label = (f"SS = {ss_result['ss_mv_dec']:.1f} mV/dec "
                         f"({ss_result['ss_fit_slope_v_dec']:.4g} V/dec)")
            for axis in ss_axes:
                axis.semilogy(fit[0], fit[1], color=color, linewidth=2.2,
                               linestyle=":", label=fit_label)
            fit_vg = np.asarray(vg, dtype=float)[indices]
            fit_id = np.abs(np.asarray(id_raw, dtype=float)[indices]) / scale
            for axis in ss_axes:
                axis.scatter(fit_vg, fit_id, s=24, color=color, zorder=4)
            fit_window = _ss_fit_window_bounds(fit_vg, fit_id)
            if fit_window is not None:
                x_min, x_max, y_min, y_max = fit_window
                fit_windows.append(fit_window)
                # Bound the highlight in both Vg and current.  axvspan shaded
                # the full log-current axis and visually exaggerated the fit.
                for axis in ss_axes:
                    axis.fill_between(
                        [x_min, x_max], [y_min, y_min], [y_max, y_max],
                        color=color, alpha=0.10, edgecolor=color,
                        linewidth=0.8, zorder=1,
                    )
    if not valid_fit_count:
        ax_ss.text(0.5, 0.5,
                   "No valid SS fit: requires >=1 decade and |Id| > |Ig|",
                   transform=ax_ss.transAxes, ha="center", va="center")
    for axis in ss_axes:
        axis.set_xlabel(f"{sweep_var} (V)")
        axis.grid(True, alpha=0.3, which="both")
    ax_ss.set_ylabel("Current/W (A/um)" if normalize else "Current (A)")
    ax_ss_zoom.set_ylabel("Current/W (A/um)" if normalize else "Current (A)")
    ax_ss.set_title("Full transfer curves")
    ax_ss_zoom.set_title("Selected SS fit regions (zoomed)")
    if fit_windows:
        x_min = min(window[0] for window in fit_windows)
        x_max = max(window[1] for window in fit_windows)
        y_min = min(window[2] for window in fit_windows)
        y_max = max(window[3] for window in fit_windows)
        x_pad = max(0.5, 0.12 * max(x_max - x_min, 1.0))
        ax_ss_zoom.set_xlim(x_min - x_pad, x_max + x_pad)
        ax_ss_zoom.set_ylim(y_min / 1.25, y_max * 1.25)
    if len(forward_segs) <= 5:
        ax_ss.legend(fontsize=8, loc="best")
    fig_ss.suptitle(f"{base_title} - Subthreshold Swing Fit")
    fig_ss.tight_layout()
    fig_ss.savefig(prepare_write_path(output_dir / "transfer_ss_fit.png"))
    plt.close(fig_ss)

    # ── 3. |gm|-Vg ─────────────────────────────────────────────────
    fig3, ax3 = plt.subplots(figsize=plot_cfg.get("figsize", [8, 6]))
    gm_max_global = 0.0
    gm_max_vg_global = 0.0

    gm_label = "|gm| (S)"  # default, overridden per segment
    gm_peak_raw = 0.0  # track raw gm peak (S) for metrics

    for idx, (bias_key, segs) in enumerate(sorted(bias_groups.items())):
        for seg in segs:
            if seg.direction != "forward":
                continue
            color = colors[idx % len(colors)]
            vg = seg.data.get(sweep_var, [])
            id_raw = seg.data.get(drain_raw, [])

            gm_result = compute_gm_with_diagnostics(vg, id_raw, transfer_cfg)
            vg_mid, gm = gm_result["vg"], gm_result["gm"]
            gm_metric = gm_result["gm_for_metrics"]
            metrics["gm_smoothing"][f"{bias_key}:{seg.direction}"] = gm_result["smoothing"]

            if not gm:
                continue

            # Use |gm| for p-type readability; gm already has correct sign from derivative
            gm_abs = [abs(g) for g in gm]

            # Normalize gm by width for display (S/μm)
            if normalize and width_um:
                gm_plot = [g / width_um for g in gm_abs]
                gm_label = "|gm|/W (S/μm)"
            else:
                gm_plot = gm_abs
                gm_label = "|gm| (S)"

            label = f"{seg.bias_variable or 'Bias'} = {bias_key:.3g} V" if bias_key != "unbiased" else None
            ax3.plot(vg_mid, gm_plot, color=color, linewidth=1.2, label=label)

            # Track global |gm| max — raw S for metrics, plot for display
            metric_array = np.asarray(gm_metric, dtype=float)
            gm_arr = np.abs(metric_array / width_um) if normalize and width_um else np.abs(metric_array)
            gm_raw_arr = np.abs(metric_array)
            if np.isfinite(gm_arr).any():
                peak_i = np.nanargmax(gm_arr)
                if gm_arr[peak_i] > abs(gm_max_global):
                    gm_max_global = gm_plot[peak_i]
                    gm_max_vg_global = vg_mid[peak_i] if peak_i < len(vg_mid) else 0
                # Track raw (un-normalized) peak for metrics
                raw_peak_i = np.nanargmax(gm_raw_arr)
                if gm_raw_arr[raw_peak_i] > abs(gm_peak_raw):
                    gm_peak_raw = abs(gm_abs[raw_peak_i])

    # Annotate peak on the plot
    if abs(gm_max_global) > 0:
        gm_unit = "S/μm" if normalize else "S"
        ax3.annotate(
            f"|gm,max| = {abs(gm_max_global):.3e} {gm_unit}\n@ Vg = {gm_max_vg_global:.3g} V",
            xy=(gm_max_vg_global, abs(gm_max_global)),
            xytext=(0.03, 0.97),
            textcoords="axes fraction",
            ha="left",
            va="top",
            fontsize=9,
            arrowprops=dict(arrowstyle="->", color="black"),
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8),
            annotation_clip=False,
        )

    ax3.set_xlabel(f"{sweep_var} (V)")
    ax3.set_ylabel(gm_label)
    ax3.set_title(f"{base_title} — Transconductance")
    if len(bias_groups) <= 5:
        ax3.legend(fontsize=9, loc="best")
    ax3.grid(True, alpha=0.3)
    fig3.tight_layout()
    fig3.savefig(prepare_write_path(output_dir / "transfer_gm.png"))
    plt.close(fig3)

    metrics["gm_max_s"] = gm_peak_raw  # raw S (unnormalized for downstream correctness)
    metrics["gm_max_vg"] = gm_max_vg_global

    # ── 4. |Id| vs |Ig| Leakage Comparison ────────────────────────────
    if gate_col:
        fig4, ax4 = plt.subplots(figsize=plot_cfg.get("figsize", [8, 6]))
        max_leak_ratio = 0.0

        for idx, (bias_key, segs) in enumerate(sorted(bias_groups.items())):
            for seg in segs:
                if seg.direction != "forward":
                    continue
                color = colors[idx % len(colors)]
                vg = seg.data.get(sweep_var, [])
                id_vals = [abs(v) for v in seg.data.get(drain_raw, [])]
                ig_vals = [abs(v) for v in seg.data.get(gate_col, [])]

                id_label = f"|{drain_col}| ({seg.bias_variable}={bias_key:.3g})" if bias_key != "unbiased" else f"|{drain_col}|"
                ig_label = f"|{gate_col}| ({seg.bias_variable}={bias_key:.3g})" if bias_key != "unbiased" else f"|{gate_col}|"

                ax4.semilogy(vg, id_vals, color=color, linewidth=1.5, linestyle="-", label=id_label)
                ax4.semilogy(vg, ig_vals, color=color, linewidth=1.0, linestyle="--", label=ig_label)

                # Leakage ratio
                for j in range(min(len(id_vals), len(ig_vals))):
                    if abs(id_vals[j]) > noise_floor:
                        ratio = abs(ig_vals[j] / id_vals[j])
                        if ratio > max_leak_ratio:
                            max_leak_ratio = ratio

        ax4.set_xlabel(f"{sweep_var} (V)")
        ax4.set_ylabel("Current (A)")
        ax4.set_title(f"{base_title} — Gate Leakage")
        ax4.legend(fontsize=8, loc="best")
        ax4.grid(True, alpha=0.3, which="both")
        fig4.tight_layout()
        fig4.savefig(prepare_write_path(output_dir / "transfer_leakage.png"))
        plt.close(fig4)

        metrics["leakage_ratio_max"] = max_leak_ratio

    # ── 5. Vth Extraction Plot (Tangent Fit) ─────────────────────────
    from fet_analyzer.analysis.extraction import extract_vth_peak_gm_tangent

    for bias_key in sorted(bias_groups.keys()):
        fwd = [s for s in bias_groups[bias_key] if s.direction == "forward"]
        if not fwd:
            continue
        seg = fwd[0]
        vg = seg.sweep_values
        id_raw = seg.data.get(drain_raw, [])

        # Determine Vds for correction
        vds = seg.bias_level if seg.bias_variable and seg.bias_variable.lower() in ("vd", "vs") else 0.1
        if vds is None or vds == 0:
            vds = 0.1

        # Reuse the same derivative used by the gm plot. The input is one
        # bias/direction segment, never a concatenated measurement array.
        gm_result = compute_gm_with_diagnostics(vg, id_raw, transfer_cfg)
        vg_gm, gm_values = gm_result["vg"], gm_result["gm_for_metrics"]

        if not gm_result["smoothing"]["metric_eligible"]:
            continue

        vth_result = extract_vth_peak_gm_tangent(
            vg, id_raw,
            gm=gm_values or None, vg_gm=vg_gm or None,
            tangent_window_v=transfer_cfg.get("tangent_window_v", 2.0),
            tangent_min_points=transfer_cfg.get("tangent_min_points", 5),
            vds=vds,
            vds_correction=transfer_cfg.get("vth_vds_correction", True),
        )

        if vth_result.get("vth_v") is None:
            continue

        fig_vth, ax_vth = plt.subplots(figsize=plot_cfg.get("figsize", [8, 6]))

        # Plot |Id| vs Vg
        vg_arr = np.asarray(vg, dtype=float)
        id_arr = np.asarray(id_raw, dtype=float)
        finite_plot = np.isfinite(vg_arr) & np.isfinite(id_arr)
        vg_arr, id_arr = vg_arr[finite_plot], id_arr[finite_plot]
        id_plot = np.abs(id_arr)
        if normalize and width_um:
            id_plot = id_plot / width_um  # A/μm
        ax_vth.plot(vg_arr, id_plot, 'b-', linewidth=1.5, label="|Id| Data")

        # Plot tangent line
        win_start = vth_result["tangent_vg_range"][0]
        win_end = vth_result["tangent_vg_range"][1]
        slope = vth_result["tangent_slope_a_per_v"]
        intercept = -slope * vth_result["vg_intercept_v"]  # Id=0 at Vg_intercept
        vg_tangent = np.linspace(win_start, win_end, 100)
        id_tangent = slope * vg_tangent + intercept
        if use_abs := transfer_cfg.get("abs_current_for_log", True):
            id_tangent = np.abs(id_tangent)
        if normalize and width_um:
            id_tangent = id_tangent / width_um
        ax_vth.plot(vg_tangent, id_tangent, 'r--', linewidth=1.5, label="Tangent fit")

        # Mark Vg_intercept
        vg_int = vth_result["vg_intercept_v"]
        ax_vth.axvline(vg_int, color='green', linestyle=':', alpha=0.7, label=f"Vg,intercept = {vg_int:.2f} V")

        # Mark Vth (with correction)
        vth_v = vth_result["vth_v"]
        ax_vth.axvline(vth_v, color='red', linestyle='-', alpha=0.7,
                       label=f"Vth = {vth_v:.2f} V")

        # Mark peak gm
        gm_pk_vg = vth_result["gm_peak_vg"]
        ax_vth.axvline(gm_pk_vg, color='orange', linestyle='--', alpha=0.5,
                       label=f"gm,peak @ {gm_pk_vg:.2f} V")

        ax_vth.set_xlabel(f"{sweep_var} (V)")
        ylbl = f"|{drain_col}|/W (A/μm)" if normalize else f"|{drain_col}| (A)"
        ax_vth.set_ylabel(ylbl)
        bias_label = f" (Vds={vds:.3g}V)" if seg.bias_variable else ""
        ax_vth.set_title(f"{base_title} — Vth Extraction (Peak-gm Tangent{bias_label})")
        ax_vth.legend(fontsize=8, loc="best")
        ax_vth.grid(True, alpha=0.3)
        fig_vth.tight_layout()
        fig_vth.savefig(prepare_write_path(
            output_dir / f"transfer_vth_extraction_bias{bias_key}.png"
        ))
        plt.close(fig_vth)

        break  # Only plot for first bias level

    # ── 6. Hysteresis Plot ────────────────────────────────────────────
    for bias_key in sorted(bias_groups.keys()):
        fwd = [s for s in bias_groups[bias_key] if s.direction == "forward"]
        rev = [s for s in bias_groups[bias_key] if s.direction == "reverse"]
        if not fwd or not rev:
            continue

        fig_hyst, ax_hyst = plt.subplots(figsize=plot_cfg.get("figsize", [8, 6]))

        vg_f = np.array(fwd[0].sweep_values)
        id_f = np.abs(np.array(fwd[0].data.get(drain_raw, [])))
        vg_r = np.array(rev[0].sweep_values)
        id_r = np.abs(np.array(rev[0].data.get(drain_raw, [])))

        mask_f = np.isfinite(vg_f) & np.isfinite(id_f) & (id_f > noise_floor)
        mask_r = np.isfinite(vg_r) & np.isfinite(id_r) & (id_r > noise_floor)

        if normalize and width_um:
            id_f = id_f / width_um
            id_r = id_r / width_um

        ax_hyst.semilogy(vg_f[mask_f], id_f[mask_f], 'b-', linewidth=1.5, label="Forward")
        ax_hyst.semilogy(vg_r[mask_r], id_r[mask_r], 'r--', linewidth=1.5, label="Reverse")

        # Compute Cox/2 hysteresis only when both directions retain valid data.
        if mask_f.any() and mask_r.any():
            i_min = max(np.min(id_f[mask_f]), np.min(id_r[mask_r]))
            i_max = min(np.max(id_f[mask_f]), np.max(id_r[mask_r]))
        else:
            i_min = i_max = None
        if i_min is not None and i_max is not None and i_min < i_max:
            i_mid = 10 ** ((np.log10(i_min) + np.log10(i_max)) / 2)
            vg_at_f = vg_f[mask_f][np.argmin(np.abs(id_f[mask_f] - i_mid))]
            vg_at_r = vg_r[mask_r][np.argmin(np.abs(id_r[mask_r] - i_mid))]
            delta_v = vg_at_r - vg_at_f

            # Draw horizontal line at Cox/2
            ax_hyst.axhline(i_mid, color='gray', linestyle=':', alpha=0.5)
            # Vertical markers
            ax_hyst.axvline(vg_at_f, color='blue', linestyle=':', alpha=0.5)
            ax_hyst.axvline(vg_at_r, color='red', linestyle=':', alpha=0.5)
            # Annotation
            ax_hyst.annotate(
                f"ΔV = {abs(delta_v):.2f} V",
                xy=((vg_at_f + vg_at_r)/2, i_mid),
                fontsize=10, ha='center',
                bbox=dict(boxstyle="round,pad=0.3", facecolor="yellow", alpha=0.8),
            )

        ax_hyst.set_xlabel(f"{sweep_var} (V)")
        ylbl = f"|{drain_col}|/W (A/μm)" if normalize else f"|{drain_col}| (A)"
        ax_hyst.set_ylabel(ylbl)
        ax_hyst.set_title(f"{base_title} — Hysteresis")
        ax_hyst.legend(fontsize=9)
        ax_hyst.grid(True, alpha=0.3, which="both")
        fig_hyst.tight_layout()
        fig_hyst.savefig(prepare_write_path(
            output_dir / f"transfer_hysteresis_bias{bias_key}.png"
        ))
        plt.close(fig_hyst)

        break  # Only plot for first bias level

    # ── 7. Extract per-segment metrics ─────────────────────────────────
    for seg in forward_segs:
        vg = seg.data.get(sweep_var, [])
        id_raw = seg.data.get(drain_raw, [])
        if len(vg) < 5:
            continue

        bias_key = round(seg.bias_level, 6) if seg.bias_level is not None else "unbiased"
        seg_metrics: dict[str, Any] = {}

        # SS
        gate_raw = seg.data.get(gate_leak_col, []) if gate_leak_col else None
        ss_result = ss_results_by_segment[id(seg)]
        seg_metrics.update(ss_result)
        seg_metrics["ss_at_vg"] = ss_result["ss_vg"]
        seg_metrics["ss_decades"] = ss_result.get("ss_decades")
        seg_metrics["ss_avg_mv_dec"] = ss_result.get("ss_avg_mv_dec")
        seg_metrics["ss_avg_decades"] = ss_result.get("ss_avg_decades")

        # gm — store |gm| for display
        gm_result = compute_gm_with_diagnostics(vg, id_raw, transfer_cfg)
        vg_mid, gm = gm_result["vg"], gm_result["gm_for_metrics"]
        seg_metrics["gm_smoothing"] = gm_result["smoothing"]
        if gm and np.isfinite(np.asarray(gm, dtype=float)).any():
            gm_abs = np.abs(gm)
            gm_peak = np.nanargmax(gm_abs)
            seg_metrics["gm_max_s"] = float(gm_abs[gm_peak])
            seg_metrics["gm_max_vg"] = float(vg_mid[gm_peak]) if gm_peak < len(vg_mid) else None

        # On/Off — use max/min |Id| (direction-agnostic)
        gate_raw = seg.data.get(gate_leak_col, []) if gate_leak_col else None
        on_off = _compute_on_off(
            id_raw, gate_raw,
            leakage_factor=float(transfer_cfg.get("ioff_leakage_factor", 3.0)),
        )
        seg_metrics.update(on_off)

        seg_metrics["n_points"] = len(vg)
        id_valid_raw = [v for v in id_raw if v == v]
        seg_metrics["id_min_a"] = min(id_valid_raw) if id_valid_raw else None
        seg_metrics["id_max_a"] = max(id_valid_raw) if id_valid_raw else None

        metrics["segments"][str(bias_key)] = seg_metrics

        # Track global SS min
        if seg_metrics["ss_mv_dec"] is not None:
            if metrics["ss_min_mv_dec"] is None or seg_metrics["ss_mv_dec"] < metrics["ss_min_mv_dec"]:
                metrics["ss_min_mv_dec"] = seg_metrics["ss_mv_dec"]

        # Track global Ion/Ioff
        if seg_metrics.get("ion_ioff_log10") is not None:
            if metrics["ion_ioff_log10"] is None or seg_metrics["ion_ioff_log10"] > metrics["ion_ioff_log10"]:
                metrics["ion_ioff"] = seg_metrics["ion_ioff"]
                metrics["ion_ioff_log10"] = seg_metrics["ion_ioff_log10"]

    # Save metrics to JSON
    import json
    from fet_analyzer.analysis.extraction import extract_all_transfer_metrics

    # Run extraction engine for mobility, hysteresis, DIBL — using per-device params
    ext_results = extract_all_transfer_metrics(
        segments, classification, config,
        device_params=device_params,
    )
    summary = ext_results.get("summary", {})
    metrics["summary"] = summary
    metrics["mobility_cm2_vs_max"] = summary.get("mobility_cm2_vs_max")
    metrics["vth_v_mean"] = summary.get("vth_v_mean")
    metrics["per_bias_mobility"] = ext_results.get("mobility", {})
    metrics["per_bias_vth"] = ext_results.get("vth", {})
    metrics["per_bias_hysteresis"] = ext_results.get("hysteresis", {})
    metrics["per_bias_ss"] = ext_results.get("ss", {})
    metrics["dibl"] = ext_results.get("dibl", {})
    dibl = metrics["dibl"]
    fit_points = dibl.get("fit_points", []) if isinstance(dibl, dict) else []
    if HAS_MPL and len(fit_points) >= 2 and dibl.get("raw_vth_slope_v_v") is not None:
        x = np.asarray([point["abs_vds_v"] for point in fit_points], dtype=float)
        y = np.asarray([point["vth_v"] for point in fit_points], dtype=float)
        order = np.argsort(x)
        predicted = dibl["raw_vth_slope_v_v"] * x[order] + dibl["intercept_v"]
        fig_dibl, ax_dibl = plt.subplots(figsize=(7.2, 5.2))
        ax_dibl.scatter(x, y, color=_get_colors(config)[0], edgecolor="white", s=58, zorder=3, label="Extracted Vth")
        ax_dibl.plot(x[order], predicted, "--", color=_get_colors(config)[1], label="Least-squares fit")
        for point in fit_points:
            ax_dibl.annotate(
                f"Vds={point['measured_vds_v']:g} V",
                (point["abs_vds_v"], point["vth_v"]), xytext=(5, 6), textcoords="offset points", fontsize=8,
            )
        ax_dibl.set(xlabel="|Vds| (V)", ylabel="Vth (V)", title="DIBL calculation audit")
        ax_dibl.legend()
        ax_dibl.text(
            0.02, 0.02,
            f"Vth = {dibl['raw_vth_slope_v_v']:.4g}|Vds| + {dibl['intercept_v']:.4g}\n"
            f"polarity multiplier = {dibl['polarity_multiplier']:+g}\n"
            f"DIBL = {dibl['dibl_mv_v']:.4g} mV/V; R² = {dibl.get('r2') if dibl.get('r2') is not None else 'N/A'}; N = {len(fit_points)}",
            transform=ax_dibl.transAxes, va="bottom", fontsize=9,
            bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.85},
        )
        fig_dibl.tight_layout()
        fig_dibl.savefig(prepare_write_path(output_dir / "transfer_dibl_audit.png"))
        plt.close(fig_dibl)

    ion_bias = resolve_ion_bias(cfg, device_params)
    const_vg = ion_bias["fixed_vg_v"]
    const_overdrive = ion_bias["overdrive_v"]
    if const_vg is not None or const_overdrive is not None:
        for seg in forward_segs:
            bias_key = round(seg.bias_level, 6) if seg.bias_level is not None else "unbiased"
            seg_metric = metrics["segments"].setdefault(str(bias_key), {})
            vg = seg.data.get(sweep_var, [])
            id_raw = seg.data.get(drain_raw, [])
            if const_vg is not None:
                read = nearest_abs_current_at_voltage(vg, id_raw, float(const_vg))
                seg_metric["ion_const_vg_requested_v"] = read["requested_v"]
                seg_metric["ion_const_vg_v"] = read["actual_v"]
                seg_metric["ion_const_vg_actual_v"] = read["actual_v"]
                seg_metric["ion_const_vg_delta_v"] = read["delta_v"]
                seg_metric["ion_const_vg_a"] = read["current_a"]
            if const_overdrive is not None:
                vth_result = metrics["per_bias_vth"].get(str(bias_key), {})
                vth = vth_result.get("vth_v") if isinstance(vth_result, dict) else None
                target_vg = float(vth) + float(const_overdrive) if vth is not None else None
                read = nearest_abs_current_at_voltage(vg, id_raw, target_vg)
                actual_vov = (
                    float(read["actual_v"]) - float(vth)
                    if read["actual_v"] is not None and vth is not None else None
                )
                seg_metric["ion_const_overdrive_requested_v"] = float(const_overdrive)
                seg_metric["ion_const_overdrive_v"] = actual_vov
                seg_metric["ion_const_overdrive_target_vg_v"] = target_vg
                seg_metric["ion_const_overdrive_actual_vg_v"] = read["actual_v"]
                seg_metric["ion_const_overdrive_delta_vg_v"] = read["delta_v"]
                seg_metric["ion_const_overdrive_a"] = read["current_a"]
            seg_metric["ion_overdrive_input_v"] = ion_bias["overdrive_input_v"]
            seg_metric["ion_overdrive_field_mv_cm"] = ion_bias["overdrive_field_mv_cm"]
            seg_metric["ion_gate_field_mv_cm"] = ion_bias["gate_field_mv_cm"]
            seg_metric["ion_oxide_thickness_nm"] = ion_bias["oxide_thickness_nm"]
            seg_metric["ion_overdrive_source"] = ion_bias["overdrive_source"]

    metrics["sample_id"] = classification.get("filename_info", {}).get(
        "sample_label", classification.get("source_filename", "unknown"))
    metrics["measurement_type"] = classification.get("filename_info", {}).get(
        "measurement_type", "transfer")
    with open(prepare_write_path(output_dir / "transfer_metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, default=str)

    return metrics
