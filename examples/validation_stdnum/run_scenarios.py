"""Exercises python-stdnum (github.com/arthurdejong/python-stdnum) —
enterprise-grade complexity: three modules, a custom exception hierarchy
(InvalidFormat/InvalidLength/InvalidChecksum/InvalidComponent), and IBAN
country rules.

Driven through `retrace migrate` (see README.md).
"""

import retrace

for fn in ("validate", "checksum", "calc_check_digit", "is_valid"):
    retrace.wrap("stdnum.luhn", fn)
for fn in ("validate", "compact", "isbn_type", "to_isbn13", "to_isbn10",
           "is_valid"):
    retrace.wrap("stdnum.isbn", fn)
for fn in ("validate", "compact", "calc_check_digits", "is_valid"):
    retrace.wrap("stdnum.iban", fn)

from stdnum import iban, isbn, luhn  # noqa: E402

CARDS_VALID = ["79927398713", "4532015112830366", "5555555555554444",
               "378282246310005", "6011111111111117", "0"]
CARDS_INVALID = ["79927398714", "4532015112830367", "1234567812345678"]
CARDS_MALFORMED = ["", "4532a15112830366", "45320151 12830366", "-1"]

ISBNS = [
    "978-0-13-468599-1", "9780134685991", "978-0134685991",
    "0-19-852663-6", "0198526636", "080442957X", "0804429574",
    "979-10-90636-07-1",
    "978-0-13-468599-2",      # bad check digit
    "0-19-852663-7",          # bad check digit
    "12345", "978013468599", "abcdefghij", "", "978-3-16-148410-0",
    "5901234123457",          # valid EAN, not a bookland ISBN
]

IBANS_VALID = [
    "GB82WEST12345698765432", "DE89370400440532013000",
    "FR1420041010050500013M02606", "ES9121000418450200051332",
    "IT60X0542811101000000123456", "NL91ABNA0417164300",
    "BE68539007547034", "CH9300762011623852957",
    "AT611904300234573201", "SE4550000000058398257466",
    "PL61109010140000071219812874", "SA0380000000608010167519",
    "AE070331234567890123456", "NO9386011117947",
    "GB82 WEST 1234 5698 7654 32", "gb82west12345698765432",
]
IBANS_INVALID = [
    "GB82WEST12345698765433",      # bad checksum
    "GB82WEST1234569876543",       # bad length
    "XX82WEST12345698765432",      # unknown country
    "GB82WEST1234569876543!",      # bad character
    "DE8937040044053201300",       # bad length for DE
    "",
]


def main():
    calls = 0
    raised = 0

    def try_call(fn, *args):
        nonlocal_counts[0] += 1
        try:
            fn(*args)
        except Exception:
            nonlocal_counts[1] += 1

    nonlocal_counts = [0, 0]

    for number in CARDS_VALID + CARDS_INVALID + CARDS_MALFORMED:
        try_call(luhn.validate, number)
        luhn.is_valid(number)
        nonlocal_counts[0] += 1
    for number in CARDS_VALID:
        try_call(luhn.checksum, number)
        try_call(luhn.calc_check_digit, number)

    for number in ISBNS:
        try_call(isbn.validate, number)
        try_call(isbn.compact, number)
        try_call(isbn.isbn_type, number)
        isbn.is_valid(number)
        nonlocal_counts[0] += 1
    for number in ("0-19-852663-6", "080442957X", "978-0-13-468599-1",
                   "979-10-90636-07-1"):
        try_call(isbn.to_isbn13, number)
        try_call(isbn.to_isbn10, number)

    for number in IBANS_VALID + IBANS_INVALID:
        try_call(iban.validate, number)
        try_call(iban.compact, number)
        iban.is_valid(number)
        nonlocal_counts[0] += 1
    for number in ("GB82WEST12345698765432", "DE89370400440532013000"):
        try_call(iban.calc_check_digits, number)

    calls, raised = nonlocal_counts
    print("scenarios: %d calls (%d raised)" % (calls, raised))


if __name__ == "__main__":
    main()
