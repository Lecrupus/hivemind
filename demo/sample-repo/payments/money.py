from decimal import ROUND_HALF_UP, Decimal


def round_cents(amount) -> int:
    """Round a (possibly fractional) cent amount to whole cents, half-up."""
    return int(Decimal(str(amount)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
