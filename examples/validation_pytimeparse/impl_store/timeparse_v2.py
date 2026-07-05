"""Modern rewrite of pytimeparse.timeparse."""

import re

_UNITS = [
    ("weeks", 604800, r"w|wk|wks|week|weeks"),
    ("days", 86400, r"d|day|days"),
    ("hours", 3600, r"h|hr|hrs|hour|hours"),
    ("minutes", 60, r"m|min|mins|minute|minutes"),
    ("seconds", 1, r"s|sec|secs|second|seconds"),
]

# recorded contracts: bare numbers are NOT durations ("32" -> None) and
# "and" is not a connector ("1 hour and 2 minutes" -> None); commas are
_NUMBER = r"\d+(?:\.\d+)?"
_SEP = r"[,/]?\s*"

_SEGMENTS = "".join(
    r"(?:(?P<%s>%s)\s*(?:%s)%s)?" % (name, _NUMBER, pattern, _SEP)
    for name, _, pattern in _UNITS)
_DURATION_RE = re.compile(r"^\s*(?P<sign>[+-]\s*)?" + _SEGMENTS
                          + r"\s*$")

_CLOCK_RE = re.compile(
    r"^\s*(?P<sign>[+-]\s*)?"
    r"(?:(?P<hours>\d+):)?"
    r"(?P<minutes>\d*):"
    r"(?P<seconds>\d+(?:\.\d+)?)\s*$")


def _as_number(text):
    value = float(text)
    return int(value) if value.is_integer() else value


def timeparse(sval, granularity="seconds"):
    """'3d2h32m' -> 268320; returns None (never raises) on garbage."""
    match = _CLOCK_RE.match(sval)
    if match:
        total = 0.0
        total += int(match.group("hours") or 0) * 3600
        total += int(match.group("minutes") or 0) * 60
        total += float(match.group("seconds"))
        if match.group("sign") and match.group("sign").strip() == "-":
            total = -total
        return _as_number(total)

    match = _DURATION_RE.match(sval)
    if not match or not any(match.group(name) for name, _, _ in _UNITS):
        return None
    total = 0.0
    for name, multiplier, _ in _UNITS:
        if match.group(name):
            total += float(match.group(name)) * multiplier
    if match.group("sign") and match.group("sign").strip() == "-":
        total = -total
    return _as_number(total)
