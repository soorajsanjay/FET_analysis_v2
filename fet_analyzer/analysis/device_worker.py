"""Process-safe per-device analysis used by the batch orchestrator."""
from __future__ import annotations

from typing import Any


def analyze_device(payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Generate all per-device plots and metrics without rendering reports twice."""
    from fet_analyzer.analysis.classifier import MeasurementType
    from fet_analyzer.output_structure import save_metrics_json

    fp = payload["source_file"]
    segments = payload["segments"]
    classification = payload["classification"]
    meas_type = classification["type"]
    config = payload["config"]
    device_params = payload["device_params"]
    parameter_sources = payload["parameter_sources"]
    parameter_warnings = payload["parameter_warnings"]
    parameter_preflight = payload["parameter_preflight"]
    config_validation = payload["config_validation"]
    clean_results = payload["clean_results"]
    parsed_metadata = payload["parsed_metadata"]
    paths = payload["paths"]

    if meas_type == MeasurementType.TRANSFER:
        from fet_analyzer.plotting.transfer_plots import plot_transfer_curves
        from fet_analyzer.analysis.engine import analyze_result_objects
        from fet_analyzer.analysis.metric_summary import build_device_summary
        from fet_analyzer.preflight import apply_preflight_suppression
        from fet_analyzer.analysis.quality import assess_quality

        metrics = plot_transfer_curves(
            segments, classification, paths["plots"], config=config,
            device_params=device_params, metadata=parsed_metadata,
        )
        numerical_results = analyze_result_objects(segments, classification, config, device_params)
        metrics["sweep_results"] = [result.to_dict() for result in numerical_results]
        apply_preflight_suppression(metrics, parameter_preflight)
        metrics["device_summary"] = build_device_summary(metrics, config)
        metrics["device_geometry"] = device_params
        metrics["geometry_sources"] = parameter_sources
        metrics["parameter_warnings"] = parameter_warnings
        metrics["config_validation"] = config_validation
        metrics["quality"] = assess_quality(clean_results, metrics, config)
        metrics["device_summary"] = build_device_summary(metrics, config)
        if classification.get("is_tlm"):
            from fet_analyzer.analysis.tlm import extract_rtotal
            metrics["rtotal"] = extract_rtotal(segments, classification, config, device_params)
        stat_key = "transfer"

    elif meas_type == MeasurementType.OUTPUT:
        from fet_analyzer.plotting.output_plots import plot_output_curves
        from fet_analyzer.analysis.engine import analyze_result_objects
        from fet_analyzer.analysis.output_sweep import summarize_resistance_by_gate_bias
        from fet_analyzer.analysis.metric_summary import build_device_summary
        from fet_analyzer.analysis.quality import assess_quality

        metrics = plot_output_curves(
            segments, classification, paths["plots"], config=config,
            device_params=device_params, metadata=parsed_metadata,
        )
        numerical_results = analyze_result_objects(segments, classification, config, device_params)
        metrics["sweep_results"] = [result.to_dict() for result in numerical_results]
        metrics["resistance_by_gate_bias"] = summarize_resistance_by_gate_bias(numerical_results)
        metrics["device_summary"] = build_device_summary(metrics, config)
        metrics["device_geometry"] = device_params
        metrics["geometry_sources"] = parameter_sources
        metrics["parameter_warnings"] = parameter_warnings
        metrics["parameter_preflight"] = parameter_preflight
        metrics["config_validation"] = config_validation
        metrics["quality"] = assess_quality(clean_results, metrics, config)
        metrics["device_summary"] = build_device_summary(metrics, config)
        if classification.get("is_tlm"):
            from fet_analyzer.analysis.tlm import extract_rtotal
            metrics["rtotal"] = extract_rtotal(segments, classification, config, device_params)
        stat_key = "output"

    elif meas_type == MeasurementType.TLM:
        from fet_analyzer.analysis.tlm import extract_rtotal
        metrics = {
            "classification": classification,
            "rtotal": extract_rtotal(segments, classification, config, device_params),
            "n_segments": len(segments),
            "parameter_preflight": parameter_preflight,
            "config_validation": config_validation,
        }
        stat_key = "tlm"

    elif meas_type == MeasurementType.GENERAL_IV:
        metrics = {
            "classification": classification, "n_segments": len(segments),
            "parameter_preflight": parameter_preflight,
            "config_validation": config_validation,
        }
        if "tlm" in fp.name.lower():
            from fet_analyzer.analysis.tlm import extract_rtotal
            metrics["rtotal"] = extract_rtotal(segments, classification, config, device_params)
            stat_key = "tlm"
        else:
            stat_key = "general_iv"
    else:
        metrics = {
            "classification": classification, "n_segments": len(segments),
            "parameter_preflight": parameter_preflight,
            "config_validation": config_validation,
        }
        stat_key = "general_iv"

    metrics["analysis_type"] = meas_type.name.lower()
    save_metrics_json(paths["metrics_json"], metrics)
    return metrics, stat_key


def render_device(record: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Render one finalized device's HTML, workbook, and canonical metrics."""
    from fet_analyzer.output_structure import save_metrics_json
    from fet_analyzer.reports.device_report import generate_device_report, write_device_excel

    source = record["source_file"]
    paths = record["paths"]
    generate_device_report(
        device_name=source.stem,
        classification=record["classification"],
        metrics=record["metrics"],
        parsed_metadata=record["parsed_metadata"],
        plot_dir=paths["plots"],
        output_path=paths["report"],
        source_file=str(source),
    )
    if record["generate_device_excel"]:
        write_device_excel(
            segments=record["segments"],
            classification=record["classification"],
            metrics=record["metrics"],
            output_path=paths["analysis_xlsx"],
            raw_segments=record["raw_segments"],
        )
    save_metrics_json(paths["metrics_json"], record["metrics"])
    return str(source), record["metrics"]
