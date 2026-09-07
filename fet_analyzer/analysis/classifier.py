"""
Measurement type classifier for FET data.

Determines whether a parsed dataset is a transfer curve (Id-Vg),
output characteristic (Id-Vd), general IV, or TLM structure.
"""

from __future__ import annotations

import re
from enum import Enum, auto
from pathlib import Path
from typing import Any

from fet_analyzer.utils.logging import LOGGER


class MeasurementType(Enum):
    """Classification of a FET measurement sweep."""
    TRANSFER = auto()          # Id vs Vg sweep (multiple Vd bias steps)
    OUTPUT = auto()            # Id vs Vd sweep (multiple Vg/Vbg bias steps)
    GENERAL_IV = auto()        # General IV curve (floating gate, diode, etc.)
    TLM = auto()               # TLM structure (multiple channel lengths)
    UNKNOWN = auto()


class Polarity(Enum):
    """Carrier type inferred from data."""
    N_TYPE = auto()            # Electrons: Id increases with positive Vg
    P_TYPE = auto()            # Holes: |Id| increases with negative Vg
    AMBIPOLAR = auto()         # Both signs of conduction
    UNKNOWN = auto()


def _detect_sweep_variable(columns: list[str], data: dict[str, list[float]]) -> str | None:
    """Detect the primary sweep (ramp) variable by looking for the column
    with the most monotonic change (simplest heuristic: widest range)."""
    candidates = [
        c for c in columns
        if c.lower() in {"vg", "vd", "vds", "vbg", "vs", "vb"}
        and c in data
    ]
    if not candidates:
        return None
    ranges = {}
    for c in candidates:
        vals = [v for v in data[c] if v == v]
        if vals:
            ranges[c] = max(vals) - min(vals)
    if not ranges:
        return None
    return max(ranges, key=ranges.get)


def _detect_bias_variable(columns: list[str], data: dict[str, list[float]],
                          sweep_var: str | None) -> str | None:
    """Detect the bias (fixed-step) variable — has multiple repeating values,
    fewer unique values, smaller range than sweep variable."""
    candidates = [
        c for c in columns
        if c.lower() in {"vg", "vd", "vds", "vbg", "vs", "vb"}
        and c in data and c != sweep_var
    ]
    if not candidates:
        return None
    # Pick the one with the fewest unique values (most "stepped"),
    # but exclude constant columns (need ≥2 unique values to be a bias)
    scored = []
    for c in candidates:
        uniq = len(set(round(v, 6) for v in data[c] if v == v))
        if uniq >= 1:
            sweep_is_gate = str(sweep_var).lower() in {"vg", "vbg"}
            if sweep_is_gate:
                # Vds is the direct physical bias.  When instruments expose
                # terminal voltages separately, Vd must be selected ahead of
                # a constant grounded Vs reference so Vd bias steps are not
                # hidden by the fewer-unique-values heuristic.
                role_rank = {"vds": 0, "vd": 1, "vs": 2}.get(c.lower(), 3)
                scored.append((role_rank, uniq, c))
            else:
                preferred = c.lower() in {"vg", "vbg"}
                scored.append((0 if preferred else 1, uniq, c))
    if not scored:
        return None
    best = min(scored)[2]
    return best


def _detect_secondary_sweep(columns: list[str], data: dict[str, list[float]],
                            sweep_var: str | None, bias_var: str | None) -> str | None:
    """Detect a secondary sweep variable — mid-range unique-value count."""
    candidates = [
        c for c in columns
        if c.lower() in {"vg", "vd", "vds", "vbg", "vs", "vb"}
        and c in data and c not in (sweep_var, bias_var)
    ]
    if not candidates:
        return None
    best = min(candidates, key=lambda c: len(set(
        round(v, 6) for v in data[c] if v == v
    )))
    return best


def parse_filename_groups(
    filename: str,
    patterns: dict[str, Any],
) -> dict[str, str]:
    """Parse filename using the configured regex pattern(s).

    Falls back to simple prefix-based detection if regex fails.
    Returns dict of named groups (measurement_type, sample_label, etc.).
    """
    result: dict[str, str] = {}

    if not patterns or not filename:
        return result

    # Get active pattern
    active_key = patterns.get("active", "")
    pattern_list = patterns.get("patterns", {})
    pattern_cfg = pattern_list.get(active_key, {})
    regex_str = pattern_cfg.get("regex", "")

    if regex_str:
        # Strip YAML block scalar noise
        regex_str = regex_str.strip()
        try:
            m = re.search(regex_str, filename, re.VERBOSE | re.IGNORECASE)
            if m:
                result = {k: v for k, v in m.groupdict().items() if v is not None}
        except re.error:
            pass

    # Fallback: simple prefix detection (handles both IdVg_ and Id-Vg_ styles)
    if "measurement_type" not in result:
        base = Path(filename).stem if isinstance(filename, str) else ""
        # Normalize: strip Telegram UUID suffix
        base = re.sub(r"---[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", "", base)

        # Try underscore-based pattern
        parts = base.split("_")
        if parts:
            first = parts[0].lower().replace("-", "_")
            result["measurement_type"] = parts[0]

    return result


def recover_filename_info_from_metadata(metadata: dict[str, Any]) -> dict[str, str]:
    """Recover naming fields from an instrument header as a fallback."""
    result: dict[str, str] = {}
    measurement_type = str(
        metadata.get("setup_title") or metadata.get("measurement_type") or ""
    ).strip()
    device_id = str(metadata.get("device_id") or "").strip()
    count = str(metadata.get("count") or "").strip()
    if measurement_type:
        result["measurement_type"] = measurement_type
    if device_id:
        result["device_id"] = device_id
        result["device_name"] = device_id
        sample = re.sub(
            r"_TLM\d*_\d+(?:\.\d+)?\s*(?:um|µm|μm)$", "", device_id,
            flags=re.IGNORECASE,
        )
        result["sample_label"] = sample or device_id
        tlm = re.search(
            r"(?:^|_)(TLM\d*)_(\d+(?:\.\d+)?)\s*(?:um|µm|μm)$",
            device_id, re.IGNORECASE,
        )
        if tlm:
            result["device_type"] = tlm.group(1)
            result["channel_length_um"] = tlm.group(2)
    if count:
        result["measurement_count"] = count
    result["naming_source"] = "csv_header"
    return result


def classify_measurement(
    metadata: dict[str, Any],
    columns: list[str],
    data: dict[str, list[float]],
    filename: str = "",
    filename_patterns: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify a parsed dataset.

    Returns a dict with:
        type: MeasurementType
        sweep_variable: name (e.g. 'Vg', 'Vd')
        bias_variable: name (e.g. 'Vd', 'Vbg')
        secondary_sweep: name or None
        drain_current_column: 'Id' or 'Is'
        drain_current_raw_column: un-abs'd column
        gate_current_column: 'Ig', 'Ibg', or None
        gate_leakage_column: abs column for leakage comparison
        polarity: Polarity
        confidence: 0.0–1.0
        reasoning: short explanation
    """
    result: dict[str, Any] = {
        "type": MeasurementType.UNKNOWN,
        "sweep_variable": None,
        "bias_variable": None,
        "secondary_sweep": None,
        "drain_current_column": "Id",
        "drain_current_raw_column": "Id",
        "gate_current_column": None,
        "gate_leakage_column": None,
        "polarity": Polarity.UNKNOWN,
        "confidence": 0.0,
        "reasoning": "",
        "filename_info": {},
    }

    # ── Step 1: parse filename (PRIMARY source) ──────────────────────────
    meas_type = ""
    filename_info: dict[str, str] = {}

    if filename and filename_patterns:
        filename_info = parse_filename_groups(filename, filename_patterns)
        if not filename_info.get("sample_label"):
            recovered = recover_filename_info_from_metadata(metadata)
            if recovered:
                filename_info = recovered
        else:
            filename_info.setdefault("naming_source", "filename")
        meas_type = filename_info.get("measurement_type", "").lower()
        LOGGER.debug("Filename parsed: %s → measurement_type='%s'", filename, meas_type)

    # Header identity is used only when the configured filename pattern did
    # not match; valid filename fields always retain precedence.

    # Normalize common naming conventions
    is_transfer_name = any(t in meas_type.replace("-", "_") for t in (
        "idvg", "id_vg", "transfer", "id_vg", "id-vg",
    ))
    is_output_name = any(t in meas_type.replace("-", "_") for t in (
        "idvd", "id_vd", "output", "id_vd", "id-vd",
    ))
    is_general_name = any(t in meas_type for t in (
        "iv", "i-v", "general",
    ))
    is_tlm_name = "tlm" in meas_type
    filename_stem = Path(filename).stem if filename else ""
    # LTLM is an explicit measurement contract: these files are ungated
    # longitudinal TLM IV sweeps even when an instrument export contains an
    # incidental gate column or misleading setup metadata.
    is_explicit_ltlm = bool(re.match(r"^ltlm(?:_|-|$)", filename_stem, re.I))

    # A TLM-named transfer or output file should carry the is_tlm flag
    # for R_total extraction, even when primary type is TRANSFER/OUTPUT
    result["is_tlm"] = is_tlm_name or (filename and "tlm" in filename.lower())
    result["is_explicit_ltlm"] = is_explicit_ltlm

    # Store parsed filename info in result
    result["filename_info"] = filename_info

    # ── Step 2: detect sweep/bias variables from column content ───────────
    cols_lower = {c.lower(): c for c in columns}
    sweep = _detect_sweep_variable(columns, data)
    bias = _detect_bias_variable(columns, data, sweep)
    secondary = _detect_secondary_sweep(columns, data, sweep, bias)

    result["sweep_variable"] = sweep
    result["bias_variable"] = bias
    result["secondary_sweep"] = secondary

    # ── Step 3: identify current columns ──────────────────────────────────
    # Gate current
    for gc in ("ig", "ibg"):
        if gc in cols_lower:
            result["gate_current_column"] = cols_lower[gc]
            break
    # Gate leakage (absolute)
    for gl in ("absig", "abs_ig", "absibg", "abs_ibg"):
        if gl in cols_lower:
            result["gate_leakage_column"] = cols_lower[gl]
            break
    if result["gate_leakage_column"] is None and result["gate_current_column"]:
        result["gate_leakage_column"] = result["gate_current_column"]

    # Drain current — prefer Is if present and Id is absent
    drain_col = "Id"
    if "id" in cols_lower:
        drain_col = cols_lower["id"]
    elif "is" in cols_lower:
        drain_col = cols_lower["is"]
    result["drain_current_raw_column"] = drain_col
    # Use absId if available (handles p-type convention)
    abs_col = "absid" if "absid" in cols_lower else "abs_id"
    if abs_col in cols_lower:
        result["drain_current_column"] = cols_lower[abs_col]
    else:
        result["drain_current_column"] = drain_col

    # ── Step 4: classify by sweep variable identity ────────────────────────
    # IMPORTANT: filename takes priority over sweep-variable heuristic.
    # Example: IdVd measurement where Vbg sweep range > Vd range —
    # sweep detector would pick Vbg, but filename says "output characteristic".
    if is_output_name:
        result["type"] = MeasurementType.OUTPUT
        result["confidence"] = 0.95
        result["reasoning"] = f"Filename says output characteristic ({meas_type})"
        # Re-derive sweep variable: for output, the x-axis is Vd
        if "vd" in cols_lower:
            result["sweep_variable"] = cols_lower["vd"]
        # An output curve is Id(Vd) at fixed gate steps.  Do not retain Vd
        # as its own bias variable after overriding the sweep axis.
        if "vbg" in cols_lower:
            result["bias_variable"] = cols_lower["vbg"]
        elif "vg" in cols_lower:
            result["bias_variable"] = cols_lower["vg"]
        else:
            result["bias_variable"] = None

    elif is_transfer_name:
        result["type"] = MeasurementType.TRANSFER
        result["confidence"] = 0.95
        result["reasoning"] = f"Filename says transfer ({meas_type})"

    elif sweep:
        sweep_lower = sweep.lower()

        if sweep_lower in ("vg", "vbg"):
            if bias and bias.lower() in ("vd", "vs"):
                result["type"] = MeasurementType.TRANSFER
                result["confidence"] = 0.95
                result["reasoning"] = (
                    f"Sweep={sweep} (gate), bias={bias} (drain) → transfer"
                )
            else:
                result["type"] = MeasurementType.TRANSFER
                result["confidence"] = 0.85
                result["reasoning"] = (
                    f"Sweep={sweep} (gate), no drain bias step → transfer"
                )

        elif sweep_lower in ("vd", "vs"):
            if bias and bias.lower() in ("vg", "vbg"):
                result["type"] = MeasurementType.OUTPUT
                result["confidence"] = 0.95
                result["reasoning"] = (
                    f"Sweep={sweep} (drain), bias={bias} (gate) → output characteristic"
                )
            else:
                result["type"] = MeasurementType.OUTPUT
                result["confidence"] = 0.80
                result["reasoning"] = (
                    f"Sweep={sweep} (drain), no gate step → output (or general IV)"
                )

        elif sweep_lower == "vb":
            result["type"] = MeasurementType.GENERAL_IV
            result["confidence"] = 0.90
            result["reasoning"] = f"Sweep={sweep} (body/bulk) → general IV"

        else:
            result["type"] = MeasurementType.GENERAL_IV
            result["confidence"] = 0.50
            result["reasoning"] = f"Unknown sweep variable: {sweep}"

    # ── Step 6: detect polarity from Id vs sweep direction ─────────────────
    if sweep and result["drain_current_raw_column"] in data:
        sweep_vals = data[sweep]
        id_vals = data[result["drain_current_raw_column"]]

        # Check if |Id| grows with positive or negative sweep
        sweep_mid = len(sweep_vals) // 2
        if sweep_mid > 0:
            first_half_id = [abs(v) for v in id_vals[:sweep_mid] if v == v]
            second_half_id = [abs(v) for v in id_vals[sweep_mid:] if v == v]
            if first_half_id and second_half_id:
                avg_first = sum(first_half_id) / len(first_half_id)
                avg_second = sum(second_half_id) / len(second_half_id)
                if avg_second > avg_first * 1.5:
                    # |Id| larger in second half → where is sweep going?
                    if sweep_vals[sweep_mid] > 0:
                        result["polarity"] = Polarity.N_TYPE
                    else:
                        result["polarity"] = Polarity.P_TYPE
                elif avg_first > avg_second * 1.5:
                    if sweep_vals[0] > 0:
                        result["polarity"] = Polarity.N_TYPE
                    else:
                        result["polarity"] = Polarity.P_TYPE

    # ── Step 7: TLM detection from filename ───────────────────────────────
    if is_tlm_name or (filename and "tlm" in filename.lower()):
        # TLM can be a modifier on transfer/output, don't override type
        if result["type"] == MeasurementType.UNKNOWN:
            result["type"] = MeasurementType.TLM

    if result["is_tlm"]:
        has_gate_column = any(column.lower() in {"vg", "vbg"} for column in columns)
        sweep_lower = str(result.get("sweep_variable") or "").lower()
        ungated = is_explicit_ltlm or (sweep_lower in {"vd", "vs"} and not has_gate_column)
        result["is_ungated_tlm"] = ungated
        result["tlm_analysis_mode"] = "ungated" if ungated else "gated"
        result["tlm_role"] = (
            "ungated_ltlm" if ungated else
            "gated_transfer" if sweep_lower in {"vg", "vbg"} else
            "output_sanity"
        )

    return result


def detect_sweep_direction(vg_values: list[float]) -> str:
    """Detect sweep direction: 'forward', 'reverse', or 'single'.

    Forward = first derivative of Vg values is monotonic in one direction.
    If it changes sign midway, the sweep is bidirectional.
    """
    if len(vg_values) < 2:
        return "single"

    diffs = []
    for i in range(1, len(vg_values)):
        if vg_values[i] == vg_values[i] and vg_values[i - 1] == vg_values[i - 1]:
            diffs.append(vg_values[i] - vg_values[i - 1])

    if not diffs:
        return "single"

    # If all diffs have the same sign, it's a single sweep
    signs = [d > 0 for d in diffs]
    if all(signs) or not any(signs):
        return "forward"

    # Check if direction changes at a clear turning point
    # A bidirectional sweep will have roughly equal segments
    sign_changes = sum(1 for i in range(1, len(signs)) if signs[i] != signs[i - 1])
    if sign_changes <= 2:
        return "bidirectional"

    return "noisy"
