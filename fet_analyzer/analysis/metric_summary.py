"""Canonical device metrics and preferred-sweep selection.

All report surfaces consume this module so Excel, CSV, statistics, and the
dashboard use the same metric definitions and selection semantics.
"""
from __future__ import annotations

from typing import Any

import numpy as np


METRIC_DEFINITIONS: list[dict[str, str]] = [
    {"key": "ion_ioff", "label": "Ion/Ioff — configured methods", "unit": "unitless"},
    {"key": "ion_ioff_log10", "label": "log10(Ion/Ioff)", "unit": "decades"},
    {"key": "ion_ioff_const_vg", "label": "Ion/Ioff — constant Vg or gate field", "unit": "unitless"},
    {"key": "ion_ioff_const_vg_log10", "label": "log10(Ion/Ioff) — constant Vg or gate field", "unit": "decades"},
    {"key": "ion_ioff_const_vov", "label": "Ion/Ioff — constant Vov or overdrive field", "unit": "unitless"},
    {"key": "ion_ioff_const_vov_log10", "label": "log10(Ion/Ioff) — constant Vov or overdrive field", "unit": "decades"},
    {"key": "ion_ioff_max", "label": "Ion/Ioff — maximum measured Ion", "unit": "unitless"},
    {"key": "ion_ioff_max_log10", "label": "log10(Ion/Ioff) — maximum measured Ion", "unit": "decades"},
    {"key": "ion_configured_a", "label": "Ion — configured method", "unit": "A"},
    {"key": "ion_configured_ua_per_um", "label": "Ion — configured method, width-normalized", "unit": "µA/µm"},
    {"key": "ion_max_a", "label": "Ion — maximum measured", "unit": "A"},
    {"key": "ion_max_ua_per_um", "label": "Ion — maximum measured, width-normalized", "unit": "µA/µm"},
    {"key": "ion_const_vov_a", "label": "Ion at constant Vov", "unit": "A"},
    {"key": "ion_const_vov_ua_per_um", "label": "Ion at constant Vov or overdrive field", "unit": "µA/µm"},
    {"key": "ion_const_vov_requested_v", "label": "Requested constant Vov", "unit": "V"},
    {"key": "ion_const_vov_v", "label": "Actual constant Vov used", "unit": "V"},
    {"key": "ion_const_vov_target_vg_v", "label": "Requested Vg = Vth + Vov", "unit": "V"},
    {"key": "ion_const_vov_actual_vg_v", "label": "Actual measured Vg used for Vov Ion", "unit": "V"},
    {"key": "ion_overdrive_field_requested_mv_cm", "label": "Requested overdrive field", "unit": "MV/cm"},
    {"key": "ion_overdrive_field_actual_mv_cm", "label": "Actual overdrive field used", "unit": "MV/cm"},
    {"key": "ion_const_vg_a", "label": "Ion at constant Vg", "unit": "A"},
    {"key": "ion_const_vg_ua_per_um", "label": "Ion at constant Vg or gate field", "unit": "µA/µm"},
    {"key": "ion_const_vg_requested_v", "label": "Requested constant Vg", "unit": "V"},
    {"key": "ion_const_vg_v", "label": "Actual measured Vg used", "unit": "V"},
    {"key": "ion_gate_field_requested_mv_cm", "label": "Requested nominal gate field", "unit": "MV/cm"},
    {"key": "ion_gate_field_actual_mv_cm", "label": "Actual nominal gate field used", "unit": "MV/cm"},
    {"key": "ioff_above_ig_a", "label": "Ioff above Ig criterion", "unit": "A"},
    {"key": "ioff_above_ig_ua_per_um", "label": "Ioff above Ig criterion, width-normalized", "unit": "µA/µm"},
    {"key": "ioff_min_a", "label": "Ioff — minimum measured", "unit": "A"},
    {"key": "ioff_min_ua_per_um", "label": "Ioff — minimum measured, width-normalized", "unit": "µA/µm"},
    {"key": "ioff_configured_ua_per_um", "label": "Ioff — configured method, width-normalized", "unit": "µA/µm"},
    {"key": "vth_v", "label": "Threshold voltage, Vth", "unit": "V"},
    {"key": "ss_min_mv_dec", "label": "SS — minimum valid ≥1 decade", "unit": "mV/dec"},
    {"key": "mobility_cm2_vs", "label": "Field-effect mobility", "unit": "cm²/V·s"},
    {"key": "gm_max_s", "label": "Maximum transconductance, gm,max", "unit": "S"},
    {"key": "gm_smoothing_mode", "label": "gm smoothing mode", "unit": ""},
    {"key": "gm_smoothing_window_points", "label": "gm peak-region smoothing window", "unit": "points"},
    {"key": "gm_smoothing_status", "label": "gm smoothing selection status", "unit": ""},
    {"key": "hysteresis_abs_v", "label": "Hysteresis — absolute", "unit": "V"},
    {"key": "hysteresis_signed_v", "label": "Hysteresis — reverse minus forward", "unit": "V"},
    {"key": "dibl_mv_v", "label": "DIBL", "unit": "mV/V"},
    {"key": "rout_ohm", "label": "Output resistance, Rout", "unit": "Ω"},
    {"key": "rout_fit_r2", "label": "Rout fit R²", "unit": "unitless"},
    {"key": "rc_ohm", "label": "Contact resistance, Rc (group-derived)", "unit": "Ω"},
    {"key": "rcw_ohm_um", "label": "Width-normalized contact resistance, RcW", "unit": "Ω·µm"},
    {"key": "rcw_kohm_um", "label": "Width-normalized contact resistance, RcW", "unit": "kΩ·µm"},
    {"key": "rho_film_ohm_cm", "label": "Semiconductor film resistivity", "unit": "Ω·cm"},
    {"key": "rhoc_ohm_cm2", "label": "Specific contact resistivity", "unit": "Ω·cm²"},
    {"key": "tlm_fit_r2", "label": "TLM fit R²", "unit": "unitless"},
    {"key": "gds_max_s", "label": "Maximum output conductance, gds,max", "unit": "S"},
    {"key": "leakage_ratio_max", "label": "Maximum |Ig|/|Id|", "unit": "unitless"},
    {"key": "quality_status", "label": "Quality status", "unit": ""},
    {"key": "warnings", "label": "Warnings", "unit": ""},
]

STATISTIC_METRICS = [
    item["key"] for item in METRIC_DEFINITIONS
    if item["key"] not in {
        "quality_status", "warnings", "ion_const_vov_v", "ion_const_vg_v",
        "ion_const_vov_requested_v", "ion_const_vov_target_vg_v",
        "ion_const_vov_actual_vg_v", "ion_overdrive_field_requested_mv_cm",
        "ion_overdrive_field_actual_mv_cm", "ion_const_vg_requested_v",
        "ion_gate_field_requested_mv_cm", "ion_gate_field_actual_mv_cm",
        "gm_smoothing_mode", "gm_smoothing_window_points", "gm_smoothing_status",
    }
]


def _finite(value: Any) -> float | None:
    if isinstance(value, (int, float)) and np.isfinite(value):
        return float(value)
    return None


def _ratio(ion: float | None, ioff: float | None) -> tuple[float | None, float | None]:
    if ion is None or ioff is None or ion <= 0 or ioff <= 0:
        return None, None
    ratio = float(ion / ioff)
    return ratio, float(np.log10(ratio))


def choose_ion(current: dict[str, Any], method: str | None) -> tuple[float | None, str, str | None]:
    """Return configured Ion, normalized method name, and fallback note."""
    requested = str(method or "maximum_measured").lower()
    aliases = {
        "max": "maximum_measured", "maximum": "maximum_measured",
        "maximum_measured_abs_id": "maximum_measured",
        "constant_vg": "constant_vg", "fixed_vg": "constant_vg",
        "constant_gate_field": "constant_vg", "fixed_gate_field": "constant_vg",
        "constant_vov": "constant_vov", "fixed_overdrive": "constant_vov",
        "constant_overdrive_field": "constant_vov", "fixed_overdrive_field": "constant_vov",
        "max_common_overdrive": "max_common_overdrive", "maximum_common_vov": "max_common_overdrive",
    }
    normalized = aliases.get(requested, requested)
    fields = {
        "maximum_measured": "ion_max_a",
        "constant_vg": "ion_const_vg_a",
        "constant_vov": "ion_const_vov_a",
        "max_common_overdrive": "ion_const_vov_a",
    }
    value = _finite(current.get(fields.get(normalized, "ion_max_a")))
    if value is not None:
        return value, normalized, None
    fallback = _finite(current.get("ion_max_a"))
    note = None if normalized == "maximum_measured" else f"{normalized} unavailable; used maximum_measured"
    return fallback, "maximum_measured" if fallback is not None else normalized, note


def choose_ioff(current: dict[str, Any], method: str | None) -> tuple[float | None, str, str | None]:
    requested = str(method or "minimum_above_ig").lower()
    above = requested in {"minimum_above_ig", "minimum_above_gate_leakage", "leakage_aware"}
    key = "ioff_above_ig_a" if above else "ioff_min_a"
    value = _finite(current.get(key))
    normalized = "minimum_above_ig" if above else "minimum_measured"
    if value is not None:
        return value, normalized, None
    fallback = _finite(current.get("ioff_min_a"))
    note = None if not above else "minimum_above_ig unavailable; used minimum_measured"
    return fallback, "minimum_measured" if fallback is not None else normalized, note


def transfer_sweep_metrics(result: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    identity = result.get("identity", {})
    on_off = result.get("on_off", {})
    current = result.get("current_summary", {})
    values = {
        "ion_max_a": _finite(on_off.get("ion_a")) or _finite(current.get("id_max_a")),
        "ion_const_vg_a": _finite(current.get("ion_const_vg_a")),
        "ion_const_vg_v": _finite(current.get("ion_const_vg_v")),
        "ion_const_vg_requested_v": _finite(current.get("ion_const_vg_requested_v")),
        "ion_gate_field_requested_mv_cm": _finite(current.get("ion_gate_field_requested_mv_cm")),
        "ion_gate_field_actual_mv_cm": _finite(current.get("ion_gate_field_actual_mv_cm")),
        "ion_const_vov_a": _finite(current.get("ion_const_vov_a")),
        "ion_const_vov_v": _finite(current.get("ion_const_vov_v")),
        "ion_const_vov_requested_v": _finite(current.get("ion_const_vov_requested_v")),
        "ion_const_vov_target_vg_v": _finite(current.get("ion_const_vov_target_vg_v")),
        "ion_const_vov_actual_vg_v": _finite(current.get("ion_const_vov_actual_vg_v")),
        "ion_overdrive_field_requested_mv_cm": _finite(current.get("ion_overdrive_field_mv_cm")),
        "ion_overdrive_field_actual_mv_cm": _finite(current.get("ion_overdrive_field_actual_mv_cm")),
        "ioff_above_ig_a": _finite(on_off.get("ioff_a")),
        "ioff_min_a": _finite(current.get("id_min_a")),
    }
    ion, ion_method, ion_note = choose_ion(values, settings.get("ion_method_configured") or settings.get("ion_method"))
    ioff, ioff_method, ioff_note = choose_ioff(values, settings.get("ioff_method_configured") or settings.get("ioff_method"))
    width_um = _finite(settings.get("channel_width_um"))
    def normalized(value: Any) -> float | None:
        return (
            float(value) * 1e6 / width_um
            if value is not None and width_um is not None and width_um > 0 else None
        )
    method_key = str(settings.get("ion_method_configured") or settings.get("ion_method") or "").lower()
    report_fixed_vg = bool(settings.get("report_ion_at_fixed_vg", False)) or method_key in {
        "fixed_vg", "constant_vg", "fixed_gate_field", "constant_gate_field",
    }
    report_fixed_vov = bool(settings.get("report_ion_at_fixed_overdrive", False)) or method_key in {
        "fixed_overdrive", "constant_overdrive", "fixed_overdrive_field",
        "constant_overdrive_field", "max_common_overdrive", "maximum_common_vov",
    }
    ratio = ion / ioff if ion and ioff and ion > 0 and ioff > 0 else None
    ratio_vg, ratio_vg_log = _ratio(values.get("ion_const_vg_a"), ioff)
    ratio_vov, ratio_vov_log = _ratio(values.get("ion_const_vov_a"), ioff)
    ratio_max, ratio_max_log = _ratio(values.get("ion_max_a"), ioff)
    warnings = list(result.get("warnings", []))
    warnings.extend(note for note in (ion_note, ioff_note) if note)
    smoothing = result.get("gm", {}).get("smoothing", {})
    values.update({
        "sweep_id": result.get("sweep_id"),
        "direction": identity.get("direction"),
        "bias_variable": identity.get("bias_variable"),
        "bias_value_v": _finite(identity.get("bias_value_v")),
        "measured_vd_v": _finite(identity.get("measured_vd_v")),
        "measured_vs_v": _finite(identity.get("measured_vs_v")),
        "measured_vds_v": (
            _finite(identity.get("measured_vds_v"))
            if _finite(identity.get("measured_vds_v")) is not None
            else _finite(identity.get("bias_value_v"))
        ),
        "vds_reference": identity.get("vds_reference"),
        "measured_vds_spread_v": _finite(identity.get("measured_vds_spread_v")),
        "measured_vds_n": identity.get("measured_vds_n"),
        "ion_configured_a": ion,
        "ion_configured_ua_per_um": normalized(ion),
        "ion_method_used": ion_method,
        "ioff_configured_a": ioff,
        "ioff_configured_ua_per_um": normalized(ioff),
        "ioff_method_used": ioff_method,
        "ion_ioff": ratio,
        "ion_ioff_log10": float(np.log10(ratio)) if ratio and ratio > 0 else None,
        "ion_ioff_const_vg": ratio_vg,
        "ion_ioff_const_vg_log10": ratio_vg_log,
        "ion_ioff_const_vov": ratio_vov,
        "ion_ioff_const_vov_log10": ratio_vov_log,
        "ion_ioff_max": ratio_max,
        "ion_ioff_max_log10": ratio_max_log,
        "vth_v": _finite(result.get("vth", {}).get("vth_v")),
        "ss_min_mv_dec": _finite(result.get("subthreshold_swing", {}).get("ss_mv_dec")),
        "ss_decades": _finite(result.get("subthreshold_swing", {}).get("ss_decades")),
        "mobility_cm2_vs": _finite(result.get("mobility", {}).get("mobility_cm2_vs")),
        "mobility_metric_eligible": result.get("mobility", {}).get("metric_eligible"),
        "mobility_bias_homogeneous": result.get("mobility", {}).get("bias_homogeneous"),
        "gm_max_s": _finite(result.get("gm", {}).get("gm_max_s")),
        "gm_metric_eligible": result.get("gm", {}).get("metric_eligible"),
        "gm_bias_homogeneous": result.get("gm", {}).get("bias_homogeneous"),
        "gm_peak_position": result.get("gm", {}).get("gm_peak_position"),
        "gm_peak_support_vg_v": result.get("gm", {}).get("gm_peak_support_vg_v"),
        "gm_smoothing_mode": smoothing.get("mode"),
        "gm_smoothing_window_points": smoothing.get("peak_window_points"),
        "gm_smoothing_status": smoothing.get("peak_selection_status"),
        "leakage_ratio_max": _finite(current.get("leakage_ratio_max")),
        "warnings": "; ".join(warnings),
    })
    for key in ("ion_max_a", "ion_const_vg_a", "ion_const_vov_a", "ioff_above_ig_a", "ioff_min_a"):
        values[key.removesuffix("_a") + "_ua_per_um"] = normalized(values.get(key))
    if not report_fixed_vg:
        for key in list(values):
            if key.startswith("ion_const_vg_") or key.startswith("ion_gate_field_"):
                values[key] = None
    if not report_fixed_vov:
        for key in list(values):
            if key.startswith("ion_const_vov_") or key.startswith("ion_overdrive_field_"):
                values[key] = None
    return values


def output_sweep_metrics(result: dict[str, Any]) -> dict[str, Any]:
    identity = result.get("identity", {})
    return {
        "sweep_id": result.get("sweep_id"), "direction": identity.get("direction"),
        "bias_variable": identity.get("bias_variable"),
        "bias_value_v": _finite(identity.get("bias_value_v")),
        "rout_ohm": _finite(result.get("resistance_linear_fit_ohm")),
        "rout_fit_r2": _finite(result.get("linear_fit_r2")),
        "gds_max_s": _finite(result.get("gds_max_s")),
        "warnings": "; ".join(result.get("warnings", [])),
    }


def select_preferred_sweep(
    sweeps: list[dict[str, Any]], config: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Select one sweep deterministically and return an auditable reason."""
    if not sweeps:
        return None, "no usable sweeps"
    cfg = (config or {}).get("summary", config or {})
    preferred_direction = str(cfg.get("preferred_direction", "forward")).lower()
    preferred_vd = float(cfg.get("preferred_vd_v", 0.1))
    tolerance = float(cfg.get("preferred_vd_tolerance_v", 0.001))
    ranked = []
    for index, sweep in enumerate(sweeps):
        direction = str(sweep.get("direction", "")).lower()
        bias = _finite(sweep.get("bias_value_v"))
        direction_rank = 0 if direction == preferred_direction else 1
        distance = abs(abs(bias) - abs(preferred_vd)) if bias is not None else float("inf")
        ranked.append(((direction_rank, 0 if distance <= tolerance else 1, distance, index), sweep))
    rank, selected = min(ranked, key=lambda item: item[0])
    exact = rank[1] == 0
    direction_ok = rank[0] == 0
    measured = _finite(selected.get("measured_vds_v"))
    if measured is None:
        measured = _finite(selected.get("bias_value_v"))
    selected_text = "measured Vds unavailable" if measured is None else f"selected measured Vds={measured:g} V"
    reason = (
        f"preferred {preferred_direction} sweep; requested |Vds|={preferred_vd:g} V, {selected_text}"
        if exact and direction_ok else
        f"Fallback to {selected.get('direction') or 'available'} sweep; requested |Vds|={preferred_vd:g} V, {selected_text}"
    )
    return selected, reason


def _best_remarks(metric: str, sweep: dict[str, Any]) -> str:
    direction = str(sweep.get("direction") or "unknown")
    measured = _finite(sweep.get("measured_vds_v"))
    if measured is None:
        measured = _finite(sweep.get("bias_value_v"))
    bias = "measured Vds unavailable" if measured is None else f"measured Vds={measured:g} V"
    sweep_id = str(sweep.get("sweep_id") or "unidentified sweep")
    if metric == "hysteresis_abs_v":
        prefix = f"Paired forward/reverse transfer sweeps at {bias}; source sweep {sweep_id}."
    else:
        prefix = f"{direction.capitalize()} transfer sweep {sweep_id} at {bias}."
    condition = ""
    if metric in {"ion_const_vg_a", "ion_ioff_const_vg"}:
        condition = (
            f" Constant gate condition: requested Vg={sweep.get('ion_const_vg_requested_v')} V, "
            f"actual measured Vg={sweep.get('ion_const_vg_v')} V, "
            f"requested/actual field={sweep.get('ion_gate_field_requested_mv_cm')}/"
            f"{sweep.get('ion_gate_field_actual_mv_cm')} MV/cm."
        )
    elif metric in {"ion_const_vov_a", "ion_ioff_const_vov"}:
        condition = (
            f" Constant overdrive condition: requested/actual Vov="
            f"{sweep.get('ion_const_vov_requested_v')}/{sweep.get('ion_const_vov_v')} V, "
            f"actual measured Vg={sweep.get('ion_const_vov_actual_vg_v')} V."
        )
    warnings = str(sweep.get("warnings") or "").strip()
    return prefix + condition + (f" Warnings: {warnings}." if warnings else " No sweep warnings.")


def build_best_results(sweeps: list[dict[str, Any]], global_summary: dict[str, Any]) -> dict[str, Any]:
    """Select metric-aware best values within one source file, retaining provenance."""
    directions = {
        "ion_configured_a": "max", "ion_const_vg_a": "max", "ion_const_vov_a": "max",
        "ion_max_a": "max", "ion_ioff": "max", "ion_ioff_const_vg": "max",
        "ion_ioff_const_vov": "max", "ion_ioff_max": "max", "mobility_cm2_vs": "max",
        "gm_max_s": "max", "ioff_configured_a": "min", "ss_min_mv_dec": "min",
        "hysteresis_abs_v": "min",
    }
    results: dict[str, Any] = {}
    for metric, direction in directions.items():
        excluded: list[dict[str, Any]] = []
        candidates = []
        for sweep in sweeps:
            value = _finite(sweep.get(metric))
            if value is None:
                continue
            has_mobility_validity = (
                "mobility_metric_eligible" in sweep
                or "mobility_bias_homogeneous" in sweep
            )
            if metric == "mobility_cm2_vs" and has_mobility_validity and (
                sweep.get("mobility_metric_eligible") is not True
                or sweep.get("mobility_bias_homogeneous") is not True
            ):
                excluded.append({
                    "sweep_id": sweep.get("sweep_id"), "value": value,
                    "reason": "mobility candidate is not bias-homogeneous and metric-eligible",
                })
                continue
            if metric == "gm_max_s" and (
                sweep.get("gm_metric_eligible") is False
                or sweep.get("gm_bias_homogeneous") is False
            ):
                excluded.append({
                    "sweep_id": sweep.get("sweep_id"), "value": value,
                    "reason": "gm candidate is not bias-homogeneous and metric-eligible",
                })
                continue
            candidates.append((value, sweep))
        if excluded:
            results[f"{metric}_excluded_candidates"] = excluded
        if not candidates:
            continue
        value, sweep = (max(candidates, key=lambda item: item[0]) if direction == "max"
                        else min(candidates, key=lambda item: item[0]))
        results[metric] = {
            "value": value,
            "selection": direction,
            "sweep_id": sweep.get("sweep_id"),
            "sweep_type": "transfer",
            "direction": "paired forward/reverse" if metric == "hysteresis_abs_v" else sweep.get("direction"),
            "measured_vds_v": sweep.get("measured_vds_v", sweep.get("bias_value_v")),
            "warnings": sweep.get("warnings"),
            "remarks": _best_remarks(metric, sweep),
        }
    vth = [(float(sweep["vth_v"]), sweep) for sweep in sweeps if _finite(sweep.get("vth_v")) is not None]
    if vth:
        low, high = min(vth, key=lambda item: item[0]), max(vth, key=lambda item: item[0])
        results["vth_v_range"] = {
            "min": low[0], "max": high[0], "range": high[0] - low[0],
            "min_sweep_id": low[1].get("sweep_id"), "max_sweep_id": high[1].get("sweep_id"),
            "min_measured_vds_v": low[1].get("measured_vds_v", low[1].get("bias_value_v")),
            "max_measured_vds_v": high[1].get("measured_vds_v", high[1].get("bias_value_v")),
            "remarks": (
                f"Vth minimum from {low[1].get('direction')} sweep {low[1].get('sweep_id')} at "
                f"measured Vds={low[1].get('measured_vds_v', low[1].get('bias_value_v'))} V; "
                f"maximum from {high[1].get('direction')} sweep {high[1].get('sweep_id')} at "
                f"measured Vds={high[1].get('measured_vds_v', high[1].get('bias_value_v'))} V."
            ),
        }
    if _finite(global_summary.get("dibl_mv_v")) is not None:
        results["dibl_mv_v"] = {
            "value": float(global_summary["dibl_mv_v"]), "selection": "file-level fit",
            "remarks": "File-level DIBL fit across the valid measured |Vds| levels; see DIBL diagnostics for inputs and fit status.",
        }
    return results


def build_device_summary(metrics: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = dict(metrics.get("analysis_settings", {}))
    if not settings and config:
        transfer_cfg = config.get("transfer", config)
        settings.update(transfer_cfg)
        settings["ion_method_configured"] = transfer_cfg.get("ion_method")
        settings["ioff_method_configured"] = transfer_cfg.get("ioff_method")
    settings.setdefault(
        "channel_width_um", metrics.get("device_geometry", {}).get("channel_width_um")
    )
    transfer = [transfer_sweep_metrics(item, settings) for item in metrics.get("sweep_results", [])
                if item.get("identity", {}).get("measurement_type") == "transfer"]
    output = [output_sweep_metrics(item) for item in metrics.get("sweep_results", [])
              if item.get("identity", {}).get("measurement_type") == "output"]
    hysteresis = metrics.get("per_bias_hysteresis", {})
    for sweep in transfer:
        bias = sweep.get("bias_value_v")
        candidates = [str(bias), str(round(bias, 6))] if bias is not None else ["unbiased"]
        item = next((hysteresis.get(key) for key in candidates if isinstance(hysteresis.get(key), dict)), {})
        sweep["hysteresis_abs_v"] = _finite(item.get("delta_v_abs"))
        sweep["hysteresis_signed_v"] = _finite(item.get("delta_v"))
    sweeps = transfer or output
    if transfer:
        preferred, reason = select_preferred_sweep(transfer, config or settings.get("summary_config", {}))
    else:
        preferred = max(output, key=lambda item: item.get("rout_fit_r2") or -1, default=None)
        reason = "best valid Rout fit R²" if preferred else "no usable sweeps"
    summary = dict(preferred or {})
    global_summary = metrics.get("summary", {})
    summary.update({
        "dibl_mv_v": _finite(global_summary.get("dibl_mv_v")),
        "hysteresis_abs_v": _finite(global_summary.get("hysteresis_v_max")),
        "quality_status": (metrics.get("quality") or {}).get("status", "unknown"),
        "selection_reason": reason,
        "preferred_direction": (preferred or {}).get("direction"),
        "preferred_bias_v": (preferred or {}).get("bias_value_v"),
    })
    return {
        "preferred": summary,
        "segments": sweeps,
        "best": build_best_results(transfer, global_summary) if transfer else {},
        "definitions": METRIC_DEFINITIONS,
    }
