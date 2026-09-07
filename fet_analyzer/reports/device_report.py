"""
Per-device report generator.

Generates a standalone HTML report for each processed device with embedded
plots, extracted-parameter tables, and warnings.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fet_analyzer.utils.logging import LOGGER
from fet_analyzer.reports.html_report import write_html_report
from fet_analyzer.path_utils import prepare_write_path

try:
    import openpyxl
    from openpyxl.styles import Font
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


def _fmt(val: Any, digits: int = 3, unit: str = "") -> str:
    """Format a numeric value for display."""
    if val is None:
        return "—"
    if isinstance(val, bool):
        return "✓" if val else "✗"
    if isinstance(val, float):
        if abs(val) >= 1e6 or (abs(val) < 1e-3 and val != 0):
            return f"{val:.{digits-1}e}{' ' + unit if unit else ''}"
        return f"{val:.{digits}f}{' ' + unit if unit else ''}"
    return f"{val}{' ' + unit if unit else ''}"


def _setting_label(key: str) -> str:
    """Human-readable label for a recorded effective analysis setting."""
    replacements = {"vth": "Vth", "ss": "SS", "gm": "gm", "gds": "gds",
                    "ion": "Ion", "ioff": "Ioff", "vg": "Vg", "vd": "Vd"}
    return " ".join(replacements.get(part, part.capitalize()) for part in key.split("_"))


def _setting_value(value: Any) -> str:
    if value is None:
        return "not configured"
    if isinstance(value, bool):
        return "enabled" if value else "disabled"
    labels = {
        "maximum_measured_abs_id": "Maximum measured |Id| in each forward segment",
        "max_current": "Maximum measured |Id|",
        "fixed_overdrive": "|Id| at the configured Vg−Vth overdrive",
        "max_common_overdrive": "|Id| at the largest gate overdrive shared by all usable bias segments",
        "minimum_abs_id_above_gate_leakage": "Minimum |Id| above the configured gate-leakage criterion",
        "peak_gm_tangent": "Peak-gm tangent fit",
        "constant_current": "Constant-current interpolation",
        "minimum_fit_over_at_least_1_current_decade": "Minimum fit spanning at least 1 current decade",
        "finite_difference_did_dvd_within_each_segment": "Finite-difference dId/dVd within each segment",
        "linear_fit_within_abs_vd_limit": "Linear Id-Vd fit within the configured |Vd| limit",
    }
    if isinstance(value, str) and value in labels:
        return labels[value]
    return str(value)


def _write_device_excel(
    device_name: str,
    classification: dict[str, Any],
    metrics: dict[str, Any],
    parsed_metadata: dict[str, Any],
    output_path: Path,
) -> None:
    """Legacy private Excel writer retained for compatibility."""
    if not HAS_OPENPYXL:
        return

    excel_path = output_path.parent / "analysis.xlsx"

    wb = openpyxl.Workbook()

    # ── Sheet 1: Summary ──────────────────────────────────────────
    ws = wb.active
    ws.title = "Summary"

    finfo = classification.get("filename_info", {})
    sample_id = finfo.get("sample_label", Path(source_file).stem if source_file else "unknown")

    ws.cell(row=1, column=1, value="Parameter")
    ws.cell(row=1, column=2, value="Value")
    for cell in [ws.cell(row=1, column=c) for c in (1, 2)]:
        cell.font = Font(bold=True)

    info_rows = [
        ("Device", device_name),
        ("Sample ID", sample_id),
        ("Type", str(getattr(classification.get("type"), "name", classification.get("type", "")))),
    ]
    for i, (k, v) in enumerate(info_rows, 2):
        ws.cell(row=i, column=1, value=k)
        ws.cell(row=i, column=2, value=v)

    summary = metrics.get("summary", {})
    if summary:
        row = 5
        ws.cell(row=row, column=1, value="Metric")
        ws.cell(row=row, column=2, value="Value")
        for cell in [ws.cell(row=row, column=c) for c in (1, 2)]:
            cell.font = Font(bold=True)
        for key, label in [
            ("vth_v_mean", "Vth (V)"),
            ("mobility_cm2_vs_max", "\u03bc_FE (cm\u00b2/V\u00b7s)"),
            ("ss_mv_dec_min", "SS (mV/dec)"),
            ("ion_ioff_log10", "log10(Ion/Ioff)"),
            ("hysteresis_v_max", "Hysteresis (V)"),
            ("dibl_mv_v", "DIBL (mV/V)"),
        ]:
            val = summary.get(key)
            if val is not None:
                row += 1
                ws.cell(row=row, column=1, value=label)
                ws.cell(row=row, column=2, value=val)

    # ── Sheet 2: Per-Bias Transfer Metrics ────────────────────────
    segments = metrics.get("segments", {})
    if segments:
        ws2 = wb.create_sheet("Per-Bias")
        headers = ["Bias", "SS (mV/dec)", "Ion/Ioff", "log10(Ion/Ioff)", "Vth (V)", "gm,max (S)"]
        for c, h in enumerate(headers, 1):
            cell = ws2.cell(row=1, column=c, value=h)
            cell.font = Font(bold=True)

        vth_data = metrics.get("per_bias_vth", {})
        row = 2
        for bias_key in sorted(segments.keys()):
            seg = segments[bias_key]
            vt = vth_data.get(str(bias_key), {})
            ws2.cell(row=row, column=1, value=bias_key)
            ws2.cell(row=row, column=2, value=seg.get("ss_mv_dec"))
            ws2.cell(row=row, column=3, value=seg.get("ion_ioff"))
            ws2.cell(row=row, column=4, value=seg.get("ion_ioff_log10"))
            ws2.cell(row=row, column=5, value=vt.get("vth_v"))
            ws2.cell(row=row, column=6, value=seg.get("gm_max_s"))
            row += 1

    # ── Sheet 3: Hysteresis ───────────────────────────────────────
    hyst = metrics.get("per_bias_hysteresis", metrics.get("hysteresis", {}))
    if hyst:
        ws3 = wb.create_sheet("Hysteresis")
        headers = ["Bias", "\u0394V (V)", "Vg,fwd (V)", "Vg,rev (V)"]
        for c, h in enumerate(headers, 1):
            cell = ws3.cell(row=1, column=c, value=h)
            cell.font = Font(bold=True)
        row = 2
        for bias_key in sorted(hyst.keys()):
            h = hyst[bias_key]
            if h.get("delta_v") is not None:
                ws3.cell(row=row, column=1, value=bias_key)
                ws3.cell(row=row, column=2, value=h.get("delta_v_abs"))
                ws3.cell(row=row, column=3, value=h.get("vg_forward_v"))
                ws3.cell(row=row, column=4, value=h.get("vg_reverse_v"))
                row += 1

    # ── Sheet 4: Output Characteristics ───────────────────────────
    if metrics.get("gds_max") is not None:
        ws4 = wb.create_sheet("Output")
        ws4.cell(row=1, column=1, value="gds,max (S)")
        ws4.cell(row=1, column=2, value=metrics.get("gds_max"))
        bias_levels = metrics.get("bias_levels", {})
        if bias_levels:
            row = 3
            ws4.cell(row=row, column=1, value="Gate Bias (V)").font = Font(bold=True)
            ws4.cell(row=row, column=2, value="Id,max (A/\u03bcm)").font = Font(bold=True)
            row += 1
            for bk, bm in sorted(bias_levels.items()):
                ws4.cell(row=row, column=1, value=bk)
                ws4.cell(row=row, column=2, value=bm.get("id_max_a_um"))
                row += 1

    # Auto-fit column widths
    for ws_i in wb.worksheets:
        for col in ws_i.columns:
            max_len = 0
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            for cell in col:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
            ws_i.column_dimensions[col_letter].width = min(max_len + 3, 40)

    wb.save(prepare_write_path(excel_path))
    wb.close()
    LOGGER.info("  \u2192 Analysis Excel: %s", excel_path)


def generate_device_report(
    device_name: str,
    classification: dict[str, Any],
    metrics: dict[str, Any],
    parsed_metadata: dict[str, Any],
    plot_dir: Path,
    output_path: Path,
    source_file: str = "",
) -> None:
    """Generate a standalone HTML report for a processed device.

    Args:
        device_name: Human-readable device identifier
        classification: Output from classify_measurement()
        metrics: Extracted metrics from plot/analysis functions
        parsed_metadata: Raw metadata from parser
        plot_dir: Directory containing generated plots (relative or absolute)
        output_path: Where to write the HTML report
    """
    finfo = classification.get("filename_info", {})
    sample_id = finfo.get("sample_label", Path(source_file).stem if source_file else "unknown")
    dev_type = finfo.get("device_type", "")
    dev_name = finfo.get("device_name", device_name)
    meas_type_str = finfo.get("measurement_type", classification.get("type", ""))
    if hasattr(classification.get("type"), "name"):
        meas_type_str = classification["type"].name

    lines: list[str] = []
    w = lines.append

    w(f"# {sample_id} — {dev_type} {dev_name}".strip())
    w("")
    w(f"**Measurement:** {meas_type_str}")
    # Source file
    src_file = source_file
    if src_file:
        w(f"**Source file:** `{Path(src_file).name}`")
    w(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    w(f"**Classification confidence:** {classification.get('confidence', 0):.0%}")
    w("")

    # ── Device Parameters ───────────────────────────────────────────
    dev_params = dict(metrics.get("device_geometry", metrics.get("device_params", {})))
    if dev_params.get("cox_f_per_cm2") is None and isinstance(dev_params.get("oxide_thickness_nm"), (int, float)) and dev_params.get("oxide_thickness_nm", 0) > 0 and isinstance(dev_params.get("dielectric_constant"), (int, float)):
        dev_params["cox_f_per_cm2"] = 8.854187817e-14 * float(dev_params["dielectric_constant"]) / (float(dev_params["oxide_thickness_nm"]) * 1e-7)
        dev_params["cox_source"] = "calculated from dielectric constant and oxide thickness"
    if dev_params:
        w("## Device Parameters")
        w("")
        w("| Parameter | Value |")
        w("|-----------|-------|")
        for key in ("channel_width_um", "channel_length_um", "oxide_thickness_nm", "film_thickness_nm", "gate_dielectric", "dielectric_constant", "cox_f_per_cm2", "cox_source", "polarity"):
            val = dev_params.get(key)
            if val is not None:
                label = key.replace("_", " ").title()
                unit_map = {"channel_width_um": "μm", "channel_length_um": "μm", "oxide_thickness_nm": "nm", "film_thickness_nm": "nm",
                            "cox_f_per_cm2": "F/cm²"}
                w(f"| {label} | {_fmt(val)} {unit_map.get(key, '')} |")
        w("")

    analysis_settings = metrics.get("analysis_settings", {})
    if analysis_settings:
        w("## Analysis Configuration Used")
        w("")

    preflight = metrics.get("parameter_preflight", {})
    validation = metrics.get("config_validation", {})
    if preflight or validation:
        w("## Validation and Parameter Preflight")
        w("")
        w(f"**Parameter mode/status:** {preflight.get('mode', 'not recorded')} / {preflight.get('status', 'not recorded')}")
        w("")
        w(f"**Configuration status:** {validation.get('status', 'not recorded')}")
        w("")
        w("| Level | Code | Field or parameter | Effect |")
        w("|---|---|---|---|")
        for issue in validation.get("issues", []):
            w(f"| {issue.get('level')} | {issue.get('code')} | {issue.get('path')} | {issue.get('message')} |")
        for issue in preflight.get("issues", []):
            affected = ", ".join(issue.get("affected_metrics", []))
            w(f"| {issue.get('level')} | {issue.get('code')} | {issue.get('parameter')} | {issue.get('message')} ({affected}) |")
        w("")
        w("| Setting | Effective value |")
        w("|---------|-----------------|")
        for key, value in analysis_settings.items():
            w(f"| {_setting_label(str(key))} | {_setting_value(value)} |")
        w("")

    # ── Transfer Metrics ────────────────────────────────────────────
    if classification.get("type") and "TRANSFER" in str(classification["type"]):

        vth_data = metrics.get("per_bias_vth", {})
        mob_data = metrics.get("per_bias_mobility", {})
        ss_data = metrics.get("per_bias_ss", metrics.get("segments", {}))

        w("## Transfer Characteristics")
        w("")

        smoothing_results = [
            result for result in metrics.get("sweep_results", [])
            if result.get("gm", {}).get("smoothing", {}).get("mode") == "adaptive_savgol"
        ]
        if smoothing_results:
            w("### Adaptive gm Smoothing Audit")
            w("")
            w("Smoothing is applied after the central-difference derivative and independently within each contiguous finite region. The strict maximum window is below 10% of usable regional points.")
            w("")
            w("| Sweep | Region | Vg range (V) | Usable points | Selected window | Status | Selection reason |")
            w("|---|---:|---:|---:|---:|---|---|")
            for result in smoothing_results:
                smoothing = result.get("gm", {}).get("smoothing", {})
                for region in smoothing.get("regions", []):
                    w(
                        f"| {result.get('sweep_id', '')} | {region.get('region_index', '')} | "
                        f"{_fmt(region.get('vg_min'), 4)} to {_fmt(region.get('vg_max'), 4)} | "
                        f"{region.get('n_usable_points', '')} | {region.get('selected_window_points') or 'raw'} | "
                        f"{region.get('selection_status', '')} | {region.get('selection_reason', '')} |"
                    )
            w("")
            w("| Sweep | Region | Window | Order | gm peak (S) | Peak Vg (V) | Noise (S) | SNR | Peak change | Shift (steps) | SNR improvement | Peak test | Shift test | SNR plateau | Stable transition | Selected |")
            w("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|---|")
            for result in smoothing_results:
                for region in result.get("gm", {}).get("smoothing", {}).get("regions", []):
                    for candidate in region.get("candidates", []):
                        w(
                            f"| {result.get('sweep_id', '')} | {region.get('region_index', '')} | "
                            f"{candidate.get('window_points', '')} | {candidate.get('polynomial_order', '')} | "
                            f"{_fmt(candidate.get('gm_peak_s'), 4)} | {_fmt(candidate.get('gm_peak_vg'), 4)} | "
                            f"{_fmt(candidate.get('noise_sigma_s'), 4)} | {_fmt(candidate.get('snr'), 4)} | "
                            f"{_fmt(candidate.get('relative_peak_change'), 4)} | {_fmt(candidate.get('peak_shift_steps'), 3)} | "
                            f"{_fmt(candidate.get('snr_improvement_fraction'), 4)} | {candidate.get('peak_stable')} | "
                            f"{candidate.get('shift_stable')} | {candidate.get('snr_plateau')} | {candidate.get('transition_stable')} | "
                            f"{candidate.get('selected')} |"
                        )
            w("")

        if vth_data:
            w("### Threshold Voltage & Mobility")
            w("")
            w("| Vds (V) | Vth (V) | gm,peak (S) | μ_FE (cm²/V·s) | R² |")
            w("|---------|---------|-------------|-----------------|-----|")
            for bias_key in sorted(vth_data.keys()):
                vt = vth_data[bias_key]
                mb = mob_data.get(bias_key, {})
                vds = vt.get("vds_v", bias_key)
                w(f"| {vds:.3g} | {_fmt(vt.get('vth_v'), 3)} | "
                  f"{_fmt(vt.get('gm_peak_value_s'), 3, 'S')} | "
                  f"{_fmt(mb.get('mobility_cm2_vs'), 3, 'cm²/V·s')} | "
                  f"{_fmt(vt.get('tangent_r2'), 4)} |")
            w("")

        # SS & Ion/Ioff per bias
        w("### Subthreshold & On/Off")
        w("")
        w("| Direction | Measured Vds (V) | SS (mV/dec) | Ion (A) | Ion (µA/µm) | Ioff (A) | Ioff (µA/µm) | Ion/Ioff | Ion method |")
        w("|-----------|----------|-------------|---------|------------|----------|-------------|----------|------------|")
        canonical_segments = (metrics.get("device_summary") or {}).get("segments", [])
        for seg in canonical_segments:
            w(f"| {seg.get('direction', '')} | {_fmt(seg.get('bias_value_v'), 3)} | "
              f"{_fmt(seg.get('ss_min_mv_dec'), 3)} | {_fmt(seg.get('ion_configured_a'), 3)} | "
              f"{_fmt(seg.get('ion_configured_ua_per_um'), 3)} | {_fmt(seg.get('ioff_configured_a'), 3)} | "
              f"{_fmt(seg.get('ioff_configured_ua_per_um'), 3)} | {_fmt(seg.get('ion_ioff'), 3)} | "
              f"{seg.get('ion_method_used', '')} |")
        w("")

        if canonical_segments:
            w("### Ion Read Conditions (Requested vs Actual)")
            w("")
            if any(any(segment.get(key) is not None for key in (
                "ion_const_vg_a", "ion_const_vg_requested_v", "ion_const_vg_v",
                "ion_gate_field_requested_mv_cm",
            )) for segment in canonical_segments):
                w("#### Constant Vg or Gate-Field Ion")
                w("")
                w("| Direction | Measured Vds (V) | Ion (A) | Ion (µA/µm) | Requested Vg (V) | Actual Vg used (V) | Requested field (MV/cm) | Actual field (MV/cm) |")
                w("|---|---:|---:|---:|---:|---:|---:|---:|")
                for segment in canonical_segments:
                    w(f"| {segment.get('direction', '')} | {_fmt(segment.get('bias_value_v'), 3)} | {_fmt(segment.get('ion_const_vg_a'), 4)} | {_fmt(segment.get('ion_const_vg_ua_per_um'), 4)} | {_fmt(segment.get('ion_const_vg_requested_v'), 4)} | {_fmt(segment.get('ion_const_vg_v'), 4)} | {_fmt(segment.get('ion_gate_field_requested_mv_cm'), 4)} | {_fmt(segment.get('ion_gate_field_actual_mv_cm'), 4)} |")
                w("")
            if any(any(segment.get(key) is not None for key in (
                "ion_const_vov_a", "ion_const_vov_requested_v", "ion_const_vov_v",
                "ion_overdrive_field_requested_mv_cm",
            )) for segment in canonical_segments):
                w("#### Constant Vov or Overdrive-Field Ion")
                w("")
                w("| Direction | Measured Vds (V) | Ion (A) | Ion (µA/µm) | Requested Vov (V) | Actual Vov used (V) | Requested Vg=Vth+Vov (V) | Actual Vg used (V) | Requested field (MV/cm) | Actual field (MV/cm) |")
                w("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
                for segment in canonical_segments:
                    w(f"| {segment.get('direction', '')} | {_fmt(segment.get('bias_value_v'), 3)} | {_fmt(segment.get('ion_const_vov_a'), 4)} | {_fmt(segment.get('ion_const_vov_ua_per_um'), 4)} | {_fmt(segment.get('ion_const_vov_requested_v'), 4)} | {_fmt(segment.get('ion_const_vov_v'), 4)} | {_fmt(segment.get('ion_const_vov_target_vg_v'), 4)} | {_fmt(segment.get('ion_const_vov_actual_vg_v'), 4)} | {_fmt(segment.get('ion_overdrive_field_requested_mv_cm'), 4)} | {_fmt(segment.get('ion_overdrive_field_actual_mv_cm'), 4)} |")
            w("")

        # Hysteresis
        hyst = metrics.get("per_bias_hysteresis", metrics.get("hysteresis", {}))
        if hyst:
            w("### Hysteresis")
            w("")
            w("| Bias | ΔV (V) | Vg,fwd (V) | Vg,rev (V) |")
            w("|------|--------|------------|------------|")
            for bias_key in sorted(hyst.keys()):
                h = hyst[bias_key]
                if h.get("delta_v") is not None:
                    w(f"| {bias_key} | {_fmt(h.get('delta_v_abs'), 3)} | "
                      f"{_fmt(h.get('vg_forward_v'), 3)} | "
                      f"{_fmt(h.get('vg_reverse_v'), 3)} |")
            w("")

        # Summary
        summary = metrics.get("summary", {})
        w("### Summary")
        w("")
        w("| Metric | Value |")
        w("|--------|-------|")
        w(f"| Vth (mean) | {_fmt(summary.get('vth_v_mean'), 3, 'V')} |")
        w(f"| μ_FE (max) | {_fmt(summary.get('mobility_cm2_vs_max'), 3, 'cm²/V·s')} |")
        w(f"| SS (min) | {_fmt(summary.get('ss_mv_dec_min'), 3, 'mV/dec')} |")
        w(f"| Hysteresis (max) | {_fmt(summary.get('hysteresis_v_max'), 3, 'V')} |")
        # DIBL — prefer summary, fall back to per-bias
        dibl_val = summary.get("dibl_mv_v")
        if dibl_val is None:
            dibl_val = (metrics.get("dibl", {}) or {}).get("dibl_mv_v")
        w(f"| DIBL | {_fmt(dibl_val, 3, 'mV/V')} |")
        w("")

        best = (metrics.get("device_summary") or {}).get("best", {})
        if best:
            w("### Best Results Within This File")
            w("")
            w("Best values are selected across all measured Vds levels and forward/reverse sweeps in this source file. They do not combine different files.")
            w("")
            w("| Metric | Value | Selection | Measured Vds (V) | Sweep type | Direction | Sweep ID | Remarks |")
            w("|---|---:|---|---:|---|---|---|---|")
            for metric, item in best.items():
                if not isinstance(item, dict):
                    continue
                value = item.get("range") if metric == "vth_v_range" else item.get("value")
                w(
                    f"| {metric} | {_fmt(value, 4)} | {item.get('selection', '')} | "
                    f"{_fmt(item.get('measured_vds_v'), 4)} | {item.get('sweep_type', '')} | "
                    f"{item.get('direction', '')} | {item.get('sweep_id', '')} | {item.get('remarks', '')} |"
                )
            w("")

    # ── Output Metrics ──────────────────────────────────────────────
    elif classification.get("type") and "OUTPUT" in str(classification["type"]):
        bias_levels = metrics.get("bias_levels", {})
        w("## Output Characteristics")
        w("")
        w(f"**gds,max:** {_fmt(metrics.get('gds_max'), 3, 'S')}")
        w("")
        if bias_levels:
            w("| Gate Bias (V) | Id,max (A/μm) |")
            w("|---------------|---------------|")
            for bk, bm in sorted(bias_levels.items()):
                w(f"| {bk} | {_fmt(bm.get('id_max_a_um'), 3)} |")
            w("")

    # ── TLM Metrics ─────────────────────────────────────────────────
    elif classification.get("type") and "TLM" in str(classification["type"]):
        rtot = metrics.get("rtotal", {})
        w("## TLM Analysis")
        w("")
        w(f"**R_total:** {_fmt(rtot.get('rtotal_ohm'), 3, 'Ω')}")
        w("")
        per_seg = rtot.get("rtotal_per_segment", {})
        if per_seg:
            w("| Bias | R_total (Ω) | Method |")
            w("|------|-------------|--------|")
            for bk, pd in sorted(per_seg.items()):
                w(f"| {bk} | {_fmt(pd.get('rtotal_ohm'), 3)} | {pd.get('method', '')} |")
            w("")

    # ── Plots ───────────────────────────────────────────────────────
    w("## Generated Plots")
    w("")
    plot_files = sorted(plot_dir.glob("*.png")) if plot_dir.exists() else []
    w("")

    # ── Warnings ────────────────────────────────────────────────────
    all_warnings: list[str] = []

    # Collect from Vth
    for vt in metrics.get("per_bias_vth", {}).values():
        all_warnings.extend(vt.get("warnings", []))
    # Collect from mobility
    for mb in metrics.get("per_bias_mobility", {}).values():
        all_warnings.extend(mb.get("warnings", []))
    # Collect from hysteresis
    for h in metrics.get("per_bias_hysteresis", {}).values():
        all_warnings.extend(h.get("warnings", []))
    # Collect from DIBL
    dibl_warn = (metrics.get("dibl") or {}).get("warnings", [])
    all_warnings.extend(dibl_warn)

    # Quality-control flags from cleaning and extraction.
    for flag in metrics.get("quality", {}).get("flags", []):
        all_warnings.append(flag.get("message", str(flag)))
    for issue in metrics.get("parameter_preflight", {}).get("issues", []):
        all_warnings.append(issue.get("message", str(issue)))
    for issue in metrics.get("config_validation", {}).get("issues", []):
        if issue.get("level") in {"warning", "error"}:
            all_warnings.append(issue.get("message", str(issue)))
    # Unique warnings
    unique = list(dict.fromkeys(all_warnings))

    if unique:
        w("## ⚠️ Warnings")
        w("")
        for warning in unique[:20]:
            w(f"- {warning}")
        if len(unique) > 20:
            w(f"- ... and {len(unique) - 20} more warnings (see metrics JSON)")
        w("")

    # ── Raw Metadata ────────────────────────────────────────────────
    w("## Measurement Metadata")
    w("")
    w("| Key | Value |")
    w("|-----|-------|")
    for key in ("measurement_type", "record_time", "device_id", "count", "flag", "remarks"):
        val = parsed_metadata.get(key) if isinstance(parsed_metadata, dict) else ""
        if val:
            w(f"| {key.replace('_', ' ').title()} | {val} |")
    w("")

    write_html_report(output_path, f"{sample_id} FET analysis", lines, plot_files)

    LOGGER.info("  → Report: %s", output_path)



def generate_tlm_report(
    tlm_results: list[dict[str, Any]],
    output_path: Path,
    tlm_devices: list[dict[str, Any]] | None = None,
    plot_files: list[Path] | None = None,
) -> None:
    """Generate a consolidated standalone HTML TLM report.

    Args:
        tlm_results: List of TLM results from auto_group_tlm()
        output_path: Where to write the HTML report
        tlm_devices: Optional list of per-device dicts with source_file info
    """
    lines: list[str] = []
    w = lines.append

    w("# TLM Analysis — Batch Report")
    w("")
    w(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    w(f"**Samples analysed:** {len(tlm_results)}")
    w("")

    for tlm in tlm_results:
        sample = tlm.get("sample_id", "unknown")
        w(f"## {sample}")
        w("")
        w("| Parameter | Value |")
        w("|-----------|-------|")
        w(f"| Rc | {_fmt(tlm.get('rc_ohm'), 1, 'Ω')} |")
        w(f"| Rsh | {_fmt(tlm.get('rsh_ohm_sq'), 1, 'Ω/□')} |")
        w(f"| Film thickness | {_fmt(tlm.get('film_thickness_nm'), 3, 'nm')} |")
        w(f"| Film resistivity | {_fmt(tlm.get('rho_film_ohm_cm'), 3, 'Ω·cm')} |")
        w(f"| LT | {_fmt(tlm.get('lt_um'), 2, 'μm')} |")
        w(f"| ρc | {_fmt(tlm.get('rhoc_ohm_cm2'), 2, 'Ω·cm²')} |")
        w(f"| R² | {_fmt(tlm.get('r2'), 4)} |")
        w(f"| N devices | {tlm.get('n_points', 0)} |")
        for key, value in tlm.get("group_values", {}).items():
            w(f"| {key} | {value} |")
        w("")

        # Source files for this sample
        if tlm_devices:
            # Extract sample_id from group key (strip measurement type suffix)
            sample_dev_files = [
                d for d in tlm_devices
                if d.get("sample_id", "") == sample.split(" [")[0]
                or d.get("sample_id", "") in sample
            ]
            if sample_dev_files:
                read = sample_dev_files[0]
                read_settings = [
                    ("Transfer read mode", read.get("transfer_read_mode")),
                    ("Transfer read Vg (V)", read.get("transfer_read_vg_v")),
                    ("Requested read Vg (V)", read.get("requested_read_vg_v")),
                    ("Actual measured Vg used (V)", read.get("actual_read_vg_v")),
                    ("Vg mismatch, actual-requested (V)", read.get("read_vg_delta_v")),
                    ("Transfer overdrive (V)", read.get("overdrive_v")),
                    ("Requested overdrive (V)", read.get("requested_overdrive_v")),
                    ("Actual overdrive used (V)", read.get("actual_overdrive_v")),
                    ("Requested gate field (MV/cm)", read.get("requested_gate_field_mv_cm")),
                    ("Actual gate field used (MV/cm)", read.get("actual_gate_field_mv_cm")),
                    ("Requested overdrive field (MV/cm)", read.get("requested_overdrive_field_mv_cm")),
                    ("Actual overdrive field used (MV/cm)", read.get("actual_overdrive_field_mv_cm")),
                    ("Transfer read Vds (V)", read.get("vds_v")),
                ]
                if any(value is not None for _, value in read_settings):
                    w("### Analysis Configuration Used")
                    w("")
                    w("| Setting | Effective value |")
                    w("|---------|-----------------|")
                    for label, value in read_settings:
                        w(f"| {label} | {_setting_value(value)} |")
                    w("")
                w("### Source Files")
                w("")
                for d in sorted(sample_dev_files, key=lambda x: x.get("channel_length_um", 0)):
                    fname = Path(d.get("source_file", d.get("device_name", "?"))).name
                    lch = d.get("channel_length_um", "?")
                    typ = d.get("measurement_type", "?")
                    rtot = d.get("r_total_ohm", "—")
                    w(f"- `{fname}` — Lch={lch}μm, R_total={_fmt(rtot, 1, 'Ω')} ({typ})")
                w("")

        # Channel length table
        lch_vals = tlm.get("lch_values", [])
        if lch_vals:
            w("| Lch (μm) | R_total (Ω) |")
            w("|----------|-------------|")
            for lch, rtot in lch_vals:
                w(f"| {lch:.1f} | {rtot:.0f} |")
            w("")

        # Warnings
        warns = tlm.get("warnings", [])
        if warns:
            w("**Warnings:**")
            for warn in warns:
                w(f"- {warn}")
            w("")

    write_html_report(output_path, "TLM Analysis — Batch Report", lines, plot_files or [])

    LOGGER.info("TLM report: %s", output_path)


def _to_numeric_key(k: Any) -> tuple[float, str]:
    """Sort key that handles numeric strings and mixed types."""
    try:
        return (0, float(k))
    except (ValueError, TypeError):
        return (1, str(k))


def write_device_excel(
    segments: list[Any],
    classification: dict[str, Any],
    metrics: dict[str, Any],
    output_path: Path,
    raw_segments: list[Any] | None = None,
) -> None:
    """Write one auditable workbook containing raw, processed, and metric data.

    Every sheet stores typed values, not formatted strings, so it can be used
    directly for independent calculations and plotting in Excel.
    """
    try:
        import openpyxl
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
        from openpyxl.chart import ScatterChart, Series, Reference
        from openpyxl.worksheet.table import Table, TableStyleInfo
    except ImportError:
        LOGGER.warning("openpyxl not available - skipping Excel export: %s", output_path)
        return

    from fet_analyzer.analysis.numerics import compute_gm
    analysis_settings = metrics.get("analysis_settings", {})
    wb = openpyxl.Workbook()
    header_fill = PatternFill("solid", fgColor="2F5496")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")

    def _unique_excel_headers(headers: list[str]) -> list[str]:
        """Return valid, unique, non-empty Excel table column headers."""
        seen: dict[str, int] = {}
        unique: list[str] = []
        for index, header in enumerate(headers, 1):
            base = str(header).strip() if header is not None else ""
            if not base:
                base = f"Column{index}"
            count = seen.get(base, 0) + 1
            seen[base] = count
            unique.append(base if count == 1 else f"{base}_{count}")
        return unique

    def write_table(ws, headers: list[str], rows: list[list[Any]]) -> None:
        headers = _unique_excel_headers(headers)
        ws.append(headers)
        for cell in ws[1]:
            cell.fill, cell.font = header_fill, header_font
        for row in rows:
            ws.append(row)
        ws.freeze_panes = "A2"
        table_ref = f"A1:{get_column_letter(len(headers))}{max(1, len(rows) + 1)}"
        ws.auto_filter.ref = table_ref
        if rows:
            table_name = "Tbl" + "".join(ch for ch in ws.title.title() if ch.isalnum())
            table = Table(displayName=table_name, ref=table_ref)
            table.tableStyleInfo = TableStyleInfo(
                name="TableStyleMedium2",
                showRowStripes=True,
                showColumnStripes=False,
            )
            ws.add_table(table)
        for column in ws.columns:
            letter = column[0].column_letter
            width = max(len(str(cell.value or "")) for cell in column)
            ws.column_dimensions[letter].width = min(max(width + 2, 12), 30)
        if "description" in headers:
            description_col = headers.index("description") + 1
            description_letter = get_column_letter(description_col)
            ws.column_dimensions[description_letter].width = 80
            for row in range(2, ws.max_row + 1):
                cell = ws.cell(row=row, column=description_col)
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                text_length = len(str(cell.value or ""))
                ws.row_dimensions[row].height = 30 if text_length <= 100 else 45
        if "metric" in headers:
            metric_letter = get_column_letter(headers.index("metric") + 1)
            ws.column_dimensions[metric_letter].width = 48
        if "effective_value" in headers:
            value_col = headers.index("effective_value") + 1
            value_letter = get_column_letter(value_col)
            ws.column_dimensions[value_letter].width = 58
            for row in range(2, ws.max_row + 1):
                ws.cell(row=row, column=value_col).alignment = Alignment(
                    wrap_text=True, vertical="top"
                )

    metric_descriptions = {
        "measurement_type": ("Measurement class assigned by the classifier or parsed from the source filename.", ""),
        "sweep_variable": ("Voltage column actively swept during this measurement.", ""),
        "bias_variable": ("Voltage held approximately constant while the sweep variable was changed.", ""),
        "sample_id": ("Sample identifier parsed from the source filename.", ""),
        "vth_v_mean": (f"Mean threshold voltage extracted using {_setting_value(analysis_settings.get('vth_method'))} across usable biases.", "V"),
        "vth_v_std": ("Standard deviation of extracted threshold voltage.", "V"),
        "vth_v_range": ("Minimum and maximum extracted threshold voltages across usable drain-bias segments.", "V"),
        "vth_v": (f"Threshold voltage extracted using {_setting_value(analysis_settings.get('vth_method'))}.", "V"),
        "vth_method": ("Threshold-voltage extraction algorithm used for this result.", ""),
        "vg_intercept_v": ("Gate-voltage intercept where the peak-gm tangent extrapolates to Id=0; Vth may additionally include Vds correction.", "V"),
        "tangent_slope_a_per_v": ("Slope dId/dVg of the linear fit around the peak-transconductance point.", "A/V"),
        "tangent_r2": ("Coefficient of determination of the peak-gm tangent fit; values nearer 1 indicate a more linear fit window.", "unitless"),
        "tangent_n_points": ("Number of measured points included in the peak-gm tangent fit.", "count"),
        "tangent_vg_range": ("Lowest and highest gate voltages included in the peak-gm tangent fit.", "V"),
        "vds_corrected": ("Whether the configured Vds/2 threshold-voltage correction was applied.", "boolean"),
        "vds_v": ("Drain-source bias associated with this transfer segment.", "V"),
        "gm_max_s": (f"Maximum |dId/dVg|; Savitzky-Golay window={analysis_settings.get('gm_savgol_window', 'not recorded')}, order={analysis_settings.get('gm_savgol_order', 'not recorded')}.", "S"),
        "gm_max_vg": ("Gate voltage at maximum transconductance.", "V"),
        "gm_peak_value_s": ("Signed transconductance at the peak-gm threshold point.", "S"),
        "gm_peak_vg": ("Gate voltage at peak transconductance.", "V"),
        "ss_mv_dec": (f"Subthreshold swing, calculated as 1000 x |dVg/d(log10|Id|)|. The fit spans at least one current decade, uses currents above {analysis_settings.get('noise_floor_a', 'the recorded noise floor')} A, and requires |Id| > {analysis_settings.get('ss_leakage_factor', 1.0)} x |Ig|.", "mV/dec"),
        "ss_min_mv_dec": (f"Lowest valid per-bias subthreshold swing, calculated as 1000 x |dVg/d(log10|Id|)|. The fit spans at least one current decade, uses currents above {analysis_settings.get('noise_floor_a', 'the recorded noise floor')} A, and requires |Id| > {analysis_settings.get('ss_leakage_factor', 1.0)} x |Ig|.", "mV/dec"),
        "ss_mv_dec_min": (f"Lowest valid per-bias subthreshold swing, calculated as 1000 x |dVg/d(log10|Id|)|. The fit spans at least one current decade, uses currents above {analysis_settings.get('noise_floor_a', 'the recorded noise floor')} A, and requires |Id| > {analysis_settings.get('ss_leakage_factor', 1.0)} x |Ig|.", "mV/dec"),
        "ss_mv_dec_mean": ("Arithmetic mean of valid per-bias minimum subthreshold-swing values.", "mV/dec"),
        "ss_mv_dec_std": ("Sample standard deviation of valid per-bias minimum subthreshold-swing values.", "mV/dec"),
        "ss_at_vg": ("Mean gate voltage of the window used for the minimum-SS fit.", "V"),
        "ss_vg": ("Mean gate voltage of the window used for the minimum-SS fit.", "V"),
        "ss_region": ("Start and end gate voltages delimiting the minimum-SS fit window.", "V"),
        "ss_n_points": ("Number of measured points included in the minimum-SS fit window.", "count"),
        "ss_fit_slope_v_dec": ("Absolute fitted dVg/d(log10|Id|) before conversion to mV/dec; ss_mv_dec is this value multiplied by 1000.", "V/dec"),
        "ss_fit_indices": ("Zero-based source-segment indices of the exact leakage-qualified points used by the minimum-SS regression.", "index list"),
        "ss_unit": ("Explicit unit attached to the reported subthreshold-swing value.", ""),
        "ss_leakage_qualified": ("Whether measured gate leakage was available and the |Id| > factor x |Ig| rule was applied.", "boolean"),
        "ss_leakage_factor": ("Multiplier in the SS eligibility rule |Id| > factor x |Ig|.", "unitless"),
        "ss_candidate_points": ("Number of finite points remaining after noise-floor, configured Vg-range, and gate-leakage qualification.", "count"),
        "ss_excluded_below_ig": ("Points rejected from SS analysis because |Id| did not exceed the configured multiple of |Ig|.", "count"),
        "ss_avg_mv_dec": ("Slope-derived SS over the full valid current range, reported only when that range spans at least two decades.", "mV/dec"),
        "ss_avg_region": ("Start and end gate voltages of the full-range average-SS calculation.", "V"),
        "ss_decades": ("Current span used for the minimum subthreshold swing result.", "decades"),
        "ss_avg_decades": ("Current span used for average subthreshold swing.", "decades"),
        "ion_ioff": (f"Ion/Ioff using the configured Ion read condition and configured leakage-qualified Ioff rule (factor {analysis_settings.get('ioff_leakage_factor', 'not recorded')}).", "unitless"),
        "ion_ioff_log10": ("Base-10 logarithm of the reported Ion/Ioff ratio.", "decades"),
        "ion_a": (
            "On-current produced by the "
            f"{_setting_value(analysis_settings.get('ion_method_used'))[:1].lower()}"
            f"{_setting_value(analysis_settings.get('ion_method_used'))[1:]}; configured primary request: "
            f"{_setting_value(analysis_settings.get('ion_method_configured'))}.",
            "A",
        ),
        "ioff_a": (f"Minimum |Id| satisfying |Id| > {analysis_settings.get('ioff_leakage_factor', 'configured factor')} × |Ig|; used for Ion/Ioff.", "A"),
        "ioff_method": ("Rule used to choose Ioff; minimum_above_gate_leakage selects the smallest |Id| passing the drain-to-gate leakage criterion.", ""),
        "leakage_factor": ("Multiplier in the Ioff acceptance rule |Id| > leakage_factor × |Ig|.", "unitless"),
        "leakage_ratio_max": ("Largest measured |Ig|/|Id| ratio in valid forward-sweep data; larger values indicate greater gate-leakage contamination.", "unitless"),
        "id_min_a": ("Minimum signed drain-current value in the cleaned segment; the measured current sign is retained.", "A"),
        "id_max_a": ("Maximum signed drain-current value in the cleaned segment; the measured current sign is retained.", "A"),
        "ion_const_vg_a": ("|Id| at the nearest measured Vg to the requested constant-voltage or constant-field read condition.", "A"),
        "ion_const_vg_requested_v": ("Gate voltage requested directly or resolved from nominal gate field and oxide thickness.", "V"),
        "ion_const_vg_v": ("Actual measured gate voltage used for ion_const_vg_a.", "V"),
        "ion_const_vg_delta_v": ("Actual measured Vg minus requested Vg.", "V"),
        "ion_gate_field_requested_mv_cm": ("Requested nominal applied gate field, defined as Vg/tox.", "MV/cm"),
        "ion_gate_field_actual_mv_cm": ("Nominal applied gate field corresponding to the actual measured Vg used.", "MV/cm"),
        "ion_const_overdrive_a": ("|Id| at the measured Vg nearest to requested Vth+Vov.", "A"),
        "ion_const_overdrive_requested_v": ("Signed gate overdrive requested directly or resolved from overdrive field.", "V"),
        "ion_const_overdrive_v": ("Actual signed Vg-Vth at the measured point used.", "V"),
        "ion_const_overdrive_target_vg_v": ("Requested absolute gate voltage Vth+Vov.", "V"),
        "ion_const_overdrive_actual_vg_v": ("Actual measured gate voltage used for constant-overdrive Ion.", "V"),
        "ion_const_overdrive_delta_vg_v": ("Actual measured Vg minus requested Vth+Vov.", "V"),
        "ion_overdrive_input_v": ("Signed voltage overdrive entered directly; retained for audit even when an electric-field input takes precedence.", "V"),
        "ion_overdrive_field_mv_cm": ("Signed oxide electric field requested for Ion extraction; negative values are normally used for p-FETs.", "MV/cm"),
        "ion_overdrive_field_actual_mv_cm": ("Actual (Vg-Vth)/tox field at the measured point used for Ion.", "MV/cm"),
        "ion_gate_field_mv_cm": ("Configured nominal Vg/tox field for fixed-gate-field Ion.", "MV/cm"),
        "ion_oxide_thickness_nm": ("Device oxide thickness used to convert electric-field overdrive to voltage.", "nm"),
        "ion_overdrive_source": ("Whether the effective Ion overdrive was resolved from electric field or direct voltage.", ""),
        "mobility_cm2_vs": ("Linear-regime field-effect mobility calculated from peak |gm|, channel length, channel width, Cox, and |Vds|.", "cm²/V·s"),
        "mobility_cm2_vs_max": ("Largest valid per-bias linear-regime field-effect mobility for the device.", "cm²/V·s"),
        "mobility_cm2_vs_mean": ("Arithmetic mean of valid per-bias field-effect mobilities.", "cm²/V·s"),
        "mobility_cm2_vs_std": ("Sample standard deviation of valid per-bias field-effect mobilities.", "cm²/V·s"),
        "hysteresis_v_max": ("Maximum absolute hysteresis across usable biases.", "V"),
        "delta_v": ("Signed reverse-minus-forward gate-voltage shift at the midpoint of the overlapping current range.", "V"),
        "delta_v_abs": ("Absolute forward/reverse hysteresis voltage shift.", "V"),
        "vg_forward_v": ("Forward-sweep gate voltage at the current selected for hysteresis comparison.", "V"),
        "vg_reverse_v": ("Reverse-sweep gate voltage at the same comparison current used for hysteresis.", "V"),
        "i_at_hysteresis_a": ("Absolute drain current at which forward/reverse hysteresis was evaluated.", "A"),
        "dibl_mv_v": ("Change in extracted Vth divided by change in Vds, in millivolts of threshold shift per volt of drain bias.", "mV/V"),
        "gds_max": (f"Maximum |dId/dVd| from {analysis_settings.get('gds_method_used', 'finite differences within each output segment')}.", "S"),
        "gds_max_s": (f"Maximum output conductance using {analysis_settings.get('gds_method_used', 'finite differences within each segment')}.", "S"),
        "id_max_a_um": ("Maximum |Id| normalized by recorded channel width for this output-bias segment.", "A/μm"),
        "id_at_5v": ("Drain current interpolated at Vd=5 V; blank when unavailable or not implemented.", "A"),
        "resistance_avg_ohm": ("Arithmetic mean of pointwise |Vd/Id| over valid nonzero output-sweep points.", "Ω"),
        "resistance_median_ohm": ("Median of pointwise |Vd/Id| over valid nonzero output-sweep points.", "Ω"),
        "resistance_linear_fit_ohm": ("Resistance obtained as 1/|slope| from the configured low-|Vd| linear Id-Vd fit.", "Ω"),
        "linear_fit_r2": ("Coefficient of determination for the low-|Vd| linear resistance fit.", "unitless"),
        "r2": ("Coefficient of determination for a fit.", "unitless"),
        "n_points": ("Number of data points used.", "count"),
        "method": ("Named extraction method used for this result.", ""),
        "warnings": ("Warnings emitted while calculating this result; blank means none were emitted.", ""),
        "sweep_results": ("Serialized standalone results for every bias-and-direction sweep; see the Sweep Results sheet for tabular fields.", ""),
        "parameter_warnings": ("Geometry or material-parameter warnings, including use of unconfirmed template defaults.", ""),
        "points_before_cleaning": ("Total measured points across all segments before cleaning filters were applied.", "count"),
        "removed_nan": ("Points removed because a required numerical value was NaN or non-finite.", "count"),
        "removed_noise": ("Points removed because |Id| was below the effective cleaning noise floor.", "count"),
        "removed_compliance": ("Points removed because they belonged to a detected instrument-compliance plateau.", "count"),
        "flags": ("Quality-control flags raised from cleaning, extraction, leakage, or physical-plausibility checks.", ""),
        "status": ("Overall quality status derived from the recorded quality-control flags.", ""),
    }

    def describe_metric(metric: str) -> tuple[str, str]:
        path = str(metric)
        key = path.split(".")[-1]
        if path.startswith("analysis_settings."):
            setting_descriptions = {
                "ion_method_used": "Ion algorithm actually used to populate ion_a.",
                "ion_method_configured": "Value of transfer.ion_method used for the primary Ion and Ion/Ioff result.",
                "ion_method_note": "Audit note describing the configured primary and optional secondary Ion read conditions.",
                "ion_constant_vg_v": "Effective absolute gate voltage for the separately reported constant-Vg Ion value.",
                "ion_fixed_vg_v": "Effective absolute gate voltage for fixed-Vg Ion extraction.",
                "ion_overdrive_v": "Effective signed gate overdrive for the separately reported Vth+Vov Ion value.",
                "ion_overdrive_input_v": "Signed voltage input before electric-field precedence is applied.",
                "ion_overdrive_field_mv_cm": "Signed oxide electric-field input. Converted using Vov[V] = Eox[MV/cm] x tox[nm] x 0.1.",
                "ion_overdrive_source": "Source of the effective overdrive: electric_field, voltage, or blank when not configured.",
                "ion_oxide_thickness_nm": "Oxide thickness used for the electric-field-to-voltage conversion.",
                "ion_bias_warnings": "Warnings raised while resolving the fixed-Vg or fixed-overdrive Ion read condition.",
                "ioff_method_used": "Ioff selection rule actually used for Ion/Ioff.",
                "ioff_leakage_factor": "Multiplier in the gate-leakage qualification |Id| > factor×|Ig|.",
                "vth_method": "Configured threshold-voltage extraction method.",
                "vth_tangent_window_v": "Requested half-width of the gate-voltage window around peak gm for tangent fitting.",
                "vth_tangent_min_points": "Minimum number of points required for the Vth tangent fit.",
                "vth_constant_current_a_per_um": "Width-normalized current target used only by constant-current Vth extraction.",
                "vth_vds_correction": "Whether Vds/2 correction is enabled for tangent-extracted Vth.",
                "ss_method_used": "Subthreshold-swing algorithm actually used.",
                "ss_average_min_decades": "Minimum total current span required before average SS is reported.",
                "noise_floor_a": "Current floor used to exclude data from SS extraction and transfer plotting.",
                "cleaning_noise_floor_a": "Current floor used by segment cleaning before analysis.",
                "gm_savgol_window": "Savitzky-Golay smoothing window for gm; 0 means smoothing is disabled.",
                "gm_savgol_order": "Polynomial order for Savitzky-Golay gm smoothing when enabled.",
                "normalize_by_width": "Whether displayed current and conductance curves are divided by channel width.",
                "channel_width_um": "Channel width used for normalization and mobility calculations.",
                "gds_method_used": "Numerical method used to calculate output conductance.",
                "resistance_method_used": "Method used to extract output resistance.",
                "resistance_fit_vd_max_v": "Maximum |Vd| included in the low-bias resistance fit.",
            }
            units = {
                "ion_constant_vg_v": "V", "ion_fixed_vg_v": "V", "ion_fixed_vg_input_v": "V", "ion_overdrive_v": "V",
                "ion_gate_field_mv_cm": "MV/cm",
                "ion_overdrive_input_v": "V", "ion_overdrive_field_mv_cm": "MV/cm",
                "ion_oxide_thickness_nm": "nm",
                "vth_tangent_window_v": "V", "vth_tangent_min_points": "count",
                "vth_constant_current_a_per_um": "A/μm", "ss_average_min_decades": "decades",
                "noise_floor_a": "A", "cleaning_noise_floor_a": "A",
                "gm_savgol_window": "points", "gm_savgol_order": "order",
                "channel_width_um": "μm", "resistance_fit_vd_max_v": "V",
            }
            return (setting_descriptions.get(key, "Effective configuration value recorded for reproducibility."), units.get(key, ""))
        if path.startswith("device_geometry."):
            geometry = {
                "channel_width_um": ("Physical channel width used for normalization and mobility calculations.", "μm"),
                "channel_length_um": ("Physical source-to-drain channel length used for mobility and TLM calculations.", "μm"),
                "gate_length_um": ("Physical gate length when specified separately from channel length.", "μm"),
                "oxide_thickness_nm": ("Gate-dielectric thickness used when deriving Cox.", "nm"),
                "dielectric_constant": ("Relative permittivity of the gate dielectric used when deriving Cox.", "unitless"),
                "cox_f_per_cm2": ("Gate-oxide capacitance per unit area used in mobility extraction.", "F/cm²"),
                "contact_length_um": ("Length of each source/drain contact used for contact analysis when available.", "μm"),
                "contact_width_um": ("Width of each source/drain contact used for contact analysis when available.", "μm"),
                "gate_dielectric": ("Gate-dielectric material label.", ""),
                "contact_metal": ("Source/drain contact metallization label.", ""),
                "substrate": ("Substrate material label.", ""),
                "top_gated": ("True for a top-gated device; false for another gate geometry.", "boolean"),
                "temperature_c": ("Measurement or configured device temperature in degrees Celsius.", "°C"),
                "temperature_k": ("Measurement or configured device temperature in kelvin.", "K"),
                "polarity": ("Configured transistor polarity used when interpreting transfer behavior.", ""),
            }
            return geometry.get(key, ("Recorded device-geometry or material parameter.", ""))
        if path.startswith("geometry_sources."):
            return (f"Provenance of device parameter '{key}'—for example filename, device_parameters.txt, metadata, or template default.", "")
        if key == "method":
            if "mobility" in path:
                return ("Mobility extraction model; field_effect uses gm, Cox, W, L, and Vds.", "")
            if "hysteresis" in path:
                return ("Hysteresis method; midpoint_overlap compares sweep directions at the midpoint of their common current range.", "")
        if key in metric_descriptions:
            return metric_descriptions[key]
        if key.endswith("_v"):
            return ("Voltage value associated with the named extraction result.", "V")
        if key.endswith("_a"):
            return ("Current value associated with the named extraction result.", "A")
        if key.endswith("_s"):
            return ("Conductance value associated with the named extraction result.", "S")
        if "warning" in key:
            return ("Warning or diagnostic message.", "")
        return ("Recorded pipeline field retained for traceability; interpret it using its full metric path and associated analysis section.", "")

    def segment_rows(source: list[Any]) -> tuple[list[str], list[list[Any]]]:
        columns: list[str] = []
        for segment in source:
            for column in segment.data:
                if column not in columns:
                    columns.append(column)
        headers = ["segment_index", "sweep_direction", "bias_variable", "bias_level", "point_index"] + columns
        rows: list[list[Any]] = []
        for seg_index, segment in enumerate(source):
            length = max((len(values) for values in segment.data.values()), default=0)
            for point_index in range(length):
                row = [seg_index, segment.direction, segment.bias_variable, segment.bias_level, point_index]
                row.extend(
                    segment.data.get(column, [None] * length)[point_index]
                    if point_index < len(segment.data.get(column, [])) else None
                    for column in columns
                )
                rows.append(row)
        return headers, rows

    ws = wb.active
    ws.title = "Summary"
    from fet_analyzer.analysis.metric_summary import METRIC_DEFINITIONS, build_device_summary
    device_summary = metrics.get("device_summary") or build_device_summary(
        metrics, analysis_settings.get("summary_config", {})
    )
    summary_segments = list(device_summary.get("segments", []))
    preferred_id = (device_summary.get("preferred") or {}).get("sweep_id")
    if not summary_segments:
        summary_segments = [device_summary.get("preferred", {})]
    headers = ["Parameter (unit)"]
    for segment in summary_segments:
        direction = segment.get("direction") or "device"
        bias_var = segment.get("bias_variable")
        bias = segment.get("bias_value_v")
        label = f"{direction}"
        if bias_var and bias is not None:
            label = f"{direction} · {bias_var}={bias:g} V"
        if segment.get("sweep_id") == preferred_id:
            label = f"Preferred · {label}"
        headers.append(label)
    ws.append(headers)
    for cell in ws[1]:
        cell.fill, cell.font = header_fill, header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    global_values = device_summary.get("preferred", {})
    device_only = {"dibl_mv_v", "quality_status"}
    for definition in METRIC_DEFINITIONS:
        key = definition["key"]
        label = definition["label"]
        unit = definition["unit"]
        row = [f"{label} ({unit})" if unit else label]
        for segment in summary_segments:
            value = segment.get(key)
            if value is None and key in device_only and segment.get("sweep_id") == preferred_id:
                value = global_values.get(key)
            row.append(value)
        ws.append(row)
    method_rows = [
        ("Ion method used", "ion_method_used"),
        ("Ioff method used", "ioff_method_used"),
        ("Preferred-segment selection", "selection_reason"),
    ]
    for label, key in method_rows:
        ws.append([label] + [
            (segment.get(key) if key != "selection_reason" else
             global_values.get(key) if segment.get("sweep_id") == preferred_id else None)
            for segment in summary_segments
        ])
    ws.freeze_panes = "B2"
    ws.column_dimensions["A"].width = 48
    for column in range(2, ws.max_column + 1):
        letter = get_column_letter(column)
        ws.column_dimensions[letter].width = 22
        for row in range(2, ws.max_row + 1):
            cell = ws.cell(row=row, column=column)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            if isinstance(cell.value, float):
                cell.number_format = "0.000E+00" if cell.value and abs(cell.value) < 0.01 else "0.000"
        if summary_segments[column - 2].get("sweep_id") == preferred_id:
            for row in range(1, ws.max_row + 1):
                ws.cell(row=row, column=column).fill = PatternFill("solid", fgColor="DDEBF7")
            ws.cell(row=1, column=column).fill = PatternFill("solid", fgColor="126B5B")
    ws.auto_filter.ref = f"A1:{get_column_letter(ws.max_column)}{ws.max_row}"
    ws.sheet_view.showGridLines = False

    best = (metrics.get("device_summary") or {}).get("best", {})
    if best:
        best_ws = wb.create_sheet("Best Results")
        best_ws.append(["Metric", "Value", "Selection", "Measured Vds (V)", "Sweep type", "Direction", "Sweep ID", "Remarks"])
        for cell in best_ws[1]:
            cell.fill, cell.font = header_fill, header_font
            cell.alignment = Alignment(horizontal="center", wrap_text=True)
        for metric, item in best.items():
            if not isinstance(item, dict):
                continue
            best_ws.append([
                metric, item.get("range") if metric == "vth_v_range" else item.get("value"),
                item.get("selection"), item.get("measured_vds_v"), item.get("sweep_type"),
                item.get("direction"), item.get("sweep_id"), item.get("remarks"),
            ])
        best_ws.freeze_panes = "A2"
        best_ws.auto_filter.ref = best_ws.dimensions
        for column, width in enumerate([30, 16, 18, 18, 18, 22, 45, 110], 1):
            best_ws.column_dimensions[get_column_letter(column)].width = width
            for row in range(2, best_ws.max_row + 1):
                best_ws.cell(row=row, column=column).alignment = Alignment(vertical="top", wrap_text=True)

    raw = raw_segments if raw_segments is not None else segments
    ws = wb.create_sheet("Raw Data")
    headers, rows = segment_rows(raw)
    write_table(ws, headers, rows)

    ws = wb.create_sheet("Processed Data")
    headers, rows = segment_rows(segments)
    write_table(ws, headers, rows)

    if analysis_settings:
        ws = wb.create_sheet("Analysis Settings")
        write_table(
            ws,
            ["setting", "description", "units", "effective_value"],
            [
                [key, *describe_metric(f"analysis_settings.{key}"), _setting_value(value)]
                for key, value in analysis_settings.items()
            ],
        )

    derivative_rows: list[list[Any]] = []
    sweep_var = classification.get("sweep_variable", "Vg")
    drain_col = classification.get("drain_current_raw_column", "Id")
    sweep_results = metrics.get("sweep_results", [])
    for seg_index, segment in enumerate(segments):
        gm_result = sweep_results[seg_index].get("gm", {}) if seg_index < len(sweep_results) else {}
        vg = gm_result.get("vg_v")
        gm = gm_result.get("gm_display_s")
        gm_metric = gm_result.get("gm_metric_s")
        if vg is None or gm is None:
            vg, gm = compute_gm(segment.data.get(sweep_var, []), segment.data.get(drain_col, []))
            gm_metric = gm
        for point_index, (voltage, value) in enumerate(zip(vg, gm)):
            metric_value = gm_metric[point_index] if point_index < len(gm_metric) else None
            derivative_rows.append([
                seg_index, segment.direction, segment.bias_variable,
                segment.bias_level, voltage, value,
                abs(value) if value == value else None,
                metric_value,
            ])
    ws = wb.create_sheet("Derivatives")
    write_table(ws, ["segment_index", "sweep_direction", "bias_variable", "bias_level", sweep_var, "gm_display_S", "abs_gm_display_S", "gm_metric_S"], derivative_rows)

    audit_rows: list[list[Any]] = []
    for result in sweep_results:
        identity = result.get("identity", {})
        smoothing = result.get("gm", {}).get("smoothing", {})
        for region in smoothing.get("regions", []):
            for candidate in region.get("candidates", []):
                audit_rows.append([
                    result.get("sweep_id"), identity.get("direction"),
                    identity.get("bias_value_v"), region.get("region_index"),
                    region.get("vg_min"), region.get("vg_max"),
                    candidate.get("window_points"), candidate.get("polynomial_order"),
                    candidate.get("gm_peak_s"), candidate.get("gm_peak_vg"),
                    candidate.get("noise_sigma_s"), candidate.get("snr"),
                    candidate.get("relative_peak_change"), candidate.get("peak_shift_steps"),
                    candidate.get("snr_improvement_fraction"),
                    candidate.get("peak_stable"), candidate.get("shift_stable"),
                    candidate.get("snr_plateau"), candidate.get("transition_stable"),
                    candidate.get("selected"), region.get("selection_status"),
                    region.get("selection_reason"), "; ".join(region.get("warnings", [])),
                ])
    if audit_rows:
        ws = wb.create_sheet("gm Smoothing Audit")
        write_table(ws, [
            "sweep_id", "direction", "bias_value_v", "region_index", "vg_min_v", "vg_max_v",
            "window_points", "polynomial_order", "gm_peak_s", "peak_vg_v",
            "noise_estimate_s", "snr", "peak_change_fraction", "peak_shift_steps",
            "snr_improvement_fraction", "peak_stable", "shift_stable", "snr_plateau",
            "transition_stable", "selected", "selection_status",
            "selection_reason", "warnings",
        ], audit_rows)

    def flatten(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
        if isinstance(value, dict):
            rows: list[tuple[str, Any]] = []
            for key, child in value.items():
                rows.extend(flatten(child, f"{prefix}.{key}" if prefix else str(key)))
            return rows
        if isinstance(value, (list, tuple)):
            return [(prefix, "; ".join(map(str, value)))]
        if value is not None and not isinstance(value, (str, int, float, bool)):
            value = str(value)
        return [(prefix, value)]

    summary_rows = []
    for key, value in [
        ("measurement_type", getattr(classification.get("type"), "name", classification.get("type"))),
        ("sweep_variable", sweep_var),
        ("bias_variable", classification.get("bias_variable")),
    ] + flatten(metrics):
        desc, units = describe_metric(key)
        summary_rows.append([key, desc, units, value])
    ws = wb.create_sheet("Audit Metrics")
    write_table(ws, ["metric", "description", "units", "value"], summary_rows)
    ws.sheet_state = "hidden"

    # One explicit result object for every unique (bias, direction) sweep.
    ws = wb.create_sheet("Sweep Results")
    sweep_rows: list[list[Any]] = []
    for result in metrics.get("sweep_results", []):
        identity = result.get("identity", {})
        fixed = [
            result.get("sweep_id"),
            identity.get("measurement_type"),
            identity.get("sweep_index"),
            identity.get("direction"),
            identity.get("bias_variable"),
            identity.get("bias_value_v"),
            result.get("n_points"),
        ]
        for section, values in result.items():
            if section in {"identity", "sweep_id", "n_points"}:
                continue
            if isinstance(values, dict):
                for metric, value in values.items():
                    if isinstance(value, (dict, list, tuple)):
                        value = "; ".join(map(str, value)) if isinstance(value, (list, tuple)) else str(value)
                    sweep_rows.append(fixed + [section, metric, value])
            elif section == "warnings":
                sweep_rows.append(fixed + ["quality", "warnings", "; ".join(map(str, values))])
            else:
                sweep_rows.append(fixed + ["result", section, values])
    write_table(
        ws,
        [
            "sweep_id", "measurement_type", "sweep_index", "direction",
            "bias_variable", "bias_value_v", "n_points", "section", "metric", "value",
        ],
        sweep_rows,
    )

    ws = wb.create_sheet("Parameters")
    parameter_rows = []
    geometry = metrics.get("device_geometry", {})
    sources = metrics.get("geometry_sources", {})
    for key in sorted(geometry):
        parameter_rows.append([key, geometry.get(key), sources.get(key, "unknown"),
                               sources.get(key) == "template_default"])
    write_table(ws, ["parameter", "value", "source", "provisional"], parameter_rows)

    ws = wb.create_sheet("Warnings")
    warning_rows = []
    for warning in metrics.get("parameter_warnings", []):
        warning_rows.append([warning.get("level", "warning"), warning.get("code", "parameter"),
                             warning.get("parameter"), warning.get("message")])
    for warning in (metrics.get("quality") or {}).get("flags", []):
        warning_rows.append([warning.get("level", "warning"), warning.get("code", "quality"),
                             None, warning.get("message")])
    write_table(ws, ["level", "code", "parameter", "message"], warning_rows)

    # Stable ASCII, flat, numeric table for Origin and scripted plotting.
    if analysis_settings.get("summary_config", {}).get("export_origin_import", False):
        ws = wb.create_sheet("Origin Import")
        origin_headers = ["segment_index", "sweep_direction", "bias_variable", "bias_level_v", "point_index"]
        processed_headers, origin_rows = segment_rows(segments)
        origin_headers.extend("".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_") for name in processed_headers[5:])
        write_table(ws, origin_headers, origin_rows)

    # Excel-native quick-look charts; the underlying raw/processed tables remain
    # the source of truth for independent plotting and calculations.
    ws_charts = wb.create_sheet("Charts")
    ws_charts["A1"] = "Charts use the complete processed/derivative tables. Filter those sheets for a single segment if needed."
    processed = wb["Processed Data"]
    processed_headers = [cell.value for cell in processed[1]]
    if sweep_var in processed_headers and drain_col in processed_headers and processed.max_row > 2:
        x_col = processed_headers.index(sweep_var) + 1
        y_col = processed_headers.index(drain_col) + 1
        chart = ScatterChart()
        chart.title = f"{drain_col} vs {sweep_var} (processed)"
        chart.x_axis.title, chart.y_axis.title = sweep_var, drain_col
        chart.series.append(Series(Reference(processed, min_col=y_col, min_row=2, max_row=processed.max_row),
                                   xvalues=Reference(processed, min_col=x_col, min_row=2, max_row=processed.max_row),
                                   title="Processed data"))
        ws_charts.add_chart(chart, "A3")
    derivatives = wb["Derivatives"]
    if derivatives.max_row > 2:
        chart = ScatterChart()
        chart.title = f"gm vs {sweep_var}"
        chart.x_axis.title, chart.y_axis.title = sweep_var, "gm (S)"
        chart.series.append(Series(Reference(derivatives, min_col=6, min_row=2, max_row=derivatives.max_row),
                                   xvalues=Reference(derivatives, min_col=5, min_row=2, max_row=derivatives.max_row),
                                   title="gm"))
        ws_charts.add_chart(chart, "J3")

    wb._sheets.remove(ws_charts)
    wb._sheets.insert(1, ws_charts)

    wb.save(prepare_write_path(output_path))
    wb.close()
    LOGGER.info("Excel data workbook: %s", output_path)

def write_tlm_excel(
    tlm_result: dict[str, Any],
    sample_devices: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """Write a per-TLM-group Excel report with raw and processed data.

    Sheets:
      - **Summary**: Source files used, TLM fit parameters, per-Lch table
      - **Raw Data**: All contributing device data (Lch, R_total, type, file)
      - **Processed Data**: Fitted R(L) curve points and residual analysis

    Requires ``openpyxl``; if unavailable, logs a warning and returns.
    """
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
        from openpyxl.worksheet.table import Table, TableStyleInfo
        from openpyxl.chart import ScatterChart, Series, Reference
    except ImportError:
        LOGGER.warning(
            "openpyxl not available — skipping TLM Excel report: %s",
            output_path,
        )
        return

    wb = openpyxl.Workbook()

    # ── Style definitions ───────────────────────────────────────────────
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )
    bold_font = Font(name="Calibri", size=11, bold=True)
    section_fill = PatternFill(start_color="D9E2F3", end_color="D9E2F3", fill_type="solid")

    def _write_header_row(ws, row, headers, start_col=1):
        for i, h in enumerate(headers, start_col):
            cell = ws.cell(row=row, column=i, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align
            cell.border = thin_border

    sample_id = tlm_result.get("sample_id", "unknown")

    # ═════════════════════════════════════════════════════════════════════
    # Sheet 1 — Summary
    # ═════════════════════════════════════════════════════════════════════
    ws_sum = wb.active
    ws_sum.title = "Summary"

    # Title
    ws_sum.cell(row=1, column=1, value=f"TLM Analysis — {sample_id}").font = Font(
        name="Calibri", size=14, bold=True)
    ws_sum.merge_cells("A1:D1")

    # Source files section
    row = 3
    cell = ws_sum.cell(row=row, column=1, value="Source Files")
    cell.font = Font(name="Calibri", size=12, bold=True)
    cell.fill = section_fill
    ws_sum.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)

    row += 1
    _write_header_row(ws_sum, row, ["File", "Lch (μm)", "R_total (Ω)", "Type"])
    row += 1

    for d in sorted(sample_devices, key=lambda x: x.get("channel_length_um", 0)):
        fname = Path(d.get("source_file", d.get("device_name", "?"))).name
        for col, val in enumerate(
            [fname, d.get("channel_length_um"), d.get("r_total_ohm"),
             d.get("measurement_type", "")], 1
        ):
            cell = ws_sum.cell(row=row, column=col, value=val)
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="center")
        row += 1

    # TLM parameters
    row += 1
    cell = ws_sum.cell(row=row, column=1, value="Fitted TLM Parameters")
    cell.font = Font(name="Calibri", size=12, bold=True)
    cell.fill = section_fill
    ws_sum.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)

    row += 1
    params = [
        ("Rc (Ω)", tlm_result.get("rc_ohm")),
        ("Rsh (Ω/□)", tlm_result.get("rsh_ohm_sq")),
        ("Film thickness (nm)", tlm_result.get("film_thickness_nm")),
        ("Film resistivity (Ω·cm)", tlm_result.get("rho_film_ohm_cm")),
        ("LT (μm)", tlm_result.get("lt_um")),
        ("ρc (Ω·cm²)", tlm_result.get("rhoc_ohm_cm2")),
        ("R²", tlm_result.get("r2")),
        ("W (μm)", tlm_result.get("width_um")),
        ("N devices", tlm_result.get("n_points")),
    ]
    for param_name, param_val in params:
        ck = ws_sum.cell(row=row, column=1, value=param_name)
        ck.font = bold_font
        ck.border = thin_border
        cv = ws_sum.cell(row=row, column=2, value=_fmt(param_val, 4))
        cv.border = thin_border
        cv.alignment = Alignment(horizontal="center")
        row += 1

    # Read/group conditions used for this fit.
    for key, value in tlm_result.get("group_values", {}).items():
        ck = ws_sum.cell(row=row, column=1, value=str(key))
        ck.font = bold_font
        ck.border = thin_border
        cv = ws_sum.cell(row=row, column=2, value=value)
        cv.border = thin_border
        row += 1

    # Per-Lch table
    row += 1
    cell = ws_sum.cell(row=row, column=1, value="Per-Lch Summary")
    cell.font = Font(name="Calibri", size=12, bold=True)
    cell.fill = section_fill
    ws_sum.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)

    row += 1
    _write_header_row(ws_sum, row, ["Lch (μm)", "R_total (Ω)", "N devices", "Devices"])
    row += 1

    lch_vals = tlm_result.get("lch_values", [])
    lch_stats = tlm_result.get("lch_stats", {})
    for lch, rtot in sorted(lch_vals, key=lambda x: x[0]):
        # Count how many devices contributed to this Lch
        lch_devs = [d for d in sample_devices
                     if abs(d.get("channel_length_um", 0) - lch) < 0.01]
        n_devs = len(lch_devs)
        dev_names = ", ".join(
            Path(d.get("source_file", d.get("device_name", "?"))).name
            for d in lch_devs
        )
        for col, val in enumerate([lch, rtot, n_devs, dev_names], 1):
            cell = ws_sum.cell(row=row, column=col, value=val)
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="center")
        row += 1

    ws_sum.column_dimensions["A"].width = 22
    ws_sum.column_dimensions["B"].width = 20
    ws_sum.column_dimensions["C"].width = 18
    ws_sum.column_dimensions["D"].width = 50

    # ═════════════════════════════════════════════════════════════════════
    # Sheet 2 — Raw Data
    # ═════════════════════════════════════════════════════════════════════
    ws_raw = wb.create_sheet("Raw Data")

    _write_header_row(ws_raw, 1,
                      ["Device", "Sample ID", "Lch (μm)", "R_total (Ω)",
                       "W (μm)", "Type", "Source File"])
    row = 2
    for d in sorted(sample_devices, key=lambda x: x.get("channel_length_um", 0)):
        vals = [
            d.get("device_name", ""),
            d.get("sample_id", ""),
            d.get("channel_length_um"),
            d.get("r_total_ohm"),
            d.get("channel_width_um"),
            d.get("measurement_type", ""),
            d.get("source_file", ""),
        ]
        for col, val in enumerate(vals, 1):
            cell = ws_raw.cell(row=row, column=col, value=val)
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="center")
        row += 1

    for i in range(1, 8):
        ws_raw.column_dimensions[get_column_letter(i)].width = 20
    ws_raw.freeze_panes = "A2"

    ws_read = wb.create_sheet("Read Conditions")
    read_headers = [
        "Device", "Requested Vg (V)", "Actual Vg used (V)", "Vg mismatch (V)",
        "Requested Vov (V)", "Actual Vov used (V)",
        "Requested gate field (MV/cm)", "Actual gate field (MV/cm)",
        "Requested overdrive field (MV/cm)", "Actual overdrive field (MV/cm)",
    ]
    _write_header_row(ws_read, 1, read_headers)
    for row, device in enumerate(sorted(
        sample_devices, key=lambda item: item.get("channel_length_um", 0)
    ), 2):
        values = [
            device.get("device_name", ""), device.get("requested_read_vg_v"),
            device.get("actual_read_vg_v"), device.get("read_vg_delta_v"),
            device.get("requested_overdrive_v"), device.get("actual_overdrive_v"),
            device.get("requested_gate_field_mv_cm"), device.get("actual_gate_field_mv_cm"),
            device.get("requested_overdrive_field_mv_cm"), device.get("actual_overdrive_field_mv_cm"),
        ]
        for column, value in enumerate(values, 1):
            ws_read.cell(row=row, column=column, value=value).border = thin_border
    for column in range(1, len(read_headers) + 1):
        ws_read.column_dimensions[get_column_letter(column)].width = 24
    ws_read.freeze_panes = "A2"

    # ═════════════════════════════════════════════════════════════════════
    # Sheet 3 — Processed Data
    # ═════════════════════════════════════════════════════════════════════
    ws_proc = wb.create_sheet("Processed Data")

    _write_header_row(ws_proc, 1,
                      ["Lch (μm)", "R_total (Ω)", "R_total×W (Ω·μm)",
                       "Fitted R_total×W (Ω·μm)", "Residual (Ω·μm)",
                       "Fitted R_total (Ω)"])

    slope = tlm_result.get("slope_ohm_per_um", 0)
    intercept = tlm_result.get("intercept_ohm", 0)
    width_um = tlm_result.get("width_um", 100.0)

    row = 2
    for lch, rtot in sorted(lch_vals, key=lambda x: x[0]):
        r_norm = rtot * width_um
        r_fit_norm = slope * lch + intercept
        residual_norm = r_norm - r_fit_norm
        r_fit = r_fit_norm / width_um if width_um and width_um > 0 else None
        for col, val in enumerate([lch, rtot, r_norm, r_fit_norm, residual_norm, r_fit], 1):
            cell = ws_proc.cell(row=row, column=col, value=val)
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="center")
        row += 1

    # Fit equation
    row += 1
    ws_proc.cell(row=row, column=1,
                 value=f"Fit: R_total×W = {slope:.4f}×Lch + {intercept:.4f} (Ω·μm)").font = bold_font

    for i in range(1, 7):
        ws_proc.column_dimensions[get_column_letter(i)].width = 18
    ws_proc.freeze_panes = "A2"

    for index, (sheet, max_data_row) in enumerate(
        ((ws_raw, ws_raw.max_row), (ws_proc, 1 + len(lch_vals))),
        1,
    ):
        if max_data_row > 1:
            ref = f"A1:{get_column_letter(sheet.max_column)}{max_data_row}"
            table = Table(displayName=f"TlmTable{index}", ref=ref)
            table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
            sheet.add_table(table)

    if ws_proc.max_row > 2:
        chart = ScatterChart()
        chart.title = "TLM fit: R_total×W vs channel length"
        chart.x_axis.title = "Lch (μm)"
        chart.y_axis.title = "R_total×W (Ω·μm)"
        last_data_row = 1 + len(lch_vals)
        xvalues = Reference(ws_proc, min_col=1, min_row=2, max_row=last_data_row)
        chart.series.append(Series(Reference(ws_proc, min_col=3, min_row=2, max_row=last_data_row), xvalues=xvalues, title="Measured"))
        chart.series.append(Series(Reference(ws_proc, min_col=4, min_row=2, max_row=last_data_row), xvalues=xvalues, title="Fitted"))
        ws_sum.add_chart(chart, "F2")

    # ── Save ───────────────────────────────────────────────────────────
    wb.save(prepare_write_path(output_path))
    wb.close()
    LOGGER.info("  → TLM Excel report: %s", output_path)
