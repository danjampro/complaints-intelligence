# complaints-intelligence

Part 3 of a technical interview exercise: the **agentic report generation loop**
that turns a week of complaint metrics into a written, fact-grounded and fully
cited compliance report.

| Part | Document |
|---|---|
| 1 — Problem statement | [`01-problem-statement.md`](docs/design/01-problem-statement.md) |
| 2 — Solution architecture | [`02-architecture.md`](docs/design/02-architecture.md) |
| 3 — Code | this package, implementing **section 8** of the architecture |
| 4 — Evaluation | [`04-evaluation.md`](docs/design/04-evaluation.md) |

Design decisions, including the alternatives rejected, are in the
[*Key decisions*](docs/design/02-architecture.md#key-decisions) table.

**All data here is synthetic.** Nothing resembles any real firm's systems,
taxonomies or complaints.

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

- [`agent/graph.py`](src/complaints_intelligence/agent/graph.py) — the graph, which reads as the diagram in §8
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

## Out of scope

Ingestion, transcription, PII redaction, injection screening, classification,
taxonomy management, statistical computation of metrics, dashboards and
infrastructure are assumed to have happened upstream — see
[`02-architecture.md`](docs/design/02-architecture.md) for how each is designed.
The fixture is written *as if* it had passed through all of them.
