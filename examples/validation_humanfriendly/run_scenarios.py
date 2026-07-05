"""Exercises humanfriendly (github.com/xolox/python-humanfriendly) —
size/timespan parsing and formatting, dense with unit-ambiguity rules.

    retrace record -o traces -- python run_scenarios.py
"""

import retrace

for fn in ("parse_size", "format_size", "parse_timespan",
           "format_timespan"):
    retrace.wrap("humanfriendly", fn)

import humanfriendly  # noqa: E402

SIZES_TO_PARSE = [
    "0", "1", "42", "1B", "5 bytes", "1 KB", "1K", "1k", "1 kilobyte",
    "1 KiB", "1.5 GB", "1.5 GiB", "0.5 MB", "10 MB", "1 TB", "1 PB",
    "2 megabytes", "  8   GB  ", "1.5", "1e3 KB",
]
INVALID_SIZES = ["", "abc", "1 XB", "KB", "1..5 MB", "1 KB extra"]

BYTE_COUNTS = [0, 1, 5, 999, 1000, 1023, 1024, 1500, 10**6, 2**20,
               3 * 2**20, 10**9, 2**30, 10**12, 2**40, 10**15]

TIMESPANS_TO_PARSE = ["0", "5", "5s", "30s", "5m", "1h", "0.5h", "1d",
                      "1w", "2 hours", "5 minutes", "1 minute",
                      "6.5 seconds", "1y"]
INVALID_TIMESPANS = ["", "abc", "5 lightyears"]

SECONDS_TO_FORMAT = [0, 1, 0.5, 2.5, 59, 60, 61, 90, 3600, 3725, 7200,
                     86400, 90061, 604800, 2 * 604800 + 86400 + 3725,
                     31556952]


def main():
    calls = 0
    raised = 0
    for text in SIZES_TO_PARSE:
        for binary in (False, True):
            calls += 1
            try:
                humanfriendly.parse_size(text, binary=binary)
            except Exception:
                raised += 1
    for text in INVALID_SIZES:
        calls += 1
        try:
            humanfriendly.parse_size(text)
        except Exception:
            raised += 1
    for count in BYTE_COUNTS:
        for binary in (False, True):
            humanfriendly.format_size(count, binary=binary)
            calls += 1
    humanfriendly.format_size(1500, keep_width=True)
    calls += 1
    for text in TIMESPANS_TO_PARSE:
        calls += 1
        try:
            humanfriendly.parse_timespan(text)
        except Exception:
            raised += 1
    for text in INVALID_TIMESPANS:
        calls += 1
        try:
            humanfriendly.parse_timespan(text)
        except Exception:
            raised += 1
    for seconds in SECONDS_TO_FORMAT:
        humanfriendly.format_timespan(seconds)
        calls += 1
    humanfriendly.format_timespan(90061, detailed=True)
    calls += 1
    print("scenarios: %d calls (%d raised)" % (calls, raised))


if __name__ == "__main__":
    main()
