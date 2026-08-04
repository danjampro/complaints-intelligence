# 04 — Evaluation

How performance is measured in development and monitored in production.

The system has components with very different evaluation needs, and treating
them alike is the main way this goes wrong. A classifier has ground truth and
a confusion matrix. A generated report has neither. So the evaluation strategy
is stratified, and the top-level principle is this:

> **Wherever a property can be made structurally impossible to violate, it is
> asserted rather than measured.** Metrics are for things that can degrade.
> Assertions are for things that must never happen.

That distinction runs through everything below.

---

## 1 · What is asserted, not measured

These are checked programmatically on every run, expected to pass at 100%, and
a failure fails the run. They are not KPIs and they do not have targets.

| Assertion | Enforced by |
|---|---|
| Every numeric claim resolves to a stored fact ID | `critic.checks.check_facts_resolve` |
| No claim states a figure directly | `check_no_literal_numbers` |
| Every qualitative claim carries ≥2 citations | `check_citations_present` |
| Every citation resolves to source text at its offsets | `check_citations_resolve` |
| No unhedged causal language | `check_no_causal_language` |
| No personal data in output | `check_no_pii` |

Three of these are stronger than checks, because the architecture removes the
failure mode rather than detecting it. The model cannot emit a number — it
emits a fact ID, and the value is substituted at render. It cannot alter a
quotation — it emits offsets, and the text is sliced from the store. It cannot
reach the network or write anywhere, because no such tool exists.

**Measuring hallucination rate would be the wrong metric here.** A non-zero
target implies an acceptable rate of fabricated figures in a regulatory
document. There isn't one.

---

## 2 · Development evaluation

### 2.1 Enrichment — the classifier

Ground truth exists, so this is conventional supervised evaluation.

| Metric | Why this one |
|---|---|
| Macro-F1 across categories | Weights rare categories equally. Accuracy would be dominated by the two or three largest and hide failure on the rest. |
| Per-category precision/recall | A category that feeds a trend line needs its own error profile; an aggregate hides which series is unreliable. |
| Expected Calibration Error | Confidence drives the abstention routing. A miscalibrated score sends the wrong records to the LLM tail and corrupts the residual pool. |
| Abstention rate at threshold | Too low and hard cases are forced into wrong categories; too high and the trend denominators thin out. |
| Novelty AUC on held-out categories | Train with a category removed, check its records score as novel. This directly tests the emerging-risk capability. |

**Labelling.** Dual annotation on a stratified sample with Cohen's κ reported.
Where κ is low, the taxonomy definition is the suspect, not the annotators —
ambiguity between annotators is evidence the inclusion criteria need work.

**Slice evaluation is mandatory, not optional.** Macro-F1 by channel and by
product. A model that performs well overall and badly on call-centre
transcripts is a Consumer Duty problem, because
transcription noise correlates with customers who could not use digital
channels.

### 2.2 Metrics layer

Deterministic code, so this is ordinary software testing — and it is where the
`tests/unit/test_statistics.py` suite sits.

- **Property tests** on Benjamini-Hochberg: monotonicity in rank, adjusted ≥
  raw, capped at 1.
- **Null simulation.** With every null true, the flagged count must be near
  zero. Testing ~40 categories weekly at an uncorrected 5% produces roughly
  two false alarms a week, indefinitely — this test is what proves the
  correction is doing its job.
- **Power simulation.** Inject known effects at known baselines; recover the
  minimum detectable effect curve.
- **Reconciliation.** Every fact's recorded provenance is re-run and must
  return the recorded value (`tests/unit/test_store.py`).

**The MDE is published with the report, not just measured.** A null result is
meaningless without a stated sensitivity: "no significant change" in a
category with a baseline of 19 means something very different from the same
statement about a baseline of 500.

### 2.3 Retrieval

| Metric | Notes |
|---|---|
| Recall@k against a labelled relevance set | k matches the production retrieval limit; recall above it is irrelevant. |
| nDCG@k | Rank quality, since the model reads the top items most carefully. |
| Filter containment | An exemplar outside the requested week or category is a *correctness* failure, not a quality one. Asserted. |

### 2.4 Generation — the hard part

No ground truth, so evaluation is a golden set plus targeted adversarial cases.

**Golden set.** ~50 weeks of curated inputs with reviewed reference outputs.
Every prompt change runs against it. A prompt change is a code change and goes
through this suite.

**Rubric scoring**, dual-rated by human reviewers on a held-out sample:
faithfulness to cited evidence, completeness against the brief, plain English,
and actionability of the remediation.

**On LLM-as-judge.** Useful for *screening* — cheap, fast, catches obvious
regressions between human review cycles. Not sufficient for sign-off, for two
reasons. It correlates with human judgement on clear cases and diverges
precisely on the marginal ones that matter, and a judge sharing a family with
the generator shares its blind spots. Used as a filter, with human review of
everything it flags plus a random sample of what it passes; its agreement with
human raters is itself tracked, and a drop in agreement invalidates the
screening.

**Adversarial suite** (`tests/adversarial/`), which is where most of the real
assurance lives:

- Injection payloads reach retrieval and are fenced. Verified against the
  prompts *actually sent*, not by reading the source.
- Each critic check fires when provoked through the full graph.
- A defect that is never repaired fails the run rather than degrading quietly.
- The revise loop terminates when repair is impossible.
- Budget exhaustion produces a partial report with a recorded reason.

**Theme adjudication is evaluated on a decoy.** The fixtures contain a
genuine emerging theme, an ingest artefact engineered to look compelling, and
an incoherent cluster. Rejecting the artefact is the discriminating test — and
the fixtures are built so that a system adjudicating on cluster coherence
alone would get it backwards, because near-identical duplicated text scores
*more* coherent than a real theme described in varied words.

---

## 3 · Production monitoring

### 3.1 The core difficulty

Report quality has no automatic signal. Nobody labels a weekly report. So
monitoring is built on two things that *are* observable: **inputs drifting**,
and **humans intervening**.

### 3.2 Leading indicators — input and pipeline health

Monitored weekly, alerting on change rather than on level.

| Signal | What a move means |
|---|---|
| Abstention rate | Up sharply: input has shifted away from the taxonomy, or the classifier has degraded. Changes how every other number should be read. |
| Residual pool share | Sustained growth means the taxonomy is falling behind reality. |
| Embedding drift (PSI on cluster centroids) | Vocabulary or complaint mix is changing. |
| Category mix χ² vs trailing mean | Distinguishes a real shift from a classifier change. |
| Quarantine volume and reason codes | Ingest health. Complaints are regulatory records and are never silently dropped, so this is a count that must reconcile. |
| Channel mix | Sentiment is compared within channel precisely because this moves. |

### 3.3 The primary quality signal — reviewer edits

A named reviewer moves every report from draft to published. **What they
change is the ground truth this system gets**, and it is the most valuable
signal available.

Captured per report:

- **Edit distance** between draft and published text, per section.
- **Claims deleted** — the strongest negative signal. A deleted claim was
  unsupported, wrong, or not worth saying.
- **Findings added** by the reviewer — the brief's thresholds missed
  something, which is a metrics-layer problem, not a generation one.
- **Time to sign-off** — a proxy for how much work the draft created.
- **Rejected adjudications** — a theme the reviewer disagreed with.

These feed back as labelled data for the golden set and for classifier
retraining, which closes the loop between the human gate and the model.

### 3.4 Outcome metrics

Slower, noisier, and the only ones that measure whether the product works.

- **Time from theme emergence to remediation action opened.** Lead time is the
  entire value of emerging-risk detection.
- **Precision of emerging themes at 90 days** — did a reported theme become a
  real, actioned issue, or was it noise?
- **Missed themes**, found by retrospective review of issues that surfaced
  through other routes. Painful to measure and the most honest metric here.
- **Repeat complaint rate** in categories where remediation was actioned.

### 3.5 Operational

Cost per run, latency, tool-call and LLM-call counts against budget, cassette
or model version drift, and budget-exhaustion frequency. A run that regularly
exhausts its budget is a run whose report is regularly incomplete.

---

## 4 · Governance

Aligned to **PRA SS1/23** expectations. The framework is the sensible
reference whether or not it formally binds.

| Requirement | How it is met |
|---|---|
| Model inventory | Classifier, embedding model and LLM are each registered with version, owner and tier. |
| Tiering | Tiered on materiality: this is customer-outcome and regulatory reporting, so high. |
| Documentation | These design documents and the run trace. |
| Independent validation | The metrics layer is testable without invoking a model — deliberately, and it is the first thing a validator will ask for. |
| Ongoing monitoring | Section 3. |
| Human accountability | A named SMF holder owns the report; a named reviewer publishes each one. |

**Reproducibility is the foundation of all of it.** Every report pins prompt
content hashes, model identifier, taxonomy version and data seed, and every
tool call is traced. A hash rather than a version string, because a version
string can be forgotten on edit and a content hash cannot — that is what makes
an undeclared prompt change detectable eighteen months later.

---

## 5 · Thresholds and what happens when they trip

| Signal | Action |
|---|---|
| Any assertion in §1 fails | Run fails. No report published. Investigate before re-running. |
| Abstention rate moves >5pp week on week | Report flagged; taxonomy health review brought forward. |
| Macro-F1 drops >3pp on the monitoring sample | Retraining triggered; report continues with the degradation stated in it. |
| Reviewer deletes >20% of claims in a section | Prompt regression review for that section. |
| Emerging-theme precision at 90 days <50% | Adjudication thresholds and prompt reviewed. |
| Budget exhausted on >1 run in 4 | Budgets re-sized, or the brief is carrying more than the agent can cover. |

Two of these deliberately do **not** stop the report. A degraded classifier or
a shifted abstention rate produces a report that says so, because a compliance
team with a caveated report is better served than one with no report and no
explanation.
