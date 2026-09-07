"""Structured configuration validation for reproducible FET analysis."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ValidationIssue:
    level: str
    code: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class ValidationReport:
    issues: list[ValidationIssue]

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.level == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.level == "warning"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "error" if self.errors else "warning" if self.warnings else "pass",
            "issues": [issue.to_dict() for issue in self.issues],
        }


class ConfigValidationError(ValueError):
    def __init__(self, report: ValidationReport):
        self.report = report
        details = "; ".join(f"{item.path}: {item.message}" for item in report.errors)
        super().__init__(f"Invalid configuration: {details}")


def validate_config(data: dict[str, Any]) -> ValidationReport:
    """Validate cross-field constraints and report errors, warnings, and notes."""
    issues: list[ValidationIssue] = []
    transfer = data.get("transfer", {})
    device = data.get("device_defaults", {})
    tlm = data.get("tlm", {})
    advanced = data.get("advanced", {})
    method = str(transfer.get("ion_method", "maximum_measured")).lower()
    unsupported = {
        "transfer.smooth_method": ({"gaussian"}, str(transfer.get("smooth_method", "savgol")).lower(), "Gaussian gm smoothing is currently unsupported; choose savgol, adaptive_savgol, or none"),
        "transfer.vth_method": ({"max_gm_point", "second_derivative"}, str(transfer.get("vth_method", "peak_gm_tangent")).lower(), "This Vth method is currently unsupported; choose peak_gm_tangent or constant_current"),
        "transfer.ss_method": ({"average", "linear_fit"}, str(transfer.get("ss_method", "minimum")).lower(), "This subthreshold-swing method is currently unsupported; choose minimum"),
        "tlm.tlm_ss_method": ({"average"}, str(tlm.get("tlm_ss_method", "minimum")).lower(), "Average TLM subthreshold swing is currently unsupported; choose minimum"),
    }
    for path, (values, selected, message) in unsupported.items():
        if selected in values:
            issues.append(ValidationIssue("error", "method_not_implemented", path, message))
    allowed_methods = {
        "maximum_measured", "max_current", "fixed_vg", "constant_vg",
        "fixed_gate_field", "constant_gate_field",
        "fixed_overdrive", "constant_vov", "fixed_overdrive_field",
        "max_common_overdrive", "maximum_common_vov",
    }
    if method not in allowed_methods:
        issues.append(ValidationIssue("error", "unknown_ion_method", "transfer.ion_method", f"Unsupported Ion method {method!r}"))

    fixed_vg = transfer.get("ion_fixed_vg_v")
    legacy_vg = transfer.get("ion_constant_vg_v")
    gate_field = transfer.get("ion_gate_field_mv_cm")
    voltage = transfer.get("ion_overdrive_v")
    legacy_voltage = transfer.get("overdrive_v")
    field = transfer.get("ion_overdrive_field_mv_cm")
    report_fixed_vg = bool(transfer.get("report_ion_at_fixed_vg", False))
    report_fixed_vov = bool(transfer.get("report_ion_at_fixed_overdrive", False)) or any(
        value is not None for value in (voltage, legacy_voltage, field)
    )
    if method in {"fixed_vg", "constant_vg"} and fixed_vg is None and legacy_vg is None and gate_field is None:
        # Keep the built-in configuration editable in a fresh GUI project.  The
        # stricter analysis-readiness check below promotes this to an error at
        # preflight/run time, before any measurement is processed.
        issues.append(ValidationIssue("warning", "missing_fixed_vg", "transfer.ion_fixed_vg_v", "Constant-gate Ion requires ion_fixed_vg_v or ion_gate_field_mv_cm before analysis"))
    if method in {"fixed_gate_field", "constant_gate_field"} and gate_field is None:
        issues.append(ValidationIssue("error", "missing_gate_field", "transfer.ion_gate_field_mv_cm", "fixed_gate_field requires a signed nominal Vg/tox electric field"))
    if report_fixed_vg and fixed_vg is None and legacy_vg is None and gate_field is None:
        issues.append(ValidationIssue("error", "missing_optional_fixed_vg", "transfer.report_ion_at_fixed_vg", "Fixed-gate Ion reporting requires ion_fixed_vg_v or ion_gate_field_mv_cm"))
    if gate_field is not None and method not in {"fixed_gate_field", "constant_gate_field", "fixed_vg", "constant_vg"} and not report_fixed_vg:
        issues.append(ValidationIssue("warning", "unused_gate_field", "transfer.ion_gate_field_mv_cm", f"Gate field is not used by ion_method={method}"))
    if method in {"fixed_overdrive", "constant_vov"} and voltage is None and legacy_voltage is None and field is None:
        issues.append(ValidationIssue("error", "missing_overdrive", "transfer.ion_overdrive_v", "fixed_overdrive requires a signed voltage (or the legacy field-compatible input)"))
    if method == "fixed_overdrive_field" and field is None:
        issues.append(ValidationIssue("error", "missing_overdrive_field", "transfer.ion_overdrive_field_mv_cm", "fixed_overdrive_field requires a signed electric field"))
    if report_fixed_vov and voltage is None and legacy_voltage is None and field is None:
        issues.append(ValidationIssue("error", "missing_optional_overdrive", "transfer.report_ion_at_fixed_overdrive", "Fixed-overdrive Ion reporting requires ion_overdrive_v or ion_overdrive_field_mv_cm"))
    if field is not None and method not in {"fixed_overdrive_field", "fixed_overdrive", "constant_vov"} and not report_fixed_vov:
        issues.append(ValidationIssue("warning", "unused_overdrive_field", "transfer.ion_overdrive_field_mv_cm", f"Electric field is not used by ion_method={method}"))
    if gate_field is not None and (fixed_vg is not None or legacy_vg is not None):
        issues.append(ValidationIssue("info", "gate_field_precedence", "transfer.ion_gate_field_mv_cm", "Electric field takes precedence over fixed gate voltage"))
    if field is not None and (voltage is not None or legacy_voltage is not None):
        issues.append(ValidationIssue("info", "field_precedence", "transfer.ion_overdrive_field_mv_cm", "Electric field takes precedence over voltage overdrive"))
    if fixed_vg is not None and legacy_vg is not None and float(fixed_vg) != float(legacy_vg):
        issues.append(ValidationIssue("error", "conflicting_fixed_vg", "transfer.ion_fixed_vg_v", "New and legacy fixed-Vg settings disagree"))
    if voltage is not None and legacy_voltage is not None and float(voltage) != float(legacy_voltage):
        issues.append(ValidationIssue("error", "conflicting_overdrive", "transfer.ion_overdrive_v", "New and legacy voltage-overdrive settings disagree"))

    tox = device.get("oxide_thickness_nm")
    if tox is not None and (not isinstance(tox, (int, float)) or float(tox) <= 0):
        issues.append(ValidationIssue("error", "invalid_oxide_thickness", "device_defaults.oxide_thickness_nm", "Oxide thickness must be positive"))
    film_thickness = device.get("film_thickness_nm")
    if film_thickness is not None and (not isinstance(film_thickness, (int, float)) or film_thickness <= 0):
        issues.append(ValidationIssue("error", "invalid_film_thickness", "device_defaults.film_thickness_nm", "Film thickness must be positive when specified"))
    polarity = str(device.get("polarity", "")).lower()
    allow_sign = bool(advanced.get("allow_ion_sign_mismatch", False))
    if field is not None and not allow_sign and ((polarity == "p" and float(field) > 0) or (polarity == "n" and float(field) < 0)):
        issues.append(ValidationIssue("warning", "ion_field_sign_mismatch", "transfer.ion_overdrive_field_mv_cm", f"Field sign is unusual for {polarity}-FET polarity"))
    if gate_field is not None and not allow_sign and ((polarity == "p" and float(gate_field) > 0) or (polarity == "n" and float(gate_field) < 0)):
        issues.append(ValidationIssue("warning", "ion_gate_field_sign_mismatch", "transfer.ion_gate_field_mv_cm", f"Gate-field sign is unusual for {polarity}-FET polarity"))

    window = int(transfer.get("savgol_window", 0) or 0)
    order = int(transfer.get("savgol_order", 1) or 1)
    vds_tolerance = transfer.get("vds_segmentation_tolerance_v", 1e-6)
    if not isinstance(vds_tolerance, (int, float)) or float(vds_tolerance) < 0:
        issues.append(ValidationIssue(
            "error", "invalid_vds_segmentation_tolerance",
            "transfer.vds_segmentation_tolerance_v",
            "Transfer Vds segmentation tolerance must be a non-negative voltage",
        ))
    if window and (window < 3 or window % 2 == 0 or window <= order):
        issues.append(ValidationIssue("error", "invalid_savgol_window", "transfer.savgol_window", "Savitzky-Golay window must be odd, at least 3, and greater than the polynomial order"))
    smooth_method = str(transfer.get("smooth_method", "savgol")).lower()
    if smooth_method not in {"savgol", "adaptive_savgol", "none", "gaussian"}:
        issues.append(ValidationIssue("error", "invalid_smooth_method", "transfer.smooth_method", "Choose savgol, adaptive_savgol, or none"))
    adaptive_min = float(transfer.get("adaptive_gm_min_fraction", 0.05))
    adaptive_max = float(transfer.get("adaptive_gm_max_fraction", 0.10))
    if not 0 < adaptive_min < adaptive_max < 1:
        issues.append(ValidationIssue("error", "invalid_adaptive_gm_bounds", "transfer.adaptive_gm_min_fraction", "Adaptive gm fractions must satisfy 0 < minimum < maximum < 1"))
    if float(transfer.get("adaptive_gm_peak_tolerance", 0.05)) <= 0:
        issues.append(ValidationIssue("error", "invalid_adaptive_gm_peak_tolerance", "transfer.adaptive_gm_peak_tolerance", "Adaptive gm peak tolerance must be positive"))
    if float(transfer.get("adaptive_gm_peak_shift_steps", 1.0)) < 0:
        issues.append(ValidationIssue("error", "invalid_adaptive_gm_peak_shift", "transfer.adaptive_gm_peak_shift_steps", "Adaptive gm peak shift limit cannot be negative"))
    if float(transfer.get("adaptive_gm_snr_plateau_tolerance", 0.10)) < 0:
        issues.append(ValidationIssue("error", "invalid_adaptive_gm_snr_tolerance", "transfer.adaptive_gm_snr_plateau_tolerance", "Adaptive gm SNR tolerance cannot be negative"))
    if int(transfer.get("adaptive_gm_stable_transitions", 2)) < 1:
        issues.append(ValidationIssue("error", "invalid_adaptive_gm_transitions", "transfer.adaptive_gm_stable_transitions", "Adaptive gm requires at least one stable transition"))
    min_lengths = int(tlm.get("min_channel_lengths", 3) or 0)
    if min_lengths < 3:
        issues.append(ValidationIssue("error", "invalid_tlm_min_lengths", "tlm.min_channel_lengths", "TLM requires at least three unique channel lengths"))
    tlm_mode = str(tlm.get("transfer_read_mode", "constant_vg")).lower()
    allowed_tlm_modes = {
        "maximum_current", "maximum_measured", "constant_vg", "constant_gate_field", "constant_overdrive",
        "constant_overdrive_field",
    }
    if tlm_mode not in allowed_tlm_modes:
        issues.append(ValidationIssue("error", "invalid_tlm_read_mode", "tlm.transfer_read_mode", f"Unsupported TLM transfer read mode {tlm_mode!r}"))
    mode = str(advanced.get("parameter_preflight_mode", "warning")).lower()
    if mode not in {"warning", "strict", "error"}:
        issues.append(ValidationIssue("error", "invalid_preflight_mode", "advanced.parameter_preflight_mode", "Choose warning, strict, or error"))
    dominance = float(advanced.get("gate_leakage_id_dominance_fraction", 0.90))
    if not 0 < dominance <= 1:
        issues.append(ValidationIssue("error", "invalid_gate_leakage_coverage", "advanced.gate_leakage_id_dominance_fraction", "Gate-leakage dominance coverage must be greater than 0 and at most 1"))
    sanity_fraction = float(advanced.get("sanity_sweep_fraction", 0.90))
    if not 0 < sanity_fraction <= 1:
        issues.append(ValidationIssue("error", "invalid_sanity_sweep_fraction", "advanced.sanity_sweep_fraction", "Sanity-check sweep fraction must be greater than 0 and at most 1"))
    if int(advanced.get("sanity_min_points", 10)) < 3:
        issues.append(ValidationIssue("error", "invalid_sanity_min_points", "advanced.sanity_min_points", "Sanity checks require at least three points"))
    for key in ("open_p95_current_a", "open_noise_floor_factor", "short_p10_ua_per_um", "short_flatness_ratio"):
        if float(advanced.get(key, 1.0)) <= 0:
            issues.append(ValidationIssue("error", f"invalid_{key}", f"advanced.{key}", f"{key} must be positive"))
    return ValidationReport(issues)


def validate_analysis_readiness(data: dict[str, Any]) -> ValidationReport:
    """Validate conditions that may remain incomplete while a GUI config is edited."""
    issues: list[ValidationIssue] = []
    transfer = data.get("transfer", {})
    method = str(transfer.get("ion_method", "maximum_measured")).lower()
    if method in {"fixed_vg", "constant_vg"} and all(
        transfer.get(key) is None
        for key in ("ion_fixed_vg_v", "ion_constant_vg_v", "ion_gate_field_mv_cm")
    ):
        issues.append(ValidationIssue(
            "error", "missing_fixed_vg", "transfer.ion_fixed_vg_v",
            "Set a constant Vg or constant gate electric field for the primary Ion read condition",
        ))
    return ValidationReport(issues)
