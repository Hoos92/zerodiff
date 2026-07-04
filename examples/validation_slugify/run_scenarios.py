"""Exercises python-slugify (github.com/un33p/python-slugify) — medium
complexity: a text pipeline with ~10 interacting options.

    retrace record --include slugify.slugify -o traces -- python run_scenarios.py
"""

from slugify import slugify

TEXTS = [
    "Hello World",
    "Héllo Wörld -- 100% legit!",
    "  spaces   everywhere   ",
    "C'est déjà l'été",
    "Компьютер",
    "影師嗎 王小明",
    "10.5% of $1,000.00",
    "foo & bar | baz",
    "The Quick Brown Fox -- and the lazy dog",
    "___under___scores___",
    "CamelCaseText and ALLCAPS",
    "a" * 80,
    "", "-", "!!!",
    "smart “quotes” and — dashes…",
]

OPTION_SETS = [
    {},
    {"max_length": 12},
    {"max_length": 12, "word_boundary": True},
    {"max_length": 12, "word_boundary": True, "save_order": True},
    {"separator": "_"},
    {"lowercase": False},
    {"stopwords": ["the", "and", "of"]},
    {"replacements": [["|", "or"], ["&", "and"]]},
    {"allow_unicode": True},
    {"entities": False, "decimal": False, "hexadecimal": False},
]


def main():
    calls = 0
    for text in TEXTS:
        for opts in OPTION_SETS:
            slugify(text, **opts)
            calls += 1
    print("scenarios: %d calls" % calls)


if __name__ == "__main__":
    main()
