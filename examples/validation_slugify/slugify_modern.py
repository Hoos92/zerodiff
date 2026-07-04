"""Modern rewrite of python-slugify (slugify + smart_truncate).

Reuses the same transliteration dependency (text-unidecode) the original
uses -- a rewrite is allowed to keep its dependencies.
"""

import html
import re
import unicodedata

import text_unidecode

CHAR_ENTITY_RE = re.compile(r"&(%s);" % "|".join("amp lt gt quot".split()))
DECIMAL_RE = re.compile(r"&#(\d+);")
HEX_RE = re.compile(r"&#x([\da-fA-F]+);")
QUOTE_RE = re.compile(r"[']+")
DISALLOWED_RE = re.compile(r"[^-a-z0-9]+")
DISALLOWED_WITH_UPPER_RE = re.compile(r"[^-A-Za-z0-9]+")
DISALLOWED_UNICODE_RE = re.compile(r"[^-\w]+")
DUPLICATE_DASH_RE = re.compile(r"[-_]{2,}")
NUMBERS_RE = re.compile(r"(?<=\d),(?=\d)")
DEFAULT_SEPARATOR = "-"


def smart_truncate(string, max_length=0, word_boundary=False,
                   separator=" ", save_order=False):
    """Truncate a string, optionally only at word boundaries."""
    string = string.strip(separator)
    if not max_length:
        return string
    if len(string) < max_length:
        return string
    if not word_boundary:
        return string[:max_length].strip(separator)

    if separator not in string:
        return string[:max_length]

    truncated = ""
    for word in string.split(separator):
        if word:
            next_len = len(truncated) + len(word)
            if next_len < max_length:
                truncated += "{}{}".format(word, separator)
            elif next_len == max_length:
                truncated += "{}".format(word)
                break
            else:
                if save_order:
                    break
    if not truncated:
        truncated = string[:max_length]
    return truncated.strip(separator)


def slugify(text, entities=True, decimal=True, hexadecimal=True,
            max_length=0, word_boundary=False, separator=DEFAULT_SEPARATOR,
            save_order=False, stopwords=(), regex_pattern=None,
            lowercase=True, replacements=(), allow_unicode=False):
    """Make a slug from the given text."""
    for old, new in replacements:
        text = text.replace(old, new)

    if entities:
        text = html.unescape(text)
    if decimal:
        text = DECIMAL_RE.sub(lambda m: chr(int(m.group(1))), text)
    if hexadecimal:
        text = HEX_RE.sub(lambda m: chr(int(m.group(1), 16)), text)

    # apostrophes IN THE INPUT act as separators (c'est -> c-est) ...
    text = QUOTE_RE.sub(DEFAULT_SEPARATOR, text)

    if allow_unicode:
        text = unicodedata.normalize("NFKC", text)
    else:
        text = text_unidecode.unidecode(text)

    if lowercase:
        text = text.lower()

    # ... but apostrophes INTRODUCED BY TRANSLITERATION are deleted
    # (Cyrillic soft sign: "Komp'iuter" -> "kompiuter")
    text = QUOTE_RE.sub("", text)
    text = NUMBERS_RE.sub("", text)

    pattern = regex_pattern
    if pattern is None:
        if allow_unicode:
            pattern = DISALLOWED_UNICODE_RE
        elif lowercase:
            pattern = DISALLOWED_RE
        else:
            pattern = DISALLOWED_WITH_UPPER_RE
    text = re.sub(pattern, DEFAULT_SEPARATOR, text)
    # underscores collapse like dashes (matters for the unicode pattern)
    text = re.sub(r"[-_]+", DEFAULT_SEPARATOR, text).strip(
        DEFAULT_SEPARATOR)

    if stopwords:
        if lowercase:
            words = [w for w in text.split(DEFAULT_SEPARATOR)
                     if w not in [s.lower() for s in stopwords]]
        else:
            lowered = [s.lower() for s in stopwords]
            words = [w for w in text.split(DEFAULT_SEPARATOR)
                     if w.lower() not in lowered]
        text = DEFAULT_SEPARATOR.join(words)

    if max_length > 0:
        text = smart_truncate(text, max_length, word_boundary,
                              DEFAULT_SEPARATOR, save_order)

    if separator != DEFAULT_SEPARATOR:
        text = text.replace(DEFAULT_SEPARATOR, separator)

    return text
