"""Dependency-light HTTP server for the FET Analyzer dashboard."""
from __future__ import annotations

import argparse
import csv
import json
import math
import mimetypes
import subprocess
import sys
import threading
import webbrowser
import os
import re
import signal
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, quote, unquote, urlparse

from .adapters import DatasetRef, ReportCatalog
from .results_api import resolve_artifact, sample_results_payload, tlm_results_payload
from fet_analyzer.config import DEFAULT_CONFIG, deep_merge, load_config
from fet_analyzer.runtime import (
    application_data_dir, resolve_worker_command, version_payload, write_diagnostic_bundle,
)
from fet_analyzer.path_utils import (
    output_path_warning, prepare_write_path, safe_copyfile, safe_path,
    safe_replace, safe_unlink,
)
from fet_analyzer.validation import ConfigValidationError, validate_analysis_readiness, validate_config

try:
    import yaml
except ImportError:  # pragma: no cover - already a core pipeline dependency
    yaml = None

STATIC = Path(__file__).with_name("static")
_SOURCE_CONFIG = Path(__file__).resolve().parents[2] / "config"
_FROZEN_CONFIG = Path(getattr(sys, "_MEIPASS", "")) / "config" if getattr(sys, "frozen", False) else None
CONFIG_ROOT = _FROZEN_CONFIG if _FROZEN_CONFIG and _FROZEN_CONFIG.is_dir() else _SOURCE_CONFIG
CONFIG_TEMPLATE = CONFIG_ROOT / "config_template.yaml"
PRESET_DIR = CONFIG_ROOT / "presets"
LOCAL_CONFIG_NAME = "fet_analyzer_config.yaml"

CONFIG_CHOICES: dict[str, list[str]] = {
    "general.log_level": ["DEBUG", "INFO", "WARNING", "ERROR"],
    "general.current_unit": ["A/um", "uA/um"],
    "general.mobility_unit": ["cm2/Vs", "m2/Vs"],
    "general.length_unit": ["m", "cm", "mm", "um", "nm"],
    "general.area_unit": ["m2", "cm2", "mm2", "um2", "nm2"],
    "device_defaults.polarity": ["p", "n"],
    "transfer.vth_method": ["peak_gm_tangent", "constant_current"],
    "transfer.smooth_method": ["savgol", "adaptive_savgol", "none"],
    "transfer.ion_method": ["maximum_measured", "fixed_vg", "fixed_gate_field", "fixed_overdrive", "fixed_overdrive_field", "max_common_overdrive"],
    "transfer.ioff_method": ["minimum_above_ig", "minimum_measured"],
    "transfer.ss_method": ["minimum"],
    "tlm.lch_unit": ["m", "cm", "mm", "um", "nm"],
    "tlm.transfer_read_mode": ["maximum_current", "constant_vg", "constant_gate_field", "constant_overdrive", "constant_overdrive_field"],
    "tlm.tlm_ss_method": ["minimum"],
    "plots.font_family": ["sans-serif", "serif", "monospace"],
    "summary.preferred_direction": ["forward", "reverse"],
    "advanced.parameter_preflight_mode": ["warning", "strict", "error"],
}


class _SkipMeasurementInspection(Exception):
    """Internal control flow for scalable filename/parameter-only preflight."""


class DashboardState:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.input_dir = self.root
        self.output_dir = self.root / "output"
        self.catalog = ReportCatalog()
        self.datasets: dict[str, DatasetRef] = {}
        self.graphics: list[dict[str, str]] = []
        self.process: subprocess.Popen[str] | None = None
        self.starting = False
        self.log: list[str] = []
        self.return_code: int | None = None
        self.cancelled = False
        self.progress_current = 0
        self.progress_total = 0
        self.progress_label = "Not started"
        self.progress_complete = False
        self.manifest_warning: str | None = None
        self.folder_picker: Callable[[Path], object] | None = None
        self.lock = threading.Lock()
        self.project_revision = 0
        self.catalog_loading = False
        self.catalog_stage = "Ready"
        self._tlm_preflight_cache_key: tuple[str, str, str, bool, int] | None = None
        self._tlm_preflight_cache_payload: dict | None = None
        self.refresh()
        self._remember_project()

    def _remember_project(self) -> None:
        path = application_data_dir() / "recent-projects.json"
        recent: list[str] = []
        try:
            loaded = (
                json.loads(safe_path(path).read_text(encoding="utf-8"))
                if safe_path(path).exists() else []
            )
            recent = [str(item) for item in loaded if Path(str(item)).is_dir()]
        except (OSError, ValueError, TypeError):
            recent = []
        value = str(self.input_dir)
        recent = [value, *(item for item in recent if item != value)][:10]
        try:
            prepare_write_path(path).write_text(
                json.dumps(recent, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    def recent_projects(self) -> list[str]:
        path = application_data_dir() / "recent-projects.json"
        try:
            return [
                str(item)
                for item in json.loads(safe_path(path).read_text(encoding="utf-8"))
                if safe_path(Path(str(item))).is_dir()
            ]
        except (OSError, ValueError, TypeError):
            return [str(self.input_dir)]

    def refresh(self) -> None:
        refs = self.catalog.scan(self.output_dir) if self.output_dir.exists() else []
        self.datasets = {ref.id: ref for ref in refs}
        self.graphics = self._graphics_for(self.output_dir)

    @staticmethod
    def _graphics_for(output: Path) -> list[dict[str, str]]:
        graphics: list[dict[str, str]] = []
        if not output.exists():
            return graphics
        for path in sorted(output.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".png", ".svg", ".jpg", ".jpeg"}:
                rel = path.relative_to(output).as_posix()
                graphics.append({
                    "id": rel, "name": path.stem, "path": rel,
                    "group": path.parent.relative_to(output).as_posix(),
                })
        return graphics

    def switch_project(self, folder: Path, output_path: Path | None = None) -> None:
        """Switch paths immediately; index an existing output without blocking the UI."""
        output = (output_path or folder / "output").expanduser().resolve()
        with self.lock:
            self.input_dir = folder
            self.output_dir = output
            self.project_revision += 1
            revision = self.project_revision
            self.datasets = {}
            self.graphics = []
            self.catalog = ReportCatalog()
            self.catalog_loading = True
            self.catalog_stage = f"Indexing results in {output}"
            self.manifest_warning = None
            self._tlm_preflight_cache_key = None
            self._tlm_preflight_cache_payload = None
        self._remember_project()

        def scan() -> None:
            catalog = ReportCatalog()
            refs = catalog.scan(output) if output.exists() else []
            graphics = self._graphics_for(output)
            with self.lock:
                if revision != self.project_revision:
                    return
                self.catalog = catalog
                self.datasets = {ref.id: ref for ref in refs}
                self.graphics = graphics
                self.catalog_loading = False
                self.catalog_stage = (
                    f"Loaded {len(refs)} report table(s)" if refs else "No existing results found"
                )

        threading.Thread(target=scan, daemon=True, name=f"fet-catalog-{revision}").start()

    def browse_for_folder(self, initial: Path | None = None) -> str | None:
        """Use the native host picker when available, otherwise Tkinter."""
        initial = initial or self.input_dir
        while not initial.is_dir() and initial != initial.parent:
            initial = initial.parent
        if self.folder_picker is not None:
            selected = self.folder_picker(initial)
        else:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            try:
                root.withdraw()
                root.attributes("-topmost", True)
                selected = filedialog.askdirectory(initialdir=str(initial))
            finally:
                root.destroy()
        if isinstance(selected, (list, tuple)):
            selected = selected[0] if selected else None
        value = str(selected).strip() if selected else ""
        return value or None

    @property
    def local_config_path(self) -> Path:
        return self.input_dir / LOCAL_CONFIG_NAME

    def config_payload(
        self, *, create: bool = False, reset: bool = False, preset: str | None = None,
    ) -> dict:
        """Return the editable project-local configuration and field metadata."""
        path = self.local_config_path
        if create and (reset or not path.exists()):
            if preset and not re.fullmatch(r"[A-Za-z0-9_-]+", preset):
                raise ValueError("Unknown configuration preset")
            preset_path = PRESET_DIR / f"{preset}.yaml" if preset else None
            if preset_path and preset_path.resolve().parent != PRESET_DIR.resolve():
                raise ValueError("Unknown configuration preset")
            if preset_path and not preset_path.is_file():
                raise ValueError(f"Unknown configuration preset: {preset}")
            source = preset_path if preset_path and preset_path.is_file() else CONFIG_TEMPLATE
            if source.is_file():
                safe_copyfile(source, path)
            elif yaml is not None:
                # Installed wheels contain the canonical in-code defaults even
                # when the repository-level commented template is unavailable.
                prepare_write_path(path).write_text(
                    yaml.safe_dump(DEFAULT_CONFIG, sort_keys=False, allow_unicode=True),
                    encoding="utf-8",
                )
            else:
                raise FileNotFoundError(f"Configuration template not found: {CONFIG_TEMPLATE}")
        if not path.exists():
            return {"exists": False, "path": str(path), "sections": [], "presets": _config_presets()}
        if yaml is None:
            raise RuntimeError("PyYAML is required to edit configuration")
        data = yaml.safe_load(
            safe_path(path).read_text(encoding="utf-8-sig", errors="replace")
        ) or {}
        if not isinstance(data, dict):
            raise ValueError("Configuration root must be a YAML mapping")
        return {
            "exists": True,
            "path": str(path),
            "sections": _config_sections(deep_merge(DEFAULT_CONFIG, data)),
            "presets": _config_presets(),
        }

    def save_config(self, values: dict[str, object]) -> dict:
        """Validate typed GUI values and save the local configuration."""
        if yaml is None:
            raise RuntimeError("PyYAML is required to edit configuration")
        if not self.local_config_path.exists():
            self.config_payload(create=True)
        current = yaml.safe_load(
            safe_path(self.local_config_path).read_text(
                encoding="utf-8-sig", errors="replace"
            )
        ) or {}
        known = {
            field["path"]
            for section in _config_sections(deep_merge(DEFAULT_CONFIG, current))
            for field in section["fields"]
        }
        unknown = sorted(set(values) - known)
        if unknown:
            raise ValueError(f"Unknown configuration field(s): {', '.join(unknown)}")
        for dotted, value in values.items():
            _set_dotted(current, dotted, value)
        validation = validate_config(deep_merge(DEFAULT_CONFIG, current))
        if validation.errors:
            raise ConfigValidationError(validation)
        rendered = yaml.safe_dump(current, sort_keys=False, allow_unicode=True)
        prepare_write_path(self.local_config_path).write_text(
            rendered, encoding="utf-8"
        )
        # Exercise the same merge and validation path used by an analysis run.
        load_config(self.local_config_path)
        return self.config_payload()

    @property
    def device_parameters_path(self) -> Path:
        return self.input_dir / "device_parameters.txt"

    def device_parameters_payload(self, *, create: bool = False) -> dict:
        """Return the editable master device-parameter table."""
        from fet_analyzer.device_parameters import (
            BOOLEAN_COLUMNS, DEVICE_PARAMETER_COLUMNS, NUMERIC_COLUMNS,
            load_master_table, write_master_template,
        )
        path = self.device_parameters_path
        if create and not path.exists():
            config = load_config(self.local_config_path if self.local_config_path.exists() else None)
            write_master_template(path, config.device_defaults)
        if not path.exists():
            return {
                "exists": False, "path": str(path), "columns": DEVICE_PARAMETER_COLUMNS,
                "fields": [], "rows": [],
            }
        rows = load_master_table(path)
        columns = list(DEVICE_PARAMETER_COLUMNS)
        return {
            "exists": True,
            "path": str(path),
            "columns": columns,
            "fields": [
                {
                    "name": name,
                    "type": "number" if name in NUMERIC_COLUMNS else "boolean" if name in BOOLEAN_COLUMNS else "text",
                    "required": name in {"sample_label", "device_pattern"},
                    "options": ["p", "n"] if name == "polarity" else None,
                }
                for name in columns
            ],
            "rows": [{name: row.get(name, "") for name in columns} for row in rows],
        }

    def save_device_parameters(self, rows: object) -> dict:
        """Validate and atomically save device_parameters.txt rows."""
        from fet_analyzer.device_parameters import (
            ALLOWED_COLUMNS, BOOLEAN_COLUMNS, DEVICE_PARAMETER_COLUMNS,
            IDENTITY_COLUMNS, NUMERIC_COLUMNS, _coerce,
        )
        if not isinstance(rows, list):
            raise ValueError("Device parameter rows must be a list")
        normalized: list[dict[str, str]] = []
        seen_values: dict[tuple[str, str, str], str] = {}
        positive_fields = NUMERIC_COLUMNS - {"temperature_c"}
        for index, raw_row in enumerate(rows, start=1):
            if not isinstance(raw_row, dict):
                raise ValueError(f"Device parameter row {index} must be an object")
            unknown = sorted(set(raw_row) - ALLOWED_COLUMNS)
            if unknown:
                raise ValueError(f"Unknown device parameter field(s) in row {index}: {', '.join(unknown)}")
            row = {
                name: "" if raw_row.get(name) is None else str(raw_row.get(name, "")).strip()
                for name in DEVICE_PARAMETER_COLUMNS
            }
            if not row["sample_label"] or not row["device_pattern"]:
                raise ValueError(f"Row {index} requires sample_label and device_pattern")
            identity = (row["sample_label"].casefold(), row["device_pattern"].casefold())
            for name, value in row.items():
                if not value or name not in (NUMERIC_COLUMNS | BOOLEAN_COLUMNS | {"polarity"}):
                    continue
                coerced = _coerce(name, value)
                if name in NUMERIC_COLUMNS:
                    number = float(coerced)
                    if not math.isfinite(number):
                        raise ValueError(f"Row {index}: {name} must be finite")
                    if name in positive_fields and number <= 0:
                        raise ValueError(f"Row {index}: {name} must be greater than zero")
                    row[name] = format(number, ".15g")
                elif name in BOOLEAN_COLUMNS:
                    row[name] = "true" if bool(coerced) else "false"
                else:
                    row[name] = str(coerced)
            for name, value in row.items():
                if name in IDENTITY_COLUMNS or not value:
                    continue
                key = (*identity, name)
                if key in seen_values and seen_values[key] != value:
                    raise ValueError(
                        f"Row {index} conflicts with an equally specific row for {name}"
                    )
                seen_values[key] = value
            normalized.append(row)
        path = self.device_parameters_path
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            with prepare_write_path(temporary).open(
                "w", newline="", encoding="utf-8"
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=DEVICE_PARAMETER_COLUMNS, delimiter="\t")
                writer.writeheader()
                writer.writerows(normalized)
            safe_replace(temporary, path)
        finally:
            if safe_path(temporary).exists():
                safe_unlink(temporary)
        return self.device_parameters_payload()

    def ion_preflight(
        self, config_path: str | None = None, recursive: bool | None = None,
        *, inspect_measurements: bool = True,
    ) -> dict:
        """Resolve Ion read conditions and required parameters without running analysis."""
        selected_config = config_path or (str(self.local_config_path) if self.local_config_path.exists() else None)
        config = load_config(selected_config)
        from fet_analyzer.file_discovery import discover_files
        from fet_analyzer.analysis.classifier import parse_filename_groups
        from fet_analyzer.analysis.geometry import infer_geometry
        from fet_analyzer.analysis.ion_bias import resolve_ion_bias
        from fet_analyzer.device_parameters import load_master_table, resolve_device_parameters
        files, _ = discover_files(
            self.input_dir, config.recursive if recursive is None else recursive,
            config.skip_patterns,
            config.file_priority,
            excluded_roots=[self.output_dir, self.input_dir / "decompressed_ztr"],
        )
        parameter_path = self.input_dir / "device_parameters.txt"
        parameter_rows = load_master_table(parameter_path) if parameter_path.exists() else []
        method = str(config._data.get("transfer", {}).get("ion_method", "maximum_measured"))
        rows = []
        for path in files:
            info = parse_filename_groups(path.name, config._data.get("filename_patterns", {}))
            sample = str(info.get("sample_label", "unknown"))
            inferred, inferred_sources = infer_geometry(path, {})
            values, sources, parameter_warnings = resolve_device_parameters(
                config.device_defaults, parameter_rows, sample, path.name,
                inferred=inferred, inferred_sources=inferred_sources,
            )
            resolved = resolve_ion_bias(config._data, values)
            status, reasons = "Ready", []
            if parameter_warnings:
                status = "Review"
                reasons.extend(str(item.get("message", item)) for item in parameter_warnings)
            if resolved["warnings"]:
                status, reasons = "Blocked", list(resolved["warnings"])
            if method in {"max_common_overdrive", "maximum_common_vov"}:
                status = "Provisional"
                reasons.append("Final voltage is calculated after all group Vth and sweep ranges are known")
            if sources.get("oxide_thickness_nm") == "template_default" and resolved["overdrive_field_mv_cm"] is not None:
                if status != "Blocked": status = "Review"
                reasons.append("Oxide thickness is an unconfirmed template value")
            polarity = str(values.get("polarity", "")).lower()
            field = resolved["overdrive_field_mv_cm"]
            if field is not None and ((polarity == "p" and field > 0) or (polarity == "n" and field < 0)):
                if status != "Blocked": status = "Review"
                reasons.append(f"Field sign is unusual for {polarity}-FET polarity")
            gate_field = resolved["gate_field_mv_cm"]
            if gate_field is not None and ((polarity == "p" and gate_field > 0) or (polarity == "n" and gate_field < 0)):
                if status != "Blocked": status = "Review"
                reasons.append(f"Gate-field sign is unusual for {polarity}-FET polarity")
            measured_vg: list[float] = []
            parse_warning = None
            classification_name = str(info.get("measurement_type", "unknown")).lower()
            try:
                if not inspect_measurements:
                    raise _SkipMeasurementInspection
                from fet_analyzer.registry import parse_measurement
                from fet_analyzer.analysis.classifier import classify_measurement
                if path.suffix.lower() in {".ztr", ".zip"}:
                    import tempfile
                    from fet_analyzer.parsers.ztr_parser import decompress_ztr_to_cache
                    with tempfile.TemporaryDirectory(prefix="fet-preflight-") as temporary:
                        cached = decompress_ztr_to_cache(path, Path(temporary))
                        parsed = parse_measurement(path, cached_path=cached)
                else:
                    parsed = parse_measurement(path)
                data = parsed.get("data", {})
                classified = classify_measurement(
                    parsed.get("metadata", {}), list(data), data,
                    filename=path.name,
                    filename_patterns=config._data.get("filename_patterns"),
                )
                classification_name = str(getattr(classified.get("type"), "name", classified.get("type", "unknown"))).lower()
                if classification_name == "unknown":
                    if status != "Blocked": status = "Review"
                    reasons.append("Measurement type could not be classified during preflight")
                vg_key = next((key for key in data if str(key).lower() in {"vg", "vbg", "gate voltage"}), None)
                if vg_key:
                    measured_vg = sorted({float(value) for value in data.get(vg_key, []) if math.isfinite(float(value))})
            except _SkipMeasurementInspection:
                pass
            except Exception as exc:
                parse_warning = f"Preflight could not inspect measured Vg: {type(exc).__name__}: {exc}"
                if status != "Blocked": status = "Review"
                reasons.append(parse_warning)
            requested_fixed = resolved["fixed_vg_v"]
            nearest_fixed = min(measured_vg, key=lambda value: abs(value - requested_fixed)) if measured_vg and requested_fixed is not None else None
            rows.append({
                "device": path.name, "sample": sample, "polarity": polarity,
                "ion_method": method,
                "classification": classification_name,
                "oxide_thickness_nm": resolved["oxide_thickness_nm"],
                "oxide_source": sources.get("oxide_thickness_nm", "missing"),
                "requested_field_mv_cm": resolved["overdrive_field_mv_cm"],
                "requested_overdrive_v": resolved["overdrive_input_v"],
                "resolved_overdrive_v": resolved["overdrive_v"],
                "fixed_vg_v": resolved["fixed_vg_v"],
                "fixed_vg_input_v": resolved["fixed_vg_input_v"],
                "requested_gate_field_mv_cm": resolved["gate_field_mv_cm"],
                "fixed_vg_source": resolved["fixed_vg_source"],
                "measured_vg_min_v": measured_vg[0] if measured_vg else None,
                "measured_vg_max_v": measured_vg[-1] if measured_vg else None,
                "nearest_fixed_vg_v": nearest_fixed,
                "fixed_vg_delta_v": nearest_fixed - requested_fixed if nearest_fixed is not None and requested_fixed is not None else None,
                "overdrive_read_status": "requires analyzed Vth" if resolved["overdrive_v"] is not None else None,
                "status": status, "reasons": reasons,
                "parameter_warning_count": len(parameter_warnings),
            })
        return {
            "method": method,
            "rows": rows,
            "config_validation": config.validation_report,
            "measurement_inspection": inspect_measurements,
        }

    def summary(self) -> dict:
        manifest_path = self.output_dir / "run_manifest.json"
        manifest = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(
                    safe_path(manifest_path).read_text(encoding="utf-8")
                )
            except (OSError, ValueError, TypeError) as exc:
                self.manifest_warning = f"Could not read run manifest: {type(exc).__name__}: {exc}"
        with self.lock:
            starting = self.starting
            running = starting or (self.process is not None and self.process.poll() is None)
            log = self.log[-500:]
            code = self.return_code
            project_revision = self.project_revision
            catalog_loading = self.catalog_loading
            catalog_stage = self.catalog_stage
            discovered_report_count = len(self.datasets)
            catalog_errors = list(self.catalog.last_errors)
        return {
            "input_dir": str(self.input_dir), "output_dir": str(self.output_dir),
            "config_path": str(self.local_config_path) if self.local_config_path.exists() else None,
            "running": running, "starting": starting, "return_code": code, "log": log,
            "cancelled": self.cancelled,
            "progress": {
                "current": self.progress_current,
                "total": self.progress_total,
                "label": self.progress_label,
                "complete": self.progress_complete,
            },
            "manifest": manifest,
            "manifest_warning": self.manifest_warning,
            "discovered_report_count": discovered_report_count,
            "versions": version_payload(),
            "recent_projects": self.recent_projects(),
            "catalog_errors": catalog_errors,
            "project_revision": project_revision,
            "catalog_loading": catalog_loading,
            "catalog_stage": catalog_stage,
        }

    def diagnostic_payload(self) -> dict:
        checks: list[dict[str, object]] = []
        for label, path, needs_write in (
            ("input", self.input_dir, False), ("output", self.output_dir, True),
        ):
            exists = path.exists()
            writable = os.access(path if exists else path.parent, os.W_OK) if needs_write else None
            warning = output_path_warning(path) if label == "output" else None
            checks.append({
                "name": label, "path": str(path), "exists": exists,
                "writable": writable, "path_length": len(os.path.abspath(path)),
                "warning": warning,
            })
        try:
            worker = resolve_worker_command()
            worker_error = None
        except Exception as exc:
            worker, worker_error = [], str(exc)
        return {
            "versions": version_payload(), "checks": checks,
            "worker_command": worker, "worker_error": worker_error,
            "status": self.summary(),
        }

    def preflight_payload(
        self, *, overwrite: bool = False, config_path: str | None = None,
        recursive: bool | None = None,
    ) -> dict:
        selected_config = config_path or (str(self.local_config_path) if self.local_config_path.exists() else None)
        config = load_config(selected_config)
        from fet_analyzer.file_discovery import discover_files
        files, duplicates = discover_files(
            self.input_dir, config.recursive if recursive is None else recursive,
            config.skip_patterns, config.file_priority,
            excluded_roots=[self.output_dir, self.input_dir / "decompressed_ztr"],
        )
        issues = list(config.validation_report.get("issues", []))
        issues.extend(item.to_dict() for item in validate_analysis_readiness(config._data).issues)
        path_warning = output_path_warning(self.output_dir)
        if path_warning:
            issues.append({
                "level": "warning", "code": "output_path_long",
                "path": str(self.output_dir), "message": path_warning,
            })
        if not files:
            issues.append({"level": "error", "code": "no_inputs", "path": str(self.input_dir), "message": "No supported measurement files were found"})
        if self.output_dir.exists() and any(self.output_dir.iterdir()) and not overwrite:
            issues.append({"level": "error", "code": "output_exists", "path": str(self.output_dir), "message": "Output already contains files; enable overwrite or choose another output"})
        for path in files:
            if not os.access(path, os.R_OK):
                issues.append({"level": "error", "code": "unreadable_input", "path": str(path), "message": "Input is not readable"})
        for duplicate in duplicates:
            issues.append({"level": "warning", "code": "duplicate_input", "path": str(duplicate.get("chosen", "")), "message": f"Duplicate candidates resolved for {duplicate.get('stem', 'measurement')}"})
        try:
            # Run preflight must scale to large batches. Geometry, configuration,
            # filenames, readability, duplicates, and output safety are checked
            # here; full measurement parsing occurs once in the analysis worker.
            # The explicit Ion calculator remains the deep measured-bias audit.
            ion = self.ion_preflight(
                selected_config, recursive, inspect_measurements=False
            )
            for row in ion.get("rows", []):
                for reason in row.get("reasons", []):
                    level = "error" if row.get("status") == "Blocked" else "warning"
                    issues.append({"level": level, "code": "device_preflight", "path": row.get("device", ""), "message": str(reason)})
        except Exception as exc:
            issues.append({"level": "error", "code": "ion_preflight_failed", "path": str(self.input_dir), "message": f"Ion preflight failed: {type(exc).__name__}: {exc}"})
        status = "error" if any(item.get("level") == "error" for item in issues) else "warning" if issues else "pass"
        return {
            "status": status,
            "issues": issues,
            "input_count": len(files),
            "duplicate_groups": len(duplicates),
            "output": str(self.output_dir),
            "measurement_inspection": False,
        }

    def tlm_preflight_payload(
        self, *, config_path: str | None = None, recursive: bool | None = None,
        consume_cached: bool = False,
    ) -> dict:
        """Inspect only raw TLM-role inputs for an existing-output continuation."""
        selected = config_path or (str(self.local_config_path) if self.local_config_path.exists() else None)
        cache_key = (
            str(self.input_dir), str(self.output_dir), str(selected or ""),
            bool(recursive), self.project_revision,
        )
        if consume_cached:
            with self.lock:
                if self._tlm_preflight_cache_key == cache_key and self._tlm_preflight_cache_payload is not None:
                    payload = self._tlm_preflight_cache_payload
                    self._tlm_preflight_cache_key = None
                    self._tlm_preflight_cache_payload = None
                    return payload
        config = load_config(selected)
        from fet_analyzer.file_discovery import discover_files
        files, duplicates = discover_files(
            self.input_dir, config.recursive if recursive is None else recursive,
            config.skip_patterns, config.file_priority,
            excluded_roots=[self.output_dir, self.input_dir / "decompressed_ztr"],
        )
        from fet_analyzer.tlm_continue import tlm_preflight
        payload = tlm_preflight(files, self.input_dir, config._data, self.output_dir)
        payload["duplicate_groups"] = len(duplicates)
        with self.lock:
            self._tlm_preflight_cache_key = cache_key
            self._tlm_preflight_cache_payload = payload
        return payload

    def batch_payload(self) -> dict:
        """Return typed preferred-file rows, statistics, and metric definitions."""
        summary_path = self.output_dir / "batch_summary" / "master_summary.csv"
        statistics_path = self.output_dir / "batch_summary" / "metric_statistics.csv"
        if not summary_path.exists():
            return {"available": False, "rows": [], "statistics": [], "definitions": []}

        def rows_from(path: Path) -> list[dict]:
            if not path.exists():
                return []
            with open(safe_path(path), newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            for row in rows:
                for key, value in list(row.items()):
                    if value in (None, ""):
                        row[key] = None
                        continue
                    try:
                        row[key] = float(value)
                    except (TypeError, ValueError):
                        pass
            return rows

        from fet_analyzer.analysis.metric_summary import METRIC_DEFINITIONS
        return {
            "available": True,
            "rows": rows_from(summary_path),
            "statistics": rows_from(statistics_path),
            "definitions": METRIC_DEFINITIONS,
            "master_csv": str(summary_path),
            "master_xlsx": str(summary_path.with_suffix(".xlsx")),
        }

    def results_payload(self) -> dict:
        from fet_analyzer.analysis.metric_summary import METRIC_DEFINITIONS
        with self.lock:
            output_dir, revision = self.output_dir, self.project_revision
        payload = sample_results_payload(output_dir, METRIC_DEFINITIONS)
        payload["project_revision"] = revision
        payload["output_root"] = str(output_dir)
        return payload

    def tlm_results_payload(self) -> dict:
        with self.lock:
            output_dir, revision = self.output_dir, self.project_revision
        results = sample_results_payload(output_dir, [])
        payload = tlm_results_payload(output_dir, results["rows"])
        payload["project_revision"] = revision
        payload["output_root"] = str(output_dir)
        return payload

    def start_run(
        self, config: str | None = None, recursive: bool = False,
        *, device_excel: bool = True, plot_copies: bool = False,
        batch_plots: bool = False, overwrite: bool = False, workers: int = 0,
        tlm_continue: bool = False,
    ) -> None:
        # Mark validation as active before performing the potentially expensive
        # ZTR/device preflight. Do not hold the state lock during that work: the
        # dashboard must remain able to poll and display a useful stage.
        with self.lock:
            if self.starting or (self.process is not None and self.process.poll() is None):
                raise RuntimeError("An analysis run is already in progress")
            self.starting = True
            self.return_code = None
            self.cancelled = False
            self.progress_current = 0
            self.progress_total = 0
            self.progress_label = "Validating inputs and configuration"
            self.progress_complete = False
            self.log = ["Validating inputs, device parameters, and output safety..."]

        try:
            effective_config = config or (
                str(self.local_config_path) if self.local_config_path.exists() else None
            )
            preflight = (
                self.tlm_preflight_payload(
                    config_path=effective_config, recursive=recursive, consume_cached=True,
                )
                if tlm_continue else
                self.preflight_payload(overwrite=overwrite, config_path=effective_config, recursive=recursive)
            )
            errors = [item for item in preflight["issues"] if item.get("level") == "error"]
            if errors:
                raise ValueError("Preflight failed: " + "; ".join(str(item.get("message")) for item in errors))
            command = [
                *resolve_worker_command(), "--input", str(self.input_dir),
                "--output", str(self.output_dir),
            ]
            if effective_config:
                command += ["--config", effective_config]
            if recursive:
                command.append("--recursive")
            if tlm_continue:
                command += ["--only", "tlm", "--tlm-continue"]
            if not device_excel:
                command.append("--no-device-excel")
            if plot_copies:
                command.append("--save-plots")
            if batch_plots:
                command.append("--batch-plots")
            if workers < 0:
                raise ValueError("Worker count must be zero (automatic) or positive")
            command += ["--workers", str(workers)]
            command.append("--overwrite" if overwrite else "--no-overwrite")
            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            creationflags = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
                if os.name == "nt" else 0
            )
            with self.lock:
                self.log = ["$ " + " ".join(command)]
                self.progress_label = "Starting analysis"
                self.process = subprocess.Popen(
                    command, cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                    env=env, creationflags=creationflags,
                    start_new_session=os.name != "nt",
                )
                process = self.process
                self.starting = False
        except Exception as exc:
            with self.lock:
                self.starting = False
                self.progress_label = "Run blocked during preflight"
                self.log.append(str(exc))
            raise

        def consume() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                with self.lock:
                    self.log.append(line.rstrip())
                    match = re.search(r"\[PROGRESS\]\s+(\d+)/(\d+)(?:\s+\d+%)?\s*(.*)", line)
                    if match:
                        self.progress_current = int(match.group(1))
                        self.progress_total = int(match.group(2))
                        if match.group(3).strip():
                            self.progress_label = match.group(3).strip()
                    status_match = re.search(r"\[STATUS\]\s+(.+)", line)
                    if status_match:
                        self.progress_label = status_match.group(1).strip()
            code = process.wait()
            with self.lock:
                self.return_code = code
                self.progress_complete = not self.cancelled
                if self.progress_complete and self.progress_total:
                    self.progress_current = self.progress_total
                self.progress_label = (
                    "Analysis complete" if code == 0
                    else "Analysis completed with issues" if not self.cancelled
                    else "Analysis stopped"
                )
            self.refresh()
            from fet_analyzer.temp_workspace import cleanup_stale_workspaces
            cleanup_stale_workspaces(self.output_dir)

        threading.Thread(target=consume, daemon=True).start()

    def stop_run(self) -> None:
        with self.lock:
            process = self.process
            if process is None or process.poll() is not None:
                raise RuntimeError("No analysis run is in progress")
            self.cancelled = True
            self.log.append("Stop requested; terminating analysis process...")
            _terminate_process_tree(process)

        def ensure_stopped() -> None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _terminate_process_tree(process, force=True)
                with self.lock:
                    self.log.append("Analysis process required forced termination.")

        threading.Thread(target=ensure_stopped, daemon=True).start()

    @staticmethod
    def comparison_payload(folder: Path) -> dict:
        """Load the canonical batch summary and manifest from a prior run."""
        root = folder.expanduser().resolve()
        if (root / "output").is_dir() and not (root / "run_manifest.json").exists():
            root = root / "output"
        if not root.is_dir():
            raise ValueError("Comparison folder does not exist")
        summary_path = root / "batch_summary" / "master_summary.csv"
        if not summary_path.exists():
            raise ValueError("Comparison folder has no batch_summary/master_summary.csv")
        from .adapters import CsvAdapter
        ref = CsvAdapter().inspect(summary_path, root)[0]
        table = CsvAdapter().read(ref)
        manifest_path = root / "run_manifest.json"
        manifest = (
            json.loads(safe_path(manifest_path).read_text(encoding="utf-8"))
            if safe_path(manifest_path).exists() else {}
        )
        return {"root": str(root), "manifest": manifest, **table}


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, default=str, ensure_ascii=False).encode("utf-8")


def _terminate_process_tree(process: subprocess.Popen[str], force: bool = False) -> None:
    """Stop the coordinator and all of its device-analysis worker processes."""
    pid = getattr(process, "pid", None)
    if not pid:
        process.kill() if force else process.terminate()
        return
    if os.name == "nt":
        command = ["taskkill", "/PID", str(pid), "/T"]
        if force:
            command.append("/F")
        completed = subprocess.run(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if completed.returncode and process.poll() is None:
            process.kill() if force else process.terminate()
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL if force else signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        if process.poll() is None:
            process.kill() if force else process.terminate()


def _config_presets() -> list[dict[str, str]]:
    presets = [{"id": "", "label": "Complete default template"}]
    if PRESET_DIR.is_dir():
        for path in sorted(PRESET_DIR.glob("*.yaml")):
            presets.append({
                "id": path.stem,
                "label": path.stem.replace("_", " ").title(),
            })
    return presets


def _config_sections(data: dict[str, object]) -> list[dict]:
    """Flatten nested YAML into sectioned, type-aware GUI field descriptors."""
    sections: list[dict] = []
    for section_name, section_value in data.items():
        if section_name not in DEFAULT_CONFIG:
            continue
        fields: list[dict] = []
        if isinstance(section_value, dict):
            for key, value in section_value.items():
                path = f"{section_name}.{key}"
                field = _config_field(path, key, value)
                if path == "filename_patterns.active":
                    patterns = section_value.get("patterns", {})
                    if isinstance(patterns, dict):
                        field["options"] = list(patterns)
                fields.append(field)
        else:
            fields.append(_config_field(section_name, section_name, section_value))
        sections.append({"name": section_name, "fields": fields})
    return sections


def _config_field(path: str, label: str, value: object) -> dict:
    if isinstance(value, bool):
        kind = "boolean"
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        kind = "number"
    elif isinstance(value, str) and re.fullmatch(
        r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", value.strip()
    ):
        kind = "number"
        value = float(value)
    elif isinstance(value, (list, dict)):
        kind = "json"
    elif value is None:
        kind = "nullable"
    else:
        kind = "text"
    return {
        "path": path, "label": label, "type": kind, "value": value,
        "options": CONFIG_CHOICES.get(path),
    }


def _set_dotted(data: dict, dotted: str, value: object) -> None:
    parts = dotted.split(".")
    target = data
    for part in parts[:-1]:
        child = target.get(part)
        if not isinstance(child, dict):
            raise ValueError(f"Configuration path is not editable: {dotted}")
        target = child
    target[parts[-1]] = value


class Handler(BaseHTTPRequestHandler):
    def parse_request(self) -> bool:
        """Restrict browser requests to this local origin, including Host rebinding."""
        if not super().parse_request():
            return False
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host = self.headers.get("Host", "").lower()
        origin = self.headers.get("Origin")
        if (host not in allowed or
                (origin is not None and origin.lower() != f"http://{host}") or
                self.headers.get("Sec-Fetch-Site") == "cross-site"):
            self.send_error(HTTPStatus.FORBIDDEN, "Only same-origin local dashboard requests are allowed")
            return False
        return True

    state: DashboardState

    def send_bytes(self, data: bytes, content_type: str, status: int = 200, disposition: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if disposition:
            self.send_header("Content-Disposition", disposition)
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: object, status: int = 200) -> None:
        self.send_bytes(_json_bytes(payload), "application/json; charset=utf-8", status)

    def body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            return self.send_json(self.state.summary())
        if parsed.path == "/api/config":
            return self.send_json(self.state.config_payload())
        if parsed.path == "/api/device-parameters":
            return self.send_json(self.state.device_parameters_payload())
        if parsed.path == "/api/ion-preflight":
            return self.send_json(self.state.ion_preflight())
        if parsed.path == "/api/diagnostics":
            return self.send_json(self.state.diagnostic_payload())
        if parsed.path == "/api/version":
            return self.send_json(version_payload())
        if parsed.path in {"/api/batch-summary", "/api/batch-statistics", "/api/metric-definitions"}:
            payload = self.state.batch_payload()
            if parsed.path == "/api/batch-statistics":
                return self.send_json({"available": payload["available"], "statistics": payload["statistics"]})
            if parsed.path == "/api/metric-definitions":
                return self.send_json(payload["definitions"])
            return self.send_json(payload)
        if parsed.path == "/api/results-overview":
            return self.send_json(self.state.results_payload())
        if parsed.path == "/api/results-tlm":
            return self.send_json(self.state.tlm_results_payload())
        if parsed.path == "/api/datasets":
            payload = [{**asdict(ref), "path": str(ref.path)} for ref in self.state.datasets.values()]
            return self.send_json(payload)
        if parsed.path == "/api/graphics":
            return self.send_json(self.state.graphics)
        if parsed.path == "/api/graphic":
            rel = parse_qs(parsed.query).get("id", [""])[0]
            target = (self.state.output_dir / rel).resolve()
            output_root = self.state.output_dir.resolve()
            if not target.is_file() or output_root not in target.parents:
                return self.send_json({"error": "Graphic not found"}, 404)
            return self.send_bytes(safe_path(target).read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        if parsed.path == "/api/data":
            query = parse_qs(parsed.query)
            ref = self.state.datasets.get(query.get("id", [""])[0])
            if not ref:
                return self.send_json({"error": "Dataset not found"}, 404)
            requested_limit = query.get("limit", [""])[0]
            limit = int(requested_limit) if requested_limit else None
            return self.send_json({"dataset": {**asdict(ref), "path": str(ref.path)}, **self.state.catalog.read(ref, limit)})
        if parsed.path == "/api/download":
            ref = self.state.datasets.get(parse_qs(parsed.query).get("id", [""])[0])
            if not ref:
                return self.send_json({"error": "Report not found"}, 404)
            return self.send_bytes(safe_path(ref.path).read_bytes(), mimetypes.guess_type(ref.path.name)[0] or "application/octet-stream", disposition=f'attachment; filename="{ref.path.name}"')
        target = STATIC / ("index.html" if parsed.path == "/" else unquote(parsed.path).lstrip("/"))
        if target.is_file() and STATIC in target.resolve().parents:
            return self.send_bytes(safe_path(target).read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        try:
            if self.path == "/api/folder":
                payload = self.body()
                selected = payload.get("path")
                if payload.get("browse"):
                    target = str(payload.get("target") or "input").lower()
                    initial = self.state.output_dir if target == "output" else self.state.input_dir
                    selected = self.state.browse_for_folder(initial)
                    if selected and target == "output":
                        output = Path(selected).expanduser().resolve()
                        if output == self.state.input_dir:
                            raise ValueError("Output folder must be different from the input folder")
                        if output != self.state.output_dir:
                            self.state.switch_project(self.state.input_dir, output)
                        return self.send_json(self.state.summary())
                if selected:
                    folder = Path(selected).expanduser().resolve()
                    if not folder.is_dir():
                        raise ValueError("Selected path is not a folder")
                    requested_output = payload.get("output_path")
                    if requested_output is not None and not str(requested_output).strip():
                        raise ValueError("Output folder cannot be blank")
                    output = Path(requested_output).expanduser().resolve() if requested_output else folder / "output"
                    if output.exists() and not output.is_dir():
                        raise ValueError("Output path is not a folder")
                    if output == folder:
                        raise ValueError("Output folder must be different from the input folder")
                    if folder != self.state.input_dir or output != self.state.output_dir:
                        self.state.switch_project(folder, output)
                return self.send_json(self.state.summary())
            if self.path == "/api/preflight":
                payload = self.body()
                return self.send_json(self.state.preflight_payload(
                    overwrite=bool(payload.get("overwrite", False)),
                    config_path=payload.get("config") or None,
                    recursive=bool(payload.get("recursive", False)),
                ))
            if self.path == "/api/tlm-preflight":
                payload = self.body()
                return self.send_json(self.state.tlm_preflight_payload(
                    config_path=payload.get("config") or None,
                    recursive=bool(payload.get("recursive", False)),
                ))
            if self.path == "/api/ion-preflight":
                payload = self.body()
                return self.send_json(self.state.ion_preflight(
                    config_path=payload.get("config") or None,
                    recursive=bool(payload.get("recursive", False)),
                ))
            if self.path == "/api/run":
                payload = self.body()
                self.state.start_run(
                    payload.get("config") or None,
                    bool(payload.get("recursive")),
                    device_excel=bool(payload.get("device_excel", True)),
                    plot_copies=bool(payload.get("plot_copies", False)),
                    batch_plots=bool(payload.get("batch_plots", False)),
                    overwrite=bool(payload.get("overwrite", False)),
                    workers=int(payload.get("workers") or 0),
                )
                return self.send_json(self.state.summary(), 202)
            if self.path == "/api/run-tlm":
                payload = self.body()
                self.state.start_run(
                    payload.get("config") or None,
                    bool(payload.get("recursive")),
                    workers=int(payload.get("workers") or 0),
                    tlm_continue=True,
                )
                return self.send_json(self.state.summary(), 202)
            if self.path == "/api/config/create":
                payload = self.body()
                return self.send_json(self.state.config_payload(
                    create=True, reset=bool(payload.get("reset")),
                    preset=payload.get("preset") or None,
                ))
            if self.path == "/api/config/save":
                payload = self.body()
                values = payload.get("values")
                if not isinstance(values, dict):
                    raise ValueError("Configuration values must be an object")
                return self.send_json(self.state.save_config(values))
            if self.path == "/api/device-parameters/create":
                return self.send_json(self.state.device_parameters_payload(create=True))
            if self.path == "/api/device-parameters/save":
                payload = self.body()
                return self.send_json(self.state.save_device_parameters(payload.get("rows")))
            if self.path == "/api/stop":
                self.state.stop_run()
                return self.send_json(self.state.summary(), 202)
            if self.path == "/api/compare":
                payload = self.body()
                current = self.state.comparison_payload(self.state.output_dir)
                previous = self.state.comparison_payload(Path(payload.get("path", "")))
                return self.send_json({"current": current, "previous": previous})
            if self.path == "/api/refresh":
                self.state.refresh()
                return self.send_json(self.state.summary())
            if self.path == "/api/open-output":
                target = self.state.output_dir
                if not target.is_dir():
                    raise ValueError("Output folder does not exist yet")
                _open_local_path(target)
                return self.send_json({"opened": str(target)})
            if self.path == "/api/open-index":
                target = self.state.output_dir / "index.html"
                if not target.is_file():
                    raise ValueError("Master HTML index does not exist yet")
                _open_local_path(target)
                return self.send_json({"opened": str(target)})
            if self.path == "/api/open-artifact":
                identifier = str(self.body().get("id") or "")
                target = resolve_artifact(self.state.output_dir, identifier)
                _open_local_path(target)
                return self.send_json({"opened": str(target)})
            if self.path == "/api/export-diagnostics":
                target = write_diagnostic_bundle(self.state.diagnostic_payload())
                return self.send_json({"path": str(target)})
            self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 400)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def _open_local_path(path: Path) -> None:
    """Open a verified local output path with the platform shell."""
    target = str(path.resolve())
    if os.name == "nt":
        os.startfile(target)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FET Analyzer browser dashboard")
    parser.add_argument(
        "--root", default=".",
        help="Pipeline project/input folder (recommended: change into it and use --root .)",
    )
    parser.add_argument(
        "--host", default="127.0.0.1", choices=["127.0.0.1", "localhost"],
        help="Loopback interface only; the dashboard is never exposed to the network",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    return parser


def create_server(
    root: Path, host: str = "127.0.0.1", port: int = 8765,
) -> tuple[ThreadingHTTPServer, str]:
    """Create a reusable dashboard server; port 0 selects a free local port."""
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Dashboard host must be a loopback address")
    state = DashboardState(root)
    handler = type("DashboardHandler", (Handler,), {"state": state})
    server = ThreadingHTTPServer((host, port), handler)
    server.dashboard_state = state  # type: ignore[attr-defined]
    bound_host, bound_port = server.server_address[:2]
    return server, f"http://{bound_host}:{bound_port}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    server, url = create_server(Path(args.root), args.host, args.port)
    print(f"FET Analyzer dashboard: {url}")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
