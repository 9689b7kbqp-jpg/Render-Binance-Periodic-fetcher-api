from __future__ import annotations

import statistics
from math import floor
from typing import Any

from app.binance_client import BinanceClient, now_ms
from app.models import DecisionResult, StrategyInputs

MIN_Q_USDC = 25_000.0
LABR_LONG = 0.60
LABR_SHORT = 0.40
DELTA_LONG = 0.10
DELTA_SHORT = -0.10
MIN_LARGE_TRADES = 8
VWAP_LONG_MAX_MULT = 1.0025
VWAP_SHORT_MIN_MULT = 0.9975
STOP_MIN = 0.0035
STOP_ATR_MULT = 0.6
TAKE_PROFIT_PCT = 0.01
RISK_PCT = 0.0025
LEVERAGE_EFF_MAX = 3.0
MIN_NOTIONAL_FALLBACK = 5.0
LOT_STEP_FALLBACK = 0.00001


def _float(x: Any) -> float:
    return float(x)


def trade_notional(trade: dict[str, Any]) -> float:
    return _float(trade["p"]) * _float(trade["q"])


def is_buyer_aggressive(trade: dict[str, Any]) -> bool:
    # Binance aggTrade field m=true means buyer is maker => seller aggressive.
    return bool(trade.get("m")) is False


def vwap(trades: list[dict[str, Any]]) -> float | None:
    qty = sum(_float(t["q"]) for t in trades)
    if qty <= 0:
        return None
    return sum(_float(t["p"]) * _float(t["q"]) for t in trades) / qty


def labr(large_trades: list[dict[str, Any]]) -> float | None:
    total = sum(trade_notional(t) for t in large_trades)
    if total <= 0:
        return None
    buy = sum(trade_notional(t) for t in large_trades if is_buyer_aggressive(t))
    return buy / total


def atr_1h(klines: list[list[Any]], period: int = 14) -> float | None:
    if len(klines) < period + 1:
        return None
    rows = klines[-(period + 1):]
    trs: list[float] = []
    for i in range(1, len(rows)):
        high = _float(rows[i][2])
        low = _float(rows[i][3])
        prev_close = _float(rows[i - 1][4])
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    if not trs:
        return None
    return sum(trs) / len(trs)


def get_filters(exchange_info: dict[str, Any]) -> tuple[float, float]:
    try:
        symbol_info = exchange_info["symbols"][0]
        min_notional = MIN_NOTIONAL_FALLBACK
        step_size = LOT_STEP_FALLBACK
        for f in symbol_info.get("filters", []):
            if f.get("filterType") == "NOTIONAL":
                min_notional = float(f.get("minNotional", min_notional))
            if f.get("filterType") == "LOT_SIZE":
                step_size = float(f.get("stepSize", step_size))
        return min_notional, step_size
    except Exception:
        return MIN_NOTIONAL_FALLBACK, LOT_STEP_FALLBACK


def floor_to_step(qty: float, step: float) -> float:
    if step <= 0:
        return qty
    return floor(qty / step) * step


async def compute_strategy_inputs(
    client: BinanceClient,
    symbol: str = "BTCUSDC",
    signal_hours: int = 2,
    kline_limit: int = 100,
) -> StrategyInputs:
    fetched_at = now_ms()
    lookback_ms = max(signal_hours, 2) * 60 * 60 * 1000
    start = fetched_at - lookback_ms

    import asyncio
    ticker_task = client.ticker_price(symbol)
    book_task = client.book_ticker(symbol)
    klines_task = client.klines_1h(symbol, kline_limit)
    trades_task = client.agg_trades_window(symbol, start_ms=start, end_ms=fetched_at, max_pages=30)

    ticker, book, klines, trades = await asyncio.gather(ticker_task, book_task, klines_task, trades_task)

    price_now = float(ticker["price"])
    bid = float(book["bidPrice"])
    ask = float(book["askPrice"])
    mid = (bid + ask) / 2 if bid and ask else price_now

    current_start = fetched_at - 60 * 60 * 1000
    previous_start = fetched_at - 2 * 60 * 60 * 1000
    current_trades = [t for t in trades if int(t["T"]) >= current_start]
    previous_trades = [t for t in trades if previous_start <= int(t["T"]) < current_start]

    notionals = [trade_notional(t) for t in trades]
    median_notional = statistics.median(notionals) if notionals else None
    q_threshold = max(MIN_Q_USDC, 3 * median_notional) if median_notional is not None else MIN_Q_USDC

    current_large = [t for t in current_trades if trade_notional(t) >= q_threshold]
    previous_large = [t for t in previous_trades if trade_notional(t) >= q_threshold]

    labr_now = labr(current_large)
    labr_prev = labr(previous_large)
    delta = labr_now - labr_prev if labr_now is not None and labr_prev is not None else None
    vwap_now = vwap(current_trades)
    atr = atr_1h(klines)

    warnings: list[str] = []
    if len(trades) >= 30_000:
        warnings.append("aggTrades pagination may be truncated; increase max_pages if needed")
    if median_notional is None:
        warnings.append("median_notional fallback: no aggTrades in window")
    if labr_now is None:
        warnings.append("LABR_1h unavailable: no large trades in current hour")
    if labr_prev is None:
        warnings.append("LABR_prev_1h unavailable: no large trades in previous hour")
    if atr is None:
        warnings.append("ATR_1h unavailable: not enough klines")

    return StrategyInputs(
        symbol=symbol,
        fetched_at_ms=fetched_at,
        price_now=price_now,
        bid_price=bid,
        ask_price=ask,
        mid_price=mid,
        median_notional_24h=median_notional,
        Q_threshold=q_threshold,
        LABR_1h=labr_now,
        LABR_prev_1h=labr_prev,
        Delta_LABR=delta,
        large_trade_count_1h=len(current_large),
        VWAP_1h=vwap_now,
        ATR_1h=atr,
        raw_trade_count=len(trades),
        kline_count=len(klines),
        warnings=warnings,
    )


async def compute_decision(
    client: BinanceClient,
    symbol: str = "BTCUSDC",
    capital: float = 1420.0,
    signal_hours: int = 2,
    kline_limit: int = 100,
) -> DecisionResult:
    inputs = await compute_strategy_inputs(client, symbol, signal_hours, kline_limit)
    computed_at = now_ms()
    reasons: list[str] = []
    warnings = list(inputs.warnings)

    decision = "NO_TRADE"
    if inputs.LABR_1h is None:
        reasons.append("LABR_1h unavailable")
    if inputs.LABR_prev_1h is None:
        reasons.append("LABR_prev_1h unavailable")
    if inputs.Delta_LABR is None:
        reasons.append("Delta_LABR unavailable")
    if inputs.VWAP_1h is None:
        reasons.append("VWAP_1h unavailable")
    if inputs.ATR_1h is None:
        reasons.append("ATR_1h unavailable")
    if inputs.large_trade_count_1h < MIN_LARGE_TRADES:
        reasons.append(f"large_trade_count_1h < {MIN_LARGE_TRADES}")

    long_valid = (
        inputs.LABR_1h is not None
        and inputs.Delta_LABR is not None
        and inputs.VWAP_1h is not None
        and inputs.large_trade_count_1h >= MIN_LARGE_TRADES
        and inputs.LABR_1h >= LABR_LONG
        and inputs.Delta_LABR >= DELTA_LONG
        and inputs.price_now <= inputs.VWAP_1h * VWAP_LONG_MAX_MULT
    )

    short_valid = (
        inputs.LABR_1h is not None
        and inputs.Delta_LABR is not None
        and inputs.VWAP_1h is not None
        and inputs.large_trade_count_1h >= MIN_LARGE_TRADES
        and inputs.LABR_1h <= LABR_SHORT
        and inputs.Delta_LABR <= DELTA_SHORT
        and inputs.price_now >= inputs.VWAP_1h * VWAP_SHORT_MIN_MULT
    )

    if long_valid and short_valid:
        reasons.append("conflicting BUY and SELL signals")
    elif long_valid:
        decision = "BUY"
    elif short_valid:
        decision = "SELL"
    else:
        if inputs.LABR_1h is not None and LABR_SHORT < inputs.LABR_1h < LABR_LONG:
            reasons.append("LABR_1h neutral")
        if inputs.Delta_LABR is not None and abs(inputs.Delta_LABR) < DELTA_LONG:
            reasons.append("abs(Delta_LABR) < 0.10")
        if inputs.VWAP_1h is not None:
            if inputs.price_now > inputs.VWAP_1h * VWAP_LONG_MAX_MULT:
                reasons.append("price too high versus VWAP for BUY")
            if inputs.price_now < inputs.VWAP_1h * VWAP_SHORT_MIN_MULT:
                reasons.append("price too low versus VWAP for SELL")

    entry = inputs.price_now if decision in ("BUY", "SELL") else None
    stop_pct = None
    stop_loss = None
    take_profit = None
    notional = None
    qty_btc = None
    risk_cash = capital * RISK_PCT

    if entry is not None and inputs.ATR_1h is not None:
        stop_pct = max(STOP_MIN, STOP_ATR_MULT * inputs.ATR_1h / entry)
        raw_notional = risk_cash / stop_pct
        notional = min(raw_notional, capital * LEVERAGE_EFF_MAX)

        # Fetch exchange filters only when actually needed.
        try:
            exchange_info = await client.exchange_info(symbol)
            min_notional, lot_step = get_filters(exchange_info)
        except Exception as exc:
            warnings.append(f"exchangeInfo unavailable, using fallback filters: {exc}")
            min_notional, lot_step = MIN_NOTIONAL_FALLBACK, LOT_STEP_FALLBACK

        qty_btc = floor_to_step(notional / entry, lot_step)
        notional = qty_btc * entry

        if notional < min_notional:
            reasons.append(f"notional < minNotional ({min_notional})")
            decision = "NO_TRADE"
            entry = None
            stop_pct = None
            stop_loss = None
            take_profit = None
            qty_btc = None
            notional = None
        elif decision == "BUY":
            stop_loss = entry * (1 - stop_pct)
            take_profit = entry * (1 + TAKE_PROFIT_PCT)
        elif decision == "SELL":
            stop_loss = entry * (1 + stop_pct)
            take_profit = entry * (1 - TAKE_PROFIT_PCT)

    return DecisionResult(
        symbol=inputs.symbol,
        decision=decision,
        fetched_at_ms=inputs.fetched_at_ms,
        computed_at_ms=computed_at,
        price_now=inputs.price_now,
        bid_price=inputs.bid_price,
        ask_price=inputs.ask_price,
        mid_price=inputs.mid_price,
        LABR_1h=inputs.LABR_1h,
        LABR_prev_1h=inputs.LABR_prev_1h,
        Delta_LABR=inputs.Delta_LABR,
        large_trade_count_1h=inputs.large_trade_count_1h,
        VWAP_1h=inputs.VWAP_1h,
        ATR_1h=inputs.ATR_1h,
        Q_threshold=inputs.Q_threshold,
        stop_pct=stop_pct,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        notional=notional,
        qty_btc=qty_btc,
        risk_cash=risk_cash,
        reasons=sorted(set(reasons)) if decision == "NO_TRADE" else reasons,
        warnings=warnings,
        meta={
            "signal_hours": signal_hours,
            "kline_limit": kline_limit,
            "capital": capital,
            "risk_pct": RISK_PCT,
            "leverage_eff_max": LEVERAGE_EFF_MAX,
            "raw_trade_count": inputs.raw_trade_count,
            "kline_count": inputs.kline_count,
        },
    )
