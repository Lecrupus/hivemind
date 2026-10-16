from .money import round_cents


def order_total(lines: list[tuple[int, int]]) -> int:
    """Sum of (unit_price_cents, quantity) lines."""
    return sum(price * qty for price, qty in lines)


def apply_tax(total_cents: int, rate_percent: float) -> int:
    return round_cents(total_cents * (1 + rate_percent / 100))
