# I recorded 11,811 behaviors of real Python libraries. Every AI rewrite was wrong.

*(Draft launch post — publish alongside the repo. Everything below is
reproducible from `examples/`.)*

AI agents are very good at rewriting code and very bad at proving the
rewrite behaves the same. I've been building a tool that closes that gap,
and the experiment that convinced me it matters is simple enough to fit in
a post.

## The experiment

Take four real, widely-used Python libraries. Record what they *actually
do* — thousands of real calls, captured at function boundaries with zero
source edits. Then write a careful, modern, clean-room rewrite of each, the
way a migration agent would. Then replay every recorded call against the
rewrite and diff the behavior.

| library | recorded behaviors | first-pass result |
|---|---|---|
| `dateutil.easter` | 1,145 | 1,141 matched, **4 diverged** |
| `roman` | 10,083 | 10,022 matched, **61 diverged** |
| `inflection` | 382 | 366 matched, **16 diverged** |
| `humanize` | 201 | 192 matched, **9 diverged** |

**Four out of four rewrites were wrong.** Not one divergence was a syntax
error, a type error, or anything a linter or typical test suite would flag.

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
- The real `humanize.intcomma("abc")` returns `"abc"`. My rewrite
  helpfully raised `ValueError`. Helpful is a breaking change.
- `dateutil.easter`'s math survived my rewrite perfectly across four
  centuries — what diverged was the text of an error message. The kind of
  thing a human reviewer waves through without a second look.

None of this is knowable from the source's intent, the docs, or the test
suites. The only place this knowledge exists is in what the code actually
does — so that's the thing to record.

## The tool

NoDrift is an open-source (MIT, zero-dependency) harness with a three-verb
workflow:

```
nodrift record --include yourmodule -o traces -- python drive_it.py
nodrift replay -t traces --map "yourmodule:yourmodule_v2"
nodrift report
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

Feed that back to any agent and the loop converges fast: all four libraries
above reached **100% of recorded behaviors matching within three passes**,
using nothing but the report hints. There's a built-in loop
(`nodrift loop --agent "claude -p ..."`), an MCP server so agents can call
verification natively, a GitHub Action, and a Claude Code hook that blocks
any edit which breaks recorded behavior.

## What it doesn't claim

NoDrift proves equivalence over *recorded* behaviors — never all possible
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

Repo: https://github.com/Hoos92/nodrift — the experiments are in
`examples/`, each reproducible in under a minute.
