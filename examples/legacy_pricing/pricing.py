# Legacy pricing module. Deliberately old-fashioned: implicit behaviors,
# quirky operation order, and error messages that callers depend on.
# This file plays the role of "the code nobody understands anymore".

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
    # quirk: empty string is treated like "no coupon", not an error
    if code is None or code == "":
        return 0.0
    if code not in COUPONS:
        raise ValueError("unknown coupon: %s" % code)
    return COUPONS[code]


def calc_price(order):
    items = order["items"]
    if not items:
        raise ValueError("order has no items")
    subtotal = 0.0
    lines = []
    for it in items:
        qty = it["qty"]
        price = it["unit_price"]
        if qty <= 0:
            raise ValueError("quantity must be positive")
        line = qty * price
        # bulk discount kicks in AT ten units, not above ten
        if qty >= BULK_QTY:
            line = line * BULK_FACTOR
        line = round(line, 2)
        subtotal = subtotal + line
        lines.append((it["sku"], qty, line))
    subtotal = round(subtotal, 2)
    # quirk: tier discount applies to what's left AFTER the coupon
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
