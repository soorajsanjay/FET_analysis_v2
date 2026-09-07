"""Sample-grouped metric database and generic parameter comparisons."""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from fet_analyzer.path_utils import (
    prepare_write_path, safe_mkdir, safe_path, safe_rmtree, safe_unlink,
)
from fet_analyzer.utils.logging import LOGGER


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if np.isfinite(number) else None


def _flatten_numeric(value: Any, prefix: str = "") -> dict[str, float]:
    result: dict[str, float] = {}
    number = _finite_number(value)
    if number is not None and prefix:
        result[prefix] = number
    elif isinstance(value, dict):
        for key, child in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten_numeric(child, name))
    return result


def build_observations(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert processed file records into stable database observations."""
    observations: list[dict[str, Any]] = []
    for record in records:
        classification = record.get("classification", {})
        filename_info = classification.get("filename_info", {})
        source = record.get("source_file")
        source_name = Path(source).name if source else str(classification.get("source_filename", ""))
        sample_id = str(filename_info.get("sample_label") or Path(source_name).stem)
        measurement_type = getattr(
            classification.get("type"), "name", classification.get("type", "unknown")
        )
        parameters = _flatten_numeric(record.get("device_params", {}))
        metric_source = dict(record.get("metrics", {}))
        # Parameters and QA bookkeeping are stored elsewhere and must not be
        # misidentified as scientific dependent metrics.
        for administrative in ("device_geometry", "geometry_sources", "parameter_warnings", "quality"):
            metric_source.pop(administrative, None)
        metrics = {
            key: value for key, value in _flatten_numeric(metric_source).items()
            if not re.search(r"(^|[._])ss_(?:avg|mean)(?:[._]|$)", key, re.IGNORECASE)
        }
        observations.append({
            "sample_id": sample_id,
            "source_filename": source_name,
            "measurement_type": str(measurement_type).lower(),
            "parameters": parameters,
            "metrics": metrics,
        })
    return observations


def discover_comparisons(
    observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Find every metric having data at multiple values of a parameter."""
    by_sample: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        by_sample[observation["sample_id"]].append(observation)
    comparisons: list[dict[str, Any]] = []
    for sample_id, members in sorted(by_sample.items()):
        parameter_names = sorted({
            key for member in members for key in member["parameters"]
        })
        metric_names = sorted({
            key for member in members for key in member["metrics"]
        })
        for parameter in parameter_names:
            unique_parameter_values = {
                member["parameters"][parameter]
                for member in members if parameter in member["parameters"]
            }
            if len(unique_parameter_values) < 2:
                continue
            for metric in metric_names:
                points = [
                    {
                        "x": member["parameters"][parameter],
                        "y": member["metrics"][metric],
                        "source_filename": member["source_filename"],
                    }
                    for member in members
                    if parameter in member["parameters"] and metric in member["metrics"]
                ]
                if len(points) < 2 or len({point["x"] for point in points}) < 2:
                    continue
                comparisons.append({
                    "sample_id": sample_id,
                    "parameter": parameter,
                    "metric": metric,
                    "n_points": len(points),
                    "points": sorted(points, key=lambda point: (point["x"], point["source_filename"])),
                })
    return comparisons


def _safe_name(value: str, limit: int = 100) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_.")
    return (clean or "value")[:limit]


def _write_csv(observations: list[dict[str, Any]], path: Path) -> None:
    parameter_names = sorted({key for row in observations for key in row["parameters"]})
    metric_names = sorted({key for row in observations for key in row["metrics"]})
    headers = ["sample_id", "source_filename", "measurement_type"]
    headers += [f"parameter.{key}" for key in parameter_names]
    headers += [f"metric.{key}" for key in metric_names]
    with prepare_write_path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for observation in observations:
            row = {
                "sample_id": observation["sample_id"],
                "source_filename": observation["source_filename"],
                "measurement_type": observation["measurement_type"],
            }
            row.update({
                f"parameter.{key}": value
                for key, value in observation["parameters"].items()
            })
            row.update({
                f"metric.{key}": value
                for key, value in observation["metrics"].items()
            })
            writer.writerow(row)


def _write_excel(
    observations: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
    path: Path,
) -> None:
    try:
        import openpyxl
    except ImportError:
        LOGGER.warning("openpyxl unavailable: sample database Excel skipped")
        return
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Observations"
    parameter_names = sorted({key for row in observations for key in row["parameters"]})
    metric_names = sorted({key for row in observations for key in row["metrics"]})
    headers = ["sample_id", "source_filename", "measurement_type"]
    headers += [f"parameter.{key}" for key in parameter_names]
    headers += [f"metric.{key}" for key in metric_names]
    ws.append(headers)
    for observation in observations:
        ws.append([
            observation["sample_id"],
            observation["source_filename"],
            observation["measurement_type"],
            *[observation["parameters"].get(key) for key in parameter_names],
            *[observation["metrics"].get(key) for key in metric_names],
        ])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    comparison_sheet = wb.create_sheet("Comparisons")
    comparison_sheet.append([
        "sample_id", "parameter", "metric", "n_points",
        "parameter_value", "metric_value", "source_filename",
    ])
    for comparison in comparisons:
        for point in comparison["points"]:
            comparison_sheet.append([
                comparison["sample_id"], comparison["parameter"],
                comparison["metric"], comparison["n_points"],
                point["x"], point["y"], point["source_filename"],
            ])
    comparison_sheet.freeze_panes = "A2"
    comparison_sheet.auto_filter.ref = comparison_sheet.dimensions
    for sheet in wb.worksheets:
        for column in sheet.columns:
            width = min(max(len(str(cell.value or "")) for cell in column) + 2, 45)
            sheet.column_dimensions[column[0].column_letter].width = max(width, 12)
    wb.save(prepare_write_path(path))
    wb.close()


def _plot_comparisons(
    comparisons: list[dict[str, Any]], root: Path,
    config: dict[str, Any] | None = None,
    executor: Any = None,
) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        LOGGER.warning("matplotlib unavailable: sample comparison plots skipped")
        return
    filesystem_root = safe_path(root)
    if filesystem_root.exists():
        for stale_plot in filesystem_root.rglob("*.png"):
            if re.search(r"ss_(?:avg|mean)|avg.?ss", stale_plot.name, re.IGNORECASE):
                safe_unlink(stale_plot)
    if executor is None:
        for comparison in comparisons:
            _plot_comparison(comparison, root, config)
    else:
        futures = [
            executor.submit(_plot_comparison, comparison, root, config)
            for comparison in comparisons
        ]
        for future in futures:
            future.result()


def _plot_comparison(
    comparison: dict[str, Any], root: Path,
    config: dict[str, Any] | None = None,
) -> None:
    """Render one deterministic sample comparison in any worker process."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from fet_analyzer.plotting.transfer_plots import _setup_style

    _setup_style(config)
    sample_dir = root / _safe_name(comparison["sample_id"])
    safe_mkdir(sample_dir, parents=True, exist_ok=True)
    points = comparison["points"]
    x = np.asarray([point["x"] for point in points], dtype=float)
    y = np.asarray([point["y"] for point in points], dtype=float)
    fig, ax = plt.subplots()
    ax.scatter(x, y)
    order = np.argsort(x)
    ax.plot(x[order], y[order], alpha=0.5)
    ax.set(
        xlabel=comparison["parameter"],
        ylabel=comparison["metric"],
        title=f"{comparison['sample_id']}: {comparison['metric']} vs {comparison['parameter']}",
    )
    ax.grid(alpha=0.3)
    fig.tight_layout()
    name = _safe_name(
        f"{comparison['metric']}_vs_{comparison['parameter']}", limit=180
    )
    fig.savefig(prepare_write_path(sample_dir / f"{name}.png"))
    plt.close(fig)


def generate_sample_database(
    records: list[dict[str, Any]],
    output_root: Path,
    keep_plots: bool = False,
    config: dict[str, Any] | None = None,
    executor: Any = None,
) -> dict[str, Any]:
    """Write the durable sample database and all discovered comparisons."""
    safe_mkdir(output_root, parents=True, exist_ok=True)
    observations = build_observations(records)
    comparisons = discover_comparisons(observations)
    payload = {
        "schema_version": 2,
        "observations": observations,
        "comparisons": comparisons,
    }
    prepare_write_path(output_root / "sample_database.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_csv(observations, output_root / "sample_database.csv")
    _write_excel(observations, comparisons, output_root / "sample_database.xlsx")
    if keep_plots:
        _plot_comparisons(comparisons, output_root / "plots", config, executor)
    elif safe_path(output_root / "plots").exists():
        safe_rmtree(output_root / "plots")
    LOGGER.info(
        "Sample database: %d observations, %d parameter/metric comparisons",
        len(observations), len(comparisons),
    )
    return payload
