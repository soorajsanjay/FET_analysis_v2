"""Versioned canonical result schema shared by renderers and external clients."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = "5.0"


@dataclass
class MeasurementIdentity:
    type: str
    source_file: str
    sample_id: str | None = None


@dataclass
class IonResult:
    method_requested: str | None = None
    method_used: str | None = None
    field_mv_cm: float | None = None
    actual_field_mv_cm: float | None = None
    gate_field_mv_cm: float | None = None
    actual_gate_field_mv_cm: float | None = None
    oxide_thickness_nm: float | None = None
    film_thickness_nm: float | None = None
    input_overdrive_v: float | None = None
    resolved_overdrive_v: float | None = None
    fixed_vg_v: float | None = None
    requested_fixed_vg_v: float | None = None
    actual_fixed_vg_v: float | None = None
    requested_gate_vov_v: float | None = None
    actual_gate_vov_v: float | None = None
    current_a: float | None = None
    current_ua_per_um: float | None = None
    ioff_a: float | None = None
    ioff_ua_per_um: float | None = None
    fixed_gate_current_a: float | None = None
    fixed_gate_current_ua_per_um: float | None = None
    fixed_overdrive_current_a: float | None = None
    fixed_overdrive_current_ua_per_um: float | None = None
    fixed_gate_delta_v: float | None = None
    fixed_overdrive_delta_vg: float | None = None
    fixed_gate_warning: str | None = None
    fixed_overdrive_warning: str | None = None
    source: str | None = None
    comparison_group: str | None = None
    condition_ratios: dict[str, Any] = field(default_factory=dict)


@dataclass
class CanonicalResult:
    measurement: MeasurementIdentity
    ion: IonResult = field(default_factory=IonResult)
    preferred: dict[str, Any] = field(default_factory=dict)
    sweeps: list[dict[str, Any]] = field(default_factory=list)
    quality: dict[str, Any] = field(default_factory=dict)
    parameter_preflight: dict[str, Any] = field(default_factory=dict)
    config_validation: dict[str, Any] = field(default_factory=dict)
    gm_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    tlm: dict[str, Any] = field(default_factory=dict)
    best_results: dict[str, Any] = field(default_factory=dict)
    dibl: dict[str, Any] = field(default_factory=dict)
    materials: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def canonical_from_metrics(metrics: dict[str, Any]) -> CanonicalResult:
    settings = metrics.get("analysis_settings", {})
    preferred = (metrics.get("device_summary") or {}).get("preferred", {})
    classification = metrics.get("classification", {})
    measurement_type = str(metrics.get("analysis_type") or metrics.get("measurement_type") or classification.get("type") or "unknown").lower()
    source = str(metrics.get("source_file") or classification.get("source_filename") or "")
    identity = CanonicalResult(
        measurement=MeasurementIdentity(measurement_type, source, metrics.get("sample_id")),
        ion=IonResult(
            method_requested=settings.get("ion_method_configured"),
            method_used=preferred.get("ion_method_used") or settings.get("ion_method_used"),
            field_mv_cm=settings.get("ion_overdrive_field_mv_cm"),
            actual_field_mv_cm=preferred.get("ion_overdrive_field_actual_mv_cm"),
            gate_field_mv_cm=settings.get("ion_gate_field_mv_cm"),
            actual_gate_field_mv_cm=preferred.get("ion_gate_field_actual_mv_cm"),
            oxide_thickness_nm=settings.get("ion_oxide_thickness_nm"),
            film_thickness_nm=(metrics.get("device_geometry") or {}).get("film_thickness_nm"),
            input_overdrive_v=settings.get("ion_overdrive_input_v"),
            resolved_overdrive_v=preferred.get("ion_const_vov_v", settings.get("ion_overdrive_v")),
            fixed_vg_v=preferred.get("ion_const_vg_v", settings.get("ion_fixed_vg_v")),
            requested_fixed_vg_v=preferred.get("ion_const_vg_requested_v", settings.get("ion_fixed_vg_v")),
            actual_fixed_vg_v=preferred.get("ion_const_vg_v"),
            requested_gate_vov_v=preferred.get("ion_const_vov_target_vg_v"),
            actual_gate_vov_v=preferred.get("ion_const_vov_actual_vg_v"),
            current_a=preferred.get("ion_configured_a"),
            current_ua_per_um=preferred.get("ion_configured_ua_per_um"),
            ioff_a=preferred.get("ioff_configured_a"),
            ioff_ua_per_um=preferred.get("ioff_configured_ua_per_um"),
            fixed_gate_current_a=preferred.get("ion_const_vg_a"),
            fixed_gate_current_ua_per_um=preferred.get("ion_const_vg_ua_per_um"),
            fixed_overdrive_current_a=preferred.get("ion_const_vov_a"),
            fixed_overdrive_current_ua_per_um=preferred.get("ion_const_vov_ua_per_um"),
            fixed_gate_delta_v=preferred.get("ion_const_vg_delta_v"),
            fixed_overdrive_delta_vg=preferred.get("ion_const_vov_delta_vg_v"),
            fixed_gate_warning=preferred.get("ion_const_vg_warning"),
            fixed_overdrive_warning=preferred.get("ion_const_vov_warning"),
            source=settings.get("ion_overdrive_source"),
            comparison_group=settings.get("ion_common_overdrive_group"),
            condition_ratios={
                key: preferred.get(key) for key in (
                    "ion_ioff", "ion_ioff_log10", "ion_ioff_const_vg", "ion_ioff_const_vg_log10",
                    "ion_ioff_const_vov", "ion_ioff_const_vov_log10", "ion_ioff_max", "ion_ioff_max_log10",
                )
            },
        ),
        preferred=preferred,
        sweeps=list(metrics.get("sweep_results", [])),
        quality=dict(metrics.get("quality", {})),
        parameter_preflight=dict(metrics.get("parameter_preflight", {})),
        config_validation=dict(metrics.get("config_validation", {})),
        gm_diagnostics=[
            dict(sweep.get("gm", {}).get("smoothing", {}))
            for sweep in metrics.get("sweep_results", [])
            if isinstance(sweep, dict) and isinstance(sweep.get("gm"), dict)
        ],
        tlm=dict(metrics.get("tlm_result") or metrics.get("tlm") or {}),
        best_results=dict((metrics.get("device_summary") or {}).get("best", {})),
        dibl=dict(metrics.get("dibl") or {}),
        materials=dict(metrics.get("device_geometry") or {}),
    )
    return identity


def attach_canonical_result(metrics: dict[str, Any]) -> dict[str, Any]:
    metrics["schema_version"] = SCHEMA_VERSION
    metrics["canonical_result"] = canonical_from_metrics(metrics).to_dict()
    return metrics


def validate_canonical_result(value: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    measurement = value.get("measurement")
    if not isinstance(measurement, dict) or not isinstance(measurement.get("type"), str):
        errors.append("measurement.type is required")
    if not isinstance(value.get("sweeps", []), list):
        errors.append("sweeps must be a list")
    return errors


def validate_metrics_consistency(metrics: dict[str, Any]) -> list[str]:
    """Check that renderer-facing preferred fields match the canonical contract."""
    canonical = metrics.get("canonical_result")
    if not isinstance(canonical, dict):
        return ["canonical_result is missing"]
    preferred = (metrics.get("device_summary") or {}).get("preferred", {})
    ion = canonical.get("ion") or {}
    checks = {
        "ion.current_a": (ion.get("current_a"), preferred.get("ion_configured_a")),
        "ion.current_ua_per_um": (ion.get("current_ua_per_um"), preferred.get("ion_configured_ua_per_um")),
        "ion.ioff_a": (ion.get("ioff_a"), preferred.get("ioff_configured_a")),
        "ion.fixed_gate_current_a": (ion.get("fixed_gate_current_a"), preferred.get("ion_const_vg_a")),
        "ion.fixed_overdrive_current_a": (ion.get("fixed_overdrive_current_a"), preferred.get("ion_const_vov_a")),
    }
    errors: list[str] = []
    for label, (canonical_value, preferred_value) in checks.items():
        if canonical_value != preferred_value:
            errors.append(
                f"{label}={canonical_value!r} disagrees with preferred={preferred_value!r}"
            )
    return errors


def migrate_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a v5 canonical result from a legacy or current metrics payload."""
    if payload.get("schema_version") == SCHEMA_VERSION and isinstance(payload.get("canonical_result"), dict):
        return payload["canonical_result"]
    return canonical_from_metrics(payload).to_dict()
