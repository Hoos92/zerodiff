"""Modern rewrite of stdnum.luhn."""


class ValidationError(Exception):
    pass


class InvalidFormat(ValidationError):
    def __str__(self):
        return "The number has an invalid format."


class InvalidChecksum(ValidationError):
    def __str__(self):
        return "The number's checksum or check digit is invalid."


def checksum(number, alphabet="0123456789"):
    n = len(alphabet)
    number = tuple(alphabet.index(i) for i in reversed(str(number)))
    return (sum(number[::2]) +
            sum(sum(divmod(i * 2, n)) for i in number[1::2])) % n


def validate(number, alphabet="0123456789"):
    if not bool(number) or not all(c in alphabet for c in str(number)):
        raise InvalidFormat()
    if checksum(number, alphabet) != 0:
        raise InvalidChecksum()
    return number


def is_valid(number, alphabet="0123456789"):
    try:
        return bool(validate(number, alphabet))
    except ValidationError:
        return False


def calc_check_digit(number, alphabet="0123456789"):
    check = checksum(str(number) + alphabet[0], alphabet)
    return alphabet[-check % len(alphabet)]
