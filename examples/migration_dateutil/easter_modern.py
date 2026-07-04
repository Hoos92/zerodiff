"""Modern rewrite of dateutil.easter.

The original is 74 lines of unexplained magic numbers from a 1990s
algorithm book. This rewrite implements the same three methods as separate,
named algorithms (Meeus), with the Julian-to-Gregorian conversion done with
a timedelta instead of folded into the arithmetic.
"""

import datetime

EASTER_JULIAN = 1     # date in the Julian (unreformed) calendar
EASTER_ORTHODOX = 2   # Julian computation, expressed in the Gregorian calendar
EASTER_WESTERN = 3    # Gregorian (Butcher/Meeus) algorithm


def easter(year, method=EASTER_WESTERN):
    """Easter Sunday of `year` for the given method (1, 2, or 3)."""
    if not 1 <= method <= 3:
        # exact original wording: callers may match on the message
        raise ValueError("invalid method")
    if method == EASTER_WESTERN:
        return _easter_gregorian(year)
    julian_date = _easter_julian(year)
    if method == EASTER_JULIAN:
        return julian_date
    return julian_date + datetime.timedelta(
        days=_julian_gregorian_gap(year))


def _easter_gregorian(year):
    """Butcher/Meeus algorithm, valid 1583-4099."""
    a = year % 19
    century, year_of_century = divmod(year, 100)
    leap_centuries, century_remainder = divmod(century, 4)
    metonic_correction = (century + 8) // 25
    h = (19 * a + century - leap_centuries
         - (century - metonic_correction + 1) // 3 + 15) % 30
    quarters, remainder = divmod(year_of_century, 4)
    weekday_offset = (32 + 2 * century_remainder + 2 * quarters
                      - h - remainder) % 7
    correction = (a + 11 * h + 22 * weekday_offset) // 451
    month, day = divmod(h + weekday_offset - 7 * correction + 114, 31)
    return datetime.date(year, month, day + 1)


def _easter_julian(year):
    """Meeus' Julian algorithm; result is a Julian-calendar date."""
    a = year % 4
    b = year % 7
    c = year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month, day = divmod(d + e + 114, 31)
    return datetime.date(year, month, day + 1)


def _julian_gregorian_gap(year):
    """Days the Gregorian calendar is ahead of the Julian in March/April."""
    return year // 100 - year // 400 - 2
