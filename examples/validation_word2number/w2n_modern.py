"""Modern rewrite of word2number's word_to_num.

Faithful to the original's observable behavior, including its quirks:
unknown words are silently ignored, "point" alone returns 0, and the
famous tail bug -- "one billion two million" really returns 1003000002,
because the original re-adds the words after "billion" as a hundreds
part. Callers may have compensated for these; a drop-in must keep them.
"""

VALUES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100, "thousand": 1000, "million": 10**6, "billion": 10**9,
    "point": ".",
}
DECIMAL_WORDS = frozenset(
    "zero one two three four five six seven eight nine".split())

EXAMPLE = "(eg. two million twenty three thousand and forty nine)"


def _formation(words):
    numbers = [VALUES[w] for w in words]
    if len(numbers) == 4:
        return numbers[0] * numbers[1] + numbers[2] + numbers[3]
    if len(numbers) == 3:
        return numbers[0] * numbers[1] + numbers[2]
    if len(numbers) == 2:
        if 100 in numbers:
            return numbers[0] * numbers[1]
        return numbers[0] + numbers[1]
    return numbers[0]


def _decimal_sum(words):
    digits = []
    for word in words:
        if word not in DECIMAL_WORDS:
            return 0
        digits.append(str(VALUES[word]))
    return float("0." + "".join(digits))


def word_to_num(number_sentence):
    if not isinstance(number_sentence, str):
        raise ValueError("Type of input is not string! Please enter a "
                         "valid number word (eg. 'two million twenty "
                         "three thousand and forty nine')")
    sentence = number_sentence.replace("-", " ").lower()
    if sentence.isdigit():
        return int(sentence)

    # unknown words ("and", typos, anything) are silently dropped
    clean = [w for w in sentence.strip().split() if w in VALUES]
    if not clean:
        raise ValueError("No valid number words found! Please enter a "
                         "valid number word %s" % EXAMPLE)
    if any(clean.count(scale) > 1
           for scale in ("thousand", "million", "billion", "point")):
        raise ValueError("Redundant number word! Please enter a valid "
                         "number word %s" % EXAMPLE)

    decimals = []
    if "point" in clean:
        split_at = clean.index("point")
        decimals = clean[split_at + 1:]
        clean = clean[:split_at]

    billion = clean.index("billion") if "billion" in clean else -1
    million = clean.index("million") if "million" in clean else -1
    thousand = clean.index("thousand") if "thousand" in clean else -1

    if (thousand > -1 and (thousand < million or thousand < billion)) or \
            (million > -1 and million < billion):
        raise ValueError("Malformed number! Please enter a valid number "
                         "word %s" % EXAMPLE)

    total = 0
    if clean:
        if len(clean) == 1:
            total += VALUES[clean[0]]
        else:
            if billion > -1:
                total += _formation(clean[0:billion]) * 10**9
            if million > -1:
                start = billion + 1 if billion > -1 else 0
                total += _formation(clean[start:million]) * 10**6
            if thousand > -1:
                if million > -1:
                    start = million + 1
                elif billion > -1:
                    start = billion + 1
                else:
                    start = 0
                total += _formation(clean[start:thousand]) * 1000

            # the original's tail logic, preserved bug and all: after a
            # bare billion, the remaining words (including "million") are
            # re-added as a hundreds part
            if thousand > -1 and thousand != len(clean) - 1:
                total += _formation(clean[thousand + 1:])
            elif million > -1 and million != len(clean) - 1:
                total += _formation(clean[million + 1:])
            elif billion > -1 and billion != len(clean) - 1:
                total += _formation(clean[billion + 1:])
            elif thousand == -1 and million == -1 and billion == -1:
                total += _formation(clean)

    if decimals:
        total += _decimal_sum(decimals)
    return total
