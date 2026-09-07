"""
Command-line interface for FET Analyzer.

Usage:
    python -m fet_analyzer --input ./data
    python -m fet_analyzer --output ./output --config config.yaml
    python -m fet_analyzer --recursive --dry-run
"""

from __future__ import annotations

import argparse
import multiprocessing
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import get_context
from pathlib import Path
from typing import Any

from fet_analyzer import __version__
from fet_analyzer.config import load_config
from fet_analyzer.file_discovery import discover_files
from fet_analyzer.validation import validate_analysis_readiness
from fet_analyzer.utils.logging import setup_logging, LOGGER, set_log_context, clear_log_context
from fet_analyzer.path_utils import (
    output_path_warning, safe_copy2, safe_mkdir, safe_path, safe_rmtree,
)


def _warn_if_output_path_long(output_path: Path) -> bool:
    """Print the non-blocking startup warning once, before file logging starts."""
    warning = output_path_warning(output_path)
    if not warning:
        return False
    print(f"WARNING: {warning}", file=sys.stderr)
    return True


def _copy_category_plots(
    device_plot_dir: Path,
    all_plots_dir: Path,
    category: str,
    source_stem: str,
) -> None:
    """Copy generated plot PNGs into a category-level sanity-check folder."""
    category_dir = all_plots_dir / category
    safe_mkdir(category_dir, parents=True, exist_ok=True)
    safe_stem = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in source_stem)
    for plot_path in sorted(safe_path(device_plot_dir).glob("*.png")):
        target = category_dir / f"{safe_stem}__{plot_path.name}"
        safe_copy2(plot_path, target)



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fet-analyzer",
        description="Automated FET electrical characterization analysis pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m fet_analyzer                                  # Process current directory
  python -m fet_analyzer --input ./data                    # Process specific folder
  python -m fet_analyzer --config my_config.yaml           # Use custom config
  python -m fet_analyzer --recursive                       # Search subdirectories
  python -m fet_analyzer --dry-run                         # List files, don't process
  python -m fet_analyzer --only transfer                   # Only transfer curves
  python -m fet_analyzer --only tlm --tlm-continue         # Refresh only TLM artifacts in existing output
  python -m fet_analyzer --summary-only                    # Batch summary only

Interfaces:
  cd <measurement-folder>                                    # Choose a valid working directory
  fet-native --root .                                        # Native desktop GUI
  python -m fet_analyzer.native --root .                     # Native module equivalent
  python -m fet_analyzer.dashboard --root .                  # Browser dashboard
  python -m fet_analyzer.dashboard --root . --no-browser
  fet-dashboard --root .                                     # Browser command equivalent

  Install native support from a source checkout with:
  python -m pip install -e ".[native]"
        """,
    )
    parser.add_argument(
        "--input", "-i",
        type=str,
        default=None,
        help="Input folder containing measurement files (default: current directory)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output folder (default: 'output' inside input folder)",
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="Path to YAML configuration file",
    )
    parser.add_argument(
        "--recursive", "-r",
        action="store_true",
        default=None,
        help="Search input folder recursively for files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover and list files without processing",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        choices=["transfer", "output", "general_iv", "tlm"],
        help="Process only specified measurement type",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Only generate batch summary from existing output folders",
    )
    parser.add_argument(
        "--version", "-V",
        action="version",
        version=f"fet-analyzer {__version__}",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Increase log verbosity (DEBUG level)",
    )
    parser.add_argument(
        "--doctor", action="store_true",
        help="Check required dependencies and exit",
    )
    parser.add_argument(
        "--tlm-continue", action="store_true",
        help="With --only tlm, atomically refresh TLM artifacts in an existing output folder",
    )
    parser.add_argument(
        "--no-device-excel", action="store_true",
        help="Skip input-named per-file Excel workbooks (HTML reports remain enabled)",
    )
    parser.add_argument(
        "--save-plots", action="store_true",
        help="Retain per-file PNG plot folders (HTML reports always embed plots)",
    )
    parser.add_argument(
        "--no-plot-copies", action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--batch-plots", action="store_true",
        help="Retain batch statistical PNG files (disabled by default)",
    )
    overwrite_group = parser.add_mutually_exclusive_group()
    overwrite_group.add_argument(
        "--overwrite", dest="overwrite", action="store_true", default=None,
        help="Replace existing per-file output artifacts",
    )
    overwrite_group.add_argument(
        "--no-overwrite", dest="overwrite", action="store_false",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--no-batch-plots", action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--workers", type=int, default=0,
        help="Parallel device-analysis processes (0=automatic, 1=serial)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Main entry point. Returns exit code."""
    multiprocessing.freeze_support()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.tlm_continue and args.only != "tlm":
        parser.error("--tlm-continue is valid only with --only tlm")
    if args.summary_only and (args.tlm_continue or args.dry_run or args.only):
        parser.error("--summary-only cannot be combined with --only, --tlm-continue, or --dry-run")
    if args.workers < 0:
        parser.error("--workers must be zero or a positive integer")

    if args.doctor:
        import importlib
        failures = []
        print(f"Python: {sys.version.split()[0]}")
        for module in ["numpy", "yaml", "matplotlib", "openpyxl", "scipy"]:
            try:
                loaded = importlib.import_module(module)
                print(f"[OK] {module} {getattr(loaded, '__version__', '')}")
            except Exception as exc:
                failures.append(module)
                print(f"[MISSING] {module}: {exc}")
        try:
            importlib.import_module("webview")
            print("[OK] webview native host")
        except Exception as exc:
            print(f"[OPTIONAL] webview unavailable: {exc}")
        try:
            from fet_analyzer.registry import PARSERS
            parsers = PARSERS.describe()
            if not parsers:
                raise RuntimeError("no parsers registered")
            print("[OK] parser registry:", ", ".join(item["key"] for item in parsers))
        except Exception as exc:
            failures.append("parser_registry")
            print(f"[FAILED] parser registry: {exc}")
        try:
            checked = load_config(args.config)
            validation = checked.validation_report
            if validation.get("status") == "error":
                raise RuntimeError("; ".join(item["message"] for item in validation.get("issues", []) if item.get("level") == "error"))
            readiness = validate_analysis_readiness(checked._data)
            if readiness.errors:
                raise RuntimeError("; ".join(item.message for item in readiness.errors))
            print(f"[OK] configuration ({validation.get('status', 'pass')})")
        except Exception as exc:
            failures.append("configuration")
            print(f"[FAILED] configuration: {exc}")
        input_path = Path(args.input or ".").expanduser().resolve()
        output_path = Path(args.output).expanduser().resolve() if args.output else input_path / "output"
        print(f"[{'OK' if input_path.is_dir() else 'FAILED'}] input path: {input_path}")
        if not input_path.is_dir():
            failures.append("input_path")
        output_parent = output_path if output_path.exists() else output_path.parent
        writable = output_parent.exists() and os.access(output_parent, os.W_OK)
        print(f"[{'OK' if writable else 'FAILED'}] output writable: {output_path}")
        if not writable:
            failures.append("output_path")
        from fet_analyzer.runtime import version_payload
        print("Versions:", version_payload())
        print("Environment status:", "FAILED" if failures else "READY")
        return 1 if failures else 0

    # ── Load config ─────────────────────────────────────────────────────
    try:
        config = load_config(args.config)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error loading config: {e}", file=sys.stderr)
        return 1
    readiness = validate_analysis_readiness(config._data)
    if readiness.errors and not (args.tlm_continue or args.summary_only):
        details = "; ".join(f"{item.path}: {item.message}" for item in readiness.errors)
        print(f"Analysis preflight failed: {details}", file=sys.stderr)
        return 1

    # ── Override config with CLI args ───────────────────────────────────
    if args.verbose:
        config._data["general"]["log_level"] = "DEBUG"
    if args.overwrite is not None:
        config._data["general"]["overwrite"] = args.overwrite
    config._data["execution"] = {
        "generate_device_excel": not args.no_device_excel,
        "save_plots": bool(args.save_plots),
        "copy_plots_to_gallery": bool(args.save_plots and not args.no_plot_copies),
        "generate_batch_plots": bool(args.batch_plots and not args.no_batch_plots),
    }

    # ── Setup logging ───────────────────────────────────────────────────
    # Resolve the input override before deriving a relative configured output.
    if args.input:
        config._data["general"]["input_folder"] = str(Path(args.input).resolve())
    configured_output = Path(args.output) if args.output else Path(config.output_folder)
    if args.summary_only:
        if not configured_output.is_dir():
            print(f"Summary output folder does not exist: {configured_output}", file=sys.stderr)
            return 1
        try:
            from fet_analyzer.reports.batch_summary import generate_batch_summary
            from fet_analyzer.reports.index_page import generate_html_index
            generate_batch_summary(configured_output, config._data)
            generate_html_index(configured_output)
        except Exception:
            LOGGER.exception("Batch summary generation failed")
            return 1
        return 0
    _warn_if_output_path_long(configured_output)
    setup_logging(
        level=config.log_level,
        log_file=configured_output / config.processing_log
        if not args.dry_run else None,
    )

    LOGGER.info("FET Analyzer v%s", __version__)
    LOGGER.info("Config: %s", args.config or "defaults")

    # ── Determine input/output folders ──────────────────────────────────
    input_folder = Path(args.input) if args.input else config.input_folder
    if not input_folder.exists():
        LOGGER.error("Input folder does not exist: %s", input_folder)
        return 1

    output_folder = Path(args.output) if args.output else config.output_folder
    LOGGER.info("Input:  %s", input_folder.resolve())
    LOGGER.info("Output: %s", output_folder.resolve())

    # ── Override config paths for downstream use ────────────────────────
    config._data["general"]["input_folder"] = str(input_folder)
    config._data["general"]["output_folder"] = str(output_folder)
    if args.recursive is not None:
        config._data["general"]["recursive"] = args.recursive

    # ── Discover files ──────────────────────────────────────────────────
    try:
        file_list, duplicate_info = discover_files(
            input_folder=input_folder,
            recursive=config.recursive,
            skip_patterns=config.skip_patterns,
            file_priority=config.file_priority,
            excluded_roots=[output_folder, input_folder / "decompressed_ztr"],
        )
    except Exception as e:
        LOGGER.error("File discovery failed: %s", e)
        return 1

    if not file_list:
        LOGGER.warning("No supported measurement files found in %s", input_folder)
        return 1 if args.tlm_continue else 0

    if args.tlm_continue:
        LOGGER.info("TLM-only continuation mode - ordinary device and batch summaries will not be modified")
        try:
            if args.dry_run:
                import json
                from fet_analyzer.tlm_continue import tlm_preflight
                payload = tlm_preflight(file_list, input_folder, config._data, output_folder)
                print(json.dumps(payload, indent=2, default=str))
                return 1 if payload.get("status") == "error" else 0
            from fet_analyzer.tlm_continue import run_tlm_continuation
            manifest = run_tlm_continuation(file_list, input_folder, output_folder, config._data)
            LOGGER.info("TLM continuation complete: %s", manifest)
        except Exception:
            LOGGER.exception("TLM continuation failed; existing TLM artifacts were preserved")
            return 1
        return 0

    # ── Dry run: just list what would be processed ──────────────────────
    if args.dry_run:
        print(f"\nFound {len(file_list)} file(s) to process:\n")
        for fp in file_list:
            print(f"  {fp.relative_to(input_folder)}")
        if duplicate_info:
            print(f"\n{len(duplicate_info)} duplicate group(s) resolved:")
            for info in duplicate_info:
                print(f"  {info['stem']}:")
                print(f"    ✓ {Path(info['chosen']).name}")
                for r in info["rejected"]:
                    print(f"    ✗ {Path(r).name} (skipped)")
        return 0

    # ── Create output structure ─────────────────────────────────────────
    safe_mkdir(output_folder, parents=True, exist_ok=True)

    # Add one editable master-parameter row for each newly detected sample.
    from fet_analyzer.analysis.classifier import parse_filename_groups
    from fet_analyzer.device_parameters import synchronize_sample_rows, write_master_template
    master_params_path = input_folder / "device_parameters.txt"
    write_master_template(master_params_path, config.device_defaults)
    detected_samples = [
        parse_filename_groups(path.name, config._data.get("filename_patterns", {})).get("sample_label", "")
        for path in file_list
    ]
    added_samples = synchronize_sample_rows(master_params_path, detected_samples)
    if added_samples:
        LOGGER.warning("Added provisional device-parameter row(s) for sample(s): %s",
                       ", ".join(added_samples))

    # The master table is shared by the whole batch.  Loading it once avoids
    # repeated disk parsing without changing parameter precedence or results.
    from fet_analyzer.device_parameters import load_master_table
    parameter_rows = load_master_table(master_params_path)

    # ── Filter by measurement type if requested ─────────────────────────
    only_filter: str | None = args.only
    if only_filter:
        LOGGER.info("Filtering for measurement type: %s", only_filter)

    # ── Process files ───────────────────────────────────────────────────
    from fet_analyzer.temp_workspace import RunWorkspace
    run_workspace = RunWorkspace(output_folder)
    config._data["execution"]["temporary_root"] = str(run_workspace.path)
    LOGGER.info("Processing %d file(s)", len(file_list))
    progress_total = len(file_list) + 4

    def report_progress(current: int, label: str) -> None:
        percent = round(current * 100 / progress_total) if progress_total else 0
        print(f"[PROGRESS] {current}/{progress_total} {percent}% {label}", flush=True)

    def report_status(label: str) -> None:
        set_log_context(stage=label, source="-")
        print(f"[STATUS] {label}", flush=True)

    report_progress(0, "Preparing input files")

    from fet_analyzer.parsers.ztr_parser import decompress_ztr_to_cache
    from fet_analyzer.registry import parse_measurement
    from fet_analyzer.analysis.classifier import classify_measurement, MeasurementType
    from fet_analyzer.analysis.segmentation import segment_sweeps
    from fet_analyzer.analysis.cleaning import clean_all_segments
    from fet_analyzer.output_structure import (
        create_output_structure, save_metadata_json,
    )

    # Pre-decompress ZTR/ZIP archives once into a reusable cache. Subsequent
    # runs parse the cached XTR directly instead of reopening/decompressing the
    # same archive for every analysis pass.
    ztr_cache_dir = output_folder / "decompressed_ztr"
    ztr_cache: dict[Path, Path] = {}
    for fp in file_list:
        if fp.suffix.lower() in (".ztr", ".zip"):
            try:
                ztr_cache[fp] = decompress_ztr_to_cache(fp, ztr_cache_dir)
            except Exception:
                LOGGER.exception("Failed to decompress ZTR/ZIP input: %s", fp.name)

    stats = {"transfer": 0, "output": 0, "general_iv": 0, "tlm": 0, "error": 0}
    run_errors: list[dict[str, Any]] = []
    processed_records: list[dict[str, Any]] = []
    automatic_workers = max(1, min(8, (os.cpu_count() or 2) - 1))
    worker_count = args.workers or min(len(file_list), automatic_workers)
    if worker_count < 1:
        LOGGER.error("--workers must be 0 or a positive integer")
        return 1
    for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ.setdefault(variable, "1")
    executor = (
        ProcessPoolExecutor(max_workers=worker_count, mp_context=get_context("spawn"))
        if worker_count > 1 and len(file_list) > 1 else None
    )
    pending: dict[Any, tuple[int, dict[str, Any]]] = {}
    config._data["execution"]["workers"] = worker_count
    LOGGER.info("Device analysis workers: %d", worker_count if executor else 1)

    for file_index, fp in enumerate(file_list, start=1):
        set_log_context(stage="device_analysis", source=fp.name)
        report_status(f"Processing {fp.name}")
        LOGGER.info("Processing: %s", fp.name)
        temporary_plot_dir: Path | None = None
        try:
            # ── 1. Parse ──────────────────────────────────────────────
            parsed = parse_measurement(fp, cached_path=ztr_cache.get(fp))

            if parsed["num_rows"] == 0:
                LOGGER.warning("  → No data rows in %s — skipping", fp.name)
                stats["error"] += 1
                from fet_analyzer.reports.error_report import error_entry
                run_errors.append(error_entry(
                    "file_validation",
                    ValueError("Parsed measurement contains no data rows"),
                    str(fp),
                ))
                continue

            # ── 2. Classify ───────────────────────────────────────────
            classification = classify_measurement(
                parsed["metadata"], parsed["columns"], parsed["data"],
                filename=fp.name,
                filename_patterns=config._data.get("filename_patterns"),
            )
            classification["source_filename"] = fp.name
            meas_type = classification["type"]
            LOGGER.info("  → Classified: %s (confidence: %.2f)",
                        meas_type.name, classification["confidence"])

            # Apply the measurement-role filter before creating or replacing
            # any per-file output artifacts.  TLM is a role shared by transfer,
            # output, and explicit LTLM files, not a single enum value.
            if only_filter:
                type_map = {
                    "transfer": MeasurementType.TRANSFER,
                    "output": MeasurementType.OUTPUT,
                    "general_iv": MeasurementType.GENERAL_IV,
                }
                matches = (
                    bool(classification.get("is_tlm"))
                    if only_filter == "tlm" else meas_type == type_map.get(only_filter)
                )
                if not matches:
                    LOGGER.info("  -> Skipping (type=%s, filter=%s)", meas_type.name, only_filter)
                    continue

            # Resolve a single master parameter table for the complete input folder.
            from fet_analyzer.device_parameters import resolve_device_parameters
            from fet_analyzer.analysis.geometry import infer_geometry
            device_params_path = input_folder / "device_parameters.txt"
            inferred, inferred_sources = infer_geometry(fp, parsed["metadata"])
            sample_label = classification.get("filename_info", {}).get("sample_label", "unknown")
            device_params, parameter_sources, parameter_warnings = resolve_device_parameters(
                config.device_defaults, parameter_rows, str(sample_label), fp.name,
                inferred=inferred, inferred_sources=inferred_sources,
            )
            LOGGER.debug("  → Resolved device parameters from %s", device_params_path)
            classification["device_polarity"] = device_params.get(
                "polarity", config.device_defaults.get("polarity", "p")
            )
            from fet_analyzer.preflight import assess_parameter_preflight
            parameter_preflight = assess_parameter_preflight(
                device_params, parameter_sources, config._data
            )

            # ── 3. Segment ────────────────────────────────────────────
            segments = segment_sweeps(
                parsed, classification,
                vds_tolerance_v=float(
                    config._data.get("transfer", {}).get(
                        "vds_segmentation_tolerance_v", 1e-6
                    )
                ),
            )
            if not segments:
                LOGGER.warning("  → No valid sweep segments — skipping")
                stats["error"] += 1
                from fet_analyzer.reports.error_report import error_entry
                run_errors.append(error_entry(
                    "segmentation",
                    ValueError("No valid sweep segments were detected"),
                    str(fp),
                ))
                continue
            LOGGER.info("  → %d sweep segment(s)", len(segments))

            # ── 4. Clean ──────────────────────────────────────────────
            # Keep raw data separate because cleaning mutates the analysis segments.
            from copy import deepcopy
            raw_segments = deepcopy(segments) if not args.no_device_excel else None
            clean_results = clean_all_segments(
                segments,
                noise_floor_a=device_params.get("noise_floor_a", config.noise_floor_a),
                compliance_threshold_pct=float(
                    config._data.get("advanced", {}).get("compliance_threshold_pct", 0.005)
                ),
                compliance_cleaning_enabled=bool(
                    config._data.get("advanced", {}).get("compliance_cleaning_enabled", False)
                ),
            )
            # Replace segment data with cleaned data
            for seg, clean_result in zip(segments, clean_results):
                seg.data = clean_result["cleaned"]
                seg.sweep_values = clean_result["cleaned"][seg.sweep_variable]
                n_removed = (
                    clean_result["n_removed_nan"]
                    + clean_result["n_removed_compliance"]
                    + clean_result["n_removed_noise"]
                )
                if n_removed > 0:
                    LOGGER.debug("  → Cleaned: %d points removed", n_removed)

            # ── 5. Create output structure ────────────────────────────
            paths = create_output_structure(
                output_folder, fp.stem, fp, overwrite=config.overwrite,
                keep_plots=args.save_plots,
            )
            if not paths:
                LOGGER.info("  → Output exists, skipping")
                continue
            if not args.save_plots:
                temporary_plot_dir = run_workspace.temporary_directory("device_")
                paths["plots"] = temporary_plot_dir

            # (device_params already loaded above — use cached values)

            # Save metadata
            save_metadata_json(paths["metadata_json"], {
                "file": str(fp),
                "classification": {k: str(v) if hasattr(v, 'name') else v
                                   for k, v in classification.items()},
                "parsed_metadata": parsed["metadata"],
                "parsed_warnings": parsed.get("warnings", []),
            })

            # ── 7. Process by type ────────────────────────────────────
            from fet_analyzer.analysis.device_worker import analyze_device
            worker_payload = {
                "source_file": fp, "segments": segments,
                "classification": classification, "device_params": device_params,
                "parameter_sources": parameter_sources,
                "parameter_warnings": parameter_warnings,
                "parameter_preflight": parameter_preflight,
                "config": config._data,
                "config_validation": config.validation_report,
                "clean_results": clean_results,
                "parsed_metadata": parsed["metadata"], "paths": paths,
            }
            if executor is not None:
                record = {
                    "source_file": fp, "segments": segments,
                    "classification": classification, "device_params": device_params,
                    "parameter_sources": parameter_sources,
                    "parameter_preflight": parameter_preflight, "paths": paths,
                    "raw_segments": raw_segments, "parsed_metadata": parsed["metadata"],
                    "temporary_plot_dir": temporary_plot_dir,
                    "generate_device_excel": not args.no_device_excel,
                    "file_index": file_index,
                }
                future = executor.submit(analyze_device, worker_payload)
                pending[future] = (file_index, record)
                temporary_plot_dir = None
                continue

            metrics, stat_key = analyze_device(worker_payload)
            stats[stat_key] += 1
            if args.save_plots and not args.no_plot_copies:
                _copy_category_plots(
                    paths["plots"], output_folder / "all_plots", stat_key, fp.stem
                )

            processed_records.append({
                "source_file": fp, "segments": segments, "classification": classification,
                "device_params": device_params, "parameter_sources": parameter_sources,
                "parameter_preflight": parameter_preflight, "metrics": metrics,
                "paths": paths, "raw_segments": raw_segments,
                "parsed_metadata": parsed["metadata"],
                "temporary_plot_dir": temporary_plot_dir,
                "generate_device_excel": not args.no_device_excel,
            })
            temporary_plot_dir = None
            LOGGER.info("  ? Done: %s", paths["report"])

        except Exception as exc:
            LOGGER.exception("  -> ERROR processing %s", fp.name)
            stats["error"] += 1
            from fet_analyzer.reports.error_report import error_entry
            run_errors.append(error_entry("file_processing", exc, str(fp)))
        finally:
            if temporary_plot_dir is not None:
                safe_rmtree(temporary_plot_dir, ignore_errors=True)
            if executor is None:
                report_progress(file_index, f"Processed {fp.name}")
            clear_log_context()

    if executor is not None:
        report_status(f"Running {len(pending)} device analyses in parallel")
        completed = len(file_list) - len(pending)
        for future in as_completed(pending):
            _, record = pending[future]
            try:
                metrics, stat_key = future.result()
                record["metrics"] = metrics
                stats[stat_key] += 1
                processed_records.append(record)
                if args.save_plots and not args.no_plot_copies:
                    _copy_category_plots(
                        record["paths"]["plots"], output_folder / "all_plots",
                        stat_key, record["source_file"].stem,
                    )
                LOGGER.info("  -> Done: %s", record["paths"]["report"])
            except Exception as exc:
                LOGGER.exception("  -> ERROR processing %s", record["source_file"].name)
                stats["error"] += 1
                from fet_analyzer.reports.error_report import error_entry
                run_errors.append(error_entry("file_processing", exc, str(record["source_file"])))
                temporary = record.get("temporary_plot_dir")
                if temporary is not None:
                    safe_rmtree(temporary, ignore_errors=True)
            completed += 1
            report_progress(completed, f"Processed {record['source_file'].name}")
        processed_records.sort(key=lambda item: item.get("file_index", 0))
        if not pending:
            report_progress(len(file_list), "No device analyses required")

    # ── Batch Summary ──────────────────────────────────────────────────
    # Resolve group-level Ion semantics after all transfer sweeps are known,
    # then overwrite the preliminary per-device artifacts with final values.
    if processed_records:
        report_status("Finalizing device reports")
        from fet_analyzer.analysis.common_overdrive import apply_max_common_overdrive
        common_overdrive_audit = apply_max_common_overdrive(processed_records, config._data)
        from fet_analyzer.analysis.device_worker import render_device
        render_futures: dict[Any, dict[str, Any]] = {}
        for record in processed_records:
            try:
                record["metrics"]["common_overdrive_audit"] = common_overdrive_audit
                record["metrics"]["config_validation"] = config.validation_report
                record["metrics"]["classification"] = record["classification"]
                record["metrics"]["source_file"] = str(record["source_file"])
                if executor is None:
                    render_device(record)
                else:
                    render_futures[executor.submit(render_device, record)] = record
            except Exception as exc:
                LOGGER.exception("Final report render failed: %s", record["source_file"])
                stats["error"] += 1
                from fet_analyzer.reports.error_report import error_entry
                run_errors.append(error_entry("final_report_render", exc, str(record["source_file"])))
            finally:
                if executor is None:
                    temporary = record.get("temporary_plot_dir")
                    if temporary is not None:
                        safe_rmtree(temporary, ignore_errors=True)
        for future in as_completed(render_futures):
            record = render_futures[future]
            try:
                _, finalized_metrics = future.result()
                record["metrics"] = finalized_metrics
            except Exception as exc:
                LOGGER.exception("Final report render failed: %s", record["source_file"])
                stats["error"] += 1
                from fet_analyzer.reports.error_report import error_entry
                run_errors.append(error_entry("final_report_render", exc, str(record["source_file"])))
            finally:
                temporary = record.get("temporary_plot_dir")
                if temporary is not None:
                    safe_rmtree(temporary, ignore_errors=True)

    report_progress(len(file_list) + 1, "Finalized device reports")

    LOGGER.info("")
    LOGGER.info("----------------------------------------")
    LOGGER.info("Processing complete")
    LOGGER.info("Transfer:   %3d", stats["transfer"])
    LOGGER.info("Output:     %3d", stats["output"])
    LOGGER.info("General IV: %3d", stats["general_iv"])
    LOGGER.info("TLM:        %3d", stats["tlm"])
    LOGGER.info("Errors:     %3d", stats["error"])
    LOGGER.info("----------------------------------------")

    if processed_records:
        report_status("Generating sample comparisons")
        try:
            from fet_analyzer.analysis.sample_database import generate_sample_database
            database = generate_sample_database(
                processed_records, output_folder / "sample_database",
                keep_plots=args.save_plots, config=config._data, executor=executor,
            )
            LOGGER.info(
                "Sample database generated: %d comparison(s)",
                len(database.get("comparisons", [])),
            )
        except Exception as exc:
            LOGGER.exception("Sample database generation failed")
            stats["error"] += 1
            from fet_analyzer.reports.error_report import error_entry
            run_errors.append(error_entry("sample_database", exc))

        report_progress(len(file_list) + 2, "Generated sample comparisons")

        if executor is not None:
            executor.shutdown(wait=True)

        report_status("Running dedicated TLM analysis")
        try:
            from fet_analyzer.analysis.tlm_workflow import generate_tlm_workflow
            generated = generate_tlm_workflow(processed_records, output_folder / "TLM", config._data)
            LOGGER.info("Dedicated TLM workflow: %d group(s)", len(generated))
        except Exception as exc:
            LOGGER.exception("Dedicated TLM workflow failed")
            stats["error"] += 1
            from fet_analyzer.reports.error_report import error_entry
            run_errors.append(error_entry("tlm_workflow", exc))
    else:
        if executor is not None:
            executor.shutdown(wait=True)
        report_progress(len(file_list) + 2, "No sample summaries required")

    # ── TLM Auto-Grouping (across devices) ───────────────────────────
    # Trigger when any devices have rtotal metrics (from TLM-named files)
    if stats["transfer"] + stats["output"] + stats["tlm"] > 0:
        report_status("Finalizing TLM summaries")
        import json, re
        try:
            from fet_analyzer.analysis.tlm import auto_group_tlm, extract_tlm_with_statistics
            # Collect device-level params from all processed outputs
            tlm_devices: list[dict[str, Any]] = []
            for metadata_file in sorted(output_folder.glob("*_metadata.json")):
                device_name = metadata_file.name.removesuffix("_metadata.json")
                metrics_file = output_folder / f"{device_name}_metrics.json"
                if not metrics_file.exists(): continue
                with open(safe_path(metrics_file), encoding="utf-8") as f:
                    dev_metrics = json.load(f)
                # Extract channel length and grouping identity from filenames only.
                dev_params_loaded: dict[str, Any] = {}
                dev_meta: dict[str, Any] = {}
                finfo: dict[str, Any] = {}
                parsed_meta: dict[str, Any] = {}
                if metadata_file.exists():
                    with open(safe_path(metadata_file), encoding="utf-8") as f:
                        dev_meta = json.load(f)
                    parsed_meta = dev_meta.get("parsed_metadata", {})
                    fname = Path(dev_meta.get("file", "")).stem if dev_meta.get("file") else ""
                    lch_match = re.search(config.lch_regex, fname, re.IGNORECASE)
                    if lch_match:
                        dev_params_loaded["channel_length_um"] = float(lch_match.group(1))
                    # Sample ID — strip _TLM_Xum suffix for TLM grouping
                    finfo = dev_meta.get("classification", {}).get("filename_info", {})
                    raw_sample = finfo.get("sample_label", device_name)
                    # Remove _TLM{num}_{X}um suffix to unify TLM variants
                    sample_clean = re.sub(r'_TLM\d*_\d+\.?\d*um.*', '', str(raw_sample),
                                          flags=re.IGNORECASE)
                    dev_params_loaded["sample_id"] = sample_clean or raw_sample

                geometry = dev_metrics.get("device_geometry", {})
                dev_params_loaded = {**geometry, **dev_params_loaded}
                rtotal_data = dev_metrics.get("rtotal", {})
                rtot = rtotal_data.get("rtotal_ohm")
                read_points = [
                    value for value in (rtotal_data.get("rtotal_per_segment") or {}).values()
                    if isinstance(value, dict) and value.get("rtotal_ohm") is not None
                ]
                read_point = min(
                    read_points,
                    key=lambda value: abs(float(value["rtotal_ohm"]) - float(rtot)),
                ) if read_points and rtot is not None else {}
                lch = dev_params_loaded.get("channel_length_um")
                # Tag with measurement type so transfer/output TLM groups stay separate
                meas_type = dev_meta.get("classification", {}).get("type", "unknown")
                # Strip "MeasurementType." prefix if present
                if isinstance(meas_type, str) and "." in meas_type:
                    meas_type = meas_type.split(".")[-1]
                if rtot is not None and lch is not None:
                    tlm_devices.append({
                        "sample_id": dev_params_loaded.get("sample_id", device_name),
                        "sample_label": dev_params_loaded.get("sample_id", device_name),
                        "channel_length_um": lch,
                        "r_total_ohm": rtot,
                        "channel_width_um": dev_params_loaded.get("channel_width_um", config.channel_width_um),
                        "film_thickness_nm": dev_params_loaded.get("film_thickness_nm"),
                        "measurement_type": meas_type,
                        "device_type": finfo.get("device_type"),
                        "contact_metal": dev_params_loaded.get("contact_metal"),
                        "gate_dielectric": dev_params_loaded.get("gate_dielectric"),
                        "vds_v": (rtotal_data.get("read_conditions") or {}).get("transfer_read_vds_v"),
                        "overdrive_v": (rtotal_data.get("read_conditions") or {}).get("transfer_overdrive_v"),
                        "transfer_read_mode": (rtotal_data.get("read_conditions") or {}).get("transfer_read_mode"),
                        "transfer_read_vg_v": (rtotal_data.get("read_conditions") or {}).get("transfer_read_vg_v"),
                        "transfer_gate_field_mv_cm": (rtotal_data.get("read_conditions") or {}).get("transfer_gate_field_mv_cm"),
                        "transfer_overdrive_field_mv_cm": (rtotal_data.get("read_conditions") or {}).get("transfer_overdrive_field_mv_cm"),
                        "requested_read_vg_v": read_point.get("requested_vg_v"),
                        "actual_read_vg_v": read_point.get("actual_vg_v"),
                        "read_vg_delta_v": read_point.get("vg_delta_v"),
                        "requested_overdrive_v": read_point.get("requested_overdrive_v"),
                        "actual_overdrive_v": read_point.get("actual_overdrive_v"),
                        "requested_gate_field_mv_cm": read_point.get("requested_gate_field_mv_cm"),
                        "actual_gate_field_mv_cm": read_point.get("actual_gate_field_mv_cm"),
                        "requested_overdrive_field_mv_cm": read_point.get("requested_overdrive_field_mv_cm"),
                        "actual_overdrive_field_mv_cm": read_point.get("actual_overdrive_field_mv_cm"),
                        "source_file": dev_meta.get("file", ""),
                        "device_name": device_name,
                        "raw_metadata": parsed_meta,
                    })

            if tlm_devices:
                tlm_results = auto_group_tlm(
                    tlm_devices, min_devices=config.tlm_min_channel_lengths,
                    group_keys=config.tlm_group_keys,
                )
                if tlm_results:
                    from fet_analyzer.reports.device_report import generate_tlm_report, write_tlm_excel
                    from fet_analyzer.plotting.tlm_plots import plot_tlm
                    tlm_dir = output_folder / "batch_summary"
                    safe_mkdir(tlm_dir, parents=True, exist_ok=True)
                    tlm_plot_files: list[Path] = []
                    temporary_tlm_dir: Path | None = None
                    if args.save_plots:
                        tlm_plot_dir = tlm_dir / "plots"
                        safe_mkdir(tlm_plot_dir, parents=True, exist_ok=True)
                    else:
                        if (tlm_dir / "plots").exists():
                            safe_rmtree(tlm_dir / "plots")
                        temporary_tlm_dir = run_workspace.temporary_directory("tlm_auto_")
                        tlm_plot_dir = temporary_tlm_dir
                    for tlm_res in tlm_results:
                        sample_id = tlm_res.get("sample_id", "unknown")
                        # Filter devices for THIS sample only for statistics
                        sample_devices = [
                            d for d in tlm_devices
                            if d.get("device_name") in tlm_res.get("member_device_names", [])
                        ]
                        lch_vals = tlm_res.get("lch_values", [])
                        has_duplicates = len(lch_vals) > len({l for l, _ in lch_vals})
                        result_for_export = tlm_res
                        if has_duplicates:
                            stats_result = extract_tlm_with_statistics(
                                sample_devices, width_um=config.channel_width_um,
                                film_thickness_nm=next(iter({d.get("film_thickness_nm") for d in sample_devices if d.get("film_thickness_nm") is not None}), None))
                            if stats_result.get("n_points", 0) >= config.tlm_min_channel_lengths:
                                stats_result["sample_id"] = sample_id
                                result_for_export = stats_result
                        # Windows-safe deterministic export identifier.
                        export_id = result_for_export.get("group_id", sample_id)
                        tlm_id_clean = re.sub(r'[^A-Za-z0-9._-]+', '_', str(export_id)).strip('_') or "unknown"
                        plot_path = tlm_plot_dir / f"tlm_{tlm_id_clean}.png"
                        plot_tlm(result_for_export, plot_path, config._data)
                        tlm_plot_files.append(plot_path)
                        # The exact group filter above ensures Raw Data is populated.
                        write_tlm_excel(
                            result_for_export, sample_devices,
                            tlm_dir / f"tlm_{tlm_id_clean}.xlsx",
                        )
                    generate_tlm_report(tlm_results, tlm_dir / "tlm_report.html", tlm_devices, tlm_plot_files)
                    if temporary_tlm_dir is not None:
                        safe_rmtree(temporary_tlm_dir, ignore_errors=True)
                    LOGGER.info("TLM auto-grouping: %d sample(s)", len(tlm_results))
        except Exception as exc:
            LOGGER.exception("TLM auto-grouping failed")
            stats["error"] += 1
            from fet_analyzer.reports.error_report import error_entry
            run_errors.append(error_entry("tlm_auto_grouping", exc))

    # Generate the batch summary exactly once, after every TLM artifact exists.
    if stats["transfer"] + stats["output"] + stats["tlm"] > 0:
        report_status("Generating final batch summary")
        from fet_analyzer.reports.batch_summary import generate_batch_summary
        try:
            summary_dir = generate_batch_summary(output_folder, config._data)
            LOGGER.info("Batch summary: %s", summary_dir)
        except Exception as exc:
            LOGGER.exception("Batch summary generation failed")
            from fet_analyzer.reports.error_report import error_entry
            run_errors.append(error_entry("batch_summary", exc))
            stats["error"] += 1

    report_progress(len(file_list) + 3, "Completed TLM analysis")

    report_status("Writing manifest and HTML home page")
    from fet_analyzer.reports.error_report import write_error_reports, error_entry
    error_paths = write_error_reports(output_folder, run_errors)
    LOGGER.info("Error report: %s (%d error(s))", error_paths["html"], len(run_errors))

    from fet_analyzer.run_manifest import write_run_manifest
    manifest_path = write_run_manifest(
        output_folder, file_list, config._data, stats, duplicate_info, run_errors
    )
    LOGGER.info("Run manifest: %s", manifest_path)
    try:
        from fet_analyzer.reports.index_page import generate_html_index
        LOGGER.info("HTML home page: %s", generate_html_index(output_folder))
        from fet_analyzer.run_manifest import mark_manifest_index_complete
        mark_manifest_index_complete(manifest_path)
    except Exception as exc:
        LOGGER.exception("HTML home page generation failed")
        stats["error"] += 1
        run_errors.append(error_entry("html_index", exc))
        write_error_reports(output_folder, run_errors)
        manifest_path = write_run_manifest(
            output_folder, file_list, config._data, stats, duplicate_info, run_errors
        )
    report_progress(progress_total, "Completed all analysis outputs")
    run_workspace.cleanup()
    # A partial batch is useful, but must not look successful to automation.
    return 2 if stats["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
