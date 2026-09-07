"""Unit conversion utilities for FET analysis.

Internal: SI (V, A, m, F, s)
Display: configurable preferred units
"""

from __future__ import annotations

import numpy as np

# ── Length conversion: base = metre ────────────────────────────────────────

LENGTH_TO_M: dict[str, float] = {
    "m": 1.0,
    "cm": 1e-2,
    "mm": 1e-3,
    "um": 1e-6,
    "μm": 1e-6,
    "nm": 1e-9,
    "pm": 1e-12,
}

LENGTH_FROM_M: dict[str, float] = {k: 1.0 / v for k, v in LENGTH_TO_M.items()}


def convert_length(value: float, from_unit: str, to_unit: str) -> float:
    """Convert a length between units."""
    return value * LENGTH_TO_M.get(from_unit, 1.0) * LENGTH_FROM_M.get(to_unit, 1.0)


# ── Current conversion: base = A ───────────────────────────────────────────

CURRENT_TO_A: dict[str, float] = {
    "A": 1.0,
    "mA": 1e-3,
    "uA": 1e-6,
    "μA": 1e-6,
    "nA": 1e-9,
    "pA": 1e-12,
    "fA": 1e-15,
}

CURRENT_FROM_A: dict[str, float] = {k: 1.0 / v for k, v in CURRENT_TO_A.items()}


def convert_current(value: float, from_unit: str, to_unit: str) -> float:
    return value * CURRENT_TO_A.get(from_unit, 1.0) * CURRENT_FROM_A.get(to_unit, 1.0)


# ── Current density: A/m → A/μm, μA/μm, etc. ──────────────────────────────

def parse_current_density_unit(unit: str) -> tuple[str, str]:
    """Split 'uA/um' into ('uA', 'um')."""
    parts = unit.split("/")
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return "A", "m"


def convert_current_density(value: float, from_unit: str, to_unit: str) -> float:
    """Convert between current density units like A/m → μA/μm."""
    cur_from, len_from = parse_current_density_unit(from_unit)
    cur_to, len_to = parse_current_density_unit(to_unit)
    # Convert current: A/m → A/m
    value_a_per_m = value * CURRENT_TO_A.get(cur_from, 1.0) * LENGTH_TO_M.get(len_from, 1.0)
    # A/m → target
    return value_a_per_m * CURRENT_FROM_A.get(cur_to, 1.0) * LENGTH_FROM_M.get(len_to, 1.0)


# ── Mobility: base = cm²/V·s ──────────────────────────────────────────────

def convert_mobility(value_cm2_vs: float, to_unit: str) -> float:
    """Convert from cm²/V·s to target unit."""
    if to_unit == "cm2/Vs":
        return value_cm2_vs
    if to_unit == "m2/Vs":
        return value_cm2_vs * 1e-4
    return value_cm2_vs


# ── Area conversion ────────────────────────────────────────────────────────

AREA_TO_CM2: dict[str, float] = {
    "cm2": 1.0,
    "mm2": 1e2,
    "um2": 1e-8,
    "μm2": 1e-8,
    "nm2": 1e-14,
    "m2": 1e4,
}


def convert_area(value: float, from_unit: str, to_unit: str) -> float:
    cm2 = value * AREA_TO_CM2.get(from_unit, 1.0)
    return cm2 / AREA_TO_CM2.get(to_unit, 1.0)


# ── Normalization helpers ──────────────────────────────────────────────────

def normalize_current(id_a: float, width_cm: float) -> float:
    """Normalize drain current by width: Id / W → A/cm."""
    if width_cm <= 0:
        return id_a
    return id_a / width_cm


def denormalize_current(id_norm_a_per_cm: float, width_cm: float) -> float:
    """Reverse width normalization."""
    return id_norm_a_per_cm * width_cm


def format_eng(value: float, significant_digits: int = 3, unit: str = "") -> str:
    """Format a value with engineering notation and optional unit.

    >>> format_eng(1.23e-9, 3, "A")
    '1.23 nA'
    >>> format_eng(4.56e-3, 3, "S")
    '4.56 mS'
    """
    if value == 0:
        return f"0 {unit}".strip()
    eng_prefixes = {
        -15: "f", -12: "p", -9: "n", -6: "μ", -3: "m",
        0: "", 3: "k", 6: "M", 9: "G", 12: "T",
    }
    exponent = 0
    abs_val = abs(value)
    if abs_val < 1e-15:
        exponent = -15
    elif abs_val < 1:
        exponent = int(np.floor(np.log10(abs_val) / 3) * 3)
    else:
        exponent = int(np.floor(np.log10(abs_val) / 3) * 3)
    exponent = max(-15, min(12, exponent))
    scaled = value / (10 ** exponent)
    prefix = eng_prefixes.get(exponent, "")
    return f"{scaled:.{significant_digits - 1}f} {prefix}{unit}".strip()


def format_si(value: float, significant_digits: int = 3) -> str:
    """Format a number with SI prefix and given significant digits.

    >>> format_si(1.23e-9, 3)
    '1.23e-09'
    >>> format_si(0.00456, 3)
    '4.56e-03'
    """
    if value == 0:
        return "0.0"
    return f"{value:.{significant_digits - 1}e}"


def width_normalize_id(
    id_values: list[float],
    width_um: float,
    to_unit: str = "A/um",
) -> list[float]:
    """Normalize drain current by channel width: Id → Id/W (A/μm).

    Args:
        id_values: Raw drain current values in amperes
        width_um: Channel width in μm
        to_unit: Target unit — 'A/um' (A/μm) or 'uA/um' (μA/μm)

    Returns:
        Normalized current values
    """
    if width_um <= 0:
        return list(id_values)
    factor = 1.0 / width_um  # → A/μm
    if to_unit == "uA/um":
        factor *= 1e6  # → μA/μm
    return [v * factor for v in id_values]
