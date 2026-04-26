from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from app.models import DecisionResult


@dataclass
class DecisionCache:
    latest: Optional[DecisionResult] = None
    last_error: Optional[str] = None


cache = DecisionCache()
cache_lock = asyncio.Lock()
