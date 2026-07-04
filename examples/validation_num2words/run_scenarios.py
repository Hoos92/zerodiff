"""Exercises num2words (github.com/savoirfairelinux/num2words) — high
complexity: large linguistic rule tables. English cardinal/ordinal/year.

Uses explicit wrapping (the third supported recording style):

    retrace record -o traces -- python run_scenarios.py
"""

import retrace

retrace.wrap("num2words", "num2words")

from num2words import num2words  # noqa: E402

INTS = [0, 1, 2, 5, 9, 10, 11, 12, 13, 14, 15, 19, 20, 21, 25, 30, 40,
        55, 68, 99, 100, 101, 105, 110, 111, 123, 199, 200, 300, 999,
        1000, 1001, 1005, 1066, 1100, 1234, 1999, 2000, 2024, 5000,
        9999, 10000, 12345, 100000, 123456, 999999, 10**6, 10**6 + 1,
        2 * 10**6, 10**9, 10**12, -1, -21, -105, -1000]

FLOATS = [1.5, 3.14, 0.05, 100.75, -2.5]

YEARS = [1066, 1492, 1776, 1800, 1900, 1901, 1984, 1999, 2000, 2001,
         2010, 2024, 2100]


def main():
    calls = 0
    raised = 0
    for n in INTS:
        for kwargs in ({}, {"to": "ordinal"}, {"to": "ordinal_num"}):
            calls += 1
            try:
                num2words(n, **kwargs)
            except Exception:
                raised += 1  # e.g. negative ordinals raise TypeError
    for f in FLOATS:
        num2words(f)
        calls += 1
    for y in YEARS:
        num2words(y, to="year")
        calls += 1
    for bad_to in ("bogus", ""):
        calls += 1
        try:
            num2words(42, to=bad_to)
        except Exception:
            raised += 1
    for bad_value in ("abc", None):
        calls += 1
        try:
            num2words(bad_value)
        except Exception:
            raised += 1
    print("scenarios: %d calls (%d raised)" % (calls, raised))


if __name__ == "__main__":
    main()
