"""Money is integer minor units, rounded half-up once (Rules $1-$6)."""
import pytest

from app.config import settings
from app.services import money


def test_display_uses_the_configured_currency():
    """PKR: the minor unit is the rupee, so nothing follows a decimal point."""
    assert money.display(450) == "Rs 450"
    assert money.display(0) == "Rs 0"
    assert money.display(1250) == "Rs 1,250"
    assert money.display(-250) == "-Rs 250"


def test_display_handles_a_two_decimal_currency(monkeypatch):
    monkeypatch.setattr(settings, "currency_symbol", "$")
    monkeypatch.setattr(settings, "currency_decimals", 2)
    assert money.display(950) == "$9.50"
    assert money.display(5) == "$0.05"
    assert money.display(100000) == "$1,000.00"


def test_line_total_is_exact():
    assert money.line_total(950, 3) == 2850
    assert money.line_total(333, 3) == 999


def test_tax_rounds_half_up_not_bankers():
    # 1562 * 0.08 = 124.96 -> 125
    assert money.tax_for(1562, 0.08) == 125
    # Exactly .5 must round up; Python's round() would give 12 here.
    assert money.tax_for(1250, 0.01) == 13


def test_tax_applies_to_subtotal_not_per_line():
    lines = [333, 333, 333]
    per_line = sum(money.tax_for(l, 0.08) for l in lines)
    on_subtotal = money.tax_for(money.subtotal(lines), 0.08)
    assert on_subtotal == 80
    assert per_line == 81  # the bug this rule prevents
    assert on_subtotal != per_line


def test_order_total_is_consistent():
    sub, tax, fee = 2250, 180, 0
    assert money.order_total(sub, tax, fee) == sub + tax + fee


def test_money_fields_carry_both_forms():
    f = money.money_fields("total", 2430)
    assert f == {"total_cents": 2430, "total_display": money.display(2430)}


def test_negative_quantity_rejected():
    with pytest.raises(ValueError):
        money.line_total(100, -1)
