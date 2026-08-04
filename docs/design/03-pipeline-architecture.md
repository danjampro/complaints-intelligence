# 03 — Pipeline Architecture

Everything downstream of reading complaint text from BigQuery. Assumes ingestion,
channel adaptation, transcription, redaction and quarantine have already run and
`complaints` holds clean, redacted, one-row-per-complaint records.

Three pipelines: a one-off cold start, a recurring enrichment DAG, and a weekly
analysis DAG.

---

## Terminology

Two distinct mechanisms are easily conflated. They are named separately
throughout.

| Term | Mechanism | Operates on |
|---|---|---|
| **Classification** | Logistic regression head over embeddings | All complaints, against the frozen taxonomy |
| **Theme linking** | k-NN distance to candidate theme members | Residual pool only, against candidate themes |

Classification assigns a **category**. Theme linking assigns a **candidate theme**
(`CT-nnn`), which is not a category until adopted.

---

## Tables

```
complaints                one row / complaint · canonical, immutable
  complaint_id, channel, product_code, received_ts,
  customer_ref, text, status, resolution_note, resolved_ts

complaint_embeddings      one row / complaint · derived
  complaint_id, embedding ARRAY<FLOAT64>, model_version, task_type

enriched_complaints       one row / complaint · canonical output of DAG A
  complaint_id, taxonomy_version, routing_decision, abstain_reason,
  category, category_confidence, category_alt, margin, novelty_score,
  sentiment_score, evidence_spans ARRAY<STRUCT<start,end>>,
  enrichment_run_id, prompt_version, model_version

candidate_themes          theme_id, centroid, members, internal_knn_p90,
                          first_seen_week, status
facts                     immutable, run-stamped
reports                   immutable, version-stamped
```

**One row per complaint, always.** Abstained complaints are written to
`enriched_complaints` like any other, with `routing_decision = 'abstain'` and the
head's best guess retained for diagnostics. Splitting assigned and residual into
separate tables would require a union for every volume query and eventually break
a denominator. Consumers are views:

```sql
v_attributed  WHERE routing_decision = 'assign'    -- category trends
v_residual    WHERE routing_decision = 'abstain'   -- discovery input
v_all         (no filter)                          -- totals, denominators
v_precedent   status='closed' AND resolution_note IS NOT NULL
```

`abstain_reason` is an enum — `low_confidence`, `low_margin`, `high_novelty`,
`no_evidence`. The mix over time is diagnostic: rising `high_novelty` means the
taxonomy is going stale; rising `low_margin` means two categories are colliding.
Different problems, different fixes.

Candidate theme membership lives in `candidate_themes`, written weekly by DAG B,
not in `enriched_complaints`, written daily by DAG A. DAG B never mutates DAG A's
output.

---

## Embedding strategy

**One embedding column, `SEMANTIC_SIMILARITY`, serving every consumer:**
classification, novelty scoring, theme linking, discovery clustering, and
precedent retrieval.

A single shared space is a hard requirement for the first four: taxonomy
centroids and candidate theme centroids are compared to each other when
deduplicating a discovered theme against an existing category, and distances must
mean the same thing on both sides.

**Precedent retrieval is complaint-to-complaint, not complaint-to-resolution.**
The agent matches a complaint description against the complaint text of closed
cases, then joins to their resolution notes:

```sql
VECTOR_SEARCH(v_precedent_embeddings, query_vector, top_k => 20)
  → JOIN complaints → return complaint text + resolution_note
```

This is a symmetric like-for-like comparison, so `SEMANTIC_SIMILARITY` is
correct, and no separate resolution embedding or index is needed. Matching
complaints to resolution notes directly would be asymmetric retrieval
(`RETRIEVAL_QUERY` / `RETRIEVAL_DOCUMENT`) and would rely on the model bridging
"customer could not make a payment" to "reversed the fee and reset the payee
limit" — a real semantic gap, across notes that are terse, jargon-heavy and
written for internal readers. Complaints are richer and more consistent.

Two consequences to note:

- Retrieval **by resolution content** ("cases where the fix was a fee reversal")
  is not supported. Not required by the four outputs; would need a second index.
- The vector search must be **restricted to closed complaints with resolution
  notes before searching** (`v_precedent`), not filtered afterwards, or recall
  degrades silently when the nearest 20 complaints are mostly open.

---

## Phase 0 — Cold start (one-off)

The taxonomy is **derived from the data**, not invented, then stabilised by human
curation.

```
historical corpus (12–24 months)
  → embed
  → HDBSCAN
  → c-TF-IDF distinguishing terms + exemplars per cluster
  → Gemini drafts a name and definition per cluster
  → human curation: merge, split, discard, write inclusion/exclusion criteria
  → taxonomy v1.0 — frozen, versioned
  → train classification head on curated cluster membership
```

**Why clustering rather than LLM-labelling each complaint.** Categories reflect
actual complaint structure rather than a model's priors about what bank
complaints look like; thousands of pseudo-labels come free rather than per
document; and the same mechanism that cold-starts the taxonomy extends it weekly
over the residual pool. One technique, two uses.

**The LLM names clusters; it never groups them.** Grouping is the statistical
claim and stays deterministic and re-runnable. Naming is a language task where an
error is cosmetic.

**Why raw clusters cannot be the taxonomy.** HDBSCAN is unstable across re-runs,
so trends would be uninterpretable; a centroid is not a definition a human can
audit; 30–50% of the corpus lands in noise; and embeddings group by linguistic
similarity, which tracks product vocabulary — a failure mode spanning mortgages
and current accounts splits into two clusters, which is precisely the
cross-product systemic issue DISP 1.3.3R asks us to find. Human curation resolves
all four.

Unclustered historical complaints are simply absent from the initial training
set. They are classified normally at inference; genuinely odd ones abstain into
the residual pool, which is where they belong.

**Gap filling.** Categories the clustering under-produced (a rare but important
category with 15 members) can be topped up by targeted LLM labelling of similar
complaints. A remediation step, not a pipeline stage.

**Flat, not hierarchical.** A two-level taxonomy inheriting its top level from
existing business complaint categories was considered and rejected: those
categories are product-shaped, and a failure mode spanning products would split
across branches — defeating the cross-product root-cause analysis the system
exists to perform. Where reconciliation with existing MI is needed, each
discovered category tags which business categories it draws from. Mapping, not
hierarchy.

---

## DAG A — Enrichment (daily)

Per-complaint. Vertex AI Pipelines or Composer; mostly BigQuery SQL with one
model call.

### A1 · Prompt screening — Model Armor

Complaint text is customer-supplied and adversarial-capable. Screened before it
reaches any generative model call. Failures are flagged and routed to quarantine
with a reason code — never dropped, as complaints are regulatory records.
Response screening applied to the enrichment output as well.

**Placement.** Screening sits at the boundary so that everything downstream is
known-screened, avoiding a permanent need to reason about which stages see
unscreened text. Embedding first would be marginally cheaper — it stays inside
BigQuery, and an embedding model is not an injection surface since it follows no
instructions — but the simplicity of a single gate outweighs it at this volume.
See ADR-006.

### A2 · Embedding — BigQuery ML

`AI.GENERATE_EMBEDDING` over a remote model. `gemini-embedding-001`, task type
`SEMANTIC_SIMILARITY`, output truncated to 256 dimensions.

- Truncation matters: 3072 dimensions degrades HDBSCAN density estimation and
  makes distance-based scoring unreliable. Matryoshka training means truncation
  is cheap and usually improves clustering.
- No chunking. Complaints are embedded whole. Production would chunk call
  transcripts specifically, where the complaint is a small fraction of the text.
- `embeddinggemma-300m` via `AI.EMBED` is the alternative where no egress to a
  model endpoint is acceptable — data stays in BigQuery.

### A3 · Classification — head over embeddings

Multinomial logistic regression mapping the 256-dim embedding to taxonomy
categories. The embedding model is frozen; only the head is trained. This is a
**linear probe**, not knowledge distillation.

Returns a full probability distribution, giving:

- `category_confidence` — top-class probability
- `category_alt`, `margin` — second class and the gap to it

A trained head is used rather than LLM classification because softmax confidence
is calibratable and a margin is available. LLM self-reported confidence is
neither, and returns no ranked alternatives.

**Margin is not confidence.** With ~40 classes the residual probability mass has
somewhere to go, so the two diverge: 0.46/0.44 and 0.46/0.12 share a confidence
but describe opposite situations — a coin flip versus a weak but clear winner.
Margin's primary value is diagnostic: a category *pair* that repeatedly produces
low margins is a taxonomy defect, not a model defect, and feeds the quarterly
health review.

Fine-tuning an encoder is the upgrade path once label volume supports it; the
probe is correct while label-poor.

### A4 · Novelty scoring

k-NN distance to the nearest labelled exemplars of the nearest category,
normalised per category by that category's internal distance distribution, then
thresholded on a per-category percentile so one threshold means the same thing
everywhere.

Per-category normalisation is required because category spread differs
legitimately — broad categories sprawl, narrow ones do not. Mahalanobis with tied
covariance is the parametric alternative; k-NN makes no shape assumption and
handles multi-modal categories.

**Novelty is not low confidence.** Softmax is normalised across known classes and
has no "none of these" output, so a genuinely new complaint type is frequently
assigned to the nearest existing category *with high confidence*. Detecting that
requires an un-normalised measure.

Novelty has one job — routing at A7 — and it is effectively the sensitivity dial
on the entire emerging-risk capability. Set too tight, new problems are silently
absorbed into existing categories and never surface. It is cheap to be generous:
a false positive costs one complaint sitting in the residual pool, which linking
or clustering then absorbs; a false negative loses an emerging risk entirely.

Secondary uses: mean novelty rising across weeks signals corpus drift away from
the taxonomy; highest-novelty residuals make the best exemplars when naming a new
cluster.

### A5 · Enrichment — Gemini, structured output

One call per complaint, constrained to a JSON schema. Returns:

- `sentiment` — ordinal intensity, not polarity
- `evidence` — **verbatim quoted substrings**, not offsets

Categorisation is *not* performed here; the head owns it.

**Evidence extraction is independent of the predicted category, deliberately.**
Passing the label into the prompt would make extraction circular — the model
would find something to justify whatever label it was given, turning evidence
into post-hoc rationalisation and destroying the grounding check spans exist to
provide. Because neither step sees the other's output, agreement between them is
a genuine signal: salient spans embedding far from the predicted category's
centroid is a real disagreement worth flagging.

The prompt must therefore define salience explicitly — the problem stated and the
impact described, not account details or pleasantries.

Complaint text is placed inside delimited data blocks with explicit provenance
tags, never in an instruction position. Batched via Vertex batch prediction;
weekly volume makes cost negligible.

### A6 · Span resolution — deterministic

Quotes located in source text by exact match after whitespace normalisation,
producing character offsets.

```python
start = normalise(text).find(normalise(quote))
```

A failed match means the model produced text not present in the complaint. The
span is dropped, the event logged, and the rate monitored as a hallucination
signal. Fuzzy fallback (`rapidfuzz.partial_ratio` above threshold) recovers
punctuation drift, logged when used.

Offsets are never requested directly — models count characters unreliably, and a
silently wrong offset is worse than a missing one.

### A7 · Routing

```
assign   if confidence ≥ τ and margin ≥ δ and novelty ≤ ν
abstain  otherwise
```

Abstained records form the **residual pool**. They still count in totals but do
not contribute to per-category trends, so hard cases are never dropped from the
denominator. Abstention rate is a monitored health signal, not a failure. The
rule that fired is recorded in `abstain_reason`.

Thresholds live in config, tuned against the golden set to a precision target.

### A8 · Write `enriched_complaints`

Stamped with `taxonomy_version`, `prompt_version`, `model_version`,
`enrichment_run_id`.

---

## DAG B — Weekly analysis

### B1 · Discovery — residual pool

Two steps, in order. **Linking first, then clustering the leftovers.**

```
this week's residual embeddings
  → score against every existing candidate theme
      assign to best theme that passes threshold → update centroid
  → leftovers (passed nothing)
      → UMAP to ~10 dims → HDBSCAN (min_cluster_size ≈ 10)
      → c-TF-IDF + exemplars → Gemini names each cluster
      → new candidate themes CT-nnn
```

**Linking score.** Mean cosine distance to the *k* nearest members of the theme,
rather than distance to a centroid — this handles multimodal themes, where a
point between two sub-modes belongs but sits far from the mean. Threshold is the
theme's own internal k-NN distance p90: *assign if the complaint sits closer to
this theme than 90% of its members are to each other.* Themes with fewer than ~30
members fall back to a global threshold until their internal distribution is
stable.

```python
def link_score(vec, theme):
    d = mean_cosine_dist(vec, knn(vec, theme.members, k=5))
    tau = GLOBAL_TAU if len(theme.members) < 30 else theme.internal_knn_p90
    return d, d < tau
```

**Why linking matters more than clustering.** Fresh clustering each week produces
IDs that are meaningless across runs, so theme growth cannot be measured. A
theme's week-3 count comes from *assignment*, not from clustering rediscovering
it. This is what gives `CT-nnn` a stable identity and makes the velocity test
applicable to candidates as well as categories.

**Why HDBSCAN for the leftovers.** k is unknown, clusters are non-spherical, and
it has a **noise label**. High noise here is correct behaviour, not a defect: the
residual pool is by definition what fit nothing, and most of it genuinely is
one-offs and odd phrasings rather than emerging themes. k-means would force every
record into a group and manufacture themes that do not exist.

**Two health checks:**

- *Centroid drift* — a theme updated weekly can drift until it no longer means
  what a human approved. Track centroid movement and flag themes exceeding a
  threshold.
- *Ambiguous linking* — a complaint passing the threshold for two themes with
  similar scores signals those themes should merge. Logged, not acted on
  automatically; feeds the periodic taxonomy health review.

**Promotion.** A candidate must survive N weeks and M complaints before it is
proposed to taxonomy change control. Reporting is not gated on this — see
§Adoption.

### B2 · Metrics and facts

dbt models over BigQuery for aggregation; a Python module for statistics SQL
cannot express. Pure functions, no I/O.

**Volumes** — counts and rates by category, channel, product, week; offset by
exposure (`log(n_t)`).

**Sentiment** — aggregated within-channel, then combined with channel weighting.
Raw pooling would track channel mix rather than sentiment, since callers are more
expressive than form-fillers.

**Velocity** — negative binomial GLM per category on a trailing 52-week window
excluding the current week:

```
log(E[y_ct]) = log(n_t) + β₀ + β₁·t + seasonal
```

Dispersion estimated per category. One-sided exceedance probability under the
predictive distribution, then Benjamini-Hochberg FDR control at q = 0.10 across
all categories and candidate themes.

Two gates — a flag requires `q ≤ 0.10` **and** (rate ratio ≥ 1.5 **or** absolute
excess ≥ 20). Categories with expected count below 5 are excluded for lack of
power.

**Drift** — CUSUM on the rate, catching sustained movement no single week
reveals. Reported separately from spikes.

**Health** — abstention rate and reason mix, residual share, quarantine counts,
channel volume bounds. A week outside bounds is marked degraded and alerting
suppressed: a backdated regulator batch or a channel outage otherwise looks
exactly like signal.

**Facts** written immutably per run:

```python
Fact(id="f_0142", run_id="2026-W31",
     label="payments_failed · count · 2026-W31",
     value=142, unit="complaints", taxonomy_version="v4.2",
     provenance=Query(view="v_weekly_category_counts",
                      params={"category":"payments_failed","week":"2026-W31"}))
```

Never mutated. A taxonomy re-projection produces a new run, not an edit.

### B3 · Metrics brief

`build_brief(run_id, config)` selects flagged categories, drift signals, candidate
themes, health indicators and headline aggregates, as **fact IDs**, ranked and
truncated (top 8 flagged, top 3 candidates).

This is the agent's entire view of the week. Deliberate: it bounds the run, makes
weeks comparable, and keeps the agent reproducible. Anything the thresholds miss
cannot reach the report — hence thresholds tuned against backtest, a declared
minimum detectable effect, and the dashboard remaining available for analysts.

### B4 · Agent — LangGraph on Cloud Run

```
plan → investigate → adjudicate → remediate → critic ⇄ revise → render
```

Typed Pydantic state. Read-only tools, no write access, no external egress,
budgeted steps.

| Node | Function |
|---|---|
| `plan` | Reads the brief; allocates bounded investigations by excess volume and severity. Skips are recorded. |
| `investigate` | Per finding: `get_exemplars`, characterise what customers describe, draft with citations. |
| `adjudicate` | Per candidate theme: real, noise, or ingest artefact? Checks coherence, persistence, health facts; deduplicates against existing categories. |
| `remediate` | `get_precedent` — vector search over closed complaints, joined to their resolution notes. Assesses whether retrieved precedent genuinely transfers; retries with different retrieval if not; summarises what was done. |
| `critic` | Programmatic verification. Failures return to `revise`, max 2 loops. |
| `render` | Deterministic templating. No model. |

**Tools:** `query_metrics` (parameterised views only, no free-form SQL),
`get_exemplars`, `get_precedent`.

**Critic asserts:** every numeric claim resolves to a fact ID (100%, an assertion
not a metric); every qualitative claim carries ≥2 citations with valid, in-range
offsets; no causal language — "coincident with" permitted, "caused by" not, with
causal hypotheses emitted as requiring confirmation by a named owner; zero PII;
reading grade within threshold.

**The model types no numbers.** Findings reference fact IDs; values substituted at
render. Quotes reference `complaint_id` plus offsets and are pulled from the store
at render. Numeric hallucination and misquotation are structurally impossible,
not detected after the fact.

**Why an agent:** `remediate` is retrieve → assess → refine with an iteration
count that depends on what returns; `adjudicate` branches on evidence. Neither is
enumerable in advance. Agency covers *what to look at next*; determinism governs
*what the numbers are*.

### B5 · Report, sign-off, delivery

Report object is versioned and immutable, pinning prompt, model and taxonomy
versions plus `run_id` — any historical report is exactly reconstructable.

Named reviewer moves `draft → published`. Reviewer edits are captured as labelled
data feeding evaluation.

Outputs: Looker dashboard (drill-down from any figure to underlying complaints),
PDF/DOCX committee pack, email digest. The report is the record; the dashboard is
the drill-down.

---

## Adoption — taxonomy change control

Reporting a candidate theme and adopting it as a category are different acts.

**Reporting is immediate** — lead time is the entire value of emerging-risk
detection. Candidate themes reach the agent directly as narrative findings with
evidence, never as rows in the trend table, since they have no comparable
history. There is no in-between state: narrative before adoption, full category
with backdated history after.

**Adoption is deliberate and human-gated.** Two routes:

| Route | Cadence | Change | Cost |
|---|---|---|---|
| Discovery over residual pool | Weekly proposals | Additive — new node | Cheap; history unaffected |
| Taxonomy health review | Quarterly | Splits, merges, retirements | Breaks the series; requires re-projection |

Splits signalled by rising within-category embedding variance; merges by
persistently low-margin category pairs and by ambiguous theme linking;
retirements by sustained near-zero volume.

Approval mints a new taxonomy version plus an old→new mapping table. History is
re-projected — the classification head is retrained and re-run over past
complaints so the new category has a backdated series — as a new metrics run, not
an edit.

---

## Orchestration and platform

| Concern | Choice |
|---|---|
| DAG A, DAG B | Vertex AI Pipelines (lineage over ML artefacts) or Composer |
| Compute | Cloud Run jobs; agent as a Cloud Run service |
| Embedding | BigQuery ML remote model, `gemini-embedding-001` |
| Aggregation | dbt over BigQuery |
| Statistics | Python (`statsmodels`, `scipy`), pure functions |
| Discovery | UMAP + HDBSCAN + c-TF-IDF (BERTopic as the packaged alternative) |
| Classification | scikit-learn logistic regression, versioned artefact |
| Retrieval | BigQuery `VECTOR_SEARCH` |
| Agent | LangGraph, Pydantic state |
| IaC / CI | Terraform, GitHub Actions, ruff + mypy + pytest |

At ~5,000 complaints/week the constraint is analytical quality, not compute
scale. GKE, streaming infrastructure and a dedicated vector database are
deliberately excluded — BigQuery `VECTOR_SEARCH` is sufficient at ~250k
documents/year, with Vertex AI Vector Search as the scale-out path.

Every run emits a full trace — tool calls, arguments, facts retrieved, prompt and
model versions — to BigQuery. This is what makes a report defensible eighteen
months later.
