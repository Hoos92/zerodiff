"""Driver using explicit instrumentation (nodrift.wrap; no source edits to
the legacy module). Run via:

    nodrift record -o traces -- python driver.py

For the fully zero-edit alternative, see scenarios.py with --include.
"""

import nodrift

nodrift.wrap("pricing", "calc_price")
nodrift.wrap("pricing", "validate_coupon")
nodrift.wrap("pricing", "tier_discount")

from scenarios import main  # noqa: E402  (wrap before pricing is used)

if __name__ == "__main__":
    main()
