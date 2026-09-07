"""Non-mutating impact audit for proposed gm smoothing semantic changes."""
from __future__ import annotations

from typing import Any

import numpy as np

from fet_analyzer.analysis.numerics import (
    _adaptive_region, _candidate_metrics, _finite_runs, compute_gm_with_diagnostics,
)


def review_gm_semantics(seed: int = 20260809) -> dict[str, Any]:
    """Quantify known edge cases without changing production calculations."""
    from scipy.signal import savgol_filter

    # Two smooth regions separated by a removed-data gap. Current fixed mode
    # compacts finite gm values; the comparison applies the same filter per run.
    left = np.linspace(-6.0, -1.0, 61)
    right = np.linspace(2.0, 7.0, 61)
    vg = np.concatenate([left, right])
    current = 1e-6 / (1.0 + np.exp(-(vg - 0.5) * 2.0))
    fixed = compute_gm_with_diagnostics(
        vg.tolist(), current.tolist(),
        {"smooth_method": "savgol", "savgol_window": 7, "savgol_order": 1},
    )
    raw = compute_gm_with_diagnostics(vg.tolist(), current.tolist(), {"smooth_method": "none"})
    raw_gm = np.asarray(raw["gm"], dtype=float)
    isolated = raw_gm.copy()
    for indices in _finite_runs(raw_gm):
        if len(indices) >= 7:
            isolated[indices] = savgol_filter(raw_gm[indices], 7, 1)
    fixed_gm = np.asarray(fixed["gm"], dtype=float)
    finite_difference = np.flatnonzero(np.isfinite(fixed_gm) & np.isfinite(isolated))
    gap_delta = float(np.max(np.abs(fixed_gm[finite_difference] - isolated[finite_difference]))) if len(finite_difference) else 0.0

    rng = np.random.default_rng(seed)
    vg_adaptive = np.linspace(-4.0, 4.0, 161)
    base_gm = np.exp(-0.5 * (vg_adaptive / 0.9) ** 2)
    negative_plateau: list[dict[str, Any]] = []
    for trial in range(40):
        noisy = base_gm + rng.normal(0.0, 0.04 + trial * 0.0005, len(base_gm))
        _, _, audit = _adaptive_region(vg_adaptive, noisy, {
            "savgol_order": 1, "adaptive_gm_min_fraction": 0.05,
            "adaptive_gm_max_fraction": 0.10, "adaptive_gm_peak_tolerance": 0.05,
            "adaptive_gm_peak_shift_steps": 1.0,
            "adaptive_gm_snr_plateau_tolerance": 0.10,
            "adaptive_gm_stable_transitions": 2,
        })
        for candidate in audit["candidates"]:
            improvement = candidate.get("snr_improvement_fraction")
            if improvement is not None and improvement < -0.10 and candidate.get("snr_plateau"):
                negative_plateau.append({"trial": trial, "window_points": candidate["window_points"], "snr_change": improvement, "transition_stable": candidate.get("transition_stable")})

    tied = np.asarray([0.1, 0.5, 1.0, 1.0, 1.0, 0.5, 0.1])
    tied_vg = np.arange(len(tied), dtype=float)
    tie_metrics = _candidate_metrics(tied, tied_vg, 5, 1)
    tie_positions = tied_vg[np.isclose(np.abs(tied), np.max(np.abs(tied)))].tolist()
    return {
        "fixed_gap_isolation": {
            "current_and_isolated_differ": bool(gap_delta > np.finfo(float).eps),
            "maximum_absolute_gm_delta_s": gap_delta,
            "production_behavior_changed": False,
        },
        "adaptive_snr_plateau": {
            "negative_snr_changes_accepted_as_plateau": len(negative_plateau),
            "examples": negative_plateau[:10],
            "production_behavior_changed": False,
        },
        "tied_peak": {
            "equivalent_peak_vg": tie_positions,
            "currently_selected_vg": tie_metrics["gm_peak_vg"],
            "selection_rule": "first maximum in sorted Vg order",
            "production_behavior_changed": False,
        },
    }
