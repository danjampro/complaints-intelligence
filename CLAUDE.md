# CLAUDE.md

Guidance for Claude Code in this repository.

## What this is

`complaints-intelligence` — the Part 3 code deliverable for a technical
interview exercise. It demonstrates one stage of a larger design: the **agentic
report generation loop** that turns weekly complaint metrics into written
findings.

The full solution design lives in `private/design/` — local reference material,
gitignored, not part of the deliverable. Read `01-problem-statement.md` and
`02-architecture.md` before making changes — this package implements section 8
of the architecture.

**All data is synthetic.** Nothing here should resemble any real firm's internal
systems, taxonomies, or complaints.

## Scope

### In scope

- **The agentic loop** — a bounded graph that reads a metrics brief,
  investigates findings, adjudicates candidate themes, retrieves and assesses
  resolution precedent, verifies its own output, and renders a report.
- **Retrieval** — embedding and similarity search over complaint and resolution
  text. This is the RAG substrate the agent uses.
- **Domain models** — typed schemas for every object crossing a stage boundary.
- **Tests**, including adversarial cases.

### Out of scope

Assume these have already happened upstream and their outputs are available:

- Ingestion, channel adaptation, transcription
- PII redaction, pseudonymisation, injection screening, quarantine
- Classification and enrichment of complaints
- Taxonomy management and change control
- **Statistical computation of metrics and facts** — its output is committed as
  `fixtures/facts.json` and `fixtures/brief.json`; the approach is described in
  `02-architecture.md` §7
- Dashboards, delivery, and infrastructure

The fixture is written *as if* it had passed through all of the above. Do not
build these stages. Where the design depends on one, note the assumption.

## Invariants

These constrain every implementation decision and are the point of the exercise.

1. **The model never produces a number.** All figures originate in the fact
   store, precomputed. Findings reference facts by ID; values are substituted at
   render time.
2. **Every qualitative claim is cited** to specific complaints, resolvable to
   source text.
3. **Complaint text is untrusted input.** It is data, never instruction, at
   every point it enters a prompt — including text returned by retrieval.
   `agent/untrusted.py` is the single choke point.
4. **The agent is read-only and bounded.** No writes, no network egress, capped
   steps and revision loops.
5. **It runs with no credentials.** A reviewer must be able to execute the full
   demo offline in seconds. Any change that breaks this defeats the
   deliverable's purpose.
6. **Determinism where possible.** Pinned versions, stable output for stable
   input.

## Standards

- Python 3.12. `ruff`, `mypy --strict`, enforced in pre-commits.
- CI / CD is out of scope.
- Tests use pytest.
- Pydantic v2 models at every stage boundary. Model output is parsed into a
  schema, never scraped from text.
- Dependency injection for the LLM client and data access — modules take a
  protocol, never import a vendor SDK directly.
- Prompts live in versioned files, not string literals. **A prompt change is a
  code change** and invalidates the committed recordings.
- Pure functions where the logic allows; no I/O or globals in analysis code.

## Working style

**This is a 3–5 hour exercise deliverable, not a production system.** A reviewer
must be able to read the whole thing. That constraint outranks completeness.

- Prefer the simple thing. Depth in the agentic loop matters more than breadth
  across stages.
- **Docstrings are at most two sentences.** Design reasoning belongs in the
  *Key decisions* table of `private/design/02-architecture.md`, not in the code.
- Don't add dependencies without a reason in the commit message.
- Keep fixtures small enough that a human can read them and follow what the
  pipeline is doing.
- The submission must be understandable standalone. If a reviewer would need a
  voiceover to follow it, it belongs in the docs.

## Regenerating the model recordings

Changing a prompt, the fixture, or the brief invalidates
`llm/cassettes/*.json`, and the offline demo fails with a clear miss rather than
replaying something stale. To re-record: `uv sync --all-extras`, set
`GEMINI_API_KEY`, `uv run ci run --record`, and commit the result.
