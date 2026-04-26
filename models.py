from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


Decision = Literal["BUY", "SELL", "NO_TRADE"]


class StrategyInputs(BaseModel):
    symbol: str
    fetched_at_ms: int
    price_now: float
    bid_price: float | None = None
    ask_price: float | None = None
    mid_price: float | None = None
    median_notional_24h: float | None = None
    Q_threshold: float
    LABR_1h: float | None = None
    LABR_prev_1h: float | None = None
    Delta_LABR: float | None = None
    large_trade_count_1h: int
    VWAP_1h: float | None = None
    ATR_1h: float | None = None
    raw_trade_count: int
    kline_count: int
    warnings: list[str] = Field(default_factory=list)


class DecisionResult(BaseModel):
    symbol: str
    decision: Decision
    fetched_at_ms: int
    computed_at_ms: int
    price_now: float | None = None
    bid_price: float | None = None
    ask_price: float | None = None
    mid_price: float | None = None
    LABR_1h: float | None = None
    LABR_prev_1h: float | None = None
    Delta_LABR: float | None = None
    large_trade_count_1h: int | None = None
    VWAP_1h: float | None = None
    ATR_1h: float | None = None
    Q_threshold: float | None = None
    stop_pct: float | None = None
    entry: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    notional: float | None = None
    qty_btc: float | None = None
    risk_cash: float | None = None
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
