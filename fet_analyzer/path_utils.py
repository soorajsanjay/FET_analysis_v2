"""Filesystem-boundary helpers for Windows extended-length paths."""
from __future__ import annotations

import os
import shutil
import sys
from uuid import uuid4
from pathlib import Path
from typing import Any


WINDOWS_LONG_PATH_THRESHOLD = 240
OUTPUT_PATH_WARNING_THRESHOLD = 200
SHORT_ID_LENGTH = 8
_EXTENDED_PREFIX = "\\\\?\\"
_EXTENDED_UNC_PREFIX = "\\\\?\\UNC\\"


def _absolute_path_text(path: str | os.PathLike[str]) -> str:
    """Return a lexical absolute path without requiring the target to exist."""
    value = os.fspath(path)
    if value.startswith(_EXTENDED_PREFIX):
        return value
    return os.path.abspath(value)


def safe_path(
    path: str | os.PathLike[str], *, threshold: int = WINDOWS_LONG_PATH_THRESHOLD,
) -> Path:
    """Return a filesystem path protected from Windows ``MAX_PATH`` limits.

    Logical paths remain ordinary ``Path`` instances everywhere else in the
    application.  The extended namespace is introduced only at the filesystem
    boundary, and only when the absolute Windows path crosses the safety
    threshold.
    """
    logical = Path(path)
    if sys.platform != "win32":
        return logical

    absolute = _absolute_path_text(path)
    if absolute.startswith(_EXTENDED_PREFIX) or len(absolute) <= threshold:
        return Path(absolute) if absolute.startswith(_EXTENDED_PREFIX) else logical
    if absolute.startswith("\\\\"):
        return Path(_EXTENDED_UNC_PREFIX + absolute[2:])
    return Path(_EXTENDED_PREFIX + absolute)


def safe_mkdir(
    path: str | os.PathLike[str], *, parents: bool = True, exist_ok: bool = True,
) -> Path:
    """Create a directory through the safe filesystem representation."""
    logical = Path(path)
    safe_path(logical).mkdir(parents=parents, exist_ok=exist_ok)
    return logical


def prepare_write_path(path: str | os.PathLike[str]) -> Path:
    """Create the destination parent defensively and return a safe write path."""
    logical = Path(path)
    safe_mkdir(logical.parent, parents=True, exist_ok=True)
    return safe_path(logical)


def safe_copyfile(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> Path:
    logical = Path(destination)
    shutil.copyfile(safe_path(source), prepare_write_path(logical))
    return logical


def safe_copy2(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> Path:
    logical = Path(destination)
    shutil.copy2(safe_path(source), prepare_write_path(logical))
    return logical


def safe_replace(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> Path:
    logical = Path(destination)
    os.replace(safe_path(source), prepare_write_path(logical))
    return logical


def safe_rename(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> Path:
    logical = Path(destination)
    safe_path(source).rename(prepare_write_path(logical))
    return logical


def safe_unlink(path: str | os.PathLike[str], *, missing_ok: bool = False) -> None:
    safe_path(path).unlink(missing_ok=missing_ok)


def safe_rmtree(path: str | os.PathLike[str], **kwargs: Any) -> None:
    shutil.rmtree(safe_path(path), **kwargs)


def unique_directory(
    parent: str | os.PathLike[str], prefix: str, *, attempts: int = 16,
) -> tuple[Path, str]:
    """Create a short collision-safe directory and return its full UUID."""
    logical_parent = safe_mkdir(parent, parents=True, exist_ok=True)
    for _ in range(attempts):
        identifier = uuid4().hex
        path = logical_parent / f"{prefix}{identifier[:SHORT_ID_LENGTH]}"
        try:
            safe_mkdir(path, parents=False, exist_ok=False)
        except FileExistsError:
            continue
        return path, identifier
    raise FileExistsError(
        f"Could not allocate a unique temporary directory below {logical_parent}"
    )


def output_path_warning(
    path: str | os.PathLike[str], *, threshold: int = OUTPUT_PATH_WARNING_THRESHOLD,
) -> str | None:
    """Return a non-blocking warning for an unusually long output base path."""
    absolute = _absolute_path_text(path)
    if absolute.startswith(_EXTENDED_UNC_PREFIX):
        absolute = "\\\\" + absolute[len(_EXTENDED_UNC_PREFIX):]
    elif absolute.startswith(_EXTENDED_PREFIX):
        absolute = absolute[len(_EXTENDED_PREFIX):]
    if len(absolute) <= threshold:
        return None
    return (
        f"Output directory path is already {len(absolute)} characters long. "
        "Windows and OneDrive may add deeper generated paths; consider choosing "
        "a shorter output location near the drive root. "
        f"Output: {absolute}"
    )
