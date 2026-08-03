# CLAUDE.md

Guidance for Claude Code in this repository.

## What this is

`complaints-intelligence` — the Part 3 code deliverable for a technical interview
exercise. It demonstrates one stage of a larger design: the **agentic report
generation loop** that turns weekly complaint metrics into written findings.

The full solution design lives in `docs/design/`. Read
`01-problem-statement.md` and `02-architecture.md` before making changes — this
package implements section 8 of the architecture, and terminology is defined in
the glossary.

**All data is synthetic.** Nothing here should resemble any real firm's internal
systems, taxonomies, or complaints.

## Scope

### In scope

- **Synthetic data generation** — complaints across multiple channels, resolution
  notes on closed complaints, and a small set of precomputed facts representing
  the output of the upstream metrics layer.
- **Embedding and vector search** — embedding complaint and resolution text, and
  retrieval over it. This is the RAG substrate the agent uses for exemplars and
  for resolution notes.
- **The agentic loop** — a bounded graph that reads a metrics brief, investigates
  findings, adjudicates candidate themes, retrieves and assesses resolution
  precedent, verifies its own output, and renders a report.
- **Domain models** — typed schemas for every object crossing a stage boundary.
- **Tests**, including adversarial cases.

### Out of scope

Assume these have already happened upstream and their outputs are available:

- Ingestion, channel adaptation, transcription
- PII redaction, pseudonymisation, injection screening, quarantine
- Classification and enrichment of complaints
- Taxonomy management and change control
- Statistical computation of metrics and facts
- Dashboards, delivery, and infrastructure

Synthetic data is generated *as if* it had passed through all of the above.
Do not build these stages. Where the design depends on them, stub the interface
and note the assumption.

## Invariants

These constrain every implementation decision and are the point of the exercise.

1. **The model never produces a number.** All figures originate in the fact
   store, precomputed. Findings reference facts by ID; values are substituted at
   render time.
2. **Every qualitative claim is cited** to specific complaints, resolvable to
   source text.
3. **Complaint text is untrusted input.** It is data, never instruction, at every
   point it enters a prompt — including text returned by retrieval.
4. **The agent is read-only and bounded.** No writes, no network egress, capped
   steps and revision loops.
5. **It runs with no credentials.** A reviewer must be able to execute the full
   demo offline in a couple of minutes. Any change that breaks this defeats the
   deliverable's purpose.
6. **Determinism where possible.** Seeded generation, pinned versions, stable
   output for stable input.

## Standards

- Python 3.12. `ruff`, `mypy --strict`, enforced in pre-commits.
- CI / CD is out of scope.
- Tests use pytest.
- Pydantic v2 models at every stage boundary. Model output is parsed into a
  schema, never scraped from text.
- Dependency injection for the LLM client and data access — modules take a
  protocol, never import a vendor SDK directly.
- Prompts live in versioned files, not string literals. **A prompt change is a
  code change** and goes through review and the regression suite.
- Pure functions where the logic allows; no I/O or globals in analysis code.
- Structured logging with run and version identifiers on every record.
- Use UV pip.

## Working style

- Prefer the simple thing. This is a demonstration of approach, not a production
  system. Depth in the agentic loop matters more than breadth across stages.
- Record design decisions as ADRs in `docs/design/00-adr/` — including the
  alternatives rejected.
- Don't add dependencies without a reason in the commit message.
- Keep synthetic fixtures small enough that a human can read them and follow what
  the pipeline is doing.
- The submission must be understandable standalone. If a reviewer would need a
  voiceover to follow it, it belongs in the docs.
