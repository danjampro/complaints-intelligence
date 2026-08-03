# complaints-intelligence

Part 3 of a technical interview exercise: the **agentic report generation
loop** that turns a week of complaint metrics into a written, fact-grounded and
fully cited compliance report.

The full solution design is in [`docs/design/`](docs/design/):

| Part | Document |
|---|---|
| 1 — Problem statement | [`01-problem-statement.md`](docs/design/01-problem-statement.md) |
| 2 — Solution architecture | [`02-architecture.md`](docs/design/02-architecture.md) |
| 3 — Code | this package, implementing **section 8** of the architecture |
| 4 — Evaluation | [`04-evaluation.md`](docs/design/04-evaluation.md) |

Decisions, including the alternatives rejected, are recorded as ADRs in
[`docs/design/00-adr/`](docs/design/00-adr/).

**All data here is synthetic.** Nothing resembles any real firm's systems,
taxonomies or complaints.

---

## Quickstart

Requires [uv](https://docs.astral.sh/uv/). No API key, no network, no cloud
account.

```bash
uv sync
uv run ci demo
```

This generates the corpus, derives the fact store, runs the agent against
committed recordings of a real model, verifies the draft, and writes
`out/report.md`.

To run against the live model instead (needs `GEMINI_API_KEY`):

```bash
uv sync --all-extras
uv run ci run --live
```

### Commands

| Command | Does |
|---|---|
| `ci generate-data --seed 42` | Write the synthetic corpus to `data/*.parquet` |
| `ci build-facts` | Derive the fact store and the metrics brief |
| `ci run [--live\|--record]` | Run the agent and render the report |
| `ci demo` | All of the above, offline |

---

## The central claim

The report contains two kinds of content with very different reliability
needs, so they are produced by different machinery.

**Numbers** are computed by ordinary code before any model is invoked, stored
as facts with provenance, and referenced by ID. The model chooses *which*
stored figure to cite and writes prose around it; values are substituted at
render time.

**Judgement** — what is emerging, what to do about it — is where the model
works, always against retrieved evidence, always cited to specific complaints
by ID and character offset. Quotations are sliced out of the store at render
time, so the model never handles the words it quotes.

Numeric hallucination and misquotation are therefore **structurally
impossible** rather than detected afterwards. See
[ADR-0007](docs/design/00-adr/0007-facts-before-generation.md).

---

## What the demo actually demonstrates

The synthetic week is built around planted signals, declared in
[`synth/signals.py`](src/complaints_intelligence/synth/signals.py), so the
report has something true to say and the tests have a ground truth:

| Signal | Exercises |
|---|---|
| `payments_failed` 48 → 131, concentrated in the app | A genuine driver, with a real sentiment shift alongside it |
| `statement_errors` 19 → 24 | Clears a naive threshold, **fails** the corrected velocity test — reported as tested and not significant |
| `CT-007` round-up double-debits | A real emerging theme: coherent, persistent, spread across channels |
| `CT-012` duplicated branch notes | **The decoy.** Large and superficially compelling, but one CRM template repeated. The agent must reject it. |
| 5 injection payloads | Reach retrieval, are fenced, and cannot alter a figure or a quotation |
| 2 residual PII leaks | Exercise the critic's backstop |

The most instructive result is that **cluster coherence points the wrong
way**: the duplicated artefact measures ~0.88 and the genuine theme ~0.35,
because near-identical text is trivially coherent. Anything adjudicating on
coherence alone would accept the decoy and reject the real signal. That is why
the brief also carries persistence, channel spread and duplicate ratio.

---

## Layout

| Path | What |
|---|---|
| [`domain/`](src/complaints_intelligence/domain/) | Pydantic schemas for every object crossing a stage boundary |
| [`synth/`](src/complaints_intelligence/synth/) | Seeded generation; `signals.py` is the ground truth |
| [`metrics/`](src/complaints_intelligence/metrics/) | Velocity tests with FDR control, fact derivation, `build_brief()` |
| [`store/`](src/complaints_intelligence/store/) | DuckDB standing in for BigQuery, behind repository protocols |
| [`retrieval/`](src/complaints_intelligence/retrieval/) | Embedding and vector search — the RAG substrate |
| [`llm/`](src/complaints_intelligence/llm/) | `LLMClient` protocol; replay, recording and Gemini implementations |
| [`prompts/v1/`](src/complaints_intelligence/prompts/v1/) | Versioned prompt files. A prompt change is a code change. |
| [`agent/`](src/complaints_intelligence/agent/) | The bounded LangGraph pipeline, its tools, budgets and untrusted-text choke point |
| [`critic/`](src/complaints_intelligence/critic/) | Programmatic verification. No model involved. |
| [`render/`](src/complaints_intelligence/render/) | Deterministic templating; fact and citation resolution |

### Where to look first

- [`agent/graph.py`](src/complaints_intelligence/agent/graph.py) — the graph, which reads as the diagram in §8
- [`agent/untrusted.py`](src/complaints_intelligence/agent/untrusted.py) — the single point where customer text enters a prompt
- [`critic/checks.py`](src/complaints_intelligence/critic/checks.py) — what must hold before anything renders
- [`metrics/statistics.py`](src/complaints_intelligence/metrics/statistics.py) — the tests behind every trend claim

---

## Development

```bash
uv run pytest        # unit, adversarial and golden suites
uv run mypy          # --strict over src
uv run ruff check
uv run pre-commit install
```

The [`tests/adversarial/`](tests/adversarial/) suite is where most of the
assurance lives. It proves each critic check fires when provoked through the
full graph, that injection payloads are fenced in the prompts *actually sent*,
that the revise loop terminates when repair is impossible, and — by reading
the source — that no node can bypass the choke point or reach raw SQL.

## Out of scope

Ingestion, transcription, PII redaction, injection screening, classification,
taxonomy management, dashboards and infrastructure are assumed to have
happened upstream. Synthetic data is generated *as if* it had passed through
all of them. Where the design depends on one of these stages, the interface is
stubbed and the assumption noted.
