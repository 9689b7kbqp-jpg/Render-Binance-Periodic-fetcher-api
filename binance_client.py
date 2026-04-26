from __future__ import annotations

import time
from typing import Any

import httpx


class BinanceClient:
    def __init__(self, base_url: str = "https://api.binance.com", timeout_s: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(timeout_s, connect=timeout_s)

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    async def ticker_price(self, symbol: str) -> dict[str, Any]:
        return await self._get("/api/v3/ticker/price", {"symbol": symbol})

    async def book_ticker(self, symbol: str) -> dict[str, Any]:
        return await self._get("/api/v3/ticker/bookTicker", {"symbol": symbol})

    async def exchange_info(self, symbol: str) -> dict[str, Any]:
        return await self._get("/api/v3/exchangeInfo", {"symbol": symbol})

    async def klines_1h(self, symbol: str, limit: int = 100) -> list[list[Any]]:
        return await self._get("/api/v3/klines", {"symbol": symbol, "interval": "1h", "limit": limit})

    async def agg_trades(self, symbol: str, start_ms: int, end_ms: int | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"symbol": symbol, "startTime": start_ms, "limit": limit}
        if end_ms is not None:
            params["endTime"] = end_ms
        return await self._get("/api/v3/aggTrades", params)

    async def agg_trades_window(self, symbol: str, start_ms: int, end_ms: int, max_pages: int = 20) -> list[dict[str, Any]]:
        """Fetch aggregate trades by time window, paginated conservatively.

        Binance caps aggTrades at 1000 rows per call. This function stops when:
        - the returned batch is empty,
        - the latest trade timestamp reaches end_ms,
        - max_pages is reached.
        """
        out: list[dict[str, Any]] = []
        cursor = start_ms

        for _ in range(max_pages):
            batch = await self.agg_trades(symbol=symbol, start_ms=cursor, end_ms=end_ms, limit=1000)
            if not batch:
                break

            out.extend(batch)
            last_t = int(batch[-1]["T"])
            if last_t >= end_ms or len(batch) < 1000:
                break

            cursor = last_t + 1
            await self._rate_limit_pause()

        # Deduplicate by aggregate trade id.
        dedup: dict[int, dict[str, Any]] = {}
        for trade in out:
            dedup[int(trade["a"])] = trade
        return sorted(dedup.values(), key=lambda t: int(t["T"]))

    async def _rate_limit_pause(self) -> None:
        # Small pause to avoid bursty pagination against Binance public endpoints.
        import asyncio
        await asyncio.sleep(0.05)


def now_ms() -> int:
    return int(time.time() * 1000)
