"""Batch-level maximum-common-overdrive Ion resolution."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np

from fet_analyzer.analysis.numerics import interpolate_abs_current_at_voltage
from fet_analyzer.analysis.metric_summary import build_device_summary


def _group_key(record: dict[str, Any], keys: list[str]) -> tuple[str, ...]:
    info = record.get("classification", {}).get("filename_info", {})
    device = record.get("device_params", {})
    values = {**info, **device}
    return tuple(str(values.get(key, "unknown")) for key in keys)


def _preferred_transfer(record: dict[str, Any], config: dict[str, Any]) -> tuple[dict[str, Any], Any] | None:
    summary = config.get("summary", {})
    direction = str(summary.get("preferred_direction", "forward")).lower()
    target_vd = abs(float(summary.get("preferred_vd_v", 0.1)))
    results = record.get("metrics", {}).get("sweep_results", [])
    candidates: list[tuple[tuple[int, float, int], dict[str, Any], Any]] = []
    for result in results:
        identity = result.get("identity", {})
        if identity.get("measurement_type") != "transfer":
            continue
        index = int(identity.get("sweep_index", -1))
        if not 0 <= index < len(record.get("segments", [])):
            continue
        vth = result.get("vth", {}).get("vth_v")
        if not isinstance(vth, (int, float)) or not np.isfinite(vth):
            continue
        segment = record["segments"][index]
        vg = np.asarray(segment.sweep_values, dtype=float)
        vg = vg[np.isfinite(vg)]
        if len(vg) < 2:
            continue
        rank = (
            0 if str(identity.get("direction", "")).lower() == direction else 1,
            abs(abs(float(identity.get("bias_value_v") or 0)) - target_vd),
            index,
        )
        result.setdefault("current_summary", {})["overdrive_min_v"] = float(np.min(vg) - float(vth))
        result["current_summary"]["overdrive_max_v"] = float(np.max(vg) - float(vth))
        candidates.append((rank, result, segment))
    if not candidates:
        return None
    _, result, segment = min(candidates, key=lambda item: item[0])
    return result, segment


def apply_max_common_overdrive(records: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve and apply one strongest shared Vov per configured comparison group."""
    method = str(config.get("transfer", {}).get("ion_method", "maximum_measured")).lower()
    if method not in {"max_common_overdrive", "maximum_common_vov"}:
        return []
    keys = list(config.get("summary", {}).get("common_overdrive_group_keys", ["sample_label", "polarity"]))
    grouped: dict[tuple[str, ...], list[tuple[dict[str, Any], dict[str, Any], Any]]] = defaultdict(list)
    for record in records:
        selected = _preferred_transfer(record, config)
        if selected is not None:
            grouped[_group_key(record, keys)].append((record, selected[0], selected[1]))
    audit: list[dict[str, Any]] = []
    for group, members in grouped.items():
        lower = max(float(result["current_summary"]["overdrive_min_v"]) for _, result, _ in members)
        upper = min(float(result["current_summary"]["overdrive_max_v"]) for _, result, _ in members)
        polarities = {str(record.get("device_params", {}).get("polarity", "p")).lower() for record, _, _ in members}
        status = "ready"
        chosen = None
        warning = None
        if lower > upper:
            status = "blocked"
            warning = f"No shared overdrive range: intersection [{lower:g}, {upper:g}] V is empty"
        elif len(polarities) != 1:
            status = "blocked"
            warning = "Mixed device polarities cannot share one maximum-overdrive direction"
        else:
            chosen = lower if next(iter(polarities)) == "p" else upper
        group_name = " | ".join(f"{key}={value}" for key, value in zip(keys, group))
        for record, result, segment in members:
            current = result["current_summary"]
            current["ion_common_overdrive_group"] = group_name
            current["ion_common_overdrive_group_size"] = len(members)
            current["ion_common_overdrive_low_v"] = lower
            current["ion_common_overdrive_high_v"] = upper
            current["ion_const_vov_v"] = chosen
            vth = result.get("vth", {}).get("vth_v")
            drain = record.get("classification", {}).get("drain_current_raw_column", "Id")
            current["ion_const_vov_a"] = interpolate_abs_current_at_voltage(
                segment.sweep_values,
                segment.data.get(drain, []),
                float(vth) + float(chosen) if chosen is not None else None,
            )
            settings = record["metrics"].setdefault("analysis_settings", {})
            settings.update({
                "ion_method_used": "max_common_overdrive",
                "ion_overdrive_v": chosen,
                "ion_overdrive_source": "maximum_common_overdrive",
                "ion_common_overdrive_group": group_name,
                "ion_common_overdrive_group_size": len(members),
                "ion_common_overdrive_range_v": [lower, upper],
                "ion_common_overdrive_status": status,
            })
            if warning:
                result.setdefault("warnings", []).append(warning)
            record["metrics"]["device_summary"] = build_device_summary(record["metrics"], config)
        audit.append({"group": group_name, "size": len(members), "range_v": [lower, upper], "chosen_v": chosen, "status": status, "warning": warning})
    return audit
