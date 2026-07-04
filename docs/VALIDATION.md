# Validation: three real GitHub libraries through the Retrace loop

To validate Retrace beyond the [dateutil case study](CASE_STUDY.md), the
same loop — record real behavior with zero source edits, write a clean-room
modern rewrite, replay, fix from hints — was run against three more real
libraries, chosen for three different *shapes* of behavior:

| library | GitHub | behavior shape | behaviors verified | first pass | passes to green |
|---|---|---|---|---|---|
| `roman` | zopefoundation/roman | numeric algorithm + custom exceptions | 10,083 | 10,022 matched, **61 diverged** | 3 |
| `inflection` | jpvanhal/inflection | ordered regex rule tables (Rails port) | 382 | 366 matched, **16 diverged** | 2 |
| `humanize` | python-humanize/humanize | formatting thresholds + suffix tables | 201 | 192 matched, **9 diverged** | 2 |

**Every one of the three clean-room rewrites was wrong on the first pass** —
all three were written carefully, by an assistant that knows these libraries,
and all three still diverged from recorded reality. Total: 10,666 recorded
behaviors, 86 first-pass divergences, all reaching 100% match using only the
report hints. Each `examples/validation_*/` directory reproduces its row.

## What the rewrites got wrong (all real, all caught)

**`roman`** — the rewrite rejected `toRoman(0)`; the real library returns
`"N"` (medieval *nulla*). The range error says `0..4999`, not `1..4999`.
And the non-integer error says `"decimals can not be converted"` even for
strings and `None` — a misleading message the original uses for every bad
type, which a faithful rewrite must reproduce word-for-word.

**`inflection`** — the Rails-ported rule tables are quirkier than the Rails
rules people remember:

- `pluralize("cactus")` → `"cactus"` (unchanged!) — only octopus/virus get
  the Latin `-i`. The rewrite's "correct" `"cacti"` was a behavior change.
- `singularize("cactus")` → `"cactu"` — the generic strip-the-s rule chops
  Latin words. Ugly, but 13 years of callers depend on the ugliness.
- `singularize("police")` → `"polouse"` — the mouse/louse regex fires on
  anything ending in "lice". A genuine legacy bug, faithfully enforced.
- `pluralize("hero")` → `"heros"` (not "heroes"), `"data"` → `"data"`,
  `singularize("basis")` → `"basis"` via a rule that literally matches the
  prefix `ba`.
- Recording also caught the original *crashing*:
  `camelize("", uppercase_first_letter=False)` raises `IndexError`. That
  crash is recorded behavior; the rewrite must crash identically.

**`humanize`** — threshold and pass-through behaviors that no docstring
mentions:

- `intword(999999)` → `"1.0 million"` (not "1000.0 thousand") — there's a
  hidden round-then-promote step; and negatives are worded
  (`-1000000` → `"-1.0 million"`), which the rewrite's early-return missed.
- `intcomma("abc")` → `"abc"` and `intcomma(None)` → `"None"` — the
  original never validates input; a rewrite that "helpfully" raises
  `ValueError` breaks callers.
- `apnumber(0)` → `"zero"` — the AP-style range starts at 0, not 1.

## Why this matters

None of these 86 divergences is a syntax error, a type error, or something
a linter flags. Most are the *rewrite being more correct than the original* —
which is exactly the problem: for a drop-in replacement, "better" is broken.
The recorded original is the only ground truth that captures this, and the
replay loop converged to 100% in at most three passes using nothing but the
report hints.

Honest scope note: 100% here means 100% *of recorded behaviors*. For
example, `fromRoman("N")` was never recorded (the driver round-trips
1..4999), so nothing is claimed about it. Coverage is bounded by the driver
— that is a property of the method, stated plainly in every report.
