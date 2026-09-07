"""
TLM (Transfer Length Method) analysis: contact resistance, sheet resistance,
transfer length, and specific contact resistivity extraction.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from fet_analyzer.utils.logging import LOGGER
from fet_analyzer.analysis.ion_bias import field_to_voltage


def _prepare_interpolation(
    vg: np.ndarray, current: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Sort a sweep and collapse duplicate voltages once for repeated reads."""
    order = np.argsort(vg)
    vg, current = vg[order], current[order]
    unique_vg, inverse = np.unique(vg, return_inverse=True)
    unique_current = np.array([
        np.median(current[inverse == index]) for index in range(len(unique_vg))
    ])
    return unique_vg, unique_current


def _interpolate_prepared(
    prepared: tuple[np.ndarray, np.ndarray], read_vg: float,
) -> float | None:
    """Interpolate a sweep prepared by :func:`_prepare_interpolation`."""
    unique_vg, unique_current = prepared
    if len(unique_vg) == 0:
        return None
    if read_vg < unique_vg[0] or read_vg > unique_vg[-1]:
        return None
    return float(np.interp(read_vg, unique_vg, unique_current))


def _interpolate_current(vg: np.ndarray, current: np.ndarray, read_vg: float) -> float | None:
    """Return Id at a read voltage; retained for one-off interpolation calls."""
    return _interpolate_prepared(_prepare_interpolation(vg, current), read_vg)


def _nearest_prepared(
    prepared: tuple[np.ndarray, np.ndarray], read_vg: float,
) -> tuple[float | None, float | None]:
    """Return current and voltage at the closest measured gate point."""
    unique_vg, unique_current = prepared
    if not len(unique_vg):
        return None, None
    index = int(np.argmin(np.abs(unique_vg - float(read_vg))))
    return float(unique_current[index]), float(unique_vg[index])


def _extract_vth_for_overdrive(
    vg: np.ndarray,
    current: np.ndarray,
    vds: float,
    transfer_cfg: dict[str, Any],
) -> float | None:
    """Extract the per-device Vth used to convert a shared Vov into Vg."""
    from fet_analyzer.analysis.extraction import extract_vth_peak_gm_tangent

    result = extract_vth_peak_gm_tangent(
        vg.tolist(), current.tolist(),
        tangent_window_v=transfer_cfg.get("tangent_window_v", 2.0),
        tangent_min_points=transfer_cfg.get("tangent_min_points", 5),
        vds=vds,
        vds_correction=transfer_cfg.get("vth_vds_correction", True),
    )
    return result.get("vth_v")


def extract_rtotal(
    segments: list[Any],
    classification: dict[str, Any],
    config: dict[str, Any] | None = None,
    device_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract R_total from transfer or output TLM measurements.

    Transfer TLM supports five valid read conventions:
      - ``maximum_current``: each device is read at its measured maximum |Id|.
      - ``constant_vg``: every device is read at one absolute gate voltage.
      - ``constant_gate_field``: ``Vg`` is resolved from ``Vg/tox`` per device.
      - ``constant_overdrive``: every device is read at ``Vg - Vth = Vov``.
      - ``constant_overdrive_field``: ``Vov`` is resolved from ``Vov/tox`` per device.

    Voltage and field values are signed: for a p-FET use negative values.
    """
    results: dict[str, Any] = {"rtotal_ohm": None, "rtotal_per_segment": {}, "warnings": []}
    cfg = config or {}
    tlm_cfg = cfg.get("tlm", {})
    transfer_cfg = cfg.get("transfer", {})
    device = device_params or cfg.get("device_defaults", {})
    oxide_nm = device.get("oxide_thickness_nm")
    field_scale = (
        float(oxide_nm) * 0.1
        if isinstance(oxide_nm, (int, float)) and float(oxide_nm) > 0 else None
    )
    requested_vds = tlm_cfg.get("transfer_read_vds_v")
    vds_tolerance = float(tlm_cfg.get("vds_tolerance_v", 1e-3))

    from fet_analyzer.analysis.segmentation import group_by_bias
    bias_groups = group_by_bias(segments)
    is_transfer = classification.get("sweep_variable", "Vg").lower() in ("vg", "vbg")
    if is_transfer and len(bias_groups) > 1 and requested_vds is None:
        results["warnings"].append(
            "Transfer TLM aggregate skipped: set tlm.transfer_read_vds_v to one common |Vds|"
        )
    rtotals: list[float] = []
    for bias_key, segs in sorted(bias_groups.items()):
        fwd = [segment for segment in segs if segment.direction == "forward"]
        # Ungated/output TLM files are often a single I-V sweep. Direction
        # labels may be polarity-aware, so a sole increasing-Vd sweep can be
        # labelled reverse for a p-type device. Prefer forward when a paired
        # sweep exists, but do not discard the only available ungated sweep.
        candidates = fwd or (segs[:1] if not is_transfer and len(segs) == 1 else [])
        if not candidates:
            continue
        seg = candidates[0]
        sweep_var = classification.get("sweep_variable", "Vg")
        drain_col = classification.get("drain_current_raw_column", "Id")
        sweep = np.asarray(seg.sweep_values, dtype=float)
        current = np.asarray(seg.data.get(drain_col, []), dtype=float)
        valid = np.isfinite(sweep) & np.isfinite(current)
        sweep, current = sweep[valid], current[valid]
        if len(sweep) < 3:
            continue
        vds = abs(seg.bias_level) if seg.bias_level and abs(seg.bias_level) > 1e-6 else 0.1

        if sweep_var.lower() in ("vg", "vbg") and requested_vds is not None and abs(vds - abs(float(requested_vds))) > vds_tolerance:
            continue
        if sweep_var.lower() in ("vg", "vbg"):
            mode = tlm_cfg.get("transfer_read_mode")
            # Preserve the old configuration key for backwards compatibility.
            if mode is None:
                mode = "constant_vg" if tlm_cfg.get("transfer_read_vg_v") is not None else "constant_overdrive"
            requested_gate_field = None
            requested_overdrive_field = None
            requested_read_vg = None
            maximum_mode = mode in {"maximum_current", "maximum_measured"}
            if maximum_mode:
                index = int(np.argmax(np.abs(current)))
                id_use = float(current[index])
                actual_read_vg = requested_read_vg = float(sweep[index])
                read_delta = 0.0
                vth = overdrive = actual_overdrive = None
                results["warnings"].append(
                    "maximum_current TLM reads each device at its own maximum-current Vg; actual Vg may differ across channel lengths"
                )
            elif mode == "constant_vg":
                requested_read_vg = tlm_cfg.get("transfer_read_vg_v")
                if requested_read_vg is None:
                    results["warnings"].append("Transfer TLM skipped: set tlm.transfer_read_vg_v")
                    continue
                vth = overdrive = None
            elif mode == "constant_gate_field":
                requested_gate_field = tlm_cfg.get("transfer_gate_field_mv_cm")
                requested_read_vg = field_to_voltage(requested_gate_field, oxide_nm)
                if requested_read_vg is None:
                    results["warnings"].append(
                        "Transfer TLM skipped: constant_gate_field requires tlm.transfer_gate_field_mv_cm and positive oxide_thickness_nm"
                    )
                    continue
                vth = overdrive = None
            elif mode in {"constant_overdrive", "constant_overdrive_field"}:
                overdrive = tlm_cfg.get("transfer_overdrive_v")
                if mode == "constant_overdrive_field":
                    requested_overdrive_field = tlm_cfg.get("transfer_overdrive_field_mv_cm")
                    overdrive = field_to_voltage(requested_overdrive_field, oxide_nm)
                if overdrive is None:
                    setting = "transfer_overdrive_field_mv_cm and positive oxide_thickness_nm" if mode == "constant_overdrive_field" else "transfer_overdrive_v"
                    results["warnings"].append(f"Transfer TLM skipped: set tlm.{setting}")
                    continue
                vth = _extract_vth_for_overdrive(sweep, current, vds, transfer_cfg)
                if vth is None:
                    results["warnings"].append(f"Transfer TLM skipped: Vth extraction failed for {mode}")
                    continue
                requested_read_vg = float(vth + overdrive)
            else:
                results["warnings"].append(
                    f"Transfer TLM skipped: unknown transfer_read_mode={mode!r}"
                )
                continue

            if not maximum_mode:
                id_use, actual_read_vg = _nearest_prepared(
                    _prepare_interpolation(sweep, current), float(requested_read_vg)
                )
                if id_use is None or actual_read_vg is None:
                    results["warnings"].append("Transfer TLM skipped: no finite gate points")
                    continue
                read_delta = float(actual_read_vg - float(requested_read_vg))
                if abs(read_delta) > 1e-12:
                    results["warnings"].append(
                        f"Requested TLM Vg={float(requested_read_vg):g} V was unavailable; used nearest measured Vg={actual_read_vg:g} V"
                    )
                actual_overdrive = actual_read_vg - float(vth) if vth is not None else None
            r_total = vds / abs(id_use) if abs(id_use) > 1e-15 else None
            method = (
                f"maximum_current: used measured Vg={actual_read_vg:.3f} V"
                if maximum_mode else
                f"{mode}: requested Vg={float(requested_read_vg):.3f} V, used Vg={actual_read_vg:.3f} V"
            )
            read_vg = actual_read_vg
        else:
            vd_max = tlm_cfg.get("tlm_output_vd_max", 0.1)
            linear = np.abs(sweep) <= vd_max
            if linear.sum() >= 3:
                slope = np.polyfit(sweep[linear], current[linear], 1)[0]
                r_total = 1.0 / abs(slope) if abs(slope) > 1e-15 else None
                read_vg, method = float(sweep[linear][0]), "low-Vd slope fit"
            else:
                index = int(np.argmin(np.abs(sweep)))
                r_total = vds / abs(current[index]) if abs(current[index]) > 1e-15 else None
                read_vg, method = float(sweep[index]), "nearest-zero Vd"
            vth = overdrive = None

        if r_total is not None and (not is_transfer or requested_vds is not None or len(bias_groups) == 1):
            rtotals.append(float(r_total))
        results["rtotal_per_segment"][str(bias_key)] = {
            "rtotal_ohm": r_total, f"{sweep_var}_at_read": read_vg,
            "vds_v": vds, "method": method,
            "vth_v": vth, "overdrive_v": actual_overdrive if is_transfer else overdrive,
            "requested_vg_v": requested_read_vg if is_transfer else None,
            "actual_vg_v": read_vg if is_transfer else None,
            "vg_delta_v": read_delta if is_transfer else None,
            "requested_overdrive_v": overdrive if is_transfer else None,
            "actual_overdrive_v": actual_overdrive if is_transfer else None,
            "requested_gate_field_mv_cm": requested_gate_field if is_transfer else None,
            "actual_gate_field_mv_cm": (read_vg / field_scale if is_transfer and field_scale else None),
            "requested_overdrive_field_mv_cm": requested_overdrive_field if is_transfer else None,
            "actual_overdrive_field_mv_cm": (actual_overdrive / field_scale if is_transfer and actual_overdrive is not None and field_scale else None),
            "oxide_thickness_nm": oxide_nm,
        }

    if rtotals:
        results["rtotal_ohm"] = float(min(rtotals))
    results["read_conditions"] = {
        "transfer_read_mode": tlm_cfg.get("transfer_read_mode"),
        "transfer_read_vg_v": tlm_cfg.get("transfer_read_vg_v"),
        "transfer_gate_field_mv_cm": tlm_cfg.get("transfer_gate_field_mv_cm"),
        "transfer_overdrive_v": tlm_cfg.get("transfer_overdrive_v"),
        "transfer_overdrive_field_mv_cm": tlm_cfg.get("transfer_overdrive_field_mv_cm"),
        "oxide_thickness_nm": oxide_nm,
        "transfer_read_vds_v": requested_vds,
    }
    return results

def extract_tlm(
    r_total_values: list[tuple[float, float]],
    width_um: float = 100.0,
    width_norm: bool = True,
    r2_warning: float = 0.9,
    min_length_span_ratio: float = 2.0,
    max_relative_uncertainty: float = 1.0,
    max_leverage: float = 0.85,
    max_residual_curvature: float = 0.8,
    max_abs_lt_to_lmin_ratio: float = 10.0,
    film_thickness_nm: float | None = None,
) -> dict[str, Any]:
    """Fit R_total(L) and calculate physically consistent TLM parameters."""
    valid = [(float(length), float(resistance)) for length, resistance in r_total_values
             if np.isfinite(length) and np.isfinite(resistance) and resistance > 0]
    unique_lengths = len({item[0] for item in valid})
    if unique_lengths < 3:
        return {"rc_ohm": None, "rsh_ohm_sq": None, "lt_um": None,
                "rhoc_ohm_cm2": None, "r2": None, "n_points": len(valid),
                "film_thickness_nm": film_thickness_nm, "rho_film_ohm_cm": None,
                "acceptance_status": "review", "status": "review",
                "acceptance_reasons": ["insufficient_unique_lengths"],
                "warnings": [f"Need at least 3 unique Lch values, got {unique_lengths}"]}

    length = np.array([item[0] for item in valid])
    resistance = np.array([item[1] for item in valid])
    fitted_resistance = resistance * width_um if width_norm else resistance
    slope, intercept = np.linalg.lstsq(
        np.vstack([length, np.ones_like(length)]).T, fitted_resistance, rcond=None
    )[0]
    prediction = slope * length + intercept
    total = np.sum((fitted_resistance - np.mean(fitted_resistance)) ** 2)
    r2 = float(1 - np.sum((fitted_resistance - prediction) ** 2) / total) if total > 1e-30 else None
    warnings: list[str] = []
    review_reasons: list[str] = []
    rejection_reasons: list[str] = []
    residuals = fitted_resistance - prediction
    dof = len(valid) - 2
    slope_std = intercept_std = None
    if dof > 0:
        sigma2 = float(np.sum(residuals ** 2) / dof)
        covariance = sigma2 * np.linalg.inv(
            np.vstack([length, np.ones_like(length)]).T.T
            @ np.vstack([length, np.ones_like(length)]).T
        )
        slope_std = float(np.sqrt(max(covariance[0, 0], 0)))
        intercept_std = float(np.sqrt(max(covariance[1, 1], 0)))
    if r2 is not None and r2 < r2_warning:
        warnings.append(f"Poor TLM fit: R²={r2:.4g} is below warning threshold {r2_warning:.4g}")
        review_reasons.append("r2_below_threshold")
    length_span_ratio = float(np.max(length) / np.min(length)) if np.min(length) > 0 else None
    if length_span_ratio is None or length_span_ratio < min_length_span_ratio:
        warnings.append("TLM channel-length span is too narrow for a reliable intercept")
        review_reasons.append("insufficient_length_span")
    if slope <= 0:
        warnings.append("Non-positive TLM slope: Rsh, LT, and rho_c are not physical")
        rejection_reasons.append("non_positive_slope")
    if intercept < 0:
        warnings.append("Negative TLM intercept: extracted contact parameters are not physical")
        rejection_reasons.append("negative_intercept")
        LOGGER.warning("TLM fit has negative intercept (%.6g ohm): contact parameters may be non-physical", intercept)
    # Retain negative intercepts as diagnostic fits. They imply negative Rc/RcW
    # (and LT) under the usual TLM model, so the result is marked as a warning.
    # A non-positive slope remains invalid because Rsh cannot be interpreted.
    if slope <= 0:
        return {"rc_ohm": None, "rsh_ohm_sq": None, "lt_um": None,
                "rhoc_ohm_cm2": None, "r2": r2, "n_points": len(valid),
                "film_thickness_nm": film_thickness_nm, "rho_film_ohm_cm": None,
                "slope_ohm_per_um": float(slope), "intercept_ohm": float(intercept),
                "width_um": width_um, "width_normalized": width_norm,
                "slope_std": slope_std, "intercept_std": intercept_std,
                "length_span_ratio": length_span_ratio,
                "acceptance_status": "rejected_nonphysical",
                "status": "rejected_nonphysical",
                "acceptance_reasons": rejection_reasons + review_reasons,
                "warnings": warnings}

    # With R_total*W = Rsh*L + 2*Rc*W, RcW is intercept/2.
    rcw_ohm_um = intercept / 2
    rc_ohm = rcw_ohm_um / width_um if width_norm else rcw_ohm_um
    rsh_ohm_sq = slope if width_norm else slope * width_um
    lt_um = rcw_ohm_um / rsh_ohm_sq
    rhoc_ohm_cm2 = rsh_ohm_sq * (lt_um * 1e-4) ** 2
    rho_film_ohm_cm = (
        float(rsh_ohm_sq) * float(film_thickness_nm) * 1e-7
        if isinstance(film_thickness_nm, (int, float)) and film_thickness_nm > 0
        else None
    )
    slope_relative_uncertainty = abs(slope_std / slope) if slope_std is not None and slope else None
    intercept_relative_uncertainty = abs(intercept_std / intercept) if intercept_std is not None and intercept else None
    if any(value is not None and value > max_relative_uncertainty for value in (slope_relative_uncertainty, intercept_relative_uncertainty)):
        warnings.append("TLM parameter uncertainty is large relative to the fitted value")
        review_reasons.append("high_relative_uncertainty")
    design = np.vstack([length, np.ones_like(length)]).T
    leverage = np.diag(design @ np.linalg.inv(design.T @ design) @ design.T)
    max_observation_leverage = float(np.max(leverage))
    if max_observation_leverage > max_leverage:
        warnings.append("One channel length has excessive leverage on the TLM fit")
        review_reasons.append("high_leverage")
    residual_curvature = None
    if len(length) >= 4 and np.std(residuals) > 0 and np.std(length ** 2) > 0:
        residual_curvature = float(abs(np.corrcoef(residuals, length ** 2)[0, 1]))
        if np.isfinite(residual_curvature) and residual_curvature > max_residual_curvature:
            warnings.append("TLM residuals show systematic curvature")
            review_reasons.append("residual_curvature")
    lt_to_lmin_ratio = abs(float(lt_um)) / float(np.min(length)) if np.min(length) > 0 else None
    if lt_to_lmin_ratio is not None and lt_to_lmin_ratio > max_abs_lt_to_lmin_ratio:
        warnings.append("Transfer length is implausibly large relative to the shortest channel")
        review_reasons.append("implausible_transfer_length")
    acceptance_status = "rejected_nonphysical" if rejection_reasons else "review" if review_reasons else "accepted"
    return {"rc_ohm": float(rc_ohm), "rcw_ohm_um": float(rcw_ohm_um),
            "rsh_ohm_sq": float(rsh_ohm_sq), "lt_um": float(lt_um),
            "rhoc_ohm_cm2": float(rhoc_ohm_cm2), "r2": r2,
            "film_thickness_nm": float(film_thickness_nm) if isinstance(film_thickness_nm, (int, float)) else None,
            "rho_film_ohm_cm": rho_film_ohm_cm,
            "slope_ohm_per_um": float(slope), "intercept_ohm": float(intercept),
            "n_points": len(valid), "width_um": width_um,
            "width_normalized": width_norm, "slope_std": slope_std,
            "intercept_std": intercept_std,
            "slope_relative_uncertainty": slope_relative_uncertainty,
            "intercept_relative_uncertainty": intercept_relative_uncertainty,
            "length_span_ratio": length_span_ratio,
            "max_observation_leverage": max_observation_leverage,
            "residual_curvature": residual_curvature,
            "lt_to_lmin_ratio": lt_to_lmin_ratio,
            "acceptance_status": acceptance_status, "status": acceptance_status,
            "acceptance_reasons": rejection_reasons + review_reasons,
            "warnings": warnings}

def auto_group_tlm(
    all_devices: list[dict[str, Any]],
    min_devices: int = 3,
    group_keys: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Fit independent TLM sets using every configured grouping key."""
    from collections import defaultdict
    aliases = {"sample_label": "sample_id", "vd_value": "vds_v"}
    group_keys = group_keys or ["sample_label", "measurement_type"]
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for device in all_devices:
        if device.get("channel_length_um") is None or device.get("r_total_ohm") is None:
            continue
        key = tuple(device.get(aliases.get(name, name)) for name in group_keys)
        groups[key].append(device)

    results: list[dict[str, Any]] = []
    for key, devices in sorted(groups.items(), key=lambda item: str(item[0])):
        unique_lengths = {device["channel_length_um"] for device in devices}
        if len(unique_lengths) < min_devices:
            LOGGER.debug("TLM: skipping %s - only %d unique channel lengths", key, len(unique_lengths))
            continue
        widths = {device.get("channel_width_um") for device in devices}
        width = next(iter(widths)) if len(widths) == 1 else None
        if width is None:
            LOGGER.warning("TLM %s skipped: devices have different channel widths", key)
            continue
        values = [(device["channel_length_um"], device["r_total_ohm"]) for device in devices]
        thicknesses = {device.get("film_thickness_nm") for device in devices if device.get("film_thickness_nm") is not None}
        film_thickness_nm = next(iter(thicknesses)) if len(thicknesses) == 1 else None
        result = extract_tlm(values, width_um=float(width), film_thickness_nm=film_thickness_nm)
        result["lch_values"] = values
        result["group_keys"] = group_keys
        result["group_values"] = dict(zip(group_keys, key))
        group_values = dict(zip(group_keys, key))
        result["sample_id"] = str(group_values.get("sample_label") or devices[0].get("sample_id") or "unknown")
        result["group_id"] = " | ".join(f"{name}={value}" for name, value in zip(group_keys, key))
        result["member_device_names"] = [device.get("device_name", "") for device in devices]
        results.append(result)
    return results

def extract_tlm_with_statistics(
    raw_data: list[dict[str, Any]],
    width_um: float = 100.0,
    width_norm: bool = True,
    film_thickness_nm: float | None = None,
) -> dict[str, Any]:
    """Extract TLM with per-Lch statistics from raw device data.

    Groups multiple measurements for the same channel length together,
    computes mean ± std for R_total at each Lch, then fits.

    Args:
        raw_data: List of dicts with keys: channel_length_um, r_total_ohm, device_name
        width_um: Channel width
        width_norm: Normalize by width

    Returns:
        TLM result dict with additional keys:
            lch_stats: per-Lch (mean, std, n, device_names)
            lch_values: list of (Lch, mean_R) for fit
            errorbar_values: list of (Lch, mean_R, std_R) for plotting
    """
    from collections import defaultdict

    # Group by channel length
    by_lch: dict[float, list[float]] = defaultdict(list)
    by_lch_devices: dict[float, list[str]] = defaultdict(list)
    for dev in raw_data:
        lch = dev.get("channel_length_um")
        rtot = dev.get("r_total_ohm")
        name = dev.get("device_name", "?")
        if lch is not None and rtot is not None:
            by_lch[lch].append(rtot)
            by_lch_devices[lch].append(name)

    # Compute statistics
    lch_stats: dict[str, Any] = {}
    tlm_points: list[tuple[float, float]] = []
    errorbar_points: list[tuple[float, float, float]] = []

    for lch in sorted(by_lch.keys()):
        values = by_lch[lch]
        mean_r = float(np.mean(values))
        std_r = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
        lch_stats[str(lch)] = {
            "mean_rtotal_ohm": mean_r,
            "std_rtotal_ohm": std_r,
            "n_measurements": len(values),
            "device_names": by_lch_devices[lch],
        }
        tlm_points.append((lch, mean_r))
        errorbar_points.append((lch, mean_r, std_r))

    if len(tlm_points) < 3:
        return {
            "rc_ohm": None, "rsh_ohm_sq": None, "lt_um": None,
            "rhoc_ohm_cm2": None, "r2": None,
            "film_thickness_nm": film_thickness_nm, "rho_film_ohm_cm": None,
            "n_points": len(tlm_points), "n_devices": len(raw_data),
            "lch_stats": lch_stats, "lch_values": tlm_points,
            "errorbar_values": errorbar_points,
            "warnings": [f"Need ≥3 unique Lch values, got {len(tlm_points)}"],
        }

    # Fit with mean values
    result = extract_tlm(
        tlm_points, width_um=width_um, width_norm=width_norm,
        film_thickness_nm=film_thickness_nm,
    )
    result["lch_stats"] = lch_stats
    result["errorbar_values"] = errorbar_points
    result["n_devices"] = len(raw_data)
    return result
