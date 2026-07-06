"""Exercises word2number (github.com/akshaynagpal/w2n) — simple complexity:
one function, but a decade of accumulated parsing quirks.

    nodrift record -o traces -- python run_scenarios.py
"""

import nodrift

nodrift.wrap("word2number.w2n", "word_to_num")

from word2number import w2n  # noqa: E402

INPUTS = [
    "two", "seven", "nine", "ten", "eleven", "nineteen", "twenty",
    "twenty three", "thirty-five", "forty two", "ninety nine", "hundred",
    "one hundred", "one hundred and forty two", "two hundred", "five hundred and six",
    "thousand", "one thousand", "nine thousand nine hundred ninety nine",
    "twelve thousand", "hundred thousand",
    "million", "one million", "two million three thousand nine hundred and eighty four",
    "billion", "three billion", "one billion two million",
    "two point three", "zero point five", "point five", "one point zero two",
    "two million point two three", "point", "point point",
    "Twenty Three", "TWENTY", "  twenty  ",
    "112", "100 23",
    "", "hello", "one two hello", "million million", "two thousand thousand",
    "and", "one and one", "hundred and",
]


def main():
    ok = 0
    raised = 0
    for text in INPUTS:
        try:
            w2n.word_to_num(text)
            ok += 1
        except Exception:
            raised += 1
    # non-string inputs are behavior too
    for bad in (42, 3.5, None, ["two"]):
        try:
            w2n.word_to_num(bad)
            ok += 1
        except Exception:
            raised += 1
    print("scenarios: %d ok, %d raised" % (ok, raised))


if __name__ == "__main__":
    main()
