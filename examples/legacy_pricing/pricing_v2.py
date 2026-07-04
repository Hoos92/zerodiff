"""Modern rewrite of the legacy pricing module.

Restructured for readability (guard clauses, names, docstrings) while
preserving the observable behavior exactly — including the quirks: empty
coupon string means "no coupon", bulk discount starts at ten units, the tier
discount applies after the coupon, and the original error messages are kept
because callers match on them.
"""

TIER_DISCOUNTS = {"std": 0.0, "gold": 0.02, "vip": 0.05}
COUPONS = {"SAVE10": 0.10, "SAVE5": 0.05}
TAX_RATE = 0.0825
BULK_QTY = 10
BULK_FACTOR = 0.95


def tier_discount(tier):
    """Fractional discount for a customer tier."""
    if tier not in TIER_DISCOUNTS:
        raise ValueError("unknown tier: %s" % tier)
    return TIER_DISCOUNTS[tier]


def validate_coupon(code):
    """Fractional discount for a coupon code; empty/None means no coupon."""
    if not code:
        return 0.0
    if code not in COUPONS:
        raise ValueError("unknown coupon: %s" % code)
    return COUPONS[code]


def _line_total(item):
    qty = item["qty"]
    if qty <= 0:
        raise ValueError("quantity must be positive")
    line = qty * item["unit_price"]
    if qty >= BULK_QTY:
        line = line * BULK_FACTOR
    return qty, round(line, 2)


def calc_price(order):
    """Price an order: line totals, coupon+tier discount, tax, total."""
    items = order["items"]
    if not items:
        raise ValueError("order has no items")

    subtotal = 0.0
    lines = []
    for item in items:
        qty, line = _line_total(item)
        subtotal = subtotal + line
        lines.append((item["sku"], qty, line))
    subtotal = round(subtotal, 2)

    discount = subtotal * validate_coupon(order.get("coupon"))
    discount = discount + (subtotal - discount) * tier_discount(
        order.get("customer_tier", "std"))
    discount = round(discount, 2)

    taxed_base = subtotal - discount
    tax = round(taxed_base * TAX_RATE, 2)
    total = round(taxed_base + tax, 2)
    return {
        "subtotal": subtotal,
        "discount": discount,
        "tax": tax,
        "total": total,
        "lines": lines,
    }
