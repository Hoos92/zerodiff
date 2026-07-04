"""Modern rewrite of `inflection` (the Rails inflector port)."""

import re

PLURAL_RULES = (
    (r"(?i)(quiz)$", r"\1zes"),
    (r"(?i)^(oxen)$", r"\1"),
    (r"(?i)^(ox)$", r"\1en"),
    (r"(?i)(m|l)ice$", r"\1ice"),
    (r"(?i)(m|l)ouse$", r"\1ice"),
    (r"(?i)(matr|vert|ind)(?:ix|ex)$", r"\1ices"),
    (r"(?i)(x|ch|ss|sh)$", r"\1es"),
    (r"(?i)([^aeiouy]|qu)y$", r"\1ies"),
    (r"(?i)(hive)$", r"\1s"),
    (r"(?i)([lr])f$", r"\1ves"),
    (r"(?i)([^f])fe$", r"\1ves"),
    (r"(?i)sis$", "ses"),
    (r"(?i)([ti])um$", r"\1a"),
    (r"(?i)(buffal|tomat|potat)o$", r"\1oes"),
    (r"(?i)(bu)s$", r"\1ses"),
    (r"(?i)(alias|status)$", r"\1es"),
    (r"(?i)(octop|vir)us$", r"\1i"),
    (r"(?i)(ax|test)is$", r"\1es"),
    (r"(?i)([ti])a$", r"\1a"),
    (r"(?i)s$", "s"),
    (r"$", "s"),
)

SINGULAR_RULES = (
    (r"(?i)(database)s$", r"\1"),
    (r"(?i)(quiz)zes$", r"\1"),
    (r"(?i)(matr)ices$", r"\1ix"),
    (r"(?i)(vert|ind)ices$", r"\1ex"),
    (r"(?i)^(ox)en", r"\1"),
    (r"(?i)(alias|status)(es)?$", r"\1"),
    (r"(?i)(octop|vir)(us|i)$", r"\1us"),
    (r"(?i)^(a)x[ie]s$", r"\1xis"),
    (r"(?i)(cris|test)(is|es)$", r"\1is"),
    (r"(?i)(shoe)s$", r"\1"),
    (r"(?i)(o)es$", r"\1"),
    (r"(?i)(bus)(es)?$", r"\1"),
    (r"(?i)(m|l)ice$", r"\1ouse"),
    (r"(?i)(x|ch|ss|sh)es$", r"\1"),
    (r"(?i)(m)ovies$", r"\1ovie"),
    (r"(?i)(s)eries$", r"\1eries"),
    (r"(?i)([^aeiouy]|qu)ies$", r"\1y"),
    (r"(?i)([lr])ves$", r"\1f"),
    (r"(?i)(tive)s$", r"\1"),
    (r"(?i)(hive)s$", r"\1"),
    (r"(?i)([^f])ves$", r"\1fe"),
    (r"(?i)(t)he(sis|ses)$", r"\1hesis"),
    (r"(?i)(s)ynop(sis|ses)$", r"\1ynopsis"),
    (r"(?i)(analy|ba|diagno|parenthe|progno|synop|the)(sis|ses)$",
     r"\1sis"),
    (r"(?i)([ti])a$", r"\1um"),
    (r"(?i)(n)ews$", r"\1ews"),
    (r"(?i)(ss)$", r"\1"),
    (r"(?i)s$", ""),
)

IRREGULARS = (
    ("person", "people"),
    ("man", "men"),
    ("woman", "women"),
    ("child", "children"),
    ("sex", "sexes"),
    ("move", "moves"),
    ("cow", "kine"),
    ("zombie", "zombies"),
)

# NB: "police" is NOT uncountable in the original -- singularize("police")
# really returns "polouse" (the mice/lice rule fires); we must match that.
UNCOUNTABLES = frozenset((
    "equipment", "fish", "information", "jeans", "money", "rice",
    "series", "sheep", "species",
))


def _apply_rules(word, rules):
    if not word or word.lower() in UNCOUNTABLES:
        return word
    for pattern, replacement in rules:
        if re.search(pattern, word):
            return re.sub(pattern, replacement, word)
    return word


def pluralize(word):
    for singular, plural in IRREGULARS:
        if word.lower() == singular or word.lower() == plural:
            return plural
    return _apply_rules(word, PLURAL_RULES)


def singularize(word):
    for singular, plural in IRREGULARS:
        if word.lower() == plural or word.lower() == singular:
            return singular
    return _apply_rules(word, SINGULAR_RULES)


def camelize(string, uppercase_first_letter=True):
    """device_type -> DeviceType (or deviceType with the flag off)."""
    if uppercase_first_letter:
        return re.sub(r"(?:^|_)(.)", lambda m: m.group(1).upper(), string)
    return string[0].lower() + camelize(string)[1:]


def underscore(word):
    """DeviceType -> device_type, HTMLParser -> html_parser."""
    word = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", word)
    word = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", word)
    return word.replace("-", "_").lower()


def dasherize(word):
    return word.replace("_", "-")


def humanize(word):
    """author_id -> 'Author'."""
    word = re.sub(r"_id$", "", word)
    word = word.replace("_", " ")
    word = word.strip()
    if not word:
        return word
    return word[0].upper() + word[1:].lower()


def titleize(word):
    """'raiders_of_the_lost_ark' -> 'Raiders Of The Lost Ark'."""
    return re.sub(r"\b('?[a-z])", lambda m: m.group(1).capitalize(),
                  humanize(underscore(word)))


def ordinal(number):
    number = abs(int(number))
    if number % 100 in (11, 12, 13):
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")


def ordinalize(number):
    return "{}{}".format(number, ordinal(number))
