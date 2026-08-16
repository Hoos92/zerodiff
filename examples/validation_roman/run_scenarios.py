"""Exercises the `roman` package (github.com/zopefoundation/roman).

Zero zerodiff code — record with:
    zerodiff record --include roman -o traces -- python run_scenarios.py
"""

import roman

INVALID_NUMERALS = [
    "", "IIII", "VV", "LL", "DD", "IL", "IC", "XD", "XM", "MCMC", "IXI",
    "VX", "mcmxciv", "MCMXCIV ", " MCMXCIV", "M CMXCIV", "ABC", "0", "IVX",
    "CMCM", "XCXC", "IXIX", "IVIV",
]


def main():
    calls = 0
    failures = 0
    # toRoman across and beyond its domain
    for n in list(range(-5, 5051)) + [10000]:
        calls += 1
        try:
            roman.toRoman(n)
        except roman.RomanError:
            failures += 1
    # non-integer inputs are behavior too
    for bad in (3.5, "X", None, True):
        calls += 1
        try:
            roman.toRoman(bad)
        except (roman.RomanError, TypeError):
            failures += 1
    # fromRoman: every canonical numeral round-trips
    for n in range(1, 5000):
        calls += 1
        roman.fromRoman(roman.toRoman(n))
    # invalid numerals
    for s in INVALID_NUMERALS:
        calls += 1
        try:
            roman.fromRoman(s)
        except roman.RomanError:
            failures += 1
    print("scenarios: %d calls (%d raised, as expected)" % (calls, failures))


if __name__ == "__main__":
    main()
