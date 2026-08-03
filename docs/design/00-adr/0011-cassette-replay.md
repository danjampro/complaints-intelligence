# ADR-0011 — Cassette replay is the default LLM mode

**Status:** Accepted

## Context

Two requirements pull against each other.

A reviewer must be able to run the full demo **offline, with no credentials,
in a couple of minutes** (invariant 5). A submission that only works on the
author's machine, or that needs an API key the reviewer does not have, fails
as a deliverable regardless of how good the code is.

But the deliverable is about *language model* engineering. A demo where the
model is a hand-written stub demonstrates the plumbing and nothing else — the
agentic loop looks impressive and proves nothing, because the interesting
question is whether a real model, shown fenced untrusted text and told not to
type numbers, actually complies.

## Decision

The `LLMClient` protocol has three implementations:

| Mode | Behaviour |
|---|---|
| `replay` (**default**) | Reads committed JSON cassettes. Offline, deterministic, no credentials. |
| `live` | Calls Gemini. Needs `GEMINI_API_KEY` and the `live` extra. |
| `record` | Calls Gemini and writes cassettes back. |

Cassettes are **genuine recordings** of exchanges with the real model, made
during development and committed. Each stores the full rendered prompt
alongside the response, so a reviewer can read exactly what the model was
asked — including the fenced untrusted block with its injection payloads — and
verify for themselves that the defences were exercised.

A cassette miss is a **hard error** naming the missing key and the command to
re-record.

## Consequences

The reviewer sees real model reasoning without needing a key. Runs are
byte-deterministic, which is what makes the golden test meaningful.

The cassette key is a hash of the rendered prompt, so any change to a prompt
template, the retrieved evidence, or the brief invalidates the recordings and
produces a miss. That is deliberate and it is the main cost: cassettes must be
re-recorded whenever the inputs change. The alternative — a fuzzy match that
kept replaying after the inputs moved — would make the recordings a fiction,
and the whole value of this approach is that they are not.

**A stub is still needed for tests.** `tests/fakes.ScriptedLLM` exists so the
graph, budgets, critic and renderer can be tested without credentials, and so
specific failure modes can be provoked on demand. It is never used for the
demo, and the distinction matters: the tests exercise machinery, the cassettes
demonstrate behaviour.

## Alternatives rejected

**Live-only.** Simplest, most honest. Rejected: breaks invariant 5 outright.

**Stub-only.** No API surface at all. Rejected: the demo would show an agentic
loop with nothing agentic happening inside it, and no evidence that a real
model respects the constraints the prompts impose.

**Fall back from replay to live on a miss.** Rejected: the demo would work for
whoever has a key and fail for everyone else, and the failure would look like
a bug rather than a missing recording.

**Fall back from replay to a stub on a miss.** Rejected outright. A stub
response that a reviewer believes is a recording is a fabricated result.

## What would change our mind

If prompts churned frequently enough that re-recording became a bottleneck,
the answer is a smaller set of cassettes covering representative cases plus a
scripted client for the rest — with the boundary between "recorded" and
"simulated" stated in the report itself, never blurred.
