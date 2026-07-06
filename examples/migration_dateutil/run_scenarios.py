"""Exercises dateutil.easter across its whole documented domain.

No nodrift code anywhere — recording happens via auto-instrumentation:

    nodrift record --include dateutil.easter -o traces -- python run_scenarios.py
"""

from dateutil import easter

# the algorithms' validity ranges: Julian from 326, Gregorian 1583-4099
SPOT_YEARS = (1583, 1600, 1601, 1699, 1700, 1799, 1800, 1899, 1900, 1954,
              2000, 2019, 2024, 2025, 2026, 2038, 2099, 2100, 2199, 2200,
              2299, 2300, 2400, 3000, 4000, 4099)


def main():
    calls = 0
    failures = 0
    for year in range(1583, 4100, 7):           # broad sweep, every method
        for method in (1, 2, 3):
            easter.easter(year, method)
            calls += 1
    for year in SPOT_YEARS:                      # century boundaries etc.
        for method in (1, 2, 3):
            easter.easter(year, method)
            calls += 1
    easter.easter(2026)                          # default-argument behavior
    calls += 1
    for bad_method in (0, 4, -1, 99):            # error behavior
        calls += 1
        try:
            easter.easter(2024, bad_method)
        except ValueError:
            failures += 1
    print("scenarios: %d calls (%d raised, as expected)" % (calls, failures))


if __name__ == "__main__":
    main()
