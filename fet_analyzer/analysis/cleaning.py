"""
Data cleaning and validation for FET measurements.

Handles:
- NaN removal
- Compliance clipping (current plateau regions)
- Noise floor filtering
- Outlier detection
"""

from __future__ import annotations

from typing import Any


def clean_segment(
    segment: Any,  # SweepSegment
    noise_floor_a: float = 1e-13,
    compliance_threshold_pct: float = 0.005,
    compliance_cleaning_enabled: bool = False,
) -> dict[str, Any]:
    """Clean a single sweep segment.

    Returns a dict with:
        cleaned: dict[str, list[float]] — cleaned data columns
        indices_kept: list[int] — indices into original segment data
        n_removed_nan: int
        n_removed_compliance: int
        n_removed_noise: int
        warnings: list[str]
    """
    import copy

    data = segment.data
    sweep_var = segment.sweep_variable
    sweep_vals = data.get(sweep_var, [])
    n = len(sweep_vals)
    warnings: list[str] = []

    # ── Step 1: Remove NaN rows ──────────────────────────────────────────
    valid = [True] * n
    n_nan = 0
    key_cols = [sweep_var]
    # Include drain current and gate current if present
    for c in ("Id", "Is", "absId", "Ig", "Ibg"):
        if c in data:
            key_cols.append(c)

    for i in range(n):
        for c in key_cols:
            if c in data and i < len(data[c]):
                v = data[c][i]
                if v != v:  # NaN check
                    # Only mark invalid if NaN is in sweep var or drain current
                    # (Ignore NaN in auxiliary columns like empty Is/Vs)
                    if c == sweep_var or c == "Id" or c == "absId":
                        valid[i] = False
                        n_nan += 1
                        break

    # ── Step 2: Noise floor filtering ────────────────────────────────────
    n_noise = 0
    drain_col = None
    for c in ("absId", "Id", "Is"):
        if c in data:
            drain_col = c
            break
    if drain_col and compliance_cleaning_enabled:
        for i in range(n):
            if valid[i] and i < len(data[drain_col]):
                if abs(data[drain_col][i]) < noise_floor_a:
                    valid[i] = False
                    n_noise += 1

    # ── Step 3: Compliance clipping detection ─────────────────────────────
    n_compliance = 0
    if drain_col and compliance_cleaning_enabled:
        drain_vals = [data[drain_col][i] for i in range(n) if valid[i] and i < len(data[drain_col])]
        # Check for plateaus: consecutive points with <compliance_threshold_pct change
        if len(drain_vals) > 10:
            plateaus = _find_plateaus(
                [data[drain_col][i] for i in range(n)],
                valid,
                threshold_pct=compliance_threshold_pct,
            )
            for start, end in plateaus:
                for i in range(start, end):
                    if valid[i]:
                        valid[i] = False
                        n_compliance += 1
            if plateaus:
                warnings.append(
                    f"Compliance plateau(s) detected and clipped: "
                    f"{len(plateaus)} region(s)"
                )

    # ── Step 4: Build cleaned output ──────────────────────────────────────
    cleaned: dict[str, list[float]] = {}
    for col in data:
        cleaned[col] = [
            data[col][i] for i in range(n)
            if valid[i] and i < len(data[col])
        ]

    indices_kept = [i for i in range(n) if valid[i]]

    return {
        "cleaned": cleaned,
        "indices_kept": indices_kept,
        "n_removed_nan": n_nan,
        "n_removed_compliance": n_compliance,
        "n_removed_noise": n_noise,
        "warnings": warnings,
    }


def _find_plateaus(
    values: list[float],
    valid_mask: list[bool],
    threshold_pct: float = 0.02,
    min_points: int = 5,
) -> list[tuple[int, int]]:
    """Find plateau regions where current changes less than threshold_pct.

    Returns list of (start_index, end_index) tuples.
    """
    n = len(values)
    if n < min_points:
        return []

    plateaus = []
    i = 0
    while i < n - min_points:
        if not valid_mask[i]:
            i += 1
            continue
        # Check if next min_points points are flat
        start = i
        flat_count = 1
        for j in range(i + 1, n):
            if not valid_mask[j]:
                break
            if abs(values[start]) > 1e-15:
                pct = abs(values[j] - values[start]) / abs(values[start])
            else:
                pct = abs(values[j] - values[start])
            if pct < threshold_pct:
                flat_count += 1
            else:
                break
        if flat_count >= min_points:
            end = start + flat_count
            plateaus.append((start, end))
            i = end
        else:
            i += 1

    return plateaus


def clean_all_segments(
    segments: list[Any],
    noise_floor_a: float = 1e-13,
    compliance_threshold_pct: float = 0.005,
    compliance_cleaning_enabled: bool = False,
) -> list[dict[str, Any]]:
    """Clean all segments. Returns list of cleaning result dicts."""
    return [
        clean_segment(
            seg,
            noise_floor_a=noise_floor_a,
            compliance_threshold_pct=compliance_threshold_pct,
            compliance_cleaning_enabled=compliance_cleaning_enabled,
        )
        for seg in segments
    ]
