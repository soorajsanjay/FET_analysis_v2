"""
Output characteristic plotting: Id-Vd curves at multiple gate bias steps,
output conductance (gds), and saturation analysis.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from fet_analyzer.path_utils import prepare_write_path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


def _setup_style(config: dict[str, Any] | None = None):
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
    return (config or {}).get("plots", {}).get("palette", [
        "#0072B2", "#E69F00", "#009E73", "#F0E442", "#56B4E9",
        "#D55E00", "#CC79A7", "#000000", "#999999", "#882255",
    ])


def _compute_gds(vd: list[float], id_vals: list[float]) -> tuple[list[float], list[float]]:
    """Compute output conductance dId/dVd within one already-split segment."""
    vd_arr = np.asarray(vd, dtype=float)
    id_arr = np.asarray(id_vals, dtype=float)
    mask = np.isfinite(vd_arr) & np.isfinite(id_arr)
    vd_arr, id_arr = vd_arr[mask], id_arr[mask]
    if len(vd_arr) < 2:
        return [], []

    gds = np.full(len(vd_arr), np.nan)

    # One-sided endpoint derivatives avoid the previous artificial zero at the
    # high-bias edge while still staying inside this single split segment.
    first_dvd = vd_arr[1] - vd_arr[0]
    if abs(first_dvd) > 1e-15:
        gds[0] = abs((id_arr[1] - id_arr[0]) / first_dvd)

    last_dvd = vd_arr[-1] - vd_arr[-2]
    if abs(last_dvd) > 1e-15:
        gds[-1] = abs((id_arr[-1] - id_arr[-2]) / last_dvd)

    for index in range(1, len(vd_arr) - 1):
        dvd = vd_arr[index + 1] - vd_arr[index - 1]
        if abs(dvd) > 1e-15:
            gds[index] = abs((id_arr[index + 1] - id_arr[index - 1]) / dvd)

    return vd_arr.tolist(), gds.tolist()


def plot_output_curves(
    segments: list[Any],
    classification: dict[str, Any],
    output_dir: Path,
    config: dict[str, Any] | None = None,
    device_params: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate output characteristic plots (Id-Vd).

    Creates:
      1. |Id|-Vd linear scale (all Vbg/Vg bias steps)
      2. gds-Vd (output conductance)

    Returns dict of extracted metrics.
    """
    if not HAS_MPL:
        sweep_var = classification.get("sweep_variable", "Vd")
        drain_raw = classification.get("drain_current_raw_column", "Id")
        cfg = config or {}
        out_cfg = cfg.get("output", {})
        transfer_cfg = cfg.get("transfer", {})
        device_cfg = device_params or cfg.get("device_defaults", {})
        metrics: dict[str, Any] = {
            "bias_levels": {}, "gds_max": None, "saturation_vd": None,
            "analysis_settings": {
                "gds_method_used": "finite_difference_did_dvd_within_each_segment",
                "resistance_method_used": "linear_fit_within_abs_vd_limit",
                "resistance_fit_vd_max_v": float(cfg.get("tlm", {}).get("tlm_output_vd_max", 0.1)),
                "normalize_by_width": bool(out_cfg.get("normalize_by_width", transfer_cfg.get("normalize_by_width", True))),
                "channel_width_um": device_cfg.get("channel_width_um", 100.0),
            },
        }
        from fet_analyzer.analysis.segmentation import group_by_bias
        for bias, segs in group_by_bias(segments).items():
            if not segs:
                continue
            vd, gds = _compute_gds(
                segs[0].data.get(sweep_var, []),
                segs[0].data.get(drain_raw, []),
            )
            current = np.asarray(segs[0].data.get(drain_raw, []), dtype=float)
            current = current[np.isfinite(current)]
            gds_arr = np.asarray(gds, dtype=float)
            if len(vd) < 2 or not np.isfinite(gds_arr).any() or len(current) == 0:
                continue
            peak = float(np.nanmax(np.abs(gds_arr)))
            metrics["bias_levels"][str(bias)] = {"id_max_a": float(np.max(np.abs(current))), "gds_max_s": peak}
            metrics["gds_max"] = max(metrics["gds_max"] or 0.0, peak)
        metrics["sample_id"] = classification.get("filename_info", {}).get("sample_label", "unknown")
        metrics["measurement_type"] = classification.get("filename_info", {}).get("measurement_type", "output")
        import json
        with open(prepare_write_path(output_dir / "output_metrics.json"), "w", encoding="utf-8") as handle:
            json.dump(metrics, handle, indent=2, default=str)
        return metrics

    _setup_style(config)
    colors = _get_colors(config)
    plot_cfg = (config or {}).get("plots", {})
    device_cfg = device_params or (config or {}).get("device_defaults", {})

    sweep_var = classification.get("sweep_variable", "Vd")
    bias_var = classification.get("bias_variable", "Vbg")
    drain_col = classification.get("drain_current_column", "Id")
    drain_raw = classification.get("drain_current_raw_column", "Id")
    # Use per-type normalize setting, fall back to global
    out_cfg = (config or {}).get("output", {})
    transfer_cfg = (config or {}).get("transfer", {})
    normalize = out_cfg.get("normalize_by_width", transfer_cfg.get("normalize_by_width", True))
    width_um = device_cfg.get("channel_width_um", 100.0)

    # Build title
    finfo = classification.get("filename_info", {})
    meas_type = finfo.get("measurement_type", "Output")
    sample = finfo.get("sample_label", "")
    source_filename = classification.get("source_filename", "")
    base_title = source_filename or " — ".join(part for part in (meas_type, sample) if part)
    if source_filename and (meas_type or sample):
        parsed_label = " — ".join(part for part in (meas_type, sample) if part)
        base_title = f"{base_title}\n{parsed_label}"

    # Group segments by bias
    from fet_analyzer.analysis.segmentation import group_by_bias
    bias_groups = group_by_bias(segments)

    metrics = {
        "bias_levels": {}, "gds_max": None, "saturation_vd": None,
        "analysis_settings": {
            "gds_method_used": "finite_difference_did_dvd_within_each_segment",
            "resistance_method_used": "linear_fit_within_abs_vd_limit",
            "resistance_fit_vd_max_v": float((config or {}).get("tlm", {}).get("tlm_output_vd_max", 0.1)),
            "normalize_by_width": bool(normalize),
            "channel_width_um": width_um,
        },
    }

    # ── 1. |Id|-Vd Linear ─────────────────────────────────────────────
    fig1, ax1 = plt.subplots(figsize=plot_cfg.get("figsize", [8, 6]))
    for idx, (bias_key, segs) in enumerate(sorted(bias_groups.items())):
        # Output sweeps are single-direction — use the dominant segment
        seg = segs[0] if segs else None
        if seg is None or len(seg) < 3:
            continue
        color = colors[idx % len(colors)]
        vd = seg.sweep_values
        id_vals = [abs(v) for v in seg.data.get(drain_raw, [])]

        if normalize and width_um:
            id_plot = [v / width_um for v in id_vals]  # A/μm
        else:
            id_plot = id_vals

        bias_label = f"{bias_var} = {bias_key:.1f} V" if isinstance(bias_key, (int, float)) else f"{bias_var or 'Source'}-Drain Sweep"
        label = bias_label
        ax1.plot(vd, id_plot, color=color, linewidth=1.0, label=label)

        # Store metric — use abs() to handle n and p-type devices
        valid = [abs(v) for v in id_plot if v == v and v != 0]
        metrics["bias_levels"][str(bias_key)] = {
            "id_max_a_um": max(valid) if valid else None,
            "id_at_5v": None,  # computed below
        }

    ylbl = f"|{drain_col}|/W (A/μm)" if normalize else f"|{drain_col}| (A)"
    ax1.set_ylabel(ylbl)
    ax1.set_xlabel(f"{sweep_var} (V)")
    ax1.set_title(f"{base_title} — Output Characteristic")
    n_biases = len([k for k in bias_groups])
    if n_biases <= 12:
        ax1.legend(fontsize=7, loc="best", ncol=min(3, (n_biases + 2) // 3))
    ax1.grid(True, alpha=0.3)
    fig1.tight_layout()
    fig1.savefig(prepare_write_path(output_dir / "output_linear.png"))
    plt.close(fig1)

    # ── 2. gds-Vd ─────────────────────────────────────────────────────
    fig2, ax2 = plt.subplots(figsize=plot_cfg.get("figsize", [8, 6]))
    gds_max = 0.0
    gds_label = "gds/W (S/μm)" if (normalize and width_um) else "gds (S)"

    for idx, (bias_key, segs) in enumerate(sorted(bias_groups.items())):
        seg = segs[0] if segs else None
        if seg is None or len(seg) < 3:
            continue
        color = colors[idx % len(colors)]
        vd, gds = _compute_gds(seg.sweep_values, seg.data.get(drain_raw, []))
        if not gds:
            continue
        gds = np.asarray(gds, dtype=float)

        if normalize and width_um:
            gds_plot = gds / width_um  # S/μm
            gds_label = "gds/W (S/μm)"
        else:
            gds_plot = gds
            gds_label = "gds (S)"

        bias_label_gds = f"{bias_var} = {bias_key:.1f} V" if isinstance(bias_key, (int, float)) else f"{bias_var or 'Source'}-Drain Sweep"
        ax2.plot(vd, gds_plot, color=color, linewidth=1.0,
                 label=bias_label_gds)

        finite_gds = gds_plot[np.isfinite(gds_plot)]
        if len(finite_gds) > 0:
            peak = np.max(np.abs(finite_gds))
            if peak > abs(gds_max):
                gds_max = peak

    ax2.set_xlabel(f"{sweep_var} (V)")
    ax2.set_ylabel(gds_label)
    ax2.set_title(f"{base_title} — Output Conductance")
    if n_biases <= 12:
        ax2.legend(fontsize=7, loc="best", ncol=min(3, (n_biases + 2) // 3))
    ax2.grid(True, alpha=0.3)
    fig2.tight_layout()
    fig2.savefig(prepare_write_path(output_dir / "output_gds.png"))
    plt.close(fig2)

    metrics["gds_max"] = gds_max

    # Save metrics
    import json
    metrics["sample_id"] = classification.get("filename_info", {}).get(
        "sample_label", classification.get("source_filename", "unknown"))
    metrics["measurement_type"] = classification.get("filename_info", {}).get(
        "measurement_type", "output")
    with open(prepare_write_path(output_dir / "output_metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, default=str)

    return metrics
