"""Scoped, atomic continuation of TLM-only artifacts from raw inputs."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fet_analyzer.utils.logging import LOGGER
from fet_analyzer.path_utils import (
    prepare_write_path, safe_path, safe_rename, safe_rmtree, unique_directory,
)


def collect_tlm_records(
    file_list: list[Path], input_folder: Path, config: dict[str, Any],
    *, analyze: bool, cache_root: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from fet_analyzer.analysis.classifier import classify_measurement, MeasurementType
    from fet_analyzer.analysis.cleaning import clean_all_segments
    from fet_analyzer.analysis.engine import analyze_segments
    from fet_analyzer.analysis.geometry import infer_geometry
    from fet_analyzer.analysis.segmentation import segment_sweeps
    from fet_analyzer.device_parameters import load_master_table, resolve_device_parameters
    from fet_analyzer.preflight import assess_parameter_preflight
    from fet_analyzer.registry import parse_measurement

    parameter_path = input_folder / "device_parameters.txt"
    parameter_rows = load_master_table(parameter_path) if parameter_path.exists() else []
    records: list[dict[str, Any]] = []
    roles: Counter[str] = Counter()
    errors: list[dict[str, str]] = []
    group_lengths: dict[tuple[str, str, str], set[float]] = {}
    for path in file_list:
        try:
            cached_path = None
            if path.suffix.lower() in {".ztr", ".zip"} and cache_root is not None:
                from fet_analyzer.parsers.ztr_parser import decompress_ztr_to_cache
                cached_path = decompress_ztr_to_cache(path, cache_root)
            parsed = parse_measurement(path, cached_path=cached_path)
            classification = classify_measurement(
                parsed["metadata"], parsed["columns"], parsed["data"],
                filename=path.name, filename_patterns=config.get("filename_patterns"),
            )
            if not classification.get("is_tlm"):
                continue
            role = str(classification.get("tlm_role") or "unknown")
            roles[role] += 1
            inferred, inferred_sources = infer_geometry(path, parsed["metadata"])
            sample = classification.get("filename_info", {}).get("sample_label", "unknown")
            device, sources, warnings = resolve_device_parameters(
                config.get("device_defaults", {}), parameter_rows, str(sample), path.name,
                inferred=inferred, inferred_sources=inferred_sources,
            )
            segments = segment_sweeps(
                parsed, classification,
                vds_tolerance_v=float(config.get("transfer", {}).get("vds_segmentation_tolerance_v", 1e-6)),
            )
            if not segments:
                raise ValueError("No valid sweep segments were detected")
            clean_results = clean_all_segments(
                segments,
                noise_floor_a=device.get("noise_floor_a", config.get("device_defaults", {}).get("noise_floor_a", 1e-13)),
                compliance_threshold_pct=float(config.get("advanced", {}).get("compliance_threshold_pct", 0.005)),
                compliance_cleaning_enabled=bool(config.get("advanced", {}).get("compliance_cleaning_enabled", False)),
            )
            for segment, cleaned in zip(segments, clean_results):
                segment.data = cleaned["cleaned"]
                segment.sweep_values = cleaned["cleaned"][segment.sweep_variable]
            preflight = assess_parameter_preflight(device, sources, config)
            metrics: dict[str, Any] = {}
            if analyze and classification["type"] in {MeasurementType.TRANSFER, MeasurementType.OUTPUT}:
                metrics = analyze_segments(segments, classification, config, device)
            record = {
                "source_file": path, "segments": segments, "classification": classification,
                "device_params": device, "parameter_sources": sources,
                "parameter_warnings": warnings, "parameter_preflight": preflight,
                "metrics": metrics, "parsed_metadata": parsed["metadata"],
            }
            records.append(record)
            from fet_analyzer.analysis.tlm_workflow import _identity
            identity = _identity(record)
            if identity:
                group_lengths.setdefault((identity[0], identity[1], role), set()).add(identity[2])
        except Exception as exc:
            errors.append({"file": str(path), "error": f"{type(exc).__name__}: {exc}"})
    groups = [
        {"sample_id": sample, "tlm_id": tlm_id, "role": role, "n_lengths": len(lengths)}
        for (sample, tlm_id, role), lengths in sorted(group_lengths.items())
    ]
    parameter_coverage = {
        key: sum(
            1 for record in records
            if record.get("device_params", {}).get(key) is not None
        )
        for key in ("channel_width_um", "film_thickness_nm", "oxide_thickness_nm", "polarity")
    }
    return records, {
        "input_count": len(file_list), "tlm_input_count": len(records),
        "roles": dict(sorted(roles.items())), "groups": groups, "errors": errors,
        "parameter_coverage": parameter_coverage,
        "gated_operating_conditions": [
            "near_zero", "ion_fixed_gate_or_field", "ion_overdrive_or_field",
            "near_ioff_first_accepted",
        ],
    }


def tlm_preflight(file_list: list[Path], input_folder: Path, config: dict[str, Any], output_folder: Path) -> dict[str, Any]:
    cache_parent = output_folder if safe_path(output_folder).is_dir() else output_folder.parent
    cache, _cache_id = unique_directory(cache_parent, ".fet_tlm_preflight_")
    try:
        records, audit = collect_tlm_records(
            file_list, input_folder, config, analyze=False, cache_root=cache,
        )
    finally:
        safe_rmtree(cache, ignore_errors=True)
    issues = [
        {"level": "warning", "code": "tlm_parse_error", "path": item["file"], "message": item["error"]}
        for item in audit["errors"]
    ]
    if not records:
        issues.append({
            "level": "error", "code": "no_tlm_inputs", "path": str(input_folder),
            "message": "No raw TLM-role inputs were found (LTLM, gated IdVg TLM, or gated output TLM).",
        })
    if not safe_path(output_folder).is_dir():
        issues.append({
            "level": "error", "code": "missing_existing_output", "path": str(output_folder),
            "message": "TLM continuation requires an existing output folder.",
        })
    eligible = [group for group in audit["groups"] if group["n_lengths"] >= 3]
    if records and not eligible:
        issues.append({
            "level": "error", "code": "insufficient_tlm_lengths", "path": str(input_folder),
            "message": "No TLM group has at least three unique channel lengths.",
        })
    audit["eligible_groups"] = eligible
    audit["issues"] = issues
    audit["status"] = "error" if any(item["level"] == "error" for item in issues) else "warning" if issues else "pass"
    audit["output"] = str(output_folder)
    return audit


def run_tlm_continuation(
    file_list: list[Path], input_folder: Path, output_folder: Path, config: dict[str, Any],
) -> Path:
    if not safe_path(output_folder).is_dir():
        raise ValueError("TLM continuation requires an existing output folder")
    staging_parent, _staging_id = unique_directory(
        output_folder.parent, ".fet_tlm_continue_"
    )
    staging_tlm = staging_parent / "TLM"
    backup = output_folder / ".TLM.previous"
    target = output_folder / "TLM"
    swapped = False
    try:
        records, audit = collect_tlm_records(
            file_list, input_folder, config, analyze=True,
            cache_root=staging_parent / "decompressed_ztr",
        )
        if not records:
            raise ValueError("No raw TLM-role inputs were found")
        from fet_analyzer.analysis.tlm_workflow import generate_tlm_workflow
        generated = generate_tlm_workflow(records, staging_tlm, config)
        if not generated or not safe_path(staging_tlm / "master_tlm_summary.xlsx").exists():
            raise RuntimeError("TLM continuation produced no master TLM workbook")
        if safe_path(backup).exists() and not safe_path(target).exists():
            safe_rename(backup, target)
        elif safe_path(backup).exists():
            safe_rmtree(backup)
        if safe_path(target).exists():
            safe_rename(target, backup)
        safe_rename(staging_tlm, target)
        swapped = True
        if safe_path(backup).exists():
            safe_rmtree(backup)
        payload = {
            "schema_version": "1.0", "generated_utc": datetime.now(timezone.utc).isoformat(),
            "status": "success", "scope": "tlm_only_continuation",
            "input_folder": str(input_folder.resolve()), "output_folder": str(output_folder.resolve()),
            "audit": audit, "generated": [str(path.relative_to(staging_tlm)) for path in generated],
            "ordinary_batch_summary_modified": False,
        }
        manifest = output_folder / "TLM" / "tlm_continue_manifest.json"
        prepare_write_path(manifest).write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )
        try:
            from fet_analyzer.reports.index_page import generate_html_index
            generate_html_index(output_folder)
        except Exception:
            LOGGER.exception("TLM continuation completed, but the HTML index refresh failed")
        return manifest
    except Exception:
        if not swapped and safe_path(backup).exists() and not safe_path(target).exists():
            safe_rename(backup, target)
        raise
    finally:
        safe_rmtree(staging_parent, ignore_errors=True)
