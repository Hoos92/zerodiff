"""Modern rewrite of the `roman` package (zopefoundation/roman)."""

import re


class RomanError(Exception):
    pass


class OutOfRangeError(RomanError):
    pass


class NotIntegerError(RomanError):
    pass


class InvalidRomanNumeralError(RomanError):
    pass


_ROMAN_VALUES = (
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
    (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
    (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
)

_VALID_NUMERAL = re.compile(
    "^M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")


def toRoman(n):
    """Convert an integer (0..4999) to a Roman numeral. 0 -> 'N' (nulla)."""
    if not isinstance(n, int):
        # original wording says "decimals" even for strings/None; keep it
        raise NotIntegerError("decimals can not be converted")
    if not 0 <= n < 5000:
        raise OutOfRangeError("number out of range (must be 0..4999)")
    if n == 0:
        return "N"
    parts = []
    remaining = n
    for value, numeral in _ROMAN_VALUES:
        count, remaining = divmod(remaining, value)
        parts.append(numeral * count)
    return "".join(parts)


def fromRoman(s):
    """Convert a canonical Roman numeral to an integer."""
    if not s:
        raise InvalidRomanNumeralError("Input can not be blank")
    if not _VALID_NUMERAL.match(s):
        raise InvalidRomanNumeralError("Invalid Roman numeral: %s" % s)
    total = 0
    index = 0
    for value, numeral in _ROMAN_VALUES:
        while s[index:index + len(numeral)] == numeral:
            total += value
            index += len(numeral)
    return total
