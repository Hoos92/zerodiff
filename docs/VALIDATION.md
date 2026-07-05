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

---

# Second cohort: rising complexity

A second, independent cohort of GitHub libraries, chosen as a complexity
ladder — from one quirky parser function to a linguistic rule engine:

| library | GitHub | complexity | behaviors | first pass | passes to green |
|---|---|---|---|---|---|
| `word2number` | akshaynagpal/w2n | simple: one parser, many quirks | 51 | **7 diverged** | 2 |
| `python-slugify` | un33p/python-slugify | medium: ~10 interacting options | 202 | **17 diverged** | 3 |
| `num2words` | savoirfairelinux/num2words | high: linguistic rule tables | 187 | **5 diverged** | 2 |

Again **three out of three clean-room rewrites were wrong on the first
pass** (29 divergences, none catchable by linters or type checkers), and
again every one reached 100% of recorded behaviors.

## The best finds of the whole program so far

- **`word2number` has a real arithmetic bug, and the recording proved it**:
  `word_to_num("one billion two million")` returns **1,003,000,002** — the
  original re-adds the words after "billion" as a "hundreds" part, so two
  million is counted one-and-a-half times. It also *silently ignores
  unknown words* (`word_to_num("one two hello")` → `3`) and returns `0`
  for the bare word `"point"`. A drop-in replacement must reproduce all of
  it — "fixing" the math would break any caller that compensated for it.
- **`python-slugify` treats two kinds of apostrophes differently.**
  Apostrophes *in the input* become separators (`"C'est"` → `"c-est"`),
  but apostrophes *introduced by transliteration* are deleted (Cyrillic
  soft sign: `"Компьютер"` → `"Komp'iuter"` → `"kompiuter"`). Two quote
  passes, one before and one after transliteration — invisible in the
  docs, decisive in the output, recovered entirely from recorded behavior.
- **`num2words` has an undocumented year grammar**: centuries divisible by
  ten read as cardinals ("two thousand and one"), others pair up
  ("nineteen oh-one", "ten sixty-six", "twenty ten"). Its type error even
  formats the *value* into the message (`type(None) not in [long, int,
  float]`) — reproduce the message, wart and all.

---

# Third cohort: `python-stdnum` — the full pipeline, end to end

The hardest validation, run entirely through **`retrace migrate`**:
record → scaffold → agent loop → signed attestation, on a compliance
library with three modules, a custom exception hierarchy, and per-country
IBAN plug-ins.

| library | GitHub | behaviors | boundaries | first pass | passes to green |
|---|---|---|---|---|---|
| `python-stdnum` (luhn+isbn+iban) | arthurdejong/python-stdnum | 269 | 14 | **38 diverged** | 3 |

The run finished with `retrace attest` pinning 14 trace files **and the
three rewrite source files**, `verify-attestation` passing, and tamper
detection catching a one-character edit to an attested file (exit 1).

Finds worth the price of admission:

- **Nested-call recording captured stdnum's real internal API.** The
  driver never passed `check_country=`, but stdnum's own `is_valid` calls
  `validate(number, check_country=...)` internally — the wrapped boundary
  recorded it, and the rewrite was forced to honor the true signature.
- **The textbook IBAN `BE68539007547034` is invalid according to stdnum**
  — the Belgian country plug-in's bank-registry lookup rejects the string
  half the internet uses as the canonical valid example.
- **Exception *ordering* is a contract**: stdnum verifies the mod-97
  checksum before length or country, so a truncated GB IBAN raises
  `InvalidChecksum`, not `InvalidLength`, and an unknown-country IBAN
  raises `InvalidChecksum`, not `InvalidComponent`.
- `to_isbn13`/`to_isbn10` **preserve the input's hyphenation** (string
  surgery, not numeric conversion), `validate("")` raises `InvalidFormat`
  (format precedes length), and the 979 error carries the custom message
  "Does not use 978 Bookland prefix."

---

# Fourth cohort: spec-heavy parsers, full pipeline on v0.8.0

Three libraries chosen for edge-case density, each run end-to-end through
`retrace migrate` (record → scaffold → agent loop → **signed
attestation**), exercising the v0.8.0 loop economics live — stall
detection stopped every first run the moment the scripted agent made no
progress:

| library | GitHub | behaviors | first pass | to green |
|---|---|---|---|---|
| `semver` | python-semver/python-semver | 277 | **2 diverged** | 2 |
| `humanfriendly` | xolox/python-humanfriendly | 113 | **8 diverged** | 2 |
| `pytimeparse` | wroberts/pytimeparse | 42 | **2 diverged** | 2 |

Finds:

- **`semver.bump_prerelease` is a silent no-op** on a prerelease with no
  digits (`"1.2.3-alpha"` comes back unchanged), and it bumps the
  rightmost *embedded* number: `alpha.7.x` → `alpha.8.x`.
- **`humanfriendly.format_timespan` silently drops everything below the
  three largest units** (90061s → "1 day, 1 hour and 1 minute" — the
  second vanishes), and its **year is 52 weeks**, not 365.25 days. Its
  size tokenizer rejects `"1e3 KB"` but accepts `"1 KB extra"` (trailing
  junk ignored).
- **`pytimeparse` refuses bare numbers** (`"32"` → None, not seconds) and
  the word "and" (`"1 hour and 2 minutes"` → None) while accepting
  commas — permissive-grammar contracts a rewrite "fixes" and breaks.

---

# Live cohort: real LLM, fully unattended (v0.9.1+)

Run with `retrace migrate --llm openai:...` — a live OpenAI model writing
the code, no human in the loop, on a real funded API key:

| target | model | result | iterations |
|---|---|---|---|
| shipping demo (37 behaviors) | gpt-4o-mini | **37/37 SUCCESS** | 1 agent call |
| `pytimeparse` (42) | gpt-4o-mini | **42/42 SUCCESS** | 1 agent call |
| `roman` (10,083) | gpt-4o-mini | **10,083/10,083 SUCCESS** | 2 agent calls |
| `semver` (277) | gpt-4o-mini | stalled at 0 (kept importing the original's internal class) | stall-stopped |
| `semver` (277) | gpt-4o | **275/277** — stuck on the same two `bump_prerelease` quirks that fooled the human first pass | 8 calls |

What the live runs taught (and changed) about the product:

- **Without the original source in the prompt, from-scratch rewrites are
  nearly impossible** — models plateaued reverse-engineering formulas
  from I/O pairs (15/37, 18/37). With the source as read-only reference
  (v0.9.1), the cheapest model one-shots the same migrations.
- **Import failures must be diagnosed, not reported as "missing"** —
  gpt-4o-mini "fixed" semver's relative import by inventing a
  nonexistent module; the resolver now surfaces the actual import error
  in the hint (v0.10.0).
- **Migration difficulty splits into "translate" vs "restructure."**
  Modules whose source is self-contained (roman, pytimeparse) are
  one-shot for a mini model. Modules that are thin wrappers around
  internal classes (semver's `_deprecated.py`) need a stronger model —
  gpt-4o climbed 0 → 159 → 246 → 275 of 277.
- **The last two semver divergences are the punchline**: gpt-4o would
  not accept that `bump_prerelease("1.2.3-alpha")` is a no-op — it kept
  "fixing" it — the *same* mistake the human clean-room rewrite made.
  The model and the human failed identically; the recording caught both.
- **Stall detection paid for itself in real dollars** every time a model
  stopped progressing.

## Program totals (all cohorts + dateutil case study)

**11 real libraries verified to 100% by hint-guided rewrites (12,952
recorded behaviors, 11/11 wrong on first pass, 169 divergences), plus a
live cohort: 3 fully-unattended LLM migrations reaching 100%
(10,162 behaviors) and one hard case honestly at 275/277.**
