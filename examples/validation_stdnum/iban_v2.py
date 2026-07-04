"""Modern rewrite of stdnum.iban (validate/compact/calc_check_digits)."""

import re


class ValidationError(Exception):
    pass


class InvalidFormat(ValidationError):
    def __str__(self):
        return "The number has an invalid format."


class InvalidLength(ValidationError):
    def __str__(self):
        return "The number has an invalid length."


class InvalidChecksum(ValidationError):
    def __str__(self):
        return "The number's checksum or check digit is invalid."


class InvalidComponent(ValidationError):
    def __str__(self):
        return "One of the parts of the number are invalid or unknown."


# country -> (IBAN length, BBAN structure)
COUNTRIES = {
    "AE": (23, re.compile(r"^\d{3}\d{16}$")),
    "AT": (20, re.compile(r"^\d{16}$")),
    "BE": (16, re.compile(r"^\d{12}$")),
    "CH": (21, re.compile(r"^\d{5}[0-9A-Z]{12}$")),
    "DE": (22, re.compile(r"^\d{18}$")),
    "ES": (24, re.compile(r"^\d{20}$")),
    "FR": (27, re.compile(r"^\d{10}[0-9A-Z]{11}\d{2}$")),
    "GB": (22, re.compile(r"^[A-Z]{4}\d{14}$")),
    "IT": (27, re.compile(r"^[A-Z]\d{10}[0-9A-Z]{12}$")),
    "NL": (18, re.compile(r"^[A-Z]{4}\d{10}$")),
    "NO": (15, re.compile(r"^\d{11}$")),
    "PL": (28, re.compile(r"^\d{24}$")),
    "SA": (24, re.compile(r"^\d{2}[0-9A-Z]{18}$")),
    "SE": (24, re.compile(r"^\d{20}$")),
}

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def compact(number):
    return "".join(number.split()).replace("-", "").strip().upper()


def _to_base10(number):
    return "".join(str(_ALPHABET.index(c)) for c in number[4:] + number[:4])


def validate(number, check_country=True):
    """Validate an IBAN. ``check_country`` additionally runs the
    country-specific validation plug-in where one exists (e.g. Belgium's
    national check digits and bank registry -- which really does reject
    the textbook example BE68539007547034)."""
    number = compact(number)
    if not all(c in _ALPHABET for c in number):
        raise InvalidFormat()
    if len(number) < 4 or not number[:2].isalpha():
        raise InvalidFormat()
    # quirk preserved: the mod-97 checksum is verified BEFORE length or
    # country, so a truncated or unknown-country IBAN raises
    # InvalidChecksum, not InvalidLength/InvalidComponent
    if int(_to_base10(number)) % 97 != 1:
        raise InvalidChecksum()
    country = number[:2]
    if country not in COUNTRIES:
        raise InvalidComponent()
    length, structure = COUNTRIES[country]
    if len(number) != length:
        raise InvalidLength()
    if not structure.match(number[4:]):
        raise InvalidFormat()
    if check_country:
        _validate_country(number)
    return number


def _validate_country(number):
    # country plug-ins are a data/registry dependency, reused from stdnum
    # the same way slugify's rewrite reuses its transliteration dependency
    from stdnum.iban import get_cc_module

    module = get_cc_module(number[:2].lower(), "iban")
    if module is not None:
        module.validate(number)


def calc_check_digits(number):
    number = compact(number)
    rearranged = number[4:] + number[:2] + "00"
    base10 = "".join(str(_ALPHABET.index(c)) for c in rearranged)
    return "%02d" % (98 - int(base10) % 97)


def is_valid(number, check_country=True):
    try:
        return bool(validate(number, check_country=check_country))
    except Exception:
        return False
