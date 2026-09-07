"""Money arithmetic. Integer minor units only (DOMAIN_MODEL.md section 4).

No float ever enters these functions or leaves them. Formatting to a display
string is the single boundary where a decimal point appears.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.config import settings


def line_total(unit_price: int, quantity: int) -> int:
    """Rule $2 - exact integer multiplication."""
    if quantity < 0:
        raise ValueError("quantity must not be negative")
    return unit_price * quantity


def subtotal(line_totals: list[int]) -> int:
    """Rule $3 - exact integer sum."""
    return sum(line_totals)


def tax_for(subtotal_cents: int, rate: float | None = None) -> int:
    """Rule $3/$4 - tax applies to the subtotal, rounded half-up exactly once.

    Uses Decimal rather than round() because Python's banker's rounding would
    turn 12.5 cents into 12, not 13.
    """
    r = settings.tax_rate if rate is None else rate
    return int(
        (Decimal(subtotal_cents) * Decimal(str(r))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def order_total(subtotal_cents: int, tax_cents: int, delivery_fee_cents: int = 0) -> int:
    """Rule $3 - INV-4 holds by construction."""
    return subtotal_cents + tax_cents + delivery_fee_cents


def display(minor: int) -> str:
    """The only place a currency symbol or decimal point appears (Rule $5).

    ``currency_decimals`` is 0 for rupees, where the minor unit is the rupee
    itself, and 2 for currencies with cents.
    """
    sign = "-" if minor < 0 else ""
    minor = abs(minor)
    symbol = settings.currency_symbol
    places = settings.currency_decimals

    if places == 0:
        return f"{sign}{symbol}{minor:,}"
    scale = 10**places
    return f"{sign}{symbol}{minor // scale:,}.{minor % scale:0{places}d}"


def money_fields(prefix: str, cents: int) -> dict[str, object]:
    """Every money value crosses the API as both cents and display."""
    return {f"{prefix}_cents": cents, f"{prefix}_display": display(cents)}
