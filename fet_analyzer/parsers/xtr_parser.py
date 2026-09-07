"""
XTR (XML) parser for Keysight EasyEXPERT / B1500A measurement files.

Parses the XML TestDataSet format into structured metadata and measurement data.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from fet_analyzer.utils.logging import LOGGER

NS = "http://agilent.com/sta"


def _tag(elem: ET.Element) -> str:
    """Strip namespace from element tag."""
    tag = elem.tag
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _find_text(elem: ET.Element, *path: str) -> str | None:
    """Find text content of a nested element path."""
    current = elem
    for step in path:
        found = None
        for child in current:
            if _tag(child) == step:
                found = child
                break
        if found is None:
            return None
        current = found
    return current.text


def _parse_xml(source: Path | bytes) -> ET.ElementTree:
    """Parse XTR XML from either a file path or in-memory ZIP member bytes."""
    if isinstance(source, bytes):
        return ET.parse(io.BytesIO(source))
    return ET.parse(source)


def parse_xtr_metadata(source: Path | bytes) -> dict[str, Any]:
    """Extract metadata from an XTR (XML) file."""
    tree = _parse_xml(source)
    root = tree.getroot()

    metadata: dict[str, Any] = {
        "measurement_type": "",
        "record_time": "",
        "device_id": "",
        "iteration_index": 1,
        "flag": "",
        "remarks": "",
        "link_key": "",
        "smu_config": {},
        "sweep_params": {},
        "user_functions": [],
        "warnings": [],
    }

    # ── Title ───────────────────────────────────────────────────────────
    for elem in root.iter():
        tag = _tag(elem)
        if tag == "Title":
            metadata["measurement_type"] = elem.text or ""

        if tag == "PrimitiveTest":
            metadata["test_name"] = elem.get("Name", "")

        # ── Parameters ────────────────────────────────────────────────
        if tag == "Parameter":
            name = elem.get("Name", "")
            idx = elem.get("Index", "0")

            # Extract value — try different types
            value = None
            for child in elem:
                ct = _tag(child)
                if ct in ("String", "Double", "Number", "Boolean"):
                    value = child.text

            if value is None:
                continue

            # Device/metadata
            if name == "TestRecord.RecordTime":
                metadata["record_time"] = value
            elif name == "TestRecord.TestTarget":
                metadata["device_id"] = value
            elif name == "TestRecord.IterationIndex":
                try:
                    metadata["iteration_index"] = int(float(value))
                except ValueError:
                    pass
            elif name == "TestRecord.Flag":
                metadata["flag"] = value
            elif name == "TestRecord.Remarks":
                metadata["remarks"] = value
            elif name == "TestRecord.LinkKey":
                metadata["link_key"] = value

            # SMU configuration
            elif name.startswith("Channel."):
                key = name.split("Channel.", 1)[1]
                if "Unit" in key:
                    smu_key = f"SMU{idx}"
                    if smu_key not in metadata["smu_config"]:
                        metadata["smu_config"][smu_key] = {}
                    if "IName" in key:
                        metadata["smu_config"][smu_key]["i_name"] = value
                    elif "VName" in key:
                        metadata["smu_config"][smu_key]["v_name"] = value
                    elif "Unit" in key:
                        metadata["smu_config"][smu_key]["unit"] = value
                    elif "Func" in key:
                        metadata["smu_config"][smu_key]["func"] = value

            # Sweep parameters
            elif name == "Measurement.Primary.Start":
                metadata["sweep_params"]["primary_start"] = float(value)
            elif name == "Measurement.Primary.Stop":
                metadata["sweep_params"]["primary_stop"] = float(value)
            elif name == "Measurement.Primary.Step":
                metadata["sweep_params"]["primary_step"] = float(value)
            elif name == "Measurement.Primary.Compliance":
                metadata["sweep_params"]["primary_compliance"] = float(value)
            elif name == "Measurement.Secondary.Start":
                metadata["sweep_params"]["secondary_start"] = float(value)
            elif name == "Measurement.Secondary.Count":
                metadata["sweep_params"]["secondary_count"] = float(value)
            elif name == "Measurement.Bias.Source" and idx == "0":
                metadata["sweep_params"]["bias1_source"] = float(value)
            elif name == "Measurement.Bias.Source" and idx == "1":
                metadata["sweep_params"]["bias2_source"] = float(value)

            # User functions
            elif name.startswith("Function.User."):
                if name == "Function.User.Name":
                    metadata["user_functions"].append({"name": value, "definition": ""})
                elif name == "Function.User.Definition" and metadata["user_functions"]:
                    metadata["user_functions"][-1]["definition"] = value

    LOGGER.info(
        "XTR metadata: %s, %s, sweep: %s→%s",
        metadata["measurement_type"], metadata["device_id"],
        metadata["sweep_params"].get("primary_start"),
        metadata["sweep_params"].get("primary_stop"),
    )
    return metadata


def parse_xtr_data(filepath: Path | bytes) -> dict[str, Any]:
    """Parse XTR measurement data into structured format.

    Returns the same structure as parse_csv_data for interchangeability.
    """
    tree = _parse_xml(filepath)
    root = tree.getroot()

    metadata = parse_xtr_metadata(filepath)

    # ── Extract DataVectors ─────────────────────────────────────────────
    data: dict[str, list[float]] = {}
    columns: list[str] = []

    for elem in root.iter():
        tag = _tag(elem)
        if tag == "DataVector":
            name = elem.get("Name", "")
            unit = elem.get("PhysicalUnit", "")
            columns.append(name)

            values = []
            for data_elem in elem.iter():
                if _tag(data_elem) == "Value":
                    try:
                        values.append(float(data_elem.text))
                    except (ValueError, TypeError):
                        values.append(float("nan"))
            data[name] = values
            LOGGER.debug("  DataVector '%s' (%s): %d values", name, unit, len(values))

    LOGGER.info(
        "XTR data: %d columns, %d rows",
        len(columns), len(data[columns[0]]) if columns else 0,
    )

    return {
        "metadata": metadata,
        "columns": columns,
        "original_columns": columns,
        "data": data,
        "num_rows": len(data[columns[0]]) if columns else 0,
        "warnings": metadata.get("warnings", []),
    }
