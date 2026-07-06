"""Exercises `humanize` (github.com/python-humanize/humanize) number and
filesize formatting.

Zero nodrift code — record with:
    nodrift record --include humanize -o traces -- python run_scenarios.py
"""

import humanize

SIZES = [0, 1, 2, 5, 299, 999, 1000, 1023, 1024, 1025, 1500, 2048, 4096,
         10000, 65536, 999999, 10**6, 10**6 + 1, 2**20, 3 * 2**20, 10**9,
         2**30, 10**12, 2**40, 10**15, 2**50, 10**18, 2**60, 10**21, 2**70,
         10**24, 2**80, 10**26, -1, -1024, -999999, 1234.5, 0.5]

INTS = [0, 1, 12, 100, 1000, 1234, 12345, 123456, 1234567, 10**9,
        10**12 + 5, -1, -1000, -1234567, 999, 1001]

WORDS_INPUT = [0, 1, 100, 999, 1000, 1200, 999999, 10**6, 1200000, 10**9,
               1.5 * 10**9, 10**12, 10**15, 10**18, 10**21, 10**24, 10**30,
               10**33, 10**100, 10**101, -1, -10**6, 42]

ORDINALS = [0, 1, 2, 3, 4, 5, 10, 11, 12, 13, 14, 21, 22, 23, 24, 101,
            102, 103, 111, 112, 113, 1000, -1, -2, -11]

AP = list(range(0, 15)) + [100, -1, -5]


def main():
    calls = 0
    for v in SIZES:
        humanize.naturalsize(v)
        humanize.naturalsize(v, binary=True)
        humanize.naturalsize(v, gnu=True)
        calls += 3
    for v in INTS:
        humanize.intcomma(v)
        calls += 1
    for v in (1234.5, 12345.67, "1234567", "abc", None):
        calls += 1
        try:
            humanize.intcomma(v)
        except (TypeError, ValueError):
            pass
    for v in WORDS_INPUT:
        humanize.intword(v)
        calls += 1
    for v in ORDINALS:
        humanize.ordinal(v)
        calls += 1
    for v in AP:
        humanize.apnumber(v)
        calls += 1
    print("scenarios: %d top-level calls" % calls)


if __name__ == "__main__":
    main()
