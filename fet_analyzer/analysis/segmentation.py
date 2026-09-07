"""
Sweep segmentation: splits bidirectional sweeps into forward/reverse,
groups data by bias level, and produces clean per-segment DataFrames.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median, pstdev
from typing import Any


@dataclass
class SweepSegment:
    """A single monotonic sweep segment at one bias level."""
    direction: str               # "forward" or "reverse"
    bias_level: float | None     # Bias voltage value (e.g. Vd for transfer)
    bias_variable: str | None    # Name of the bias column
    sweep_variable: str          # Name of the sweep column
    sweep_values: list[float] = field(default_factory=list)
    data: dict[str, list[float]] = field(default_factory=dict)
    start_index: int = 0         # Index in original dataset
    end_index: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    measured_vd_v: float | None = None
    measured_vs_v: float | None = None
    measured_vds_v: float | None = None
    vds_reference: str | None = None
    measured_vds_spread_v: float | None = None
    measured_vds_n: int = 0

    def __len__(self) -> int:
        return len(self.sweep_values)


def _find_direction_flips(sweep_values: list[float]) -> list[int]:
    """Find indices where sweep direction changes.

    A direction flip occurs when the sign of the first derivative changes.
    Returns list of flip indices (inclusive of last point of previous segment).
    """
    if len(sweep_values) < 3:
        return []

    diffs = []
    for i in range(1, len(sweep_values)):
        if sweep_values[i] == sweep_values[i] and sweep_values[i - 1] == sweep_values[i - 1]:
            diffs.append(sweep_values[i] - sweep_values[i - 1])
        else:
            diffs.append(0.0)

    # Find sign changes
    flips = []
    prev_sign = None
    for i, d in enumerate(diffs):
        if d == 0:
            continue
        sign = d > 0
        if prev_sign is not None and sign != prev_sign:
            # Direction flipped at index i (diff index → original index i+1 is start of new)
            flips.append(i)  # inclusive: diffs[i] is the last diff before flip
        prev_sign = sign

    if not flips:
        return []

    # Start the new segment at the turnaround value. This keeps one copy of the
    # endpoint with each directional sweep after slicing and avoids losing the
    # first usable derivative point.
    return flips


def _find_bias_transitions(bias_values: list[float], min_step_pct: float = 0.01) -> list[int]:
    """Find indices where the bias level changes significantly.

    Returns indices where a new bias level starts (inclusive).
    """
    if len(bias_values) < 2:
        return []

    transitions = [0]  # first bias level starts at index 0
    current = bias_values[0]
    for i in range(1, len(bias_values)):
        if bias_values[i] != bias_values[i]:
            continue
        if abs(current) > 1e-12:
            pct_change = abs(bias_values[i] - current) / abs(current)
        else:
            pct_change = abs(bias_values[i] - current)
        if pct_change > min_step_pct:
            transitions.append(i)
            current = bias_values[i]

    return transitions


def _finite_values(values: list[float]) -> list[float]:
    return [float(value) for value in values if value == value]


def measured_vds_rows(data: dict[str, list[float]]) -> tuple[list[float | None], str | None]:
    """Return physical measured Vds for every row without assuming ground."""
    columns = {key.lower(): key for key in data}
    row_count = max((len(values) for values in data.values()), default=0)
    direct = data.get(columns.get("vds", ""), [])
    if direct:
        return [
            float(direct[index])
            if index < len(direct) and direct[index] == direct[index] else None
            for index in range(row_count)
        ], "Vds measured directly"
    vd = data.get(columns.get("vd", ""), [])
    vs = data.get(columns.get("vs", ""), [])
    if vd and vs:
        result: list[float | None] = []
        for index in range(row_count):
            if (
                index < len(vd) and index < len(vs)
                and vd[index] == vd[index] and vs[index] == vs[index]
            ):
                result.append(float(vd[index]) - float(vs[index]))
            else:
                result.append(None)
        return result, "Vd and Vs measured; Vds = Vd - Vs"
    return [None] * row_count, None


def measured_vds_profile(
    data: dict[str, list[float]], tolerance_v: float = 1e-6,
) -> dict[str, Any]:
    """Profile row-level physical Vds and state whether one bias is present."""
    values, source = measured_vds_rows(data)
    finite = [float(value) for value in values if value is not None]
    missing = len(values) - len(finite)
    if not finite:
        return {
            "source": source, "values_v": values, "measured_vds_v": None,
            "min_v": None, "max_v": None, "spread_v": None,
            "valid_n": 0, "missing_n": missing, "bias_homogeneous": False,
            "reason": "physical measured Vds unavailable",
        }
    low, high = min(finite), max(finite)
    spread = high - low
    homogeneous = missing == 0 and spread <= max(float(tolerance_v), 0.0)
    reason = None
    if missing:
        reason = f"physical measured Vds missing for {missing} row(s)"
    elif not homogeneous:
        reason = (
            f"mixed measured drain bias (Vds range {low:g} to {high:g} V; "
            f"spread {spread:g} V exceeds tolerance {float(tolerance_v):g} V)"
        )
    return {
        "source": source, "values_v": values,
        "measured_vds_v": float(median(finite)),
        "min_v": low, "max_v": high, "spread_v": spread,
        "valid_n": len(finite), "missing_n": missing,
        "bias_homogeneous": homogeneous, "reason": reason,
    }


def _find_measured_vds_transitions(
    values: list[float | None], tolerance_v: float,
) -> list[int]:
    """Find contiguous physical-bias runs using a robust running median."""
    if not values:
        return [0]
    tolerance = max(float(tolerance_v), 0.0)
    transitions = [0]
    run: list[float] = []
    run_is_missing = values[0] is None
    if values[0] is not None:
        run.append(float(values[0]))
    for index, value in enumerate(values[1:], 1):
        is_missing = value is None
        changed = is_missing != run_is_missing
        if not changed and not is_missing:
            changed = abs(float(value) - float(median(run))) > tolerance
        if changed:
            transitions.append(index)
            run = []
            run_is_missing = is_missing
        if value is not None:
            run.append(float(value))
    return transitions


def _measured_vds(data: dict[str, list[float]], start: int, end: int) -> dict[str, Any]:
    """Resolve measured Vds without inventing an unrecorded terminal voltage."""
    columns = {key.lower(): key for key in data}
    vds_values = _finite_values(data.get(columns.get("vds", ""), [])[start:end])
    vd_values = _finite_values(data.get(columns.get("vd", ""), [])[start:end])
    vs_values = _finite_values(data.get(columns.get("vs", ""), [])[start:end])
    vd = float(median(vd_values)) if vd_values else None
    vs = float(median(vs_values)) if vs_values else None
    if vds_values:
        return {
            "measured_vd_v": vd,
            "measured_vs_v": vs,
            "measured_vds_v": float(median(vds_values)),
            "vds_reference": "Vds measured directly",
            "measured_vds_spread_v": float(pstdev(vds_values)) if len(vds_values) > 1 else 0.0,
            "measured_vds_n": len(vds_values),
        }
    if vd is None and vs is None:
        return {}
    if not vd_values or not vs_values:
        measured_name = "Vd" if vd_values else "Vs"
        return {
            "measured_vd_v": vd,
            "measured_vs_v": vs,
            "measured_vds_v": None,
            "vds_reference": f"{measured_name} measured; Vds unavailable because the other terminal voltage was not recorded",
            "measured_vds_spread_v": None,
            "measured_vds_n": 0,
        }
    count = min(len(vd_values), len(vs_values))
    samples = [vd_values[index] - vs_values[index] for index in range(count)]
    return {
        "measured_vd_v": vd,
        "measured_vs_v": vs,
        "measured_vds_v": float(median(samples)),
        "vds_reference": "Vd and Vs measured; Vds = Vd - Vs",
        "measured_vds_spread_v": float(pstdev(samples)) if len(samples) > 1 else 0.0,
        "measured_vds_n": count,
    }


def segment_sweeps(
    parsed: dict[str, Any],
    classification: dict[str, Any],
    *,
    vds_tolerance_v: float = 1e-6,
) -> list[SweepSegment]:
    """Split parsed data into monotonic sweep segments.

    Handles:
      - Bidirectional sweeps (forward → reverse)
      - Multiple bias levels (e.g. Vd = -0.05, -1 V)
      - Single-direction sweeps
      - Combined bias + direction segmentation

    Returns list of SweepSegment objects.
    """
    data = parsed["data"]
    columns = parsed["columns"]
    sweep_var = classification["sweep_variable"]
    bias_var = classification.get("bias_variable")

    if sweep_var is None or sweep_var not in data:
        return []

    sweep_vals = data[sweep_var]
    n = len(sweep_vals)

    # ── Split by physical drain bias, then find direction flips ──
    # Gate sweeps use row-level Vds (direct, otherwise Vd-Vs), never a lone
    # terminal or a reporting preference.
    is_gate_sweep = sweep_var.lower() in {"vg", "vbg"}
    row_vds, row_vds_source = measured_vds_rows(data) if is_gate_sweep else ([], None)
    if is_gate_sweep and row_vds_source:
        bias_transitions = _find_measured_vds_transitions(row_vds, vds_tolerance_v)
    elif bias_var and bias_var in data:
        bias_transitions = _find_bias_transitions(data[bias_var])
    else:
        bias_transitions = [0]
    bias_bounds = sorted(set(bias_transitions + [n]))
    flip_indices: list[int] = []
    for block_index in range(len(bias_bounds) - 1):
        block_start, block_end = bias_bounds[block_index], bias_bounds[block_index + 1]
        local_flips = _find_direction_flips(sweep_vals[block_start:block_end])
        flip_indices.extend(block_start + flip for flip in local_flips)

    # ── Build combined cut points ─────────────────────────────────────────
    all_cuts = sorted(set([0] + flip_indices + bias_transitions))
    # Filter to valid range
    all_cuts = [c for c in all_cuts if 0 <= c < n]
    if not all_cuts or all_cuts[0] != 0:
        all_cuts = [0] + all_cuts
    # Add end marker
    if all_cuts[-1] != n:
        all_cuts.append(n)

    # ── Create segments ───────────────────────────────────────────────────
    segments: list[SweepSegment] = []
    excluded: list[dict[str, Any]] = []
    direction_index = 0
    directions = ["forward", "reverse", "forward", "reverse"]

    for i in range(len(all_cuts) - 1):
        start = all_cuts[i]
        end = all_cuts[i + 1]
        if end - start < 3:  # quarantine tiny bias/direction runs
            physical = [value for value in row_vds[start:end] if value is not None]
            excluded.append({
                "start_index": start,
                "end_index": end,
                "n_points": end - start,
                "measured_vds_v": float(median(physical)) if physical else None,
                "vds_source": row_vds_source,
                "reason": "insufficient points for transfer sweep",
            })
            continue

        # Determine direction: if this starts at a flip point, toggle
        if flip_indices and start in flip_indices:
            direction_index += 1
        seg_dir = directions[direction_index % len(directions)]

        # Get bias level. Gate sweeps use the physical signed Vds, including
        # files where Vd is a single constant column.
        vds = _measured_vds(data, start, end) if sweep_var.lower() in {"vg", "vbg"} else {}
        if bias_var and bias_var in data:
            bv = data[bias_var][start:end]
            bias_level = sum(v for v in bv if v == v) / max(
                sum(1 for v in bv if v == v), 1
            )
        else:
            bias_level = None
        if sweep_var.lower() in {"vg", "vbg"}:
            # For transfer sweeps, the bias identity is physical Vds.  Do not
            # substitute a lone terminal voltage or a configured preference.
            bias_level = vds.get("measured_vds_v")

        # Extract segment data
        seg_data: dict[str, list[float]] = {}
        for col in columns:
            if col in data:
                seg_data[col] = data[col][start:end]

        sv = sweep_vals[start:end]

        seg = SweepSegment(
            direction=seg_dir,
            bias_level=bias_level,
            bias_variable=bias_var,
            sweep_variable=sweep_var,
            sweep_values=sv,
            data=seg_data,
            start_index=start,
            end_index=end,
            **vds,
        )
        segments.append(seg)

    # ── Re-derive directions from actual data ────────────────────────────
    # Label directions by electrical meaning, not by increasing/decreasing
    # voltage.  In transfer sweeps "forward" is off→on: increasing gate for
    # nFETs, decreasing gate for pFETs.  This must happen after splitting by
    # bias and sweep turnarounds so no adjacent segment can affect the label.
    polarity_text = str(classification.get("polarity", "")).lower()
    device_polarity = str(
        classification.get("device_polarity")
        or classification.get("filename_info", {}).get("device_type", "")
    ).lower()
    is_p_type = (
        "p_type" in polarity_text or "pfet" in device_polarity or device_polarity == "p"
    )
    is_n_type = (
        "n_type" in polarity_text or "nfet" in device_polarity or device_polarity == "n"
    )

    for seg in segments:
        sv = seg.sweep_values
        if len(sv) < 2:
            continue
        diffs = [
            sv[j] - sv[j - 1]
            for j in range(1, len(sv))
            if sv[j] == sv[j] and sv[j - 1] == sv[j - 1]
        ]
        if not diffs:
            continue
        increasing = sum(1 for d in diffs if d > 0) > sum(1 for d in diffs if d < 0)
        if is_p_type:
            seg.direction = "reverse" if increasing else "forward"
        elif is_n_type:
            seg.direction = "forward" if increasing else "reverse"
        else:
            seg.direction = "forward" if increasing else "reverse"

    # ── Drop segments that are too noisy ──────────────────────────────────
    segments = [s for s in segments if len(s) >= 3]
    classification["segmentation_diagnostics"] = {
        "vds_tolerance_v": float(vds_tolerance_v),
        "vds_source": row_vds_source,
        "excluded_bias_runs": excluded,
    }

    return segments


def group_by_bias(
    segments: list[SweepSegment],
) -> dict[float | str, list[SweepSegment]]:
    """Group segments by bias level, handling both named and None bias.

    Returns {bias_key: [segments]} where segments within a key are
    forward/reverse pairs (or single segments).
    """
    groups: dict[float | str, list[SweepSegment]] = {}
    for seg in segments:
        key = round(seg.bias_level, 6) if seg.bias_level is not None else "unbiased"
        if key not in groups:
            groups[key] = []
        groups[key].append(seg)
    return groups


def segment_debug_info(segments: list[SweepSegment]) -> str:
    """Produce a compact debug summary of segments."""
    lines = [f"{len(segments)} segment(s):"]
    for i, seg in enumerate(segments):
        sv_range = f"{min(seg.sweep_values):.3g}→{max(seg.sweep_values):.3g}"
        bias_str = f"{seg.bias_level:.3g}" if seg.bias_level is not None else "N/A"
        lines.append(
            f"  [{i}] {seg.direction:>7} | "
            f"{seg.sweep_variable}: {sv_range:>18} | "
            f"{seg.bias_variable or 'bias'}={bias_str} | "
            f"{len(seg)} pts"
        )
    return "\n".join(lines)
