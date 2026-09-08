"""Central, editable measurement-filename conventions.

The tables near the top of this module are the built-in conventions shared by
the CLI, dashboard, preflight, and TLM workflows.  Add stable conventions here;
use ``filename_patterns`` or ``tlm.lch_regex`` in project YAML for local rules.

Examples
--------
>>> parse_filename_conventions("IdVg_S_TLM1_25um.csv").parameters["channel_length_um"]
25.0
>>> parse_filename_conventions("IdVg_S_TLM1_CL25_GL20_CW100.csv").parameters
{'channel_length_um': 25.0, 'channel_width_um': 100.0, 'gate_length_um': 20.0}
>>> parse_filename_conventions("IdVg_S_CL10_GL8_CW50.csv").is_tlm
False
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from pathlib import Path
import re
from typing import Any


# Edit this declarative registry when a convention is stable across projects.
# Longer aliases are deliberately listed first. Short L/W aliases are protected
# by token boundaries so they cannot match letters embedded in sample names.
PARAMETER_CONVENTIONS: tuple[dict[str, Any], ...] = (
    {"key": "channel_length_um", "name": "Electrical channel length", "unit": "um",
     "aliases": ("channel_length", "Lch", "CL", "L"), "unlabelled_tlm": True,
     "priority": 30, "positive_finite": True},
    {"key": "channel_width_um", "name": "Electrical channel width", "unit": "um",
     "aliases": ("channel_width", "width", "Wch", "CW", "W"), "unlabelled_tlm": False,
     "priority": 30, "positive_finite": True},
    {"key": "gate_length_um", "name": "Gate length", "unit": "um",
     "aliases": ("gate_length", "Lg", "GL"), "unlabelled_tlm": False,
     "priority": 30, "positive_finite": True},
    {"key": "oxide_thickness_nm", "name": "Gate oxide thickness", "unit": "nm",
     "aliases": ("oxide_thickness", "oxide", "tox"), "unlabelled_tlm": False,
     "priority": 30, "positive_finite": True},
    {"key": "film_thickness_nm", "name": "Semiconductor or film thickness", "unit": "nm",
     "aliases": ("semiconductor_thickness", "film_thickness", "tfilm"),
     "unlabelled_tlm": False, "priority": 30, "positive_finite": True},
)

_NUMBER = r"(?:[-+]?(?:\d+(?:\.\d*)?|\.\d+)|[-+]?(?:inf(?:inity)?|nan))"
_MICROMETRE = r"(?:um|µm|μm)"


@dataclass
class FilenameFacts:
    original_filename: str
    stem: str
    measurement_type_hint: str | None = None
    sample_label: str | None = None
    device_id: str | None = None
    is_tlm: bool = False
    is_ltlm: bool = False
    tlm_id: str | None = None
    parameters: dict[str, float] = field(default_factory=dict)
    parameter_sources: dict[str, str] = field(default_factory=dict)
    candidates: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    warnings: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    configured_groups: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def filename_info(self) -> dict[str, str]:
        info = dict(self.configured_groups)
        if self.measurement_type_hint:
            info.setdefault("measurement_type", self.measurement_type_hint)
        if self.sample_label:
            info.setdefault("sample_label", self.sample_label)
        if self.device_id:
            info.setdefault("device_id", self.device_id)
            info.setdefault("device_name", self.device_id)
        if self.tlm_id:
            info.setdefault("device_type", self.tlm_id)
            info.setdefault("tlm_id", self.tlm_id)
        if "channel_length_um" in self.parameters:
            info.setdefault("channel_length_um", f"{self.parameters['channel_length_um']:g}")
        info.setdefault("naming_source", "filename")
        return info


def _configured_groups(filename: str, patterns: dict[str, Any] | None,
                       warnings: list[dict[str, str]]) -> dict[str, str]:
    if not patterns:
        return {}
    active = str(patterns.get("active", ""))
    pattern_cfg = patterns.get("patterns", {}).get(active, {})
    expression = str(pattern_cfg.get("regex", "")).strip()
    if not expression:
        return {}
    try:
        match = re.search(expression, filename, re.VERBOSE | re.IGNORECASE)
    except re.error as exc:
        warnings.append({"code": "invalid_filename_regex", "message":
                         f"filename_patterns.{active or 'active'} is invalid: {exc}"})
        return {}
    return ({key: value for key, value in match.groupdict().items() if value is not None}
            if match else {})


def _add_error(facts: FilenameFacts, code: str, message: str, parameter: str | None = None) -> None:
    item = {"code": code, "message": message}
    if parameter:
        item["parameter"] = parameter
    facts.errors.append(item)


def _valid_value(raw: str, *, parameter: str, facts: FilenameFacts) -> float | None:
    try:
        value = float(raw)
    except ValueError:
        value = math.nan
    if not math.isfinite(value) or value <= 0:
        _add_error(facts, "invalid_filename_parameter",
                   f"{parameter} has invalid filename value {raw!r}; use a finite value greater than zero.", parameter)
        return None
    return value


def parse_filename_conventions(
    filename: str | Path,
    *,
    configured_filename_patterns: dict[str, Any] | None = None,
    configured_lch_regex: str | None = None,
) -> FilenameFacts:
    """Parse identity and normalized geometry from a filename only."""
    original = str(filename)
    name = Path(original).name
    stem = Path(name).stem
    facts = FilenameFacts(original_filename=original, stem=stem)
    facts.configured_groups = _configured_groups(name, configured_filename_patterns, facts.warnings)
    facts.measurement_type_hint = facts.configured_groups.get("measurement_type")
    facts.sample_label = facts.configured_groups.get("sample_label")
    facts.device_id = facts.configured_groups.get("device_id") or facts.configured_groups.get("device_name")
    if not facts.measurement_type_hint:
        cleaned = re.sub(r"---[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$", "", stem, flags=re.I)
        facts.measurement_type_hint = re.split(r"_", cleaned, maxsplit=1)[0] if cleaned else None

    facts.is_tlm = "tlm" in stem.casefold()
    facts.is_ltlm = "ltlm" in stem.casefold()
    tlm_matches = re.findall(r"TLM\d*", stem, re.IGNORECASE)
    numbered = next((item for item in tlm_matches if re.search(r"\d", item)), None)
    facts.tlm_id = numbered.upper() if numbered else ("LTLM" if facts.is_ltlm else "TLM" if facts.is_tlm else None)
    facts.device_id = facts.device_id or stem
    if facts.is_tlm and not facts.sample_label:
        prefix = re.split(r"LTLM|TLM\d*", stem, maxsplit=1, flags=re.I)[0].rstrip("_- ")
        if "__" in prefix:
            prefix = prefix.split("__", 1)[1]
        prefix = re.sub(rf"(?:^|[_-]){_NUMBER}\s*{_MICROMETRE}(?=$|[_-])", "", prefix, flags=re.I)
        facts.sample_label = prefix.strip("_- ") or "unknown"

    occupied: list[tuple[int, int]] = []
    explicit: dict[str, list[tuple[float, str, tuple[int, int]]]] = {}
    for convention in PARAMETER_CONVENTIONS:
        key, unit = convention["key"], convention["unit"]
        unit_pattern = _MICROMETRE if unit == "um" else r"nm"
        aliases = sorted(convention["aliases"], key=len, reverse=True)
        alias_pattern = "|".join(re.escape(alias) for alias in aliases)
        pattern = re.compile(
            rf"(?<![A-Za-z0-9])(?P<label>{alias_pattern})(?:_|-)?(?P<value>{_NUMBER})\s*(?P<unit>{unit_pattern})?(?![A-Za-z0-9])",
            re.IGNORECASE,
        )
        for match in pattern.finditer(stem):
            value = _valid_value(match.group("value"), parameter=key, facts=facts)
            occupied.append(match.span())
            candidate = {"value": value, "raw": match.group(0), "label": match.group("label"),
                         "source": f"filename:{match.group('label')}", "status": "valid" if value is not None else "invalid"}
            facts.candidates.setdefault(key, []).append(candidate)
            if value is not None:
                explicit.setdefault(key, []).append((value, match.group("label"), match.span()))
        empty_pattern = re.compile(
            rf"(?<![A-Za-z0-9])(?P<label>{alias_pattern})(?:_|-)?(?=$|[_-])",
            re.IGNORECASE,
        )
        for match in empty_pattern.finditer(stem):
            if any(match.start() >= start and match.end() <= end for start, end in occupied):
                continue
            occupied.append(match.span())
            facts.candidates.setdefault(key, []).append({
                "value": None, "raw": match.group(0), "label": match.group("label"),
                "source": f"filename:{match.group('label')}", "status": "invalid",
            })
            _add_error(facts, "invalid_filename_parameter",
                       f"{key} label {match.group('label')!r} has no numeric value.", key)

    configured_value: float | None = None
    if configured_lch_regex:
        try:
            configured_match = re.search(configured_lch_regex.strip(), stem, re.IGNORECASE | re.VERBOSE)
            if configured_match:
                if configured_match.lastindex is None:
                    facts.warnings.append({"code": "lch_regex_no_capture", "message":
                                           "tlm.lch_regex matched but has no capture group for channel length."})
                else:
                    configured_value = _valid_value(configured_match.group(1), parameter="channel_length_um", facts=facts)
                    if configured_value is not None:
                        facts.candidates.setdefault("channel_length_um", []).append({
                            "value": configured_value, "raw": configured_match.group(0),
                            "label": "tlm.lch_regex", "source": "filename:tlm.lch_regex", "status": "valid"})
        except re.error as exc:
            facts.warnings.append({"code": "invalid_lch_regex", "message": f"tlm.lch_regex is invalid: {exc}"})

    for key, matches in explicit.items():
        unique = sorted({value for value, _label, _span in matches})
        if len(unique) > 1 and not (key == "channel_length_um" and configured_value is not None):
            labels = ", ".join(f"{label}={value:g}" for value, label, _span in matches)
            _add_error(facts, "conflicting_filename_parameter",
                       f"Conflicting {key} values in filename: {labels}.", key)
            continue
        value, label, _span = matches[0]
        facts.parameters[key] = value
        facts.parameter_sources[key] = f"filename:{label}"

    if configured_value is not None:
        facts.parameters["channel_length_um"] = configured_value
        facts.parameter_sources["channel_length_um"] = "filename:tlm.lch_regex"

    if facts.is_tlm and "channel_length_um" not in facts.parameters:
        generic: list[float] = []
        for match in re.finditer(rf"(?<![A-Za-z0-9])(?P<value>{_NUMBER})\s*{_MICROMETRE}(?![A-Za-z0-9])", stem, re.I):
            if any(match.start() >= start and match.end() <= end for start, end in occupied):
                continue
            value = _valid_value(match.group("value"), parameter="channel_length_um", facts=facts)
            facts.candidates.setdefault("channel_length_um", []).append({
                "value": value, "raw": match.group(0), "label": "unlabelled_tlm_length",
                "source": "filename:unlabelled_tlm_length", "status": "valid" if value is not None else "invalid"})
            if value is not None:
                generic.append(value)
        unique = sorted(set(generic))
        if len(unique) == 1:
            facts.parameters["channel_length_um"] = unique[0]
            facts.parameter_sources["channel_length_um"] = "filename:unlabelled_tlm_length"
        elif len(unique) > 1:
            _add_error(facts, "ambiguous_tlm_channel_length",
                       "Multiple unlabelled TLM channel-length candidates were found: " +
                       ", ".join(f"{value:g} um" for value in unique) +
                       ". Add CL<number>, configure tlm.lch_regex, or use device_parameters.txt.",
                       "channel_length_um")

    return facts


__all__ = ["FilenameFacts", "PARAMETER_CONVENTIONS", "parse_filename_conventions"]
