"""Cost in exact Decimal from the model_price table (contract 11 section 4).

cost = uncached_in x in_price + cached x cached_price + out x out_price, all per 1M tokens.
Cached tokens use the input price when no cached price is set. A model with no price
gives None ("price not set"), never 0. A cache hit costs 0.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from app.observability.usage import Usage

MILLION = Decimal(1_000_000)
USD_PLACES = Decimal("0.000001")


@dataclass(frozen=True)
class Price:
    usd_per_1m_in: Decimal
    usd_per_1m_out: Decimal
    usd_per_1m_cached: Decimal | None = None


def _dec(value: str | None) -> Decimal | None:
    return None if value in (None, "") else Decimal(value)


def load_prices(db_path: Path) -> dict[str, Price]:
    conn = sqlite3.connect(db_path, timeout=5)
    try:
        rows = conn.execute(
            "SELECT model, usd_per_1m_in, usd_per_1m_out, usd_per_1m_cached FROM model_price"
        ).fetchall()
    finally:
        conn.close()
    prices = {}
    for model, p_in, p_out, p_cached in rows:
        dec_in, dec_out = _dec(p_in), _dec(p_out)
        if dec_in is not None and dec_out is not None:
            prices[model] = Price(dec_in, dec_out, _dec(p_cached))
    return prices


def compute_cost(usage: Usage, price: Price | None, cache_hit: bool = False) -> Decimal | None:
    if cache_hit:
        return Decimal(0)
    if price is None:
        return None
    cached = min(usage.tokens_cached, usage.tokens_in)
    cached_price = price.usd_per_1m_cached if price.usd_per_1m_cached is not None else price.usd_per_1m_in
    total = (
        Decimal(usage.tokens_in - cached) * price.usd_per_1m_in
        + Decimal(cached) * cached_price
        + Decimal(usage.tokens_out) * price.usd_per_1m_out
    )
    return total / MILLION


def format_usd(value: Decimal | None) -> str | None:
    """JSON money format of contract 05: a string with 6 decimals, or None when not priced."""
    return None if value is None else str(value.quantize(USD_PLACES))
