"""Exercises pytimeparse (github.com/wroberts/pytimeparse) — duration
expressions with a famously permissive grammar; returns None on failure
instead of raising (a contract callers depend on).

    retrace record -o traces -- python run_scenarios.py
"""

import retrace

retrace.wrap("pytimeparse.timeparse", "timeparse")

from pytimeparse.timeparse import timeparse  # noqa: E402

INPUTS = [
    "32", "32s", "32 secs", "32 seconds", "2m", "2 minutes", "2.5m",
    "1.2 minutes", "1h", "1 hr", "1.5 hours", "1d", "2 days", "1w",
    "1 week", "2w3d", "3d2h32m", "2h32m", "1h2m3s", "4:13", "04:13",
    "1:02:03", "01:02:03.5", "5:00", "0:30", ":30", "1 hour, 2 minutes",
    "1 hour and 2 minutes", "1h 2m 3s", "+32m", "-32m", "- 1 minute",
    "1.75 h", "1e2 s", "32m16s", "2 mins, 30 secs",
    "", "junk", "1 lightyear", "1:2:3:4", "h", "one hour",
]


def main():
    for text in INPUTS:
        timeparse(text)  # never raises; None is the failure contract
    print("scenarios: %d calls" % len(INPUTS))


if __name__ == "__main__":
    main()
