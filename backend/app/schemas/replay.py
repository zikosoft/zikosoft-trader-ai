"""Schémas Pydantic — B19 Étape A (squelette minimal du Replay Engine)."""

from __future__ import annotations

from pydantic import BaseModel


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
