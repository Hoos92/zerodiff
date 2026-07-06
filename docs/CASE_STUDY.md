# Case study: rewriting `dateutil.easter` with NoDrift as the gate

`dateutil.easter.easter()` is a classic piece of legacy code: 74 lines of
unexplained magic numbers implementing three Easter-computation methods
(Julian, Orthodox, Western), shipped in one of the most-downloaded Python
packages. Exactly the kind of function an AI agent gets asked to
"modernize" — and exactly the kind where a silent behavioral change would go
unnoticed until someone's calendar is wrong.

Everything below is reproducible from `examples/migration_dateutil/`.

## Step 1 — record ground truth (zero source edits)

```
nodrift record --include dateutil.easter -o traces -- python run_scenarios.py
```

The scenario driver sweeps years 1583–4099 for all three methods, hits
century boundaries (1600, 1700, 1900, 2100, 2400…), the default-argument
path, and the error paths. Neither `dateutil` nor the driver contains a
single line of nodrift code — the `--include` import hook instruments the
module as it loads.

**Result: 1,163 calls recorded (1,145 unique behaviors), including the
4 recorded exception behaviors.**

## Step 2 — a clean-room modern rewrite

`easter_modern.py` was written from the algorithm literature (Meeus), not
from dateutil's source: three named algorithms instead of one arithmetic
blob, the Julian→Gregorian conversion done with a `timedelta` instead of
being folded into the magic numbers, and readable variable names.

## Step 3 — replay: the gate catches what tests would miss

```
nodrift replay -t traces
```

First pass: **1,141 of 1,145 matched, 4 diverged, exit code 1.**

The 4 divergences were all the same class — and it's the sneaky class:

> `exception_mismatch` at `output.exception.message`, input `(2024, 0)`
> expected: `invalid method` — actual: `method must be 1, 2, or 3`
> *hint: same exception type (ValueError) but a different message —
> callers matching on the message will break; restore the original wording.*

The rewrite's math was correct across four centuries of dates. What
diverged was the error message — a change no type checker flags, virtually
no test suite asserts, and any human reviewer would wave through. It's also
precisely the kind of "improvement" AI rewrites make unprompted.

## Step 4 — apply the hint, replay again

One-line fix (restore the original wording), then:

```
nodrift replay -t traces
```

**Second pass: 1,145 of 1,145 replayed behaviors matched. Exit code 0.**

## What this shows

- **The recorded original is ground truth.** No one needed to understand
  the magic numbers to verify the rewrite — the behavior record did it.
- **The feedback loop converges fast.** The divergence hint named the
  input, the difference, and the fix; one iteration reached a full match.
- **Honest claims survive.** The report says "matched 1,145 of 1,145
  recorded behaviors" — equivalence over the recorded domain (1583–4099,
  methods 1–3, these error paths), not a proof about all possible inputs.

Total wall-clock time for the whole exercise, including recording ~1,100
calls and two replays: under a minute.
