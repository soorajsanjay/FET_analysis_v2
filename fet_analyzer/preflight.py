"""Per-device parameter preflight and dependency-aware suppression."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class PreflightIssue:
    level: str
    code: str
    parameter: str
    affected_metrics: tuple[str, ...]
    message: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["affected_metrics"] = list(self.affected_metrics)
        return value


class ParameterPreflightError(ValueError):
    pass


DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "channel_width_um": ("mobility", "current_normalization", "tlm"),
    "channel_length_um": ("mobility", "tlm"),
    "oxide_thickness_nm": ("mobility", "ion_fixed_overdrive_field"),
    "dielectric_constant": ("mobility",),
}


def assess_parameter_preflight(
    values: dict[str, Any], sources: dict[str, str], config: dict[str, Any]
) -> dict[str, Any]:
    mode = str(config.get("advanced", {}).get("parameter_preflight_mode", "warning")).lower()
    issues: list[PreflightIssue] = []
    for parameter, affected in DEPENDENCIES.items():
        value = values.get(parameter)
        source = sources.get(parameter, "missing")
        if value is None:
            issues.append(PreflightIssue("error", "missing_parameter", parameter, affected, f"{parameter} is missing"))
        elif source == "template_default":
            issues.append(PreflightIssue("warning", "unconfirmed_parameter", parameter, affected, f"{parameter} uses an unconfirmed template value"))
    blockers = [item for item in issues if item.level == "error" or (mode in {"strict", "error"} and item.code == "unconfirmed_parameter")]
    if mode == "error" and blockers:
        raise ParameterPreflightError("; ".join(item.message for item in blockers))
    return {
        "mode": mode,
        "status": "blocked" if blockers else "warning" if issues else "pass",
        "issues": [item.to_dict() for item in issues],
        "suppressed_metrics": sorted({metric for item in blockers for metric in item.affected_metrics}) if mode == "strict" else [],
    }


def apply_preflight_suppression(metrics: dict[str, Any], preflight: dict[str, Any]) -> None:
    """Suppress only metrics whose required parameters are unconfirmed in strict mode."""
    suppressed = set(preflight.get("suppressed_metrics", []))
    if not suppressed:
        metrics["parameter_preflight"] = preflight
        return
    if "mobility" in suppressed:
        for result in metrics.get("sweep_results", []):
            if isinstance(result.get("mobility"), dict):
                result["mobility"]["mobility_cm2_vs"] = None
                result["mobility"].setdefault("warnings", []).append("Suppressed by strict parameter preflight")
        for result in metrics.get("per_bias_mobility", {}).values():
            if isinstance(result, dict):
                result["mobility_cm2_vs"] = None
        for key in ("mobility_cm2_vs_max", "mobility_cm2_vs_mean", "mobility_cm2_vs_std"):
            metrics.get("summary", {})[key] = None
    if "ion_fixed_overdrive_field" in suppressed:
        for result in metrics.get("sweep_results", []):
            current = result.get("current_summary", {})
            current["ion_const_vov_a"] = None
        for result in metrics.get("segments", {}).values():
            if isinstance(result, dict):
                result["ion_const_overdrive_a"] = None
    metrics["parameter_preflight"] = preflight
