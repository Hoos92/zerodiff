# I let LLMs migrate six Python libraries unattended. Here is exactly where they broke — and what "passing" actually means.

Everyone has an opinion about whether AI can rewrite production code. Very
few people have numbers, because "did the rewrite work?" is hard to answer
— the tests pass, the code reads fine, and the bug shows up in a customer's
account three weeks later.

So I built a way to answer it mechanically, pointed it at real libraries
from PyPI, and let a model do the work with no human in the loop. This is
what came back.

## The method, briefly

For each library: record what the real thing actually does — every call at
every public function boundary, inputs, return values, exceptions, and
in-place argument mutations, captured from a driver script exercising it.
Then hand a model an empty module and the original's source, let it write a
replacement, and replay every recorded call against the replacement.

A behavior matches or it doesn't. There is no judgment call, no model
scoring another model, no "looks correct to me." The verdict is
`matched N of N`, and any divergence comes with the exact input that
exposes it.

The model gets the divergence report back and tries again, in a loop, until
everything matches or it stops making progress. Nobody intervenes.

Two things worth stating before the numbers, because they bound what this
proves:

- **Equivalence is over recorded behaviors only** — the inputs my driver
  actually exercised, not all possible inputs. Coverage is a property of
  the driver, and I report it per boundary rather than rounding it up to
  "correct."
- **I wrote the drivers.** I did not write the rewrites; the model did, and
  I could not see them until the loop finished.

## First, the part that surprised me: it often just works

I expected this to be a post about AI failing. It isn't, and the successes
are the reason I trust the failures.

| target | model | result | agent calls |
|---|---|---|---|
| `pytimeparse` (42 behaviors) | gpt-4o-mini | **42 / 42** | 1 |
| `roman` (10,083 behaviors) | gpt-4o-mini | **10,083 / 10,083** | 2 |
| a shipping-cost module (37) | gpt-4o-mini | **37 / 37** | 1 |

Ten thousand recorded behaviors of `roman`, reproduced exactly, by the
*cheap* model, in two passes, unattended. That includes the genuinely
strange ones — `toRoman(0)` returns `"N"`, the medieval *nulla*, and the
range error says `0..4999` rather than `1..4999`.

If your intuition is "LLMs can't be trusted to migrate code," that result
should move it. Mine moved.

## Then it hits a wall, and the wall has a shape

Three targets I picked specifically because I thought they'd be hard. Same
setup, GPT-4o this time, six iterations maximum:

| target | what makes it brutal | behaviors | best unattended result |
|---|---|---|---|
| `chevron` (Mustache engine) | recursive rendering — the recording captures the engine's *own internal recursive calls*, so a rewrite has to reproduce the recursion contract, not just the output | 77 | **23 / 77**, then it *regressed to 0* |
| `validators` | regex-dense, plus a contract where invalid input returns a **falsy `ValidationError` object** rather than raising | 72 | **oscillated 14 ↔ 23 forever** |
| `python-dotenv` | quoting and interpolation quirks, file-based fixtures | 19 | **12 / 19**, stalled |

The `chevron` run is the one I keep thinking about. It climbed to 23 of 77,
then followed its own fix hints *downward* to zero. Not a crash — a
confident, plausible, steadily-worsening rewrite.

`validators` is the funnier failure. It found two local optima and swung
between them, 14 → 23 → 14 → 23, indefinitely. My stall detection only
caught *consecutive identical* failures at the time, so it happily burned
iterations on a cycle. I now fingerprint recent problem sets and stop on
cycles, which is a guardrail that exists purely because a model found the
hole.

**Every one of those wrong rewrites ran fine.** They imported, executed,
returned plausible values, and would have passed code review. 148
behavioral divergences across the three, none of which a linter, a type
checker, or a reasonable human reviewer would have caught.

## The actual finding: difficulty isn't about size

The thing I did not expect is that difficulty barely tracks with how much
code there is. `roman` is 10,083 behaviors and fell in two passes.
`python-dotenv` is 19 behaviors and never got there.

What predicts difficulty is **whether the module is self-contained**.

- **Translate:** the logic is right there in the source. `roman`,
  `pytimeparse`. A cheap model one-shots these.
- **Restructure:** the module is a thin surface over internal state or
  classes elsewhere. `semver`'s deprecation wrapper, `chevron`'s recursion.
  Here gpt-4o-mini stalled at **0 of 277** — it kept importing the
  original's internal class rather than reimplementing it — while gpt-4o
  climbed 0 → 159 → 246 → **275 of 277** over eight calls.

That's a useful heuristic if you're deciding what to hand to an agent
today: look at whether the thing you're replacing can be understood without
reading the rest of the package.

## The best result in the whole set is a failure

`semver`, gpt-4o, 275 of 277. It never closed the last two.

Both were `bump_prerelease`. The real function silently does *nothing* when
the prerelease has no digits in it — `bump_prerelease("1.2.3-alpha")`
returns `1.2.3-alpha`, unchanged — and it bumps the *rightmost embedded*
number, so `alpha.7.x` becomes `alpha.8.x`. No docstring mentions either.

The model would not accept it. It kept "fixing" the no-op, because a
version bump that doesn't bump is obviously a bug.

Here's the part I like: **a careful hand-written rewrite of `semver`, done
before the model ever saw it, made the identical mistake.** Same function,
same assumption, same two behaviors. Human and model failed in exactly the
same place, for exactly the same reason — both believed the code did what
it was supposed to do rather than what it does.

Neither of us would have caught it by reading. The recording caught both.

## Update: I re-ran this against the current frontier

The runs above used gpt-4o, which is now two generations old. So I re-ran
them unattended against `gpt-5.6-luna` on the same recorded traces.

`pytimeparse`: 42/42, one call, same as before. `semver`: **277 of 277 in two
calls** — including both `bump_prerelease` quirks that gpt-4o never closed in
eight, and that I got wrong by hand. The frontier moved, and it moved exactly
where you'd expect: the "restructure" cases got easier.

Then I checked the rewrite against inputs the recording didn't cover, and it
was wrong.

Upstream's `bump_prerelease` increments the **rightmost** number in the
prerelease. Luna's incremented the **first**. On `1.2.3-0.3.7` upstream gives
`1.2.3-0.3.8`; the rewrite gave `1.2.3-1.3.7`. It passed 277 of 277 because
only six inputs ever reached that function and not one had two numbers in the
prerelease — over that traffic, the two rules are indistinguishable.

The verdict wasn't wrong. The coverage was thin, and the report said so all
along: *matched 277 of 277 recorded behaviors*, not *correct*.

So I added one input to the driver — `"1.2.3-0.3.7"` — re-recorded, and ran
the identical pipeline again:

```
iteration 1:   0 of 278 matched
iteration 2: 265 of 278 matched
iteration 3: 278 of 278 matched
```

The new implementation walks the parts in reverse and takes the rightmost
numeric field. And the fix **generalized** — `1.2.3-a.1.b.2.c.3` and
`1.2.3-9.9`, never recorded at any point, now match upstream too. It learned
the rule rather than the example.

That sequence is the honest shape of this whole idea. A passing report is a
claim about coverage, not about correctness. The remedy is more recorded
traffic. And the remedy is cheap — one line in a driver, thirty seconds, and
a class of bug closes.

## The result I did not expect

I ran the same `semver` job through the other two frontier variants,
`gpt-5.6-terra` and `gpt-5.6-sol`. Both also scored **277 of 277**, each in a
single call.

Three rewrites. Three identical reports. So I fuzzed all three against
upstream across 305 generated prerelease inputs, none of which were among the
277 recorded:

| model | recorded score | wrong on 305 unrecorded inputs |
|---|---|---|
| `gpt-5.6-luna` | 277 / 277 | **171** |
| `gpt-5.6-terra` | 277 / 277 | **0** |
| `gpt-5.6-sol` | 277 / 277 | **0** |

One of these rewrites is wrong on **56% of a wider input space**. The other two
are flawless. **The verification could not tell them apart**, because over the
recorded traffic the two implementations are genuinely indistinguishable — no
recorded prerelease had more than one number in it, so "increment the first"
and "increment the rightmost" produce identical output on every single
recorded case.

Same traces, same prompts, same harness — and one of three siblings quietly
generalizes wrong.

I want to be careful about what this does and doesn't show. It is one function
in one library, and it is not a ranking of models. What it shows is sharper
than that:

**A passing report ranks nothing.** It says the rewrite reproduces the
behavior you recorded. If you care about behavior you didn't record — and you
do — then the recording is the thing to improve, not the score.

Which is the entire argument for recording real traffic rather than writing
test cases from memory. The green check was never the point. The coverage
behind it is.


## What I take from this

Generation is largely solved and verification isn't. The interesting
question stopped being "can a model write the code" — often, yes,
astonishingly well — and became "how would you know." For a legacy module
whose behavior nobody remembers and whose tests encode what someone once
*believed*, the only ground truth left is what the code actually does when
you run it.

That's recordable. It turns out to be recordable cheaply.

And the frontier is measurable rather than a matter of vibes: self-contained
logic migrates today, at low cost, with a small model. Anything that is a
wrapper around state elsewhere does not, yet — and when it fails, it fails
*plausibly*, which is the dangerous part.

## The tool

The harness is called ZeroDiff — `pip install zerodiff`, MIT, zero runtime
dependencies. It records, replays, and reports; it contains no model, and
the verdict is deterministic. Whether an agent writes the rewrite or you do
is beside the point to it.

Everything above is reproducible from `examples/` in the repo. If you try
it on something and it's wrong, I'd genuinely like to know — a verification
tool that overstates its guarantees is worse than none.

https://github.com/Hoos92/zerodiff
