# complaints-intelligence

The **agentic report generation loop** that turns a week of complaint metrics
into a written, fact-grounded and fully cited compliance report.

**All data here is synthetic.** Nothing resembles any real firm's systems,
taxonomies or complaints.

---

## Where this fits

This package is one stage of a weekly pipeline.

**What arrives.** Complaints land from four channels — regulator referrals, a
mobile app form, branch CRM notes and call centre audio — and are mapped into a
single envelope, redacted, screened for injection, and quarantined rather than
dropped if any of that fails. Each complaint is then enriched with a category,
sentiment, evidence spans and a confidence score, and routed: records the
classifier is confident about go to closed-set attribution against a versioned
taxonomy; the rest fall into a residual pool that is clustered into *candidate
themes*. A deterministic metrics layer aggregates all of it and emits **facts** —
typed values with provenance — plus a **metrics brief** ranking the week's
significant movements. That brief and the fact store are the entire view of the
week this package gets, which is what makes a run bounded, comparable between
weeks and reproducible.

**What leaves.** The fact store is the trust boundary: everything below it is
deterministic and reproducible, everything above it generative. This package sits
directly above that seam. It emits a report object — versioned, immutable, with
every claim referencing fact IDs and every quotation referencing a complaint ID
and character offsets — which goes downstream to a named human reviewer for
sign-off before anything is published.

| Stage | Status here |
|---|---|
| Sources, transcription | Assumed upstream |
| Ingest: channel adapters, PII redaction, injection screen, quarantine | Assumed upstream |
| Enrichment: category, sentiment, evidence spans, confidence | Assumed upstream |
| Routing: attribution track, discovery track → candidate themes | Assumed upstream |
| Metrics and fact store → facts + metrics brief | Assumed upstream — its output is committed as [`fixtures/`](src/complaints_intelligence/fixtures/) |
| **Agentic loop: investigate → adjudicate → remediate → critic ⇄ revise → render** | **This package** |
| Sign-off, dashboard, committee pack, email digest | Assumed downstream |

The loop itself is read-only, budgeted in steps and revisions, has no network
egress and needs no credentials — which is why the quickstart below runs offline
in seconds.

---

## Quickstart

Requires [uv](https://docs.astral.sh/uv/). No API key, no network, no cloud
account.

```bash
uv sync
uv run ci run       # writes out/report.md
```

This runs the agent against committed recordings of a real model, verifies the
draft, and renders the report. To call the live model instead (needs
`GEMINI_API_KEY`): `uv sync --all-extras && uv run ci run --live`.

### Reading the output without running anything

**[`out/report.md`](out/report.md) is committed.** It is the actual output of
the command above — real Gemini prose, with every figure substituted from the
fact store and every quotation sliced from stored complaint text. Start there
if you would rather read the result than execute the pipeline.

[`out/report.json`](out/report.json) is committed alongside it. That object is
the record; the Markdown is a projection of it, which is what allows a
published report to be regenerated exactly from the store plus the pinned
versions in §6 of the report.

Both are regenerated in place by `ci run`, so the only line that changes
between identical runs is the generation timestamp.

---

## The central claim

The report contains two kinds of content with very different reliability needs,
so they are produced by different machinery.

**Numbers** are computed by ordinary code before any model is invoked, stored as
facts with provenance, and referenced by ID. The model chooses *which* stored
figure to cite and writes the prose around it; values are substituted at render
time.

**Judgement** — what is emerging, what to do about it — is where the model
works, always against retrieved evidence, always cited to specific complaints by
ID and character offset. Quotations are sliced out of the store at render time,
so the model never handles the words it quotes.

Numeric hallucination and misquotation are therefore **structurally impossible**
rather than detected afterwards.

---

## What the demo demonstrates

The fixture in [`fixtures/`](src/complaints_intelligence/fixtures/) is
hand-written and small enough to read. It is built around planted signals, so
the report has something true to say and the tests have a ground truth.

| Planted | Exercises |
|---|---|
| `payments_failed` 48 → 131, concentrated in the app, tone worsens | The lead driver, with a real sentiment shift alongside it |
| `direct_debit_errors` 24 → 45, tone also moves | A second sentiment story that is not an echo of the payments spike |
| `overdraft_fees` 31 → 58, arriving via the ombudsman | A rise reaching the firm through the regulator rather than its own channels |
| `branch_closure` 54 → 29 | A genuine fall — "up" is not the only direction expressible |
| `statement_errors` 19 → 24 | Clears a naive threshold, **fails** the significance test. Reported as tested and not significant, and the first thing the budget drops |
| `CT-007` round-up double-debits | A real emerging theme: coherent in meaning, persistent, spread across channels |
| `CT-012` duplicated branch notes | **The decoy.** Large and superficially compelling, but one CRM template repeated. The agent must reject it |
| 3 injection payloads, 1 residual PII leak | Reach retrieval, are fenced, and cannot alter a figure or a quotation |

Five genuine movements against an investigation budget of five, so the budget
binds exactly: the category the agent declines to investigate is the one that
failed its significance test, not whichever happened to rank last.

The most instructive result is that **cluster coherence points the wrong way**.
Measured from the vectors, the duplicated artefact scores **0.95** and the
genuine theme **0.12**, because near-identical text is trivially coherent.
Anything adjudicating on coherence alone would accept the decoy and reject the
real signal — which is why the brief also carries persistence, channel spread
and duplicate ratio.

---

## Layout

| Path | What |
|---|---|
| [`fixtures/`](src/complaints_intelligence/fixtures/) | The hand-written data, and the taxonomy it is classified against |
| [`inputs.py`](src/complaints_intelligence/inputs.py) · [`outputs.py`](src/complaints_intelligence/outputs.py) | Typed schemas for every object crossing a stage boundary |
| [`store.py`](src/complaints_intelligence/store.py) | Read-only data access and similarity search — the RAG substrate |
| [`brief.py`](src/complaints_intelligence/brief.py) | Assembles the agent's view of the week from the fact store |
| [`agent/`](src/complaints_intelligence/agent/) | The bounded graph, its tools, budgets and untrusted-text choke point |
| [`critic.py`](src/complaints_intelligence/critic.py) | Programmatic verification. No model involved |
| [`render.py`](src/complaints_intelligence/render.py) | Deterministic templating; fact and citation resolution |
| [`prompts/v1/`](src/complaints_intelligence/prompts/v1/) | Versioned prompt files. A prompt change is a code change |
| [`llm/`](src/complaints_intelligence/llm/) | The `LLMClient` seam: offline replay, and the live Gemini client |

### Where to look first

- [`agent/graph.py`](src/complaints_intelligence/agent/graph.py) — the graph: investigate, adjudicate, remediate, then critic ⇄ revise
- [`agent/untrusted.py`](src/complaints_intelligence/agent/untrusted.py) — the single point where customer text enters a prompt
- [`critic.py`](src/complaints_intelligence/critic.py) — what must hold before anything renders

---

## Development

```bash
uv run pytest        # 50 tests
uv run mypy          # --strict over src and tests
uv run ruff check
```

Most of the assurance lives in
[`tests/test_critic.py`](tests/test_critic.py) and
[`tests/test_injection.py`](tests/test_injection.py). Between them they prove
that each verification check fires when provoked through the full graph, that
the revise loop terminates when repair is impossible, and that injection
payloads are fenced in the prompts *actually sent* to the model.

---

## Glossary

Terms used consistently across the code and the report.

**Complaint envelope.** The canonical schema every channel is mapped into.
Channel-specific handling is confined to the adapters upstream; `channel` is
retained as a feature, not discarded.

**Taxonomy version.** The complaint taxonomy is versioned data, never mutated in
place. Every enriched record is stamped with the version used, so trend series
stay comparable across structural changes.

**Confidence and novelty.** Confidence is how certain the classifier is
*between known categories*; novelty is how far a record sits from the region of
embedding space the known categories occupy. They are not interchangeable — a
genuinely new complaint type is frequently assigned to the nearest existing
category *with high confidence*, so detecting it needs the un-normalised
measure.

**Abstention.** A deliberate refusal to assign a category rather than a forced
guess. Abstained complaints still count in totals but do not contribute to
per-category trends, so hard cases are never silently dropped from the
denominator.

**Residual pool.** The abstained records; the input to theme discovery.

**Candidate theme (`CT-nnn`).** A persistent cluster in the residual pool, given
a stable identity so its growth can be measured across weeks. It reaches the
agent as narrative to adjudicate, never as a row in the trend table, because it
has no comparable history.

**Fact.** A typed value with provenance, emitted by the deterministic metrics
layer and identified by a fact ID. The report references the ID; the value is
substituted at render time, which is what stops a model fabricating a figure.

**Fact store.** The immutable, run-stamped collection of facts for one week. The
trust boundary of the system.

**Run.** One weekly execution, identified by a run ID. Facts are written once per
run and never mutated — a re-projection produces a new run, not an edit, so a
published report keeps reconciling with the store it cites.

**Metrics brief.** The compact object the metrics layer emits: flagged
categories, drift signals, candidate themes, health indicators and headline
aggregates, all as fact IDs, ranked and truncated. It is the agent's entire view
of the week.

**Finding.** A drafted section of the report — a headline, claims, and citations.

**Claim.** One assertion within a finding, referencing the fact IDs it depends on
and carrying its own citations.

**Citation.** A pointer to source text: a complaint ID plus character offsets.
The renderer slices the quoted span out of the store, so the model never handles
the words it quotes.

**Exemplar.** A complaint retrieved to illustrate what customers in a flagged
category are actually describing.

**Precedent.** A closed complaint with a resolution note recording what was
actually done about it. Retrieval is complaint-to-complaint — matching the new
description against the text of closed cases, then joining to their notes — which
keeps the comparison symmetric.

**Critic.** Programmatic verification of a draft before anything renders: facts
resolve, no figure is typed in prose, every claim carries at least two citations,
every offset returns the text it claims, no personal data survives. No model is
involved.

**Revise loop.** The bounded repair path. A failing draft is re-prompted with the
specific checks that failed, against the same retrieved evidence, at most twice.

**Untrusted text.** Complaint text is customer-supplied and adversarial-capable.
It is data, never instruction, at every point it enters a prompt — including text
returned by retrieval — and all of it passes through one fencing function that
makes the boundary explicit and preserves length, so citation offsets cannot
shift.

Significance testing, effect sizing and the ranking of movements happen upstream
in the metrics layer. This package consumes their output and computes no
statistic of its own.

---

## Out of scope

Ingestion, transcription, PII redaction, injection screening, classification,
taxonomy management, statistical computation of metrics, dashboards and
infrastructure are assumed to have run upstream or to run downstream. The fixture
is written *as if* it had passed through all of them.
