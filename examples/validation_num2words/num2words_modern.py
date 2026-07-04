"""Modern rewrite of num2words for English: cardinal, ordinal,
ordinal_num, and year conversions."""

ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven",
        "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
        "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
        "eighty", "ninety"]
SCALES = [(10**12, "trillion"), (10**9, "billion"), (10**6, "million"),
          (1000, "thousand")]

ORDINAL_IRREGULAR = {
    "one": "first", "two": "second", "three": "third", "five": "fifth",
    "eight": "eighth", "nine": "ninth", "twelve": "twelfth",
}


def _under_hundred(n):
    if n < 20:
        return ONES[n]
    tens, ones = divmod(n, 10)
    word = TENS[tens]
    return word + "-" + ONES[ones] if ones else word


def _under_thousand(n, use_and=True):
    if n < 100:
        return _under_hundred(n)
    hundreds, rest = divmod(n, 100)
    word = ONES[hundreds] + " hundred"
    if rest:
        joiner = " and " if use_and else " "
        word += joiner + _under_hundred(rest)
    return word


def _cardinal_int(n):
    if n < 0:
        return "minus " + _cardinal_int(-n)
    if n < 1000:
        return _under_thousand(n)
    parts = []
    remaining = n
    for value, name in SCALES:
        count, remaining = divmod(remaining, value)
        if count:
            parts.append(_under_thousand(count, use_and=True) + " " + name)
    if remaining:
        if remaining < 100 and parts:
            return ", ".join(parts[:-1] + [parts[-1] + " and "
                                           + _under_hundred(remaining)])
        parts.append(_under_thousand(remaining))
    return ", ".join(parts) if parts else "zero"


def _cardinal_float(value):
    text = repr(float(value))
    whole_text, _, frac_text = text.partition(".")
    whole = _cardinal_int(int(whole_text))
    if value < 0 and not whole.startswith("minus"):
        whole = "minus " + whole
    digits = " ".join(ONES[int(d)] for d in frac_text)
    return whole + " point " + digits


def _ordinalize_word(cardinal):
    head, sep, last = cardinal.rpartition(" ")
    if "-" in last:
        first_part, _, hyphen_last = last.rpartition("-")
        return head + sep + first_part + "-" + _ordinalize_word(hyphen_last)
    if last in ORDINAL_IRREGULAR:
        ordinal = ORDINAL_IRREGULAR[last]
    elif last.endswith("y"):
        ordinal = last[:-1] + "ieth"
    else:
        ordinal = last + "th"
    return head + sep + ordinal


def _ordinal_num(n):
    if n % 100 in (11, 12, 13):
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return "%d%s" % (n, suffix)


def _year(n):
    """Year grammar recovered from recorded behavior: centuries divisible
    by ten read as cardinals ("two thousand", "two thousand and one"),
    other centuries pair up ("nineteen hundred", "nineteen oh-one",
    "ten sixty-six", "twenty ten")."""
    if n < 0:
        return _cardinal_int(-n) + " BC"
    high, low = divmod(n, 100)
    if high == 0:
        return _cardinal_int(n)
    if high % 10 == 0 and low < 10:
        return _cardinal_int(n)
    if low == 0:
        return _cardinal_int(high) + " hundred"
    if low < 10:
        return _cardinal_int(high) + " oh-" + ONES[low]
    return _cardinal_int(high) + " " + _under_hundred(low)


def num2words(number, ordinal=False, lang="en", to="cardinal", **kwargs):
    if to not in ("cardinal", "ordinal", "ordinal_num", "year", "currency"):
        raise NotImplementedError()
    if ordinal:
        to = "ordinal"

    if isinstance(number, str):
        import decimal
        number = decimal.Decimal(number)  # InvalidOperation is behavior
        if number == int(number):
            number = int(number)
        else:
            number = float(number)
    elif not isinstance(number, (int, float)):
        # the original formats the VALUE into this message, not the type
        raise TypeError("type(%s) not in [long, int, float]" % number)

    if to == "cardinal":
        if isinstance(number, float) and number != int(number):
            return _cardinal_float(number)
        return _cardinal_int(int(number))
    if to == "ordinal":
        if number < 0:
            raise TypeError("Cannot treat negative num %s as ordinal."
                            % number)
        return _ordinalize_word(_cardinal_int(int(number)))
    if to == "ordinal_num":
        if number < 0:
            raise TypeError("Cannot treat negative num %s as ordinal."
                            % number)
        return _ordinal_num(int(number))
    if to == "year":
        return _year(int(number))
    raise NotImplementedError()
