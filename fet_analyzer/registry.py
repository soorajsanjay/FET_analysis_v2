"""Controlled parser and analysis registries with compatibility metadata."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class Registration:
    name: str
    handler: Callable[..., Any]
    api_version: str


class ControlledRegistry:
    def __init__(self, kind: str, api_version: str = "1"):
        self.kind = kind
        self.api_version = api_version
        self._items: dict[str, Registration] = {}

    def register(self, key: str, handler: Callable[..., Any], *, name: str | None = None, api_version: str = "1", replace: bool = False) -> None:
        normalized = key.lower()
        if api_version != self.api_version:
            raise ValueError(f"{self.kind} {key!r} uses incompatible API version {api_version}")
        if normalized in self._items and not replace:
            raise ValueError(f"{self.kind} {key!r} is already registered")
        self._items[normalized] = Registration(name or normalized, handler, api_version)

    def get(self, key: str) -> Callable[..., Any]:
        try:
            return self._items[key.lower()].handler
        except KeyError as exc:
            raise ValueError(f"No {self.kind} registered for {key!r}") from exc

    def describe(self) -> list[dict[str, str]]:
        return [{"key": key, "name": item.name, "api_version": item.api_version} for key, item in sorted(self._items.items())]


PARSERS = ControlledRegistry("parser")
ANALYZERS = ControlledRegistry("analyzer")


def register_parser(extensions: list[str], parser: Callable[..., Any], *, name: str, api_version: str = "1") -> None:
    for extension in extensions:
        PARSERS.register(extension.lower().lstrip("."), parser, name=name, api_version=api_version)


def register_analysis(measurement_type: str, analyzer: Callable[..., Any], *, name: str | None = None, api_version: str = "1") -> None:
    ANALYZERS.register(measurement_type, analyzer, name=name, api_version=api_version)


def _csv(path: Path, **_: Any) -> dict[str, Any]:
    from fet_analyzer.parsers.csv_parser import parse_csv_data
    return parse_csv_data(path)


def _xtr(path: Path, **_: Any) -> dict[str, Any]:
    from fet_analyzer.parsers.xtr_parser import parse_xtr_data
    return parse_xtr_data(path)


def _ztr(path: Path, **context: Any) -> dict[str, Any]:
    from fet_analyzer.parsers.xtr_parser import parse_xtr_data
    from fet_analyzer.parsers.ztr_parser import parse_ztr_data
    cached = context.get("cached_path")
    return parse_xtr_data(cached) if cached else parse_ztr_data(path)


register_parser(["csv", "xlsx", "xls"], _csv, name="tabular")
register_parser(["xtr", "xml"], _xtr, name="keysight-xtr")
register_parser(["ztr", "zip"], _ztr, name="keysight-ztr")


def parse_measurement(path: Path, **context: Any) -> dict[str, Any]:
    return PARSERS.get(path.suffix.lower().lstrip("."))(path, **context)
