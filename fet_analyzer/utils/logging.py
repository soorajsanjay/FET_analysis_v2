"""Logging setup for FET Analyzer."""

import logging
import sys
import uuid
from contextvars import ContextVar
from pathlib import Path

from fet_analyzer.path_utils import prepare_write_path

LOGGER = logging.getLogger("fet_analyzer")
_LOG_CONTEXT: ContextVar[dict[str, str]] = ContextVar("fet_analyzer_log_context", default={})


class AnalysisContextFilter(logging.Filter):
    def __init__(self, run_id: str):
        super().__init__()
        self.run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:
        context = _LOG_CONTEXT.get()
        record.run_id = self.run_id
        record.stage = context.get("stage", "orchestrator")
        record.source = context.get("source", "-")
        return True


def set_log_context(*, stage: str | None = None, source: str | None = None) -> None:
    current = dict(_LOG_CONTEXT.get())
    if stage is not None:
        current["stage"] = stage
    if source is not None:
        current["source"] = source
    _LOG_CONTEXT.set(current)


def clear_log_context() -> None:
    _LOG_CONTEXT.set({})


class ConsoleSafeFormatter(logging.Formatter):
    """Keep console output readable on legacy Windows code pages."""

    _replacements = str.maketrans({
        "→": "->", "←": "<-", "—": "-", "–": "-", "✓": "OK",
        "✗": "X", "μ": "u", "²": "^2", "Ω": "ohm", "ε": "epsilon",
    })

    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record).translate(self._replacements)
        return rendered.encode("ascii", "replace").decode("ascii")


def setup_logging(level: str = "INFO", log_file: str | Path | None = None):
    """Configure logging to console and optionally a file."""
    LOGGER.setLevel(getattr(logging, level.upper(), logging.INFO))
    LOGGER.handlers.clear()

    run_id = uuid.uuid4().hex[:12]
    context_filter = AnalysisContextFilter(run_id)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] [run=%(run_id)s stage=%(stage)s source=%(source)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(ConsoleSafeFormatter(
        "%(asctime)s [%(levelname)-7s] [run=%(run_id)s stage=%(stage)s source=%(source)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    ch.addFilter(context_filter)
    LOGGER.addHandler(ch)

    # File handler
    if log_file:
        log_file = Path(log_file)
        fh = logging.FileHandler(
            prepare_write_path(log_file), mode="w", encoding="utf-8"
        )
        fh.setFormatter(fmt)
        fh.addFilter(context_filter)
        LOGGER.addHandler(fh)
        LOGGER.info("Log file: %s", log_file.resolve())
    return run_id
