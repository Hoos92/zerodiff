"""Modern rewrite of humanfriendly's size and timespan functions."""

import re


class InvalidSize(Exception):
    pass


class InvalidTimespan(Exception):
    pass


_DECIMAL_UNITS = [("KB", 1000 ** 1), ("MB", 1000 ** 2), ("GB", 1000 ** 3),
                  ("TB", 1000 ** 4), ("PB", 1000 ** 5), ("EB", 1000 ** 6),
                  ("ZB", 1000 ** 7), ("YB", 1000 ** 8)]
_BINARY_UNITS = [("KiB", 1024 ** 1), ("MiB", 1024 ** 2),
                 ("GiB", 1024 ** 3), ("TiB", 1024 ** 4),
                 ("PiB", 1024 ** 5), ("EiB", 1024 ** 6),
                 ("ZiB", 1024 ** 7), ("YiB", 1024 ** 8)]

_UNIT_WORDS = {
    "b": 1, "byte": 1, "bytes": 1,
    "k": 1000, "kb": 1000, "kilobyte": 1000, "kilobytes": 1000,
    "m": 1000 ** 2, "mb": 1000 ** 2, "megabyte": 1000 ** 2,
    "megabytes": 1000 ** 2,
    "g": 1000 ** 3, "gb": 1000 ** 3, "gigabyte": 1000 ** 3,
    "gigabytes": 1000 ** 3,
    "t": 1000 ** 4, "tb": 1000 ** 4, "terabyte": 1000 ** 4,
    "terabytes": 1000 ** 4,
    "p": 1000 ** 5, "pb": 1000 ** 5, "petabyte": 1000 ** 5,
    "petabytes": 1000 ** 5,
}
_BINARY_WORDS = {"kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3,
                 "tib": 1024 ** 4, "pib": 1024 ** 5}
_BINARY_EQUIVALENT = {1000 ** i: 1024 ** i for i in range(1, 9)}

# plain numbers only (no scientific notation -- '1e3' tokenizes as
# [1, 'e', 3] and is rejected); punctuation runs become string tokens
_TOKEN_RE = re.compile(r"(\d+(?:\.\d+)?)|([a-zA-Z]+)|([^\s\w]+)")


def _tokenize(text):
    tokens = []
    for number, word, symbol in _TOKEN_RE.findall(text):
        if number:
            value = float(number)
            tokens.append(int(value) if value.is_integer() else value)
        else:
            tokens.append(word or symbol)
    return tokens


def parse_size(size, binary=False):
    """'1.5 GiB' -> 1610612736; '1 KB' -> 1000 (1024 when binary=True).
    Recorded quirk: trailing tokens are ignored ('1 KB extra' -> 1000)."""
    tokens = _tokenize(size)
    if tokens and isinstance(tokens[0], (int, float)):
        if len(tokens) == 1:
            return int(tokens[0])
        if isinstance(tokens[1], str):
            word = tokens[1].lower()
            if word in _BINARY_WORDS:
                return int(tokens[0] * _BINARY_WORDS[word])
            if word in _UNIT_WORDS:
                multiplier = _UNIT_WORDS[word]
                if binary and multiplier in _BINARY_EQUIVALENT:
                    multiplier = _BINARY_EQUIVALENT[multiplier]
                return int(tokens[0] * multiplier)
    raise InvalidSize("Failed to parse size! (input %r was tokenized as "
                      "%r)" % (size, tokens))


def _round_number(count, keep_width=False):
    text = "%.2f" % float(count)
    if not keep_width:
        text = re.sub(r"0+$", "", text)
        text = re.sub(r"\.$", "", text)
    return text


def format_size(num_bytes, keep_width=False, binary=False):
    """1500 -> '1.5 KB'; 1024 (binary) -> '1 KiB'."""
    units = _BINARY_UNITS if binary else _DECIMAL_UNITS
    for name, divider in reversed(units):
        if abs(num_bytes) >= divider:
            number = _round_number(float(num_bytes) / divider, keep_width)
            return "%s %s" % (number, name)
    return "1 byte" if num_bytes == 1 else "%s bytes" % num_bytes


_TIME_UNITS = {
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
    "w": 604800, "week": 604800, "weeks": 604800,
    # a humanfriendly year is 52 weeks (31,449,600s), not 365.25 days
    "y": 31449600, "year": 31449600, "years": 31449600,
}


def parse_timespan(timespan):
    """'5m' -> 300.0 (result is always a float, like the original)."""
    tokens = _tokenize(timespan)
    if tokens and isinstance(tokens[0], (int, float)):
        if len(tokens) == 1:
            return float(tokens[0])
        if len(tokens) == 2 and isinstance(tokens[1], str):
            unit = tokens[1].lower()
            if unit in _TIME_UNITS:
                return float(tokens[0]) * _TIME_UNITS[unit]
    raise InvalidTimespan("Failed to parse timespan! (input %r was "
                          "tokenized as %r)" % (timespan, tokens))


_TIMESPAN_SERIES = [
    (31449600, "year"), (604800, "week"), (86400, "day"),
    (3600, "hour"), (60, "minute"), (1, "second"),
]


def _pluralize(count, singular):
    number = _round_number(count) if isinstance(count, float) else str(count)
    word = singular if number == "1" else singular + "s"
    return "%s %s" % (number, word)


def format_timespan(num_seconds, detailed=False):
    """3725 -> '1 hour, 2 minutes and 5 seconds'."""
    if num_seconds < 60:
        return _pluralize(
            num_seconds if isinstance(num_seconds, float)
            and not float(num_seconds).is_integer() else int(num_seconds),
            "second")
    parts = []
    remaining = num_seconds
    for divider, singular in _TIMESPAN_SERIES:
        count = int(remaining // divider)
        if count:
            parts.append(_pluralize(count, singular))
            remaining -= count * divider
    if remaining and detailed:
        parts.append(_pluralize(remaining, "second"))
    if not detailed:
        # recorded quirk: only the three largest components are shown
        # (90061s really formats as "1 day, 1 hour and 1 minute" -- the
        # trailing second is silently dropped)
        parts = parts[:3]
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]
