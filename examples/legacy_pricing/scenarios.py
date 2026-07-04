"""Exercises the legacy pricing module. Contains no retrace code at all.

Use with auto-instrumentation (zero edits to any file):

    retrace record --include pricing -o traces -- python scenarios.py
"""

import pricing

PRICES = [1.25, 3.99, 10.15, 0.375, 24.0]
QTYS = [1, 3, 9, 10, 11, 25]
COUPONS = [None, "", "SAVE10", "SAVE5", "BOGUS"]
TIERS = ["std", "gold", "vip", "platinum"]


def scenarios():
    # single-item orders across the grid (deterministic order)
    for i, price in enumerate(PRICES):
        for j, qty in enumerate(QTYS):
            coupon = COUPONS[(i + j) % len(COUPONS)]
            tier = TIERS[(i * 2 + j) % len(TIERS)]
            yield {
                "items": [{"sku": "SKU-%d%d" % (i, j), "qty": qty,
                           "unit_price": price}],
                "coupon": coupon,
                "customer_tier": tier,
            }
    # multi-item orders
    yield {"items": [
        {"sku": "A", "qty": 2, "unit_price": 3.99},
        {"sku": "B", "qty": 10, "unit_price": 1.25},
        {"sku": "C", "qty": 1, "unit_price": 10.15},
    ], "coupon": "SAVE10", "customer_tier": "vip"}
    yield {"items": [
        {"sku": "D", "qty": 25, "unit_price": 0.375},
        {"sku": "E", "qty": 9, "unit_price": 24.0},
    ], "coupon": "SAVE5", "customer_tier": "gold"}
    # edge cases: invalid quantities, empty order, tier defaulting
    yield {"items": [{"sku": "Z", "qty": 0, "unit_price": 5.0}],
           "coupon": None, "customer_tier": "std"}
    yield {"items": [{"sku": "Z", "qty": -3, "unit_price": 5.0}],
           "coupon": None, "customer_tier": "std"}
    yield {"items": [{"sku": "OK", "qty": 1, "unit_price": 5.0},
                     {"sku": "BAD", "qty": 0, "unit_price": 5.0}],
           "coupon": None, "customer_tier": "std"}
    yield {"items": [], "coupon": "SAVE10", "customer_tier": "std"}
    yield {"items": [{"sku": "NT", "qty": 2, "unit_price": 7.5}]}  # no tier


def main():
    calls = 0
    failures = 0
    for order in scenarios():
        calls += 1
        try:
            pricing.calc_price(order)
        except (ValueError, KeyError):
            failures += 1
    # exercise the small boundaries directly, including their error paths
    for code in COUPONS + ["save10"]:  # case-sensitivity is behavior too
        calls += 1
        try:
            pricing.validate_coupon(code)
        except ValueError:
            failures += 1
    for tier in TIERS + ["Gold"]:
        calls += 1
        try:
            pricing.tier_discount(tier)
        except ValueError:
            failures += 1
    print("scenarios: made %d top-level calls (%d raised, as expected)"
          % (calls, failures))


if __name__ == "__main__":
    main()
