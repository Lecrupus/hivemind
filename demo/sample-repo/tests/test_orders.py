from payments.orders import apply_tax, order_total


def test_order_total():
    assert order_total([(250, 2), (100, 1)]) == 600


def test_apply_tax_rounds_half_up():
    assert apply_tax(1005, 50) == 1508  # 1507.5 -> 1508
