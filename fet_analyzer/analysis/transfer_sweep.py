"""Standalone analysis of one transfer sweep at one drain bias."""
from __future__ import annotations

from typing import Any

import numpy as np

from fet_analyzer.analysis.extraction import (
    C,
    extract_field_effect_mobility,
    extract_vth_constant_current,
    extract_vth_peak_gm_tangent,
)
from fet_analyzer.analysis.numerics import (
    compute_gm_with_diagnostics, compute_on_off, compute_ss,
    nearest_abs_current_at_voltage,
)
from fet_analyzer.analysis.ion_bias import resolve_ion_bias
from fet_analyzer.analysis.segmentation import measured_vds_profile
from fet_analyzer.analysis.sweep_models import SweepIdentity, TransferSweepResult


def analyze_transfer_sweep(
    segment: Any,
    classification: dict[str, Any],
    config: dict[str, Any],
    device_params: dict[str, Any],
    *,
    source_filename: str = "",
    sweep_index: int = 0,
) -> TransferSweepResult:
    """Compute every single-sweep transfer metric without plotting."""
    transfer_cfg = config.get("transfer", {})
    sweep_var = segment.sweep_variable
    drain_col = classification.get("drain_current_raw_column", "Id")
    gate_col = classification.get("gate_leakage_column")
    vg = list(segment.data.get(sweep_var, segment.sweep_values))
    current = list(segment.data.get(drain_col, []))
    leakage = list(segment.data.get(gate_col, [])) if gate_col else None
    vds_tolerance = float(transfer_cfg.get("vds_segmentation_tolerance_v", 1e-6))
    vds_profile = measured_vds_profile(segment.data, vds_tolerance)
    measured_vds = getattr(segment, "measured_vds_v", None)
    # Compatibility for already-segmented callers that retain Vds only in
    # segment identity.  Raw terminal columns, when present, always win and
    # are independently validated above.
    if vds_profile["source"] is None and measured_vds is not None:
        vds_profile.update({
            "source": getattr(segment, "vds_reference", None) or "segment identity",
            "measured_vds_v": float(measured_vds),
            "min_v": float(measured_vds), "max_v": float(measured_vds),
            "spread_v": 0.0, "valid_n": len(vg), "missing_n": 0,
            "bias_homogeneous": True, "reason": None,
        })
    vds = vds_profile["measured_vds_v"]
    bias_homogeneous = bool(vds_profile["bias_homogeneous"])
    gm_result = compute_gm_with_diagnostics(vg, current, transfer_cfg)
    gm_vg = gm_result["vg"]
    gm_values = list(gm_result["gm_for_metrics"])
    if not bias_homogeneous:
        gm_values = [float("nan")] * len(gm_values)
        gm_result["smoothing"]["metric_eligible"] = False
        gm_result["smoothing"]["peak_selection_status"] = "suppressed_mixed_vds"
    finite = np.isfinite(np.asarray(gm_values, dtype=float))
    peak_index = int(np.nanargmax(np.abs(gm_values))) if finite.any() else None
    peak_position = None
    peak_support_vg: list[float] = []
    if peak_index is not None:
        if peak_index == 1:
            peak_position = "near_lower_boundary"
        elif peak_index == len(gm_vg) - 2:
            peak_position = "near_upper_boundary"
        else:
            peak_position = "interior"
        if 0 < peak_index < len(gm_vg) - 1:
            peak_support_vg = [float(value) for value in gm_vg[peak_index - 1:peak_index + 2]]
    gm = {
        "gm_max_s": abs(float(gm_values[peak_index])) if peak_index is not None else None,
        "gm_max_vg": float(gm_vg[peak_index]) if peak_index is not None else None,
        "gm_peak_index": peak_index,
        "gm_peak_position": peak_position,
        "gm_peak_distance_from_lower_boundary_steps": peak_index,
        "gm_peak_distance_from_upper_boundary_steps": (
            len(gm_vg) - 1 - peak_index if peak_index is not None else None
        ),
        "gm_peak_support_vg_v": peak_support_vg,
        "gm_peak_support_vds_v": (
            [float(vds)] * len(peak_support_vg) if vds is not None else []
        ),
        "gm_peak_support_vds_spread_v": vds_profile["spread_v"],
        "bias_homogeneous": bias_homogeneous,
        "metric_eligible": bool(peak_index is not None and bias_homogeneous),
        "vds_profile": {key: value for key, value in vds_profile.items() if key != "values_v"},
        "vg_v": gm_result["vg"],
        "gm_display_s": gm_result["gm"],
        "gm_metric_s": gm_values,
        "smoothing": gm_result["smoothing"],
    }
    method = transfer_cfg.get("vth_method", "peak_gm_tangent")
    if method == "constant_current":
        vth = extract_vth_constant_current(
            vg,
            current,
            i_target_a_per_um=float(transfer_cfg.get("constant_current_value", 1e-7)),
            width_um=float(device_params.get("channel_width_um", 100.0)),
        )
    elif gm_result["smoothing"]["metric_eligible"] and bias_homogeneous:
        vth = extract_vth_peak_gm_tangent(
            vg,
            current,
            gm=gm_values or None,
            vg_gm=gm_vg or None,
            tangent_window_v=float(transfer_cfg.get("tangent_window_v", 2.0)),
            tangent_min_points=int(transfer_cfg.get("tangent_min_points", 5)),
            vds=vds if vds is not None else 0.0,
            vds_correction=bool(transfer_cfg.get("vth_vds_correction", True)) and vds is not None,
        )
    else:
        vth = {
            "vth_v": None,
            "vth_method": method,
            "warnings": [
                f"gm-dependent Vth suppressed because {vds_profile['reason']}"
                if not bias_homogeneous else
                "gm-dependent Vth suppressed because adaptive smoothing was unavailable"
            ],
        }
    width = float(device_params.get("channel_width_um", 100.0))
    length = device_params.get("channel_length_um")
    cox = device_params.get("cox_f_per_cm2")
    if cox is None:
        tox_nm = float(device_params.get("oxide_thickness_nm", 90.0))
        epsilon_r = float(device_params.get("dielectric_constant", 3.9))
        cox = C * epsilon_r / (tox_nm * 1e-7)
    if (
        gm["gm_max_s"] is not None and length is not None and vds is not None
        and bias_homogeneous
    ):
        mobility = extract_field_effect_mobility(
            gm["gm_max_s"], float(cox), width, float(length), vds
        )
        mobility.update({
            "metric_eligible": True,
            "bias_homogeneous": True,
            "measured_vds_v": vds,
            "measured_vds_spread_v": vds_profile["spread_v"],
            "gm_max_s": gm["gm_max_s"],
            "gm_max_vg": gm["gm_max_vg"],
            "channel_width_um": width,
            "channel_length_um": float(length),
            "cox_f_per_cm2": float(cox),
        })
    else:
        reason = (
            vds_profile["reason"] if not bias_homogeneous else
            "Measured Vds unavailable" if vds is None else
            "gm or channel length unavailable"
        )
        mobility = {
            "mobility_cm2_vs": None,
            "method": "field_effect",
            "metric_eligible": False,
            "bias_homogeneous": bias_homogeneous,
            "measured_vds_v": vds,
            "measured_vds_spread_v": vds_profile["spread_v"],
            "warnings": [f"{reason}; mobility suppressed"],
        }
    ss = compute_ss(
        vg,
        current,
        noise_floor_a=float(
            device_params.get(
                "noise_floor_a", transfer_cfg.get("noise_floor_a", 1e-13)
            )
        ),
        vg_range_v=tuple(transfer_cfg["ss_vg_range_v"])
        if transfer_cfg.get("ss_vg_range_v") else None,
        gate_leakage_values=leakage,
        leakage_factor=float(transfer_cfg.get("ss_leakage_factor", 1.0)),
        require_above_gate_leakage=bool(
            transfer_cfg.get("ss_require_above_gate_leakage", True)
        ),
        polarity=device_params.get("polarity"),
    )
    on_off = compute_on_off(
        current,
        leakage,
        leakage_factor=float(transfer_cfg.get("ioff_leakage_factor", 3.0)),
    )
    finite_current = np.abs(np.asarray(current, dtype=float))
    finite_current = finite_current[np.isfinite(finite_current)]
    leakage_ratio_max = None
    if leakage is not None:
        leakage_values = np.abs(np.asarray(leakage, dtype=float))
        drain_values = np.abs(np.asarray(current, dtype=float))
        count = min(len(leakage_values), len(drain_values))
        valid_ratio = (
            np.isfinite(leakage_values[:count])
            & np.isfinite(drain_values[:count])
            & (drain_values[:count] > 0)
        )
        if valid_ratio.any():
            leakage_ratio_max = float(np.max(
                leakage_values[:count][valid_ratio] / drain_values[:count][valid_ratio]
            ))
    current_summary = {
        "id_max_a": float(np.max(finite_current)) if len(finite_current) else None,
        "id_min_a": float(np.min(finite_current)) if len(finite_current) else None,
        "leakage_ratio_max": leakage_ratio_max,
    }
    ion_bias = resolve_ion_bias(config, device_params)
    constant_vg = ion_bias["fixed_vg_v"]
    constant_vov = ion_bias["overdrive_v"]
    vth_value = vth.get("vth_v")
    vg_read = nearest_abs_current_at_voltage(vg, current, constant_vg)
    requested_vov_vg = (
        float(vth_value) + float(constant_vov)
        if vth_value is not None and constant_vov is not None else None
    )
    vov_read = nearest_abs_current_at_voltage(vg, current, requested_vov_vg)
    tox_nm = ion_bias["oxide_thickness_nm"]
    field_scale = float(tox_nm) * 0.1 if tox_nm is not None and float(tox_nm) > 0 else None
    actual_vov = (
        float(vov_read["actual_v"]) - float(vth_value)
        if vov_read["actual_v"] is not None and vth_value is not None else None
    )
    current_summary.update({
        "ion_const_vg_requested_v": vg_read["requested_v"],
        "ion_const_vg_v": vg_read["actual_v"],
        "ion_const_vg_actual_v": vg_read["actual_v"],
        "ion_const_vg_delta_v": vg_read["delta_v"],
        "ion_const_vg_equidistant_tie": vg_read["equidistant_tie"],
        "ion_const_vg_candidate_voltages_v": vg_read["candidate_voltages_v"],
        "ion_const_vg_selection_reason": vg_read["selection_reason"],
        "ion_const_vg_a": vg_read["current_a"],
        "ion_gate_field_requested_mv_cm": ion_bias["gate_field_mv_cm"],
        "ion_gate_field_actual_mv_cm": (
            float(vg_read["actual_v"]) / field_scale
            if vg_read["actual_v"] is not None and field_scale else None
        ),
        "ion_fixed_vg_source": ion_bias["fixed_vg_source"],
        "ion_const_vov_requested_v": float(constant_vov) if constant_vov is not None else None,
        "ion_const_vov_v": actual_vov,
        "ion_const_vov_actual_v": actual_vov,
        "ion_const_vov_target_vg_v": requested_vov_vg,
        "ion_const_vov_actual_vg_v": vov_read["actual_v"],
        "ion_const_vov_delta_vg_v": vov_read["delta_v"],
        "ion_const_vov_equidistant_tie": vov_read["equidistant_tie"],
        "ion_const_vov_candidate_voltages_v": vov_read["candidate_voltages_v"],
        "ion_const_vov_selection_reason": vov_read["selection_reason"],
        "ion_const_vov_a": vov_read["current_a"],
        "ion_overdrive_input_v": ion_bias["overdrive_input_v"],
        "ion_overdrive_field_mv_cm": ion_bias["overdrive_field_mv_cm"],
        "ion_overdrive_field_actual_mv_cm": (
            actual_vov / field_scale if actual_vov is not None and field_scale else None
        ),
        "ion_oxide_thickness_nm": ion_bias["oxide_thickness_nm"],
        "ion_overdrive_source": ion_bias["overdrive_source"],
    })
    warnings: list[str] = list(ion_bias["warnings"])
    if vds is None:
        warnings.append(
            "Measured Vds unavailable; no configured or assumed drain bias was substituted"
        )
    elif not bias_homogeneous:
        warnings.append(
            f"gm-dependent Vth and mobility suppressed: {vds_profile['reason']}"
        )
    warnings.extend(gm_result["smoothing"].get("warnings", []))
    finite_vg = np.asarray(vg, dtype=float)
    finite_vg = finite_vg[np.isfinite(finite_vg)]
    if len(finite_vg):
        if vg_read.get("equidistant_tie"):
            candidates = ", ".join(f"{value:g}" for value in vg_read["candidate_voltages_v"])
            warnings.append(
                f"Requested fixed Vg={float(vg_read['requested_v']):g} V was equidistant "
                f"from measured Vg values [{candidates}] V; conservatively used "
                f"Vg={float(vg_read['actual_v']):g} V with the lower |Id|"
            )
        elif vg_read["delta_v"] is not None and not vg_read["exact"]:
            warnings.append(
                f"Requested fixed Vg={float(vg_read['requested_v']):g} V was unavailable; "
                f"used nearest measured Vg={float(vg_read['actual_v']):g} V"
            )
        if vov_read.get("equidistant_tie"):
            candidates = ", ".join(f"{value:g}" for value in vov_read["candidate_voltages_v"])
            warnings.append(
                f"Requested Vth+Vov gate voltage={float(vov_read['requested_v']):g} V was "
                f"equidistant from measured Vg values [{candidates}] V; conservatively used "
                f"Vg={float(vov_read['actual_v']):g} V with the lower |Id|"
            )
        elif vov_read["delta_v"] is not None and not vov_read["exact"]:
            warnings.append(
                f"Requested Vth+Vov gate voltage={float(vov_read['requested_v']):g} V was unavailable; "
                f"used nearest measured Vg={float(vov_read['actual_v']):g} V"
            )
    for section in (vth, mobility, ss, on_off):
        warnings.extend(str(item) for item in section.get("warnings", []))
    identity = SweepIdentity(
        source_filename=source_filename,
        sweep_index=sweep_index,
        measurement_type="transfer",
        direction=segment.direction,
        sweep_variable=sweep_var,
        bias_variable=segment.bias_variable,
        bias_value_v=segment.bias_level,
        measured_vd_v=getattr(segment, "measured_vd_v", None),
        measured_vs_v=getattr(segment, "measured_vs_v", None),
        measured_vds_v=vds,
        vds_reference=vds_profile["source"],
        measured_vds_spread_v=vds_profile["spread_v"],
        measured_vds_n=vds_profile["valid_n"],
    )
    return TransferSweepResult(
        identity=identity,
        n_points=len(vg),
        vth=vth,
        mobility=mobility,
        subthreshold_swing=ss,
        on_off=on_off,
        gm=gm,
        current_summary=current_summary,
        warnings=warnings,
    )


def analyze_transfer_sweeps(
    segments: list[Any],
    classification: dict[str, Any],
    config: dict[str, Any],
    device_params: dict[str, Any],
) -> list[TransferSweepResult]:
    """Analyze every unique forward/reverse and Vds segment in one file."""
    source = str(classification.get("source_filename", ""))
    return [
        analyze_transfer_sweep(
            segment,
            classification,
            config,
            device_params,
            source_filename=source,
            sweep_index=index,
        )
        for index, segment in enumerate(segments)
    ]
