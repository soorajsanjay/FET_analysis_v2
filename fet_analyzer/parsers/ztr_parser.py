"""
ZTR parser — decompresses .ztr/.zip files containing XTR data.

ZTR files are ZIP archives containing a single .xtr file.
Decompress, then delegate to xtr_parser.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from fet_analyzer.path_utils import prepare_write_path, safe_mkdir
from typing import Any

from fet_analyzer.parsers.xtr_parser import parse_xtr_data
from fet_analyzer.utils.logging import LOGGER


def _cached_xtr_path(filepath: Path, cache_dir: Path) -> Path:
    """Return a cache path that preserves the real source filename stem."""
    safe_stem = "".join(
        ch if ch.isalnum() or ch in "._-" else "_" for ch in filepath.stem
    )
    return cache_dir / f"{safe_stem}.xtr"


def decompress_ztr_to_cache(filepath: Path, cache_dir: Path) -> Path:
    """Decompress a ZTR/ZIP archive to cache and return the cached XTR path.

    If the cached XTR already exists, it is reused without reopening or
    decompressing the archive. This keeps repeated analysis runs fast.
    """
    safe_mkdir(cache_dir, parents=True, exist_ok=True)
    if not zipfile.is_zipfile(filepath):
        raise ValueError(f"Not a valid ZIP/ZTR file: {filepath}")

    with zipfile.ZipFile(filepath, "r") as zf:
        names = zf.namelist()
        xtr_names = [n for n in names if n.lower().endswith(".xtr")]
        if not xtr_names:
            raise ValueError(f"No .xtr file found inside ZTR: {filepath} (contents: {names})")
        if len(xtr_names) > 1:
            LOGGER.warning("Multiple .xtr files in ZTR, using first: %s", xtr_names[0])

        xtr_name = xtr_names[0]
        cached_path = _cached_xtr_path(filepath, cache_dir)
        if cached_path.exists():
            LOGGER.debug("ZTR cache hit: %s → %s", filepath.name, cached_path.name)
            return cached_path

        LOGGER.info("ZTR: decompressing %s → %s", filepath.name, cached_path)
        prepare_write_path(cached_path).write_bytes(zf.read(xtr_name))
        return cached_path


def parse_ztr_data(filepath: Path) -> dict[str, Any]:
    """Decompress a ZTR file and parse the contained XTR data.

    Args:
        filepath: Path to .ztr or .zip file

    Returns:
        Same structure as parse_xtr_data / parse_csv_data
    """
    return parse_xtr_data(decompress_ztr_to_cache(filepath, filepath.parent / "decompressed_ztr"))
