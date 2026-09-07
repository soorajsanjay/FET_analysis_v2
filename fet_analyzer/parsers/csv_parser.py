"""
CSV parser for Keysight EasyEXPERT / B1500A measurement files.

Handles:
- UTF-8 BOM
- Multi-line metadata header (key-value pairs before column headers)
- Column name normalization
- Numeric conversion
- Forward/reverse sweep detection
"""

from __future__ import annotations

import csv
import io
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fet_analyzer.path_utils import safe_path
from fet_analyzer.utils.logging import LOGGER

# Column name synonyms → canonical name
COLUMN_ALIASES: dict[str, str] = {
    # Drain current
    "id": "Id", "ids": "Id", "i_d": "Id", "draini": "Id", "drain current": "Id",
    "i(d)": "Id", "drain": "Id", "i_drain": "Id",
    # Gate current
    "ig": "Ig", "i_g": "Ig", "gatei": "Ig", "gate current": "Ig",
    "i(g)": "Ig", "i_gate": "Ig",
    # Back-gate current
    "ibg": "Ibg", "i_bg": "Ibg", "backgatei": "Ibg", "backgate current": "Ibg",
    "ibgate": "Ibg",
    # Gate voltage
    "vg": "Vg", "v_g": "Vg", "gatev": "Vg", "gate voltage": "Vg",
    "v(g)": "Vg", "v_gate": "Vg",
    # Back-gate voltage
    "vbg": "Vbg", "v_bg": "Vbg", "backgatev": "Vbg", "backgate voltage": "Vbg",
    "vbgate": "Vbg",
    # Drain voltage
    "vd": "Vd", "v_d": "Vd", "drainv": "Vd", "drain voltage": "Vd",
    "v(d)": "Vd", "v_drain": "Vd",
    # Source current
    "is": "Is", "sourcei": "Is", "source current": "Is",
    # Source voltage
    "vs": "Vs", "v_s": "Vs", "sourcev": "Vs", "source voltage": "Vs",
    # Bulk/substrate current
    "ib": "Ib", "bulki": "Ib", "substrate current": "Ib",
    # Computed columns (EasyEXPERT user functions)
    "absig": "absIg", "abs ig": "absIg", "abs(ig)": "absIg",
    "absid": "absId", "abs id": "absId", "abs(id)": "absId",
    # Voltage
    "vs": "Vs", "v_s": "Vs", "sourcev": "Vs",
    # Time
    "time": "Time", "t": "Time",
}


def normalise_column(name: str) -> str:
    """Map a column name to its canonical form."""
    return COLUMN_ALIASES.get(name.strip().lower(), name.strip())


@contextmanager
def _open_table(filepath: Path, encoding: str):
    """Read one measurement sheet; never interpret binary Excel as CSV text."""
    if filepath.suffix.lower() == ".xls":
        raise ValueError("Legacy .xls input is unsupported; export the measurement as CSV or single-sheet .xlsx.")
    if filepath.suffix.lower() != ".xlsx":
        with open(safe_path(filepath), encoding=encoding, errors="replace") as handle:
            yield handle
        return
    import openpyxl
    workbook = openpyxl.load_workbook(safe_path(filepath), read_only=True, data_only=False)
    try:
        if len(workbook.worksheets) != 1:
            raise ValueError("Measurement .xlsx must have exactly one worksheet; export each measurement separately.")
        stream = io.StringIO()
        writer = csv.writer(stream, lineterminator="\n")
        for row in workbook.worksheets[0].iter_rows():
            if any(cell.data_type == "f" for cell in row):
                raise ValueError("Measurement .xlsx contains formulas; export measured numeric values as CSV.")
            values = [cell.value if cell.value is not None else "" for cell in row]
            while values and values[-1] == "":
                values.pop()
            writer.writerow(values)
        stream.seek(0)
        yield stream
    finally:
        workbook.close()


def parse_csv_metadata(filepath: Path, encoding: str = "utf-8-sig") -> dict[str, Any]:
    """Extract metadata from the header lines of an EasyEXPERT CSV.

    Reads key-value lines until a line that looks like column headers
    (containing 'Vg', 'Vd', 'Id', etc. as whole tokens).

    Returns:
        dict with keys: measurement_type, record_time, device_id, count,
                        flag, remarks, raw_headers (all header lines)
    """
    metadata: dict[str, Any] = {"raw_headers": []}

    with _open_table(filepath, encoding) as f:
        raw_header_lines = []
        for line in f:
            line = line.strip()
            if not line:
                break
            raw_header_lines.append(line)
            parts = line.split(",", 1)

            # Check if this looks like a data column header line
            if len(parts) >= 2:
                first = parts[0].strip().lower()
                # Data column indicators: Vg, Vd, Id, Ig, etc.
                if first in {"vg", "vd", "id", "ig", "is", "ib", "vbg", "ibg", "vs", "time"}:
                    # This is the column header line — not metadata
                    raw_header_lines.pop()  # Remove from metadata
                    break

            # Parse key-value (strip trailing commas from both)
            key = parts[0].strip().rstrip(",")
            value = ",".join(parts[1:]).strip().rstrip(",")
            key_lower = key.lower().replace(" ", "_")
            metadata[key_lower] = value

        metadata["raw_headers"] = raw_header_lines

    # Map to standard names
    result = {
        "measurement_type": metadata.get("i/v_sweep", metadata.get("measurement_type", "")),
        "setup_title": metadata.get("setup_title", ""),
        "classic_test_name": metadata.get("classic_test_name", ""),
        "test_date": metadata.get("test_date", ""),
        "test_time": metadata.get("test_time", ""),
        "record_time": metadata.get("recordtime", metadata.get("record_time", "")),
        "device_id": metadata.get("device_id", metadata.get("deviceid", "")),
        "count": metadata.get("count", "1"),
        "flag": metadata.get("flag", ""),
        "remarks": metadata.get("remarks", ""),
        "raw_headers": metadata["raw_headers"],
    }
    return result


def parse_csv_data(
    filepath: Path,
    encoding: str = "utf-8-sig",
) -> dict[str, Any]:
    """Parse CSV measurement data into structured format.

    Returns:
        dict with:
            metadata: extracted header metadata
            columns: list of canonical column names
            original_columns: list of original column names
            data: dict mapping canonical name → numpy array (as list of floats)
            num_rows: total data rows
            warnings: list of parsing warnings
    """
    warnings: list[str] = []
    metadata = parse_csv_metadata(filepath, encoding)

    # Read data section
    data_rows: list[dict[str, str]] = []
    original_columns: list[str] = []
    canonical_columns: list[str] = []

    with _open_table(filepath, encoding) as f:
        # Skip metadata lines
        metadata_line_count = len(metadata["raw_headers"])
        for _ in range(metadata_line_count):
            f.readline()

        # Read column header line
        header_line = f.readline().strip()
        original_columns = [col.strip() for col in header_line.split(",")]
        canonical_columns = [normalise_column(col) for col in original_columns]

        LOGGER.debug("CSV columns: %s → %s", original_columns, canonical_columns)

        # Read data
        reader = csv.reader(f)
        for row in reader:
            if not row or all(cell.strip() == "" for cell in row):
                continue
            if len(row) != len(canonical_columns):
                warnings.append(f"Row has {len(row)} fields, expected {len(canonical_columns)}")
                if len(row) < len(canonical_columns):
                    row.extend([""] * (len(canonical_columns) - len(row)))
                else:
                    row = row[: len(canonical_columns)]
            data_rows.append(dict(zip(canonical_columns, row)))

    # Convert to numeric columns
    data: dict[str, list[float]] = {col: [] for col in canonical_columns}
    skipped = 0
    for i, row in enumerate(data_rows):
        # Parse to temp dict first — only append if all columns succeed
        temp: dict[str, float] = {}
        ok = True
        for col in canonical_columns:
            val = row.get(col, "")
            if val.strip() == "":
                temp[col] = float("nan")
            else:
                try:
                    temp[col] = float(val)
                except (ValueError, TypeError):
                    ok = False
                    break
        if ok:
            for col in canonical_columns:
                data[col].append(temp[col])
        else:
            skipped += 1

    if skipped:
        warnings.append(f"Skipped {skipped} rows that failed numeric conversion")

    LOGGER.info(
        "Parsed %s: %d rows, %d columns (%s)",
        filepath.name, len(data_rows) - skipped,
        len(canonical_columns), ", ".join(canonical_columns),
    )

    return {
        "metadata": metadata,
        "columns": canonical_columns,
        "original_columns": original_columns,
        "data": data,
        "num_rows": len(data_rows) - skipped,
        "warnings": warnings,
    }
