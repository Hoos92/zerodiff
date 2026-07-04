"""Modern rewrite of stdnum.isbn (validate/compact/isbn_type/convert).

Faithful quirks preserved: format is checked before length (so "" raises
InvalidFormat, not InvalidLength), and the to_isbn10/to_isbn13 converters
do STRING surgery that preserves the input's hyphenation.
"""


class ValidationError(Exception):
    message = ""

    def __init__(self, message=None):
        if message is not None:
            self.message = message
        super().__init__(self.message)

    def __str__(self):
        return self.message


class InvalidFormat(ValidationError):
    message = "The number has an invalid format."


class InvalidLength(ValidationError):
    message = "The number has an invalid length."


class InvalidChecksum(ValidationError):
    message = "The number's checksum or check digit is invalid."


class InvalidComponent(ValidationError):
    message = "One of the parts of the number are invalid or unknown."


def compact(number, convert=False):
    number = "".join(number.split()).replace("-", "").strip().upper()
    if convert:
        return to_isbn13(number)
    return number


def _isbn10_check_digit(digits):
    total = sum((10 - i) * int(d) for i, d in enumerate(digits))
    check = (11 - total % 11) % 11
    return "X" if check == 10 else str(check)


def _ean_check_digit(digits):
    total = sum((3 if i % 2 else 1) * int(d)
                for i, d in enumerate(digits))
    return str((10 - total % 10) % 10)


def validate(number, convert=False):
    number = compact(number)
    if not number[:-1].isdigit():
        raise InvalidFormat()
    if len(number) == 10:
        if number[-1] != "X" and not number[-1].isdigit():
            raise InvalidFormat()
        if _isbn10_check_digit(number[:-1]) != number[-1]:
            raise InvalidChecksum()
    elif len(number) == 13:
        if not number.isdigit():
            raise InvalidFormat()
        if _ean_check_digit(number[:-1]) != number[-1]:
            raise InvalidChecksum()
        if number[:3] not in ("978", "979"):
            raise InvalidComponent()
    else:
        raise InvalidLength()
    if convert:
        return to_isbn13(number)
    return number


def isbn_type(number):
    try:
        number = validate(number)
    except ValidationError:
        return None
    return "ISBN13" if len(number) == 13 else "ISBN10"


def to_isbn13(number):
    """Convert to ISBN13, preserving the input's hyphenation."""
    number = number.strip()
    min_number = compact(number)
    if len(min_number) == 13:
        return number
    separator = "-" if "-" in number else ""
    return ("978" + separator + number[:-1]
            + _ean_check_digit("978" + min_number[:-1]))


def to_isbn10(number):
    """Convert a 978-prefixed ISBN13 to ISBN10, preserving hyphenation."""
    number = number.strip()
    min_number = compact(number)
    if len(min_number) == 10:
        return number
    if not min_number.startswith("978"):
        raise InvalidComponent("Does not use 978 Bookland prefix.")
    separator = "-" if "-" in number else ""
    body = number[3 + len(separator):-1]
    return body + _isbn10_check_digit(compact(body))


def is_valid(number):
    try:
        return bool(validate(number))
    except ValidationError:
        return False
