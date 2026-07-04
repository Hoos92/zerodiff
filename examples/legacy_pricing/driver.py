"""Driver using explicit instrumentation (retrace.wrap; no source edits to
the legacy module). Run via:

    retrace record -o traces -- python driver.py

For the fully zero-edit alternative, see scenarios.py with --include.
"""

import retrace

retrace.wrap("pricing", "calc_price")
retrace.wrap("pricing", "validate_coupon")
retrace.wrap("pricing", "tier_discount")

from scenarios import main  # noqa: E402  (wrap before pricing is used)

if __name__ == "__main__":
    main()
