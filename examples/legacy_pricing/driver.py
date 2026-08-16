"""Driver using explicit instrumentation (zerodiff.wrap; no source edits to
the legacy module). Run via:

    zerodiff record -o traces -- python driver.py

For the fully zero-edit alternative, see scenarios.py with --include.
"""

import zerodiff

zerodiff.wrap("pricing", "calc_price")
zerodiff.wrap("pricing", "validate_coupon")
zerodiff.wrap("pricing", "tier_discount")

from scenarios import main  # noqa: E402  (wrap before pricing is used)

if __name__ == "__main__":
    main()
