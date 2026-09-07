"""
TLM plotting: R_total vs channel length with linear fit and parameter annotation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from fet_analyzer.path_utils import prepare_write_path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


def plot_tlm(
    tlm_result: dict[str, Any],
    output_path: Path,
    config: dict[str, Any] | None = None,
) -> None:
    """Generate TLM plot: R_total vs Lch with fit line and extracted parameters."""
    if not HAS_MPL:
        return

    plot_cfg = (config or {}).get("plots", {})
    plt.rcParams.update({
        "font.size": plot_cfg.get("font_size", 11),
        "figure.dpi": plot_cfg.get("dpi", 150),
        "savefig.dpi": plot_cfg.get("dpi", 150),
        "savefig.bbox": "tight",
    })

    values = tlm_result.get("lch_values", [])
    if not values:
        return

    L = np.array([v[0] for v in values])
    R = np.array([v[1] for v in values])
    width_um = tlm_result.get("width_um", 100.0)

    # Width-normalize for display
    R_norm = R * width_um  # Ω·μm

    fig, ax = plt.subplots(figsize=(8, 6))

    ax.scatter(L, R_norm, color="#0072B2", s=50, zorder=5, label="Data")

    # Error bars if statistics available
    ebar_vals = tlm_result.get("errorbar_values", [])
    if ebar_vals:
        eL = np.array([v[0] for v in ebar_vals])
        eR = np.array([v[1] * (width_um if tlm_result.get("width_normalized", True) else 1) for v in ebar_vals])
        eS = np.array([v[2] * (width_um if tlm_result.get("width_normalized", True) else 1) for v in ebar_vals])
        if any(s > 0 for s in eS):
            ax.errorbar(eL, eR, yerr=eS, fmt="none", ecolor="#0072B2",
                        capsize=4, alpha=0.5, linewidth=0.8)

    # Fit line
    slope = tlm_result.get("slope_ohm_per_um", 0)
    intercept = tlm_result.get("intercept_ohm", 0)
    if abs(slope) > 1e-15:
        L_fit = np.linspace(0, max(L) * 1.15, 50)
        R_fit = slope * L_fit + intercept
        ax.plot(L_fit, R_fit, "r--", linewidth=1.5, label="Linear fit")

        # Mark intercept (2 × Rc × W)
        ax.axhline(intercept, color="gray", linestyle=":", alpha=0.4)
        ax.annotate(
            f"2RcW = {intercept:.0f} Ω·μm",
            xy=(0, intercept),
            xytext=(max(L)*0.05, intercept + (max(R_norm) - min(R_norm))*0.1),
            fontsize=9,
            arrowprops=dict(arrowstyle="->", color="gray"),
        )

    # L_x = -intercept / slope (where R=0)
    if abs(slope) > 1e-15 and abs(intercept) > 1e-12:
        lx = -intercept / slope
        ax.axvline(lx, color="orange", linestyle=":", alpha=0.4)
        ax.annotate(
            f"Lx = {lx:.1f} μm",
            xy=(lx, 0),
            fontsize=8, color="orange",
        )

    ax.set_xlabel("Channel Length (μm)")
    ylbl = "R_total × W (Ω·μm)" if tlm_result.get("width_normalized", True) else "R_total (Ω)"
    ax.set_ylabel(ylbl)
    ax.set_title(f"TLM Analysis — {tlm_result.get('sample_id', '')}")

    # Parameter text box
    rc = tlm_result.get("rc_ohm")
    rsh = tlm_result.get("rsh_ohm_sq")
    lt = tlm_result.get("lt_um")
    rhoc = tlm_result.get("rhoc_ohm_cm2")
    r2 = tlm_result.get("r2", 0)

    text = "TLM fit failed"
    if rc is not None and rsh is not None:
        lt_str = f"{lt:.2f}" if lt is not None else "N/A"
        rhoc_str = f"{rhoc:.2e}" if rhoc is not None else "N/A"
        r2_str = f"{r2:.4f}" if r2 is not None else "N/A"
        text = (
            f"Rc = {rc:.1f} Ω\n"
            f"Rsh = {rsh:.1f} Ω/□\n"
            f"LT = {lt_str} μm\n"
            f"ρc = {rhoc_str} Ω·cm²\n"
            f"R² = {r2_str}"
        )

    conditions = tlm_result.get("group_values", {})
    if conditions:
        rendered_conditions = "\n".join(f"{key} = {value}" for key, value in conditions.items())
        text += f"\n\nRead conditions:\n{rendered_conditions}"
    ax.text(
        0.95, 0.95, text,
        transform=ax.transAxes,
        fontsize=10, verticalalignment="top", horizontalalignment="right",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="white", alpha=0.9, edgecolor="gray"),
    )

    ax.legend(fontsize=9, loc="upper left")
    ax.grid(True, alpha=0.3)
    ax.set_xlim(left=0)
    fig.tight_layout()
    fig.savefig(prepare_write_path(output_path))
    plt.close(fig)
