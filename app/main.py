from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Query

from app.binance_client import BinanceClient, now_ms
from app.models import DecisionResult
from app.state import cache, cache_lock
from app.strategy import compute_decision, compute_strategy_inputs


def env_str(name: str, default: str) -> str:
    return os.getenv(name, default)


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


DEFAULT_SYMBOL = env_str("SYMBOL", "BTCUSDC")
DEFAULT_CAPITAL = env_float("CAPITAL", 1420.0)
DEFAULT_SIGNAL_HOURS = env_int("SIGNAL_HOURS", 2)
DEFAULT_KLINE_LIMIT = env_int("KLINE_LIMIT", 100)
REFRESH_SECONDS = env_int("REFRESH_SECONDS", 120)
STALE_SECONDS = env_int("STALE_SECONDS", 300)
BINANCE_BASE_URL = env_str("BINANCE_BASE_URL", "https://api.binance.com")

client = BinanceClient(BINANCE_BASE_URL)
_refresh_task: asyncio.Task[None] | None = None


async def refresh_loop() -> None:
    while True:
        try:
            result = await compute_decision(
                client=client,
                symbol=DEFAULT_SYMBOL,
                capital=DEFAULT_CAPITAL,
                signal_hours=DEFAULT_SIGNAL_HOURS,
                kline_limit=DEFAULT_KLINE_LIMIT,
            )
            async with cache_lock:
                cache.latest = result
                cache.last_error = None
        except Exception as exc:
            fallback = DecisionResult(
                symbol=DEFAULT_SYMBOL,
                decision="NO_TRADE",
                fetched_at_ms=now_ms(),
                computed_at_ms=now_ms(),
                reasons=["background refresh failed"],
                error=str(exc),
            )
            async with cache_lock:
                cache.latest = fallback
                cache.last_error = str(exc)
        await asyncio.sleep(REFRESH_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _refresh_task
    _refresh_task = asyncio.create_task(refresh_loop())
    try:
        yield
    finally:
        if _refresh_task is not None:
            _refresh_task.cancel()
            try:
                await _refresh_task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="Binance Decision API",
    version="1.0.0",
    description="BTC/USDC strategy API with background decision cache for Render.",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, Any]:
    async with cache_lock:
        latest = cache.latest
        last_error = cache.last_error
    age_seconds = None
    if latest is not None:
        age_seconds = (now_ms() - latest.computed_at_ms) / 1000
    return {
        "status": "ok",
        "symbol": DEFAULT_SYMBOL,
        "has_cached_decision": latest is not None,
        "age_seconds": age_seconds,
        "last_error": last_error,
    }


@app.get("/help")
async def help_endpoint() -> dict[str, Any]:
    return {
        "available_endpoints": [
            "GET /health",
            "GET /help",
            "GET /snapshot?symbol=BTCUSDC&hours=2&kline_limit=100",
            "GET /signal-inputs?symbol=BTCUSDC&signal_hours=2&kline_limit=100",
            "GET /decision?symbol=BTCUSDC&capital=1420&signal_hours=2&kline_limit=100",
            "GET /decision-latest",
        ],
        "notes": [
            "/snapshot returns compact raw public Binance inputs, not the full aggTrades payload",
            "/signal-inputs returns calculated strategy inputs",
            "/decision applies the active strategy and returns BUY / SELL / NO_TRADE",
            "/decision-latest returns the cached background decision immediately",
        ],
    }


@app.get("/snapshot")
async def snapshot(
    symbol: str = Query(DEFAULT_SYMBOL),
    hours: int = Query(DEFAULT_SIGNAL_HOURS, ge=2, le=24),
    kline_limit: int = Query(DEFAULT_KLINE_LIMIT, ge=20, le=500),
) -> dict[str, Any]:
    inputs = await compute_strategy_inputs(client, symbol=symbol, signal_hours=hours, kline_limit=kline_limit)
    return {
        "meta": {
            "symbol": symbol,
            "fetched_at_ms": inputs.fetched_at_ms,
            "window_hours": hours,
            "raw_trade_count": inputs.raw_trade_count,
            "kline_count": inputs.kline_count,
            "note": "compact snapshot; raw aggTrades intentionally omitted for speed",
        },
        "price_now": inputs.price_now,
        "bid_price": inputs.bid_price,
        "ask_price": inputs.ask_price,
        "mid_price": inputs.mid_price,
        "Q_threshold": inputs.Q_threshold,
        "VWAP_1h": inputs.VWAP_1h,
        "ATR_1h": inputs.ATR_1h,
    }


@app.get("/signal-inputs")
async def signal_inputs(
    symbol: str = Query(DEFAULT_SYMBOL),
    signal_hours: int = Query(DEFAULT_SIGNAL_HOURS, ge=2, le=24),
    kline_limit: int = Query(DEFAULT_KLINE_LIMIT, ge=20, le=500),
):
    return await compute_strategy_inputs(client, symbol=symbol, signal_hours=signal_hours, kline_limit=kline_limit)


@app.get("/decision")
async def decision(
    symbol: str = Query(DEFAULT_SYMBOL),
    capital: float = Query(DEFAULT_CAPITAL, gt=0),
    signal_hours: int = Query(DEFAULT_SIGNAL_HOURS, ge=2, le=24),
    kline_limit: int = Query(DEFAULT_KLINE_LIMIT, ge=20, le=500),
):
    return await compute_decision(
        client=client,
        symbol=symbol,
        capital=capital,
        signal_hours=signal_hours,
        kline_limit=kline_limit,
    )


@app.get("/decision-latest")
async def decision_latest() -> dict[str, Any]:
    async with cache_lock:
        latest = cache.latest
        last_error = cache.last_error

    if latest is None:
        return {
            "symbol": DEFAULT_SYMBOL,
            "decision": "NO_TRADE",
            "is_stale": True,
            "age_seconds": None,
            "reason": "no cached decision available yet",
            "last_error": last_error,
        }

    age_seconds = (now_ms() - latest.computed_at_ms) / 1000
    data = latest.model_dump()
    data["age_seconds"] = age_seconds
    data["is_stale"] = age_seconds > STALE_SECONDS
    data["stale_seconds"] = STALE_SECONDS

    if data["is_stale"] and data["decision"] != "NO_TRADE":
        data["decision_raw"] = data["decision"]
        data["decision"] = "NO_TRADE"
        data.setdefault("reasons", []).append("cached decision too old")

    return data
