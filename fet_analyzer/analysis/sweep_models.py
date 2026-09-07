"""Typed inputs and outputs for standalone sweep analysis."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SweepIdentity:
    source_filename: str
    sweep_index: int
    measurement_type: str
    direction: str
    sweep_variable: str
    bias_variable: str | None
    bias_value_v: float | None
    measured_vd_v: float | None = None
    measured_vs_v: float | None = None
    measured_vds_v: float | None = None
    vds_reference: str | None = None
    measured_vds_spread_v: float | None = None
    measured_vds_n: int = 0

    @property
    def sweep_id(self) -> str:
        bias = "unbiased" if self.bias_value_v is None else f"{self.bias_value_v:.9g}V"
        return f"{self.measurement_type}:{self.sweep_index}:{self.direction}:{bias}"


@dataclass
class TransferSweepResult:
    identity: SweepIdentity
    n_points: int
    vth: dict[str, Any] = field(default_factory=dict)
    mobility: dict[str, Any] = field(default_factory=dict)
    subthreshold_swing: dict[str, Any] = field(default_factory=dict)
    on_off: dict[str, Any] = field(default_factory=dict)
    gm: dict[str, Any] = field(default_factory=dict)
    current_summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["sweep_id"] = self.identity.sweep_id
        return value


@dataclass
class OutputSweepResult:
    identity: SweepIdentity
    n_points: int
    gate_bias_v: float | None
    no_gate_bias: bool
    resistance_avg_ohm: float | None
    resistance_median_ohm: float | None
    resistance_linear_fit_ohm: float | None
    linear_fit_r2: float | None
    gds_max_s: float | None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["sweep_id"] = self.identity.sweep_id
        return value
