"""Exercises `inflection` (github.com/jpvanhal/inflection), a direct port
of Ruby on Rails' inflector — 2012-era regex rule tables.

Zero retrace code — record with:
    retrace record --include inflection -o traces -- python run_scenarios.py
"""

import inflection

WORDS = [
    # regulars
    "car", "book", "apple", "boat", "hat", "house", "river", "table",
    # classic tricky plurals
    "octopus", "matrix", "vertex", "index", "mouse", "louse", "ox", "quiz",
    "wife", "half", "leaf", "tomato", "potato", "hero", "echo", "bus",
    "status", "alias", "axis", "analysis", "basis", "crisis", "datum",
    "medium", "curriculum", "phenomenon", "criterion", "cactus", "focus",
    "fungus", "nucleus", "syllabus", "radius", "life", "knife", "shelf",
    "wolf", "dwarf", "roof", "belief", "chief", "day", "boy", "key",
    "city", "lady", "party", "berry", "fly", "try", "buzz", "box", "fox",
    "church", "brush", "kiss", "glass", "dish", "match", "torch",
    # irregulars and uncountables
    "person", "man", "woman", "child", "sex", "move", "cow", "zombie",
    "equipment", "information", "rice", "money", "species", "series",
    "fish", "sheep", "jeans", "police", "news",
    # already-plural inputs (singularize matters too)
    "people", "men", "children", "mice", "oxen", "matrices", "vertices",
    "statuses", "analyses", "data", "media", "wives", "leaves", "cities",
]

CAMEL_UNDERSCORE = [
    "device_type", "some_long_name", "html_parser", "io_error", "api_key",
    "DeviceType", "SomeLongName", "HTMLParser", "IOError", "APIKey",
    "already", "ALLCAPS", "Mixed_Case_thing", "a", "A", "x_y_z",
    "special_guest", "author_id", "person", "",
]

NUMBERS = [0, 1, 2, 3, 4, 5, 9, 10, 11, 12, 13, 14, 20, 21, 22, 23, 24,
           100, 101, 102, 103, 111, 112, 113, 1000, 1001, 1011, -1, -11]


def main():
    calls = 0
    for word in WORDS:
        inflection.pluralize(word)
        inflection.singularize(word)
        calls += 2
    for text in CAMEL_UNDERSCORE:
        for call in (lambda: inflection.camelize(text),
                     lambda: inflection.camelize(text, False),
                     lambda: inflection.underscore(text),
                     lambda: inflection.dasherize(text),
                     lambda: inflection.humanize(text),
                     lambda: inflection.titleize(text)):
            calls += 1
            try:
                call()
            except IndexError:
                pass  # camelize("", False) crashes -- that IS its behavior
    for n in NUMBERS:
        inflection.ordinal(n)
        inflection.ordinalize(n)
        calls += 2
    print("scenarios: %d top-level calls" % calls)


if __name__ == "__main__":
    main()
