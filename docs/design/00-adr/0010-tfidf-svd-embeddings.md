# ADR-0010 — TF-IDF + SVD stands in for a hosted embedding model

**Status:** Accepted · Applies to the demonstration only

## Context

The RAG substrate needs embeddings for exemplar retrieval, resolution-note
retrieval and cluster coherence. Production would use a hosted model. The
demo must run offline in two minutes with no download.

## Decision

TF-IDF followed by truncated SVD — latent semantic indexing — behind an
`Embedder` protocol. Fitted at store open rather than persisted.

Production choice is Vertex AI `text-embedding-005` (or `gemini-embedding-001`
where the extra dimensions earn their cost), swapped in by implementing the
protocol. Nothing else changes.

## Consequences

Local, deterministic, no model download, fits ~1,100 documents in well under a
second. The index is rebuilt on every open, which is what "derived and
rebuildable" means in the architecture and removes a class of failure where a
stale matrix silently misaligns with the text it represents.

**What is lost, stated plainly.** LSI captures term co-occurrence, not
meaning. It will not connect "double debit" to "charged twice" unless those
terms co-occur in this corpus. A hosted model would. Retrieval quality here is
therefore better than the demo deserves — the synthetic text is
template-composed, so vocabulary overlap within a theme is high — and would be
noticeably worse on real complaints, where the same problem is described in
genuinely different words.

This matters for one visible result: measured cluster coherence. The
duplicated-CRM-note artefact (`CT-012`) scores ~0.88 while the genuine
emerging theme (`CT-007`) scores ~0.35, because near-identical text is
trivially coherent under any embedding. A better model would raise CT-007's
score but would not reverse the ordering, and the lesson stands either way:
coherence alone would accept the artefact and reject the real signal. That is
why the brief carries persistence, channel spread and duplicate ratio too.

## Alternatives rejected

**`sentence-transformers` (MiniLM).** Genuine semantic embeddings locally.
Rejected: pulls `torch` (~2 GB on Windows) and needs a model download on first
run, which breaks the two-minute offline promise for the exact reviewer the
deliverable is written for.

**Gemini embeddings computed once, vectors committed.** Most faithful.
Rejected: the fixtures would have to be regenerated whenever any synthetic
text changed, and a stale `.npy` misaligning with regenerated text is a silent
failure. Rejected on the same reasoning as the fitted-at-open decision.
