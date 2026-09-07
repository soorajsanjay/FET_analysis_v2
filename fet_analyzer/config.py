"""
Configuration loader, validator, and defaults for FET Analyzer.

Loads a YAML config file, fills in defaults from config_template.yaml,
and provides typed accessors with unit-aware helpers.

Also supports per-device parameter overrides via device_params.txt files.
"""

from __future__ import annotations

import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from fet_analyzer.path_utils import prepare_write_path, safe_path

import yaml

# Physical constants
EPSILON_0_F_PER_CM = 8.854187817e-14  # Vacuum permittivity in F/cm


# ── Default configuration (mirrors config_template.yaml) ────────────────────

DEFAULT_CONFIG: dict[str, Any] = {
    "general": {
        "input_folder": "./",
        "output_folder": "output",
        "recursive": True,
        "overwrite": False,
        "file_priority": ["csv", "xlsx", "xls", "xtr", "ztr"],
        "skip_patterns": [r"^~\$", r"^\.", r"_analysis\.xlsx$", r"_report\.html$"],
        "log_level": "INFO",
        "processing_log": "processing_log.txt",
        "current_unit": "uA/um",
        "mobility_unit": "cm2/Vs",
        "length_unit": "um",
        "area_unit": "cm2",
    },
    "filename_patterns": {
        "active": "default_easyexpert",
        "patterns": {
            "default_easyexpert": {
                "description": "measurementType__sampleLabel_sampleDetails_deviceType_deviceName__measurementCount",
                "regex": (
                    r"(?P<measurement_type>[^_]+)__"
                    r"(?P<sample_label>[^_]+)_"
                    r"(?P<sample_details>[^_]+)_"
                    r"(?P<device_type>[^_]+)_"
                    r"(?P<device_name>.+)__"
                    r"(?P<measurement_count>\d+)"
                ),
            },
            "simple": {
                "description": "measurementType_sampleLabel_deviceName",
                "regex": r"(?P<measurement_type>[^_]+)_(?P<sample_label>[^_]+)_(?P<device_name>.+)",
            },
        },
    },
    "device_defaults": {
        "channel_width_um": 100.0,
        "channel_length_um": None,
        "gate_length_um": None,
        "oxide_thickness_nm": 90.0,
        "film_thickness_nm": None,
        "dielectric_constant": 3.9,
        "cox_f_per_cm2": None,
        "contact_length_um": None,
        "contact_width_um": None,
        "gate_dielectric": "SiO2",
        "contact_metal": None,
        "substrate": None,
        "top_gated": False,
        "temperature_c": None,
        "temperature_k": 300.0,
        "polarity": "p",
    },
    "transfer": {
        "vth_method": "peak_gm_tangent",
        "vth_vds_correction": True,
        "vds_segmentation_tolerance_v": 1e-6,
        "constant_current_value": None,
        "smooth_method": "savgol",
        "savgol_window": 0,
        "savgol_order": 1,
        "adaptive_gm_min_fraction": 0.05,
        "adaptive_gm_max_fraction": 0.10,
        "adaptive_gm_peak_tolerance": 0.05,
        "adaptive_gm_peak_shift_steps": 1.0,
        "adaptive_gm_snr_plateau_tolerance": 0.10,
        "adaptive_gm_stable_transitions": 2,
        "tangent_window_v": 2.0,
        "tangent_min_points": 5,
        "ion_method": "fixed_vg",
        "report_ion_at_fixed_vg": False,
        "report_ion_at_fixed_overdrive": False,
        "ioff_method": "minimum_above_ig",
        "overdrive_v": None,
        "ion_overdrive_v": None,
        "ion_overdrive_field_mv_cm": None,
        "ion_fixed_vg_v": None,
        "ion_gate_field_mv_cm": None,
        "ion_constant_vg_v": None,
        "ss_method": "minimum",
        "ss_vg_range_v": None,
        "ss_require_above_gate_leakage": True,
        "ss_leakage_factor": 1.0,
        "noise_floor_a": 1e-13,
        "ioff_leakage_factor": 3.0,
        "use_leakage_aware": False,
        "normalize_by_width": True,
        "abs_current_for_log": True,
    },
    "tlm": {
        "lch_regex": r"TLM\d*_(\d+\.?\d*)\s*um",
        "lch_unit": "um",
        "low_bias_window_v": 0.1,
        "transfer_read_mode": "constant_vg",
        "transfer_read_vg_v": None,
        "transfer_gate_field_mv_cm": None,
        "transfer_overdrive_v": None,
        "transfer_overdrive_field_mv_cm": None,
        "transfer_read_vds_v": None,
        "vds_tolerance_v": 1e-3,
        "min_channel_lengths": 3,
        "group_keys": [
            "sample_label", "device_type", "contact_metal",
            "gate_dielectric", "vd_value", "overdrive_v",
        ],
        "tlm_ss_method": "minimum",
        "tlm_output_vd_max": 0.1,  # V — max Vd for linear-region R_total extraction
        "acceptance_min_length_span_ratio": 2.0,
        "acceptance_max_relative_uncertainty": 1.0,
        "acceptance_max_leverage": 0.85,
        "acceptance_max_residual_curvature": 0.8,
        "acceptance_max_lt_to_lmin_ratio": 10.0,
    },
    "plots": {
        "dpi": 150,
        "figsize": [8, 6],
        "font_size": 11,
        "font_family": "sans-serif",
        "color_palette": "colorblind",
        "publication_style": True,
        "show_grid": True,
        "show_annotations": True,
        "formats": ["png"],
        "palette": [
            "#0072B2", "#E69F00", "#009E73", "#F0E442", "#56B4E9",
            "#D55E00", "#CC79A7", "#000000", "#999999", "#882255",
        ],
    },
    "summary": {
        "preferred_direction": "forward",
        "preferred_vd_v": 0.1,
        "preferred_vd_tolerance_v": 0.001,
        "fallback_to_nearest_vd": True,
        "fallback_to_reverse": True,
        "common_overdrive_group_keys": ["sample_label", "polarity"],
        "export_origin_import": False,
    },
    "advanced": {
        "pre_smooth": False,
        "pre_smooth_window": 5,
        "dibl_use_forward_only": True,
        "max_mobility_cm2_vs": 1000,
        "min_subthreshold_slope_mv_dec": 60,
        "leakage_ratio_warning": 0.1,
        "gate_leakage_id_dominance_fraction": 0.90,
        "sanity_min_points": 10,
        "open_p95_current_a": 1e-11,
        "open_noise_floor_factor": 10.0,
        "short_p10_ua_per_um": 100.0,
        "short_flatness_ratio": 3.0,
        "sanity_sweep_fraction": 0.90,
        "tlm_r2_warning": 0.9,
        "parameter_preflight_mode": "warning",
        "allow_ion_sign_mismatch": False,
        "compliance_cleaning_enabled": False,
        "compliance_threshold_pct": 0.005,
        "export_intermediate_data": True,
        "export_raw_data_copy": True,
    },
}


class Config:
    """Typed accessor for the merged configuration."""

    def __init__(self, data: dict[str, Any], config_dir: Path):
        self._data = data
        self.config_dir = config_dir

    # ── General ──────────────────────────────────────────────────────────

    @property
    def input_folder(self) -> Path:
        p = Path(self._data["general"]["input_folder"])
        if not p.is_absolute():
            p = (self.config_dir / p).resolve()
        return p

    @property
    def output_folder(self) -> Path:
        p = Path(self._data["general"]["output_folder"])
        if not p.is_absolute():
            p = (self.input_folder / p).resolve()
        return p

    @property
    def recursive(self) -> bool:
        return self._data["general"]["recursive"]

    @property
    def overwrite(self) -> bool:
        return self._data["general"]["overwrite"]

    @property
    def file_priority(self) -> list[str]:
        return self._data["general"]["file_priority"]

    @property
    def skip_patterns(self) -> list[str]:
        return self._data["general"]["skip_patterns"]

    @property
    def log_level(self) -> str:
        return self._data["general"]["log_level"]

    @property
    def processing_log(self) -> str:
        return self._data["general"]["processing_log"]

    # ── Device defaults ──────────────────────────────────────────────────

    @property
    def device_defaults(self) -> dict:
        return self._data["device_defaults"]

    def get_device_param(self, key: str, default: Any = None) -> Any:
        return self._data["device_defaults"].get(key, default)

    @property
    def channel_width_cm(self) -> float:
        """Channel width in cm."""
        w_um = self._data["device_defaults"]["channel_width_um"]
        if w_um is None:
            return 1.0  # fallback: effectively no normalization
        return w_um * 1e-4

    @property
    def channel_width_um(self) -> float | None:
        return self._data["device_defaults"]["channel_width_um"]

    @property
    def oxide_thickness_cm(self) -> float:
        tox_nm = self._data["device_defaults"]["oxide_thickness_nm"]
        if tox_nm is None:
            return 1.0
        return tox_nm * 1e-7  # nm → cm

    @property
    def cox_f_per_cm2(self) -> float:
        """Gate capacitance per unit area in F/cm²."""
        direct = self._data["device_defaults"]["cox_f_per_cm2"]
        if direct is not None:
            return direct
        eps_r = self._data["device_defaults"]["dielectric_constant"]
        tox_cm = self.oxide_thickness_cm
        if tox_cm <= 0:
            return 1.0
        return EPSILON_0_F_PER_CM * eps_r / tox_cm

    @property
    def cox_f_per_um2(self) -> float:
        return self.cox_f_per_cm2 * 1e-8  # cm² → μm²

    # ── Transfer ─────────────────────────────────────────────────────────

    @property
    def vth_method(self) -> str:
        return self._data["transfer"]["vth_method"]

    @property
    def vth_vds_correction(self) -> bool:
        return self._data["transfer"]["vth_vds_correction"]

    @property
    def tangent_window_v(self) -> float:
        return self._data["transfer"]["tangent_window_v"]

    @property
    def normalize_by_width(self) -> bool:
        return self._data["transfer"]["normalize_by_width"]

    @property
    def noise_floor_a(self) -> float:
        return self._data["transfer"]["noise_floor_a"]

    def transfer(self, key: str, default: Any = None) -> Any:
        return self._data["transfer"].get(key, default)

    # ── TLM ──────────────────────────────────────────────────────────────

    @property
    def lch_regex(self) -> str:
        return self._data["tlm"]["lch_regex"]

    @property
    def tlm_group_keys(self) -> list[str]:
        return self._data["tlm"]["group_keys"]

    @property
    def tlm_min_channel_lengths(self) -> int:
        return self._data["tlm"]["min_channel_lengths"]

    def tlm(self, key: str, default: Any = None) -> Any:
        return self._data["tlm"].get(key, default)

    # ── Plots ────────────────────────────────────────────────────────────

    def plot(self, key: str, default: Any = None) -> Any:
        return self._data["plots"].get(key, default)

    @property
    def plot_formats(self) -> list[str]:
        return self._data["plots"]["formats"]

    @property
    def color_palette(self) -> list[str]:
        return self._data["plots"]["palette"]

    # ── Advanced ─────────────────────────────────────────────────────────

    def advanced(self, key: str, default: Any = None) -> Any:
        return self._data["advanced"].get(key, default)

    # ── Active filename regex ────────────────────────────────────────────

    @property
    def filename_regex(self) -> str:
        active = self._data["filename_patterns"]["active"]
        return self._data["filename_patterns"]["patterns"][active]["regex"]


# ── Per-device parameter overrides ──────────────────────────────────────────

DEVICE_PARAM_KEYS = [
    "channel_width_um", "channel_length_um", "gate_length_um",
    "oxide_thickness_nm", "film_thickness_nm", "dielectric_constant", "cox_f_per_cm2",
    "contact_length_um", "contact_width_um",
    "gate_dielectric", "contact_metal", "substrate",
    "top_gated", "temperature_c", "temperature_k", "polarity",
    "noise_floor_a",  # per-device noise floor for cleaning
]

DEVICE_PARAM_HEADER = """# Per-Device Parameter Overrides
# ================================
# Edit values below and re-run the pipeline.
# Lines starting with # are ignored.
# Empty values (or 'auto') use the global config defaults.
# Format: key=value
#
# Available keys:
#   channel_width_um      — Channel width in μm
#   channel_length_um     — Channel length in μm
#   gate_length_um        — Gate length in μm (if different)
#   oxide_thickness_nm    — Gate oxide thickness in nm
#   dielectric_constant   — Gate dielectric εr
#   cox_f_per_cm2         — Direct Cox override (F/cm²) — if set, skips εr·ε₀/tox
#   contact_length_um     — Contact length for TLM
#   contact_width_um      — Contact width for TLM
#   gate_dielectric       — Material label (e.g. SiO2, HfO2, Al2O3)
#   contact_metal         — Contact metallisation (e.g. Ni/Au, Ti/Au)
#   substrate             — Substrate material
#   top_gated             — true/false
#   temperature_c         — Measurement temperature in °C
#
# Values from global config defaults (for reference):
"""


def load_device_params(params_path: Path, global_defaults: dict) -> dict:
    """Load per-device parameter overrides from a key=value file."""
    overrides: dict[str, Any] = {}
    if not params_path.exists():
        return overrides

    with open(safe_path(params_path), encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key not in DEVICE_PARAM_KEYS:
                continue
            if value.lower() in ("", "auto", "null", "none"):
                continue
            # Type coercion
            if key.endswith("_um") or key.endswith("_nm"):
                overrides[key] = float(value)
            elif key.endswith("_c"):
                overrides[key] = float(value)
            elif key in ("dielectric_constant", "cox_f_per_cm2"):
                overrides[key] = float(value)
            elif key == "top_gated":
                overrides[key] = value.lower() in ("true", "1", "yes")
            else:
                overrides[key] = value

    return overrides


def write_device_params_template(path: Path, config: Config):
    """Write a template device_params.txt from global defaults."""
    defaults = config.device_defaults
    lines = [DEVICE_PARAM_HEADER]
    for key in DEVICE_PARAM_KEYS:
        val = defaults.get(key)
        if val is None:
            val_str = "auto"
        elif isinstance(val, bool):
            val_str = str(val).lower()
        else:
            val_str = str(val)
        lines.append(f"# {key}={val_str}")
        lines.append(f"{key}=auto")
        lines.append("")
    with open(prepare_write_path(path), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def merge_device_params(global_defaults: dict, overrides: dict) -> dict:
    """Merge per-device overrides into device parameter dict."""
    merged = deepcopy(global_defaults)
    for key, value in overrides.items():
        merged[key] = value
    return merged


# ── Config loading ──────────────────────────────────────────────────────────

def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base dict."""
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_config(config_path: str | Path | None = None) -> Config:
    """Load and validate configuration from a YAML file.

    If config_path is None, uses defaults only.
    """
    merged = deepcopy(DEFAULT_CONFIG)

    if config_path is not None:
        config_path = Path(config_path).resolve()
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        with open(safe_path(config_path), encoding="utf-8-sig", errors="replace") as f:
            user_config = yaml.safe_load(f) or {}
        merged = deep_merge(merged, user_config)
        config_dir = config_path.parent
    else:
        config_dir = Path.cwd()

    from fet_analyzer.validation import ConfigValidationError, validate_config
    report = validate_config(merged)
    if report.errors:
        raise ConfigValidationError(report)
    config = Config(merged, config_dir)
    config.validation_report = report.to_dict()
    return config
