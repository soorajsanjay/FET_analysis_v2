"""
File discovery and duplicate resolution for FET Analyzer.

Scans input folders for measurement files, resolves duplicates
across formats (CSV > XLSX > XTR > ZTR), and returns a clean
list of files to process.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from fet_analyzer.utils.logging import LOGGER

# Supported extensions and their canonical format labels
EXTENSION_FORMAT: dict[str, str] = {
    ".csv": "csv",
    ".xlsx": "xlsx",
    ".xls": "xls",
    ".xtr": "xtr",
    ".xml": "xtr",     # XTR files may have .xml extension
    ".ztr": "ztr",
    ".zip": "ztr",     # ZTR files are ZIP archives
}
TOOL_DIRECTORY_NAMES = {"__pycache__", "build", "dist", "node_modules"}


def _normalised_stem(path: Path) -> str:
    """Strip Telegram/media UUID suffixes for comparison.

    'file---uuid.csv' → 'file'
    """
    stem = path.stem
    # Telegram appends ---UUID
    if "---" in stem:
        stem = stem.split("---")[0]
    return stem


def _extension_priority(ext: str, priority: list[str]) -> int:
    """Return priority index; lower = preferred."""
    fmt = EXTENSION_FORMAT.get(ext.lower(), "unknown")
    try:
        return priority.index(fmt)
    except ValueError:
        return len(priority)  # unknown → lowest priority


def discover_files(
    input_folder: Path,
    recursive: bool,
    skip_patterns: list[str],
    file_priority: list[str],
    excluded_roots: list[Path] | None = None,
) -> tuple[list[Path], list[dict]]:
    """Scan input_folder for supported measurement files.

    Returns:
        (file_list, duplicate_info) where file_list contains the resolved
        files to process and duplicate_info logs what was resolved.
    """
    supported = set(EXTENSION_FORMAT.keys())
    skip_re = [re.compile(p) for p in skip_patterns] if skip_patterns else []
    excluded = [root.resolve() for root in (excluded_roots or []) if root.exists()]

    # Collect all files by normalised stem
    candidates: dict[str, list[Path]] = defaultdict(list)

    pattern = "**/*" if recursive else "*"
    for filepath in input_folder.glob(pattern):
        if not filepath.is_file():
            continue
        try:
            relative_parts = filepath.relative_to(input_folder).parts[:-1]
        except ValueError:
            relative_parts = ()
        # Hidden project/tool directories are never measurement sources and
        # commonly contain CSV/XLSX fixtures that would otherwise be ingested.
        if any(part.startswith(".") for part in relative_parts):
            continue
        if any(part.casefold() in TOOL_DIRECTORY_NAMES for part in relative_parts):
            continue
        if any(filepath.resolve().is_relative_to(root) for root in excluded):
            continue
        # Output folders may sit beneath the input directory.  Detect the
        # per-device metadata marker rather than accidentally analysing our
        # own CSV/XLSX products on a later recursive run.
        if any((parent / "parsed_metadata.json").exists() for parent in filepath.parents):
            continue
        # Never re-ingest products from any previous pipeline run.
        if any((parent / "run_manifest.json").exists() for parent in filepath.parents):
            continue
        if "batch_summary" in filepath.parts:
            continue
        if any(r.search(filepath.name) for r in skip_re):
            continue
        if filepath.suffix.lower() not in supported:
            continue
        stem = _normalised_stem(filepath)
        candidates[stem].append(filepath)

    # Resolve duplicates: pick highest priority format
    resolved: list[Path] = []
    duplicate_info: list[dict] = []

    for stem, paths in sorted(candidates.items()):
        if len(paths) == 1:
            resolved.append(paths[0])
        else:
            # Sort by format priority
            paths.sort(key=lambda p: _extension_priority(p.suffix, file_priority))
            chosen = paths[0]
            rejected = paths[1:]
            resolved.append(chosen)
            info = {
                "stem": stem,
                "chosen": str(chosen),
                "rejected": [str(r) for r in rejected],
            }
            duplicate_info.append(info)
            LOGGER.info(
                "Duplicate group '%s': chose %s, skipped %d other(s)",
                stem, chosen.name, len(rejected),
            )

    LOGGER.info("Discovered %d measurement files (%d duplicate groups resolved)",
                len(resolved), len(duplicate_info))
    return resolved, duplicate_info
