# 01 — Problem Statement

## Situation

A retail bank receives several thousand formal complaints each week across four
channels: regulator/FOS referrals, the mobile app, branch, and call centres. Only
the call centre channel is non-text. Volume is modest in data terms — roughly
250k complaints a year — but the material is unstructured, inconsistent across
channels, and currently reviewed manually.

A compliance team needs a weekly automated report summarising what customers are
complaining about, how that is changing, what is newly emerging, and what should
be done about it.

## Why this matters beyond efficiency

This is a regulated reporting product, not a text analytics exercise.

- **DISP 1.3.3R** requires firms to identify and remedy recurring or systemic
  problems, including by analysing the causes of individual complaints to find
  root causes common to types of complaint, considering whether those causes
  affect other products or processes, and reporting to senior personnel.
- **Consumer Duty (PRIN 2A)** makes complaints a primary evidence source for
  outcomes monitoring, foreseeable harm, and treatment of vulnerable customers.
- Model risk expectations along the lines of **PRA SS1/23** apply to the
  statistical and AI components: inventory, tiering, documentation, independent
  validation and ongoing monitoring. (SS1/23 formally binds firms with internal
  model approval; the framework is the sensible reference regardless.)

The consequence for design: the output must be **traceable, reproducible and
auditable**. A plausible summary is not sufficient.

## Users and use of outputs

| User | Use |
|---|---|
| Compliance analysts | Primary consumers. Investigate drivers, drill into source complaints, decide what escalates. |
| Complaints/operations leads | Own remediation actions arising from the report. |
| Senior management / committees | Receive the report as governance MI; a named SMF holder is accountable. |
| Product and engineering | Recipients of specific remediation recommendations. |

Outputs feed root-cause analysis, remediation decisions, Consumer Duty outcomes
monitoring, and committee reporting. The report is a record, so published
versions must be immutable and reconstructable.

## Required outputs

1. **Top 5 complaint drivers** — ranked, with volumes and change vs prior week.
2. **Sentiment trends vs last week** — comparable over time and across channels.
3. **Emerging risk themes** — problems that do not yet have an established
   category, or established categories moving abnormally.
4. **Remediation recommendations in plain English** — grounded in how comparable
   complaints were actually resolved, not generic advice.

## Shape of the solution

The report contains two kinds of content with very different reliability needs.

**Numbers** — drivers and sentiment trends. These must be correct and identical
on every re-run. They are computed by ordinary code (SQL and statistics) before
any model is invoked, and stored with a record of how each was derived.

**Judgement** — what is emerging, and what to do about it. These require
retrieving evidence, assessing whether it is relevant, and writing plainly. This
is where language models are used, and where an agent is warranted: the number of
retrieval and assessment steps depends on what the evidence turns out to be.

The two are separated rather than combined. The model selects which stored figure
to cite and writes the prose around it; it never produces a figure itself.

## Key requirements

- **Traceability.** Every number resolves to a stored, re-derivable fact; every
  qualitative claim cites specific complaints. No unsupported assertions.
- **Comparability over time.** Week-on-week and month-on-month trends must
  reflect real change, not shifting category definitions.
- **Statistical honesty.** With ~40 categories tested weekly, naive comparison
  produces false alarms continuously. Trend claims require significance testing
  with multiplicity control, and a stated minimum detectable effect.
- **No causal overreach.** Correlations are stated as correlations. Causal
  hypotheses are flagged as requiring confirmation by a named owner.
- **Plain English.** Consumable by non-technical readers, free of internal jargon
  and unexplained acronyms.
- **Human accountability.** The system drafts; a named reviewer publishes.
- **Safety.** Complaint text is customer-supplied and adversarial-capable. PII is
  removed before inference. No complaint is ever silently discarded — complaints
  are regulatory records.
- **Reproducibility.** Any historical report can be regenerated exactly, with
  prompt, model and taxonomy versions pinned.

## Scope

**In scope:** ingestion and standardisation across channels; per-complaint
enrichment; taxonomy management; trend and emerging-risk detection; report
generation; delivery and sign-off; evaluation.

**Out of scope:** complaint capture systems themselves; case management and
redress workflow; customer communications; the FCA complaints return.

## Assumptions

- ~5,000 complaints/week; weekly batch cadence is sufficient.
- At this volume the constraint is analytical quality, not compute scale. Design
  favours simplicity over scale machinery.
- We are not bound to an existing business complaint taxonomy and may define our
  own, provided it is versioned and its history is defensible.
- Closed complaints carry free-text resolution notes describing the action taken.
  These are the sole knowledge source for remediation recommendations.
- All data used in this submission is synthetic.

---

## Glossary

Terms used consistently across all design documents.

**Complaint envelope.** The canonical schema every channel is mapped into.
Channel-specific handling is confined to the adapters; `channel` is retained as a
feature, not discarded.

**Taxonomy version.** The complaint taxonomy is held as versioned data, never
mutated in place. Each enriched record is stamped with the version used.
Structural changes mint a new version plus an old→new mapping table, allowing
history to be re-projected so trend series stay comparable.

**Confidence.** How certain the classifier is *between known categories*. Low
confidence means the record sits near a decision boundary. Measured as top-class
probability and as the margin between the top two classes.

**Novelty.** How far the record sits from the region of embedding space occupied
by known categories. **High** novelty means "unlike anything known" — a different
condition to low confidence.

These are not interchangeable. Softmax is normalised across known classes and has
no "none of these" output, so a genuinely new complaint type is frequently
assigned to the nearest existing category *with high confidence*. Detecting that
requires an un-normalised measure.

|  | Low novelty | High novelty |
|---|---|---|
| **High confidence** | Normal — assign | Confidently wrong; where new categories hide |
| **Low confidence** | Ambiguous between known categories | Obviously new |

Novelty must account for differing cluster spread — a broad category like service
quality legitimately sprawls where a narrow one does not. Scored as k-NN distance
normalised per category (Mahalanobis with tied covariance is the alternative),
thresholded on a per-category percentile so a single threshold means the same
thing everywhere.

**Abstention.** A deliberate refusal to assign a category rather than a forced
guess, triggered by low confidence, low margin, high novelty, or failure to
ground the assignment in evidence spans. Abstained complaints still count in
totals but do not contribute to per-category trends, so hard cases are never
silently dropped from the denominator. Abstention rate is a monitored health
signal, not a failure.

**Residual pool.** Abstained records; the input to theme discovery.

**Candidate theme (`CT-nnn`).** A persistent cluster in the residual pool, given a
stable identity by cluster linking so its growth can be measured across weeks.
Reported as narrative with evidence; never counted as a category until adopted,
since it has no comparable history.

**Fact.** A typed value with provenance, emitted by the deterministic metrics
layer. Report claims reference fact IDs rather than literal values, so figures
are substituted at render time and cannot be fabricated by a language model.

**Fact store.** The immutable, run-stamped collection of facts for a given week.
The trust boundary of the system: everything below it is deterministic and
reproducible, everything above it is generative.

**Metrics brief.** The compact object the metrics layer emits at the end of each
run — flagged categories, drift signals, candidate themes, health indicators and
headline aggregates, as fact IDs. Built by fixed configured thresholds and
truncated. It is the agent's entire view of the week, which is what makes agent
runs bounded, comparable and reproducible.

**Finding.** A drafted section of the report: a headline, claims referencing fact
IDs, and citations to specific complaints by ID and character offset.
