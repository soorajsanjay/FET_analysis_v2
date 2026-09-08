"""Master TSV device-parameter loading and deterministic resolution."""
from __future__ import annotations
import csv
import fnmatch
from copy import deepcopy
from pathlib import Path
from typing import Any

from fet_analyzer.path_utils import prepare_write_path, safe_path

IDENTITY_COLUMNS = {"sample_label", "device_pattern", "parameter_set_name", "notes"}
NUMERIC_COLUMNS = {"channel_width_um", "channel_length_um", "gate_length_um", "oxide_thickness_nm", "film_thickness_nm",
                   "dielectric_constant", "cox_f_per_cm2", "contact_length_um", "contact_width_um",
                   "temperature_k", "temperature_c", "noise_floor_a"}
BOOLEAN_COLUMNS = {"top_gated"}
TEXT_COLUMNS = {"polarity", "gate_dielectric", "contact_metal", "substrate"}
ALLOWED_COLUMNS = IDENTITY_COLUMNS | NUMERIC_COLUMNS | BOOLEAN_COLUMNS | TEXT_COLUMNS
DEVICE_PARAMETER_COLUMNS = [
    "sample_label", "device_pattern", "polarity", "channel_width_um",
    "channel_length_um", "gate_length_um", "oxide_thickness_nm",
    "film_thickness_nm", "dielectric_constant", "cox_f_per_cm2",
    "gate_dielectric", "contact_metal", "contact_length_um",
    "contact_width_um", "substrate", "top_gated", "temperature_k",
    "temperature_c", "noise_floor_a", "parameter_set_name", "notes",
]

def write_master_template(path: Path, defaults: dict[str, Any]) -> None:
    if path.exists(): return
    columns = DEVICE_PARAMETER_COLUMNS
    row: dict[str, Any] = {key: "" for key in columns}
    row.update({"sample_label": "*", "device_pattern": "*", "polarity": "p",
                "parameter_set_name": "TEMPLATE_UNCONFIRMED"})
    for key in columns:
        if defaults.get(key) is not None: row[key] = defaults[key]
    if defaults.get("temperature_c") is not None: row["temperature_k"] = float(defaults["temperature_c"]) + 273.15
    with prepare_write_path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t"); writer.writeheader(); writer.writerow(row)

def load_master_table(path: Path) -> list[dict[str, str]]:
    with safe_path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fieldnames = list(reader.fieldnames or [])
        raw_rows = [dict(row) for row in reader]
    if "film_thickness_nm" not in fieldnames:
        insert_at = fieldnames.index("oxide_thickness_nm") + 1 if "oxide_thickness_nm" in fieldnames else len(fieldnames)
        fieldnames.insert(insert_at, "film_thickness_nm")
        for row in raw_rows: row["film_thickness_nm"] = ""
        with prepare_write_path(path).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
            writer.writeheader(); writer.writerows(raw_rows)
    headers = set(fieldnames)
    rows = raw_rows
    unknown = sorted(headers - ALLOWED_COLUMNS)
    if unknown: raise ValueError(f"Unknown device parameter column(s): {', '.join(unknown)}")
    if not {"sample_label", "device_pattern"}.issubset(headers):
        raise ValueError("device_parameters.txt requires sample_label and device_pattern columns")
    return [{str(k): (v or "").strip() for k, v in row.items()} for row in rows]

def synchronize_sample_rows(path: Path, sample_labels: list[str]) -> list[str]:
    """Append one provisional sample-wide row for every newly detected sample."""
    with safe_path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    existing = {(row.get("sample_label") or "").casefold()
                for row in rows if (row.get("device_pattern") or "*") == "*"}
    global_row = next((row for row in rows if (row.get("sample_label") or "") == "*"
                       and (row.get("device_pattern") or "*") == "*"), {})
    added: list[str] = []
    for label in sorted({str(item).strip() for item in sample_labels if str(item).strip()}, key=str.casefold):
        if label.casefold() in existing:
            continue
        new_row = {key: global_row.get(key, "") for key in fieldnames}
        new_row["sample_label"], new_row["device_pattern"] = label, "*"
        if "parameter_set_name" in new_row:
            new_row["parameter_set_name"] = "TEMPLATE_UNCONFIRMED"
        if "notes" in new_row:
            new_row["notes"] = "Auto-added from detected filenames; review values before publication."
        rows.append(new_row); existing.add(label.casefold()); added.append(label)
    if added:
        with prepare_write_path(path).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
            writer.writeheader(); writer.writerows(rows)
    return added

def _coerce(key: str, value: str) -> Any:
    if key in NUMERIC_COLUMNS: return float(value)
    if key in BOOLEAN_COLUMNS:
        lowered = value.lower()
        if lowered not in {"true", "false", "1", "0", "yes", "no"}: raise ValueError(f"Invalid boolean {key}={value!r}")
        return lowered in {"true", "1", "yes"}
    if key == "polarity":
        polarity = value.lower()
        if polarity not in {"p", "n"}: raise ValueError(f"polarity must be 'p' or 'n', got {value!r}")
        return polarity
    return value

def resolve_device_parameters(defaults: dict[str, Any], rows: list[dict[str, str]], sample_label: str,
                              filename: str, inferred: dict[str, Any] | None = None,
                              inferred_sources: dict[str, str] | None = None
                              ) -> tuple[dict[str, Any], dict[str, str], list[dict[str, str]]]:
    values = deepcopy(defaults)
    sources = {key: "template_default" for key, value in values.items() if value is not None}
    warnings: list[dict[str, str]] = []
    for key, value in (inferred or {}).items():
        if value is not None: values[key], sources[key] = value, (inferred_sources or {}).get(key, "inferred")
    candidates = []; sample_cf, filename_cf = sample_label.casefold(), filename.casefold()
    for line, row in enumerate(rows, 2):
        row_sample = (row.get("sample_label") or "*").casefold(); pattern = row.get("device_pattern") or "*"
        if row_sample not in {"*", sample_cf} or not fnmatch.fnmatchcase(filename_cf, pattern.casefold()): continue
        exact = 2 if pattern.casefold() == filename_cf else 1
        literal = len(pattern.replace("*", "").replace("?", ""))
        candidates.append(((1 if row_sample == sample_cf else 0, exact, literal), line, row))
    candidates.sort(key=lambda item: item[0]); seen: dict[tuple[Any, str], Any] = {}
    for rank, line, row in candidates:
        for key, raw in row.items():
            if key in IDENTITY_COLUMNS or raw == "": continue
            value = _coerce(key, raw); conflict = rank, key
            if conflict in seen and seen[conflict] != value: raise ValueError(f"Conflicting equally specific rows for {filename}: {key} at line {line}")
            seen[conflict] = value
            is_template = row.get("parameter_set_name", "").upper() == "TEMPLATE_UNCONFIRMED"
            # Auto-generated template rows are defaults, not confirmed evidence.
            # Preserve explicit filename/metadata values until a user confirms a row.
            if is_template and key in sources and sources[key] != "template_default":
                continue
            values[key] = value
            sources[key] = "template_default" if is_template else f"device_parameters.txt:line_{line}"
    if values.get("temperature_k") is not None:
        values["temperature_c"] = float(values["temperature_k"]) - 273.15; sources["temperature_c"] = sources.get("temperature_k", "resolved")
    if values.get("polarity") not in {"p", "n"}:
        values["polarity"], sources["polarity"] = "p", "configured_default"
        warnings.append({"code": "polarity_defaulted", "level": "warning", "message": "Polarity was not specified; p-type default was used."})
    for key, source in sorted(sources.items()):
        if source == "template_default": warnings.append({"code": "template_parameter_used", "level": "warning", "parameter": key, "message": f"{key} uses an unconfirmed template value."})
    return values, sources, warnings
