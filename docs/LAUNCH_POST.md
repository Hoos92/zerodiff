# I recorded 12,952 behaviors of 11 real Python libraries. Every AI rewrite was wrong.

*(Draft launch post — publish alongside the repo. Everything below is
reproducible from `examples/`.)*

AI agents are very good at rewriting code and very bad at proving the
rewrite behaves the same. I've been building a tool that closes that gap,
and the experiment that convinced me it matters is simple enough to fit in
a post.

## The experiment

Take eleven real, widely-used Python libraries. Record what they *actually
do* — thousands of real calls, captured at function boundaries with zero
source edits. Then write a careful, modern, clean-room rewrite of each, the
way a migration agent would. Then replay every recorded call against the
rewrite and diff the behavior.

| library | recorded behaviors | first-pass result |
|---|---|---|
| `roman` | 10,083 | 10,022 matched, **61 diverged** |
| `dateutil.easter` | 1,145 | 1,141 matched, **4 diverged** |
| `inflection` | 382 | 366 matched, **16 diverged** |
| `semver` | 277 | 275 matched, **2 diverged** |
| `python-stdnum` | 269 | 231 matched, **38 diverged** |
| `python-slugify` | 202 | 185 matched, **17 diverged** |
| `humanize` | 201 | 192 matched, **9 diverged** |
| `num2words` | 187 | 182 matched, **5 diverged** |
| `humanfriendly` | 113 | 105 matched, **8 diverged** |
| `word2number` | 51 | 44 matched, **7 diverged** |
| `pytimeparse` | 42 | 40 matched, **2 diverged** |

**Eleven out of eleven rewrites were wrong** — 169 behavioral divergences in
all. Not one was a syntax error, a type error, or anything a linter or
typical test suite would flag.

## What "wrong" looked like

Almost every divergence was the rewrite being *more correct than the
original* — which, for a drop-in replacement, is precisely the problem:

- The real `roman` returns `"N"` for `toRoman(0)` — the medieval *nulla*.
  My rewrite "sensibly" rejected zero. Every caller relying on `"N"` would
  break.
- The real `inflection` singularizes `"police"` to `"polouse"` — a
  mouse/louse regex firing on anything ending in "lice". A bug, plainly.
  Also a bug that's been shipping since 2012, which makes it *behavior*.
- `inflection.camelize("", uppercase_first_letter=False)` doesn't return
  anything — it crashes with `IndexError`. The recording captured the
  crash; the replay enforced that my rewrite crash identically.
- `word2number.word_to_num("one billion two million")` returns
  **1,003,000,002** — the original double-counts everything after
  "billion". It's a real arithmetic bug, shipping for years; a faithful
  replacement has to reproduce it, because somebody downstream has already
  compensated for it.
- The real `humanize.intcomma("abc")` returns `"abc"`. My rewrite
  helpfully raised `ValueError`. Helpful is a breaking change.
- The textbook IBAN `BE68539007547034` — the one half the internet uses as
  the canonical valid example — is *rejected* by `python-stdnum`'s Belgian
  bank-registry lookup. And stdnum checks the mod-97 checksum *before*
  length, so a truncated IBAN raises `InvalidChecksum`, not
  `InvalidLength`. Exception ordering is a contract too.
- `dateutil.easter`'s math survived my rewrite perfectly across four
  centuries — what diverged was the text of an error message. The kind of
  thing a human reviewer waves through without a second look.

None of this is knowable from the source's intent, the docs, or the test
suites. The only place this knowledge exists is in what the code actually
does — so that's the thing to record.

## The tool

ZeroDiff is an open-source (MIT, zero-dependency) harness with a three-verb
workflow:

```
zerodiff record --include yourmodule -o traces -- python drive_it.py
zerodiff replay -t traces --map "yourmodule:yourmodule_v2"
zerodiff report
```

Record real input→output behavior (exceptions included — they're behavior)
at function boundaries, with no edits to the code being recorded. Replay
those inputs against the rewrite — in an isolated worker if you don't trust
it; crashes and hangs become findings rather than harness failures. Get
every divergence with the exact input that exposes it and a fix hint
written for a coding agent:

> for input (2024, 0), the original raised ValueError('invalid method') but
> the rewrite raised ValueError('method must be 1, 2, or 3') — callers
> matching on the message will break; restore the original wording.

Feed that back to any agent and the loop converges fast: all eleven
libraries above reached **100% of recorded behaviors matching in at most
three passes**, using nothing but the report hints. There's a built-in loop
(`zerodiff loop --agent "claude -p ..."`), an MCP server so agents can call
verification natively, a GitHub Action, and a Claude Code hook that blocks
any edit which breaks recorded behavior.

## The obvious objection

You should be suspicious of that table. I commissioned those rewrites *and*
I built the tool that catches them. If I wanted a good demo, I could simply
have written bad code. So don't take the hand-written cohort as the
evidence — take this instead.

I handed the same job to a real LLM with no human in the loop:
`zerodiff migrate --llm openai:...`, a live funded key, the model writing
every line, the loop driving itself off the report hints. I didn't
intervene, and I couldn't have rigged the outcome:

- `roman` (10,083 behaviors) → **10,083/10,083**, two agent calls.
- `pytimeparse` (42) → **42/42**, a single call.
- a shipping demo (37) → **37/37**, a single call.

Note what those are: **successes**. The model did the migration, unattended,
and the harness confirmed it. A tool built to make AI look bad would not
report that.

Then the hard cohort, same setup, GPT-4o:

| target | why it's brutal | best unattended result |
|---|---|---|
| `chevron` (Mustache engine) | recording captures the engine's own recursive internal calls | 23/77, then it **regressed to 0** chasing hints |
| `validators` | invalid inputs return a *falsy error object* instead of raising | oscillated 14 ↔ 23 forever |
| `python-dotenv` | quoting and interpolation quirks | climbed to 12/19, stalled |

**Every one of those wrong rewrites ran fine and would have passed a
review.** 148 behavioral divergences that only recorded reality caught.

That's the finding I'd actually defend: not "AI writes bad code," but that
the frontier is *measurable*, sits in a specific place, and moves depending
on whether a module is self-contained or a wrapper around internal state.
When the agent can do the job, verification proves it. When it can't, the
gate stays red and nothing broken ships.

## What it doesn't claim

ZeroDiff proves equivalence over *recorded* behaviors — never all possible
behaviors. Reports say "matched 1,145 of 1,145 recorded behaviors" and list
coverage per boundary; the word "identical" doesn't appear. Values it can't
fully serialize are compared by fingerprint and flagged as weak, never
silently counted as matches. Coverage is bounded by the traffic you record.
That honesty is load-bearing: a verification tool that overstates its
guarantees is worse than none.

## Why now

Every team is about to have agents rewriting code faster than humans can
review it. Generation is solved; trust is not. The original's recorded
behavior is the one ground truth that requires no one to understand the
code — which matters, because for most legacy code, nobody does.

Repo: https://github.com/Hoos92/zerodiff — the experiments are in
`examples/`, each reproducible in under a minute.
