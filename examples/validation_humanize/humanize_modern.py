"""Modern rewrite of humanize's filesize and core number formatting."""

DECIMAL_SUFFIXES = (" kB", " MB", " GB", " TB", " PB", " EB", " ZB", " YB")
BINARY_SUFFIXES = (" KiB", " MiB", " GiB", " TiB", " PiB", " EiB", " ZiB",
                   " YiB")
GNU_SUFFIXES = ("K", "M", "G", "T", "P", "E", "Z", "Y")

WORD_POWERS = (
    (3, "thousand"), (6, "million"), (9, "billion"), (12, "trillion"),
    (15, "quadrillion"), (18, "quintillion"), (21, "sextillion"),
    (24, "septillion"), (27, "octillion"), (30, "nonillion"),
    (33, "decillion"),
)

AP_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven",
            "eight", "nine")


def naturalsize(value, binary=False, gnu=False, format="%.1f"):
    """Human-readable file size (decimal, binary, or GNU ls style)."""
    if gnu:
        suffixes = GNU_SUFFIXES
    elif binary:
        suffixes = BINARY_SUFFIXES
    else:
        suffixes = DECIMAL_SUFFIXES
    base = 1024 if (binary or gnu) else 1000
    size = float(value)
    abs_size = abs(size)

    if abs_size == 1 and not gnu:
        return "%d Byte" % size
    if abs_size < base:
        if gnu:
            return "%dB" % size
        return "%d Bytes" % size

    for i, suffix in enumerate(suffixes):
        unit = base ** (i + 2)
        if abs_size < unit:
            return (format % (base * size / unit)) + suffix
    return (format % (base * size / unit)) + suffix


def intcomma(value, ndigits=None):
    """1234567 -> '1,234,567'. Non-numeric input passes through as text --
    the original never validates, and callers rely on that."""
    import re

    if ndigits is not None:
        text = "{:.{}f}".format(float(value), ndigits)
    else:
        text = str(value)
    while True:
        grouped = re.sub(r"^(-?\d+)(\d{3})", r"\1,\2", text)
        if grouped == text:
            return text
        text = grouped


def intword(value, format="%.1f"):
    """1200000 -> '1.2 million' (negatives are worded too)."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return str(value)
    if value < 0:
        worded = intword(-value, format)
        return "-" + worded if worded != str(-value) else str(value)
    if value < 1000:
        return str(value)
    for exponent, name in WORD_POWERS:
        power = 10 ** exponent
        if value < power * 1000:
            chopped = format % (value / power)
            # 999999 -> "1000.0 thousand" would be silly; bump to the next
            if float(chopped) == 1000.0:
                continue
            return chopped + " " + name
    return str(value)


def apnumber(value):
    """AP style: spell out one..nine, digits otherwise."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return str(value)
    if 0 <= value <= 9:
        return AP_WORDS[value]
    return str(value)


def ordinal(value):
    """1 -> '1st', 11 -> '11th'."""
    value = int(value)
    if value % 100 in (11, 12, 13):
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return "%d%s" % (value, suffix)
