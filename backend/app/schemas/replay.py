"""Schémas Pydantic — B19 Étape A (squelette minimal du Replay Engine)."""

from __future__ import annotations

from pydantic import BaseModel
from shared.options import OptionInstrument


class ReplayDatasetOut(BaseModel):
    dataset_id: str
    trading_day: str
    timezone: str
    symbols: list[str]
    total_bars: int
    checksum: str


class ReplayBarOut(BaseModel):
    open: float
    high: float
    low: float
    close: float
    volume: float


class ReplaySessionOut(BaseModel):
    dataset_id: str
    trading_day: str
    symbols: list[str]
    total_bars: int
    current_index: int
    current_timestamp: str | None
    current_bars: dict[str, ReplayBarOut]
    is_finished: bool


class ReplayOptionsPreviewOut(BaseModel):
    """Read-only, explicitly synthetic illustration for the Replay screen."""

    source: str
    strategy_type_code: str
    strategy_parameters: dict[str, int]
    current_index: int
    underlying_symbol: str | None
    signal: str
    signal_reasoning_code: str
    option_action: str
    option_instrument: OptionInstrument | None
    risk_status: str
    execution_status: str
    is_order_evidence: bool
