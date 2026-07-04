"""A rewrite of the legacy pricing module with five seeded behavioral bugs —
the kinds of changes AI rewrites really introduce. Retrace should catch all
five. (Each bug is marked BUG-n.)

BUG-1  silently skips invalid quantities instead of raising ValueError
BUG-2  bulk discount at qty > 10 instead of >= 10 (off-by-one)
BUG-3  line items returned as lists instead of tuples (type change)
BUG-4  tax truncated toward zero instead of rounded (rounding change)
BUG-5  coupon error message reworded (callers match on the message)
"""

import math

TIER_DISCOUNTS = {"std": 0.0, "gold": 0.02, "vip": 0.05}
COUPONS = {"SAVE10": 0.10, "SAVE5": 0.05}
TAX_RATE = 0.0825
BULK_QTY = 10
BULK_FACTOR = 0.95


def tier_discount(tier):
    if tier not in TIER_DISCOUNTS:
        raise ValueError("unknown tier: %s" % tier)
    return TIER_DISCOUNTS[tier]


def validate_coupon(code):
    if not code:
        return 0.0
    if code not in COUPONS:
        # BUG-5: reworded error message
        raise ValueError("invalid coupon code: %s" % code)
    return COUPONS[code]


def calc_price(order):
    items = order["items"]
    if not items:
        raise ValueError("order has no items")

    subtotal = 0.0
    lines = []
    for item in items:
        qty = item["qty"]
        if qty <= 0:
            # BUG-1: silently skip instead of raising
            continue
        line = qty * item["unit_price"]
        # BUG-2: off-by-one — bulk discount no longer applies at exactly 10
        if qty > BULK_QTY:
            line = line * BULK_FACTOR
        line = round(line, 2)
        subtotal = subtotal + line
        # BUG-3: list instead of tuple
        lines.append([item["sku"], qty, line])
    subtotal = round(subtotal, 2)

    discount = subtotal * validate_coupon(order.get("coupon"))
    discount = discount + (subtotal - discount) * tier_discount(
        order.get("customer_tier", "std"))
    discount = round(discount, 2)

    taxed_base = subtotal - discount
    # BUG-4: truncates instead of rounding
    tax = math.floor(taxed_base * TAX_RATE * 100) / 100
    total = round(taxed_base + tax, 2)
    return {
        "subtotal": subtotal,
        "discount": discount,
        "tax": tax,
        "total": total,
        "lines": lines,
    }
