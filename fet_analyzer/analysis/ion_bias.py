"""Resolve auditable Ion read conditions from voltage or electric field."""

from __future__ import annotations

from typing import Any


def _first(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)


def field_to_voltage(field_mv_cm: Any, oxide_thickness_nm: Any) -> float | None:
    """Convert a nominal dielectric field to voltage across its thickness."""
    if field_mv_cm is None or not isinstance(oxide_thickness_nm, (int, float)):
        return None
    if float(oxide_thickness_nm) <= 0:
        return None
    return float(field_mv_cm) * float(oxide_thickness_nm) * 0.1


def resolve_ion_bias(
    config: dict[str, Any] | None,
    device_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve fixed-Vg and fixed-overdrive Ion read conditions.

    A signed electric field in MV/cm takes precedence over a configured
    overdrive voltage.  Conversion uses Vov = Eox * tox, or numerically
    ``Vov[V] = Eox[MV/cm] * tox[nm] * 0.1``.
    """
    cfg = config or {}
    transfer = cfg.get("transfer", {})
    tlm = cfg.get("tlm", {})
    method = str(transfer.get("ion_method", "maximum_measured")).lower()
    device = device_params or cfg.get("device_defaults", {})
    fixed_vg_input = _first(
        transfer.get("ion_fixed_vg_v"),
        transfer.get("ion_constant_vg_v"),
        tlm.get("transfer_read_vg_v"),
    )
    gate_field = _first(
        transfer.get("ion_gate_field_mv_cm"),
        tlm.get("transfer_gate_field_mv_cm"),
    )
    configured_voltage = _first(
        transfer.get("ion_overdrive_v"),
        transfer.get("overdrive_v"),
        tlm.get("transfer_overdrive_v"),
    )
    field = _first(
        transfer.get("ion_overdrive_field_mv_cm"),
        tlm.get("transfer_overdrive_field_mv_cm"),
    )
    oxide_nm = device.get("oxide_thickness_nm")
    warnings: list[str] = []
    fixed_vg_source = "voltage" if fixed_vg_input is not None else None
    fixed_vg = fixed_vg_input
    # A supplied electric field is the authoritative read condition, including
    # when the optional fixed-gate report is enabled alongside another primary
    # Ion method.
    use_gate_field = gate_field is not None
    if use_gate_field and gate_field is not None:
        fixed_vg_source = "electric_field"
        fixed_vg = field_to_voltage(gate_field, oxide_nm)
        if fixed_vg is None:
            warnings.append(
                "Ion gate-field read requires a positive oxide_thickness_nm; fixed-gate-field Ion is unavailable"
            )
    source = "voltage" if configured_voltage is not None else None
    resolved_voltage = configured_voltage
    if field is not None:
        source = "electric_field"
        resolved_voltage = field_to_voltage(field, oxide_nm)
        if resolved_voltage is None:
            warnings.append(
                "Ion electric-field overdrive requires a positive oxide_thickness_nm; fixed-overdrive Ion is unavailable"
            )
    return {
        "fixed_vg_v": float(fixed_vg) if fixed_vg is not None else None,
        "fixed_vg_input_v": float(fixed_vg_input) if fixed_vg_input is not None else None,
        "gate_field_mv_cm": float(gate_field) if gate_field is not None else None,
        "fixed_vg_source": fixed_vg_source,
        "overdrive_v": float(resolved_voltage) if resolved_voltage is not None else None,
        "overdrive_input_v": float(configured_voltage) if configured_voltage is not None else None,
        "overdrive_field_mv_cm": float(field) if field is not None else None,
        "oxide_thickness_nm": float(oxide_nm) if isinstance(oxide_nm, (int, float)) else None,
        "overdrive_source": source,
        "warnings": warnings,
    }
