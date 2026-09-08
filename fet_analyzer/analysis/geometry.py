"""Device-geometry inference with explicit source provenance."""
from __future__ import annotations
from pathlib import Path
from typing import Any

from fet_analyzer.filename_conventions import parse_filename_conventions


def _flatten(mapping: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in mapping.items():
        normalized = str(key).lower().replace(" ", "_")
        if isinstance(value, dict):
            flat.update(_flatten(value))
        else:
            flat[normalized] = value
    return flat


def infer_geometry(
    filename: Path, metadata: dict[str, Any], *,
    filename_patterns: dict[str, Any] | None = None,
    lch_regex: str | None = None,
) -> tuple[dict[str, float], dict[str, str]]:
    """Infer numeric parameters with filename precedence over metadata.

    The master device parameter table is applied later and remains the
    highest-priority source. Config defaults are the lowest-priority source.
    """
    values: dict[str, float] = {}
    sources: dict[str, str] = {}
    facts = parse_filename_conventions(
        filename, configured_filename_patterns=filename_patterns,
        configured_lch_regex=lch_regex,
    )
    values.update(facts.parameters)
    sources.update(facts.parameter_sources)
    flat = _flatten(metadata)
    metadata_names = {
        "channel_length_um": ("channel_length_um", "length_um", "lch_um"),
        "channel_width_um": ("channel_width_um", "width_um", "w_um"),
        "oxide_thickness_nm": ("oxide_thickness_nm", "tox_nm", "thickness_nm"),
        "film_thickness_nm": ("film_thickness_nm", "semiconductor_thickness_nm", "channel_thickness_nm"),
        "dielectric_constant": ("dielectric_constant", "epsilon_r", "er"),
    }
    for target, candidates in metadata_names.items():
        if target in values:
            continue
        for candidate in candidates:
            if candidate in flat:
                try:
                    values[target], sources[target] = float(flat[candidate]), f"metadata:{candidate}"
                    break
                except (TypeError, ValueError):
                    pass
    return values, sources
