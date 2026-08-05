"""The read-only data layer, held in memory.

In production this is BigQuery behind the same narrow interface. Note what is
absent: there is no method that takes SQL, so the agent's entire reach into the
data is the parameterised surface below.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import numpy.typing as npt
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline

from complaints_intelligence.fixtures import (
    load_complaints,
    load_facts,
    load_resolutions,
)
from complaints_intelligence.inputs import (
    ComplaintEnvelope,
    ComplaintStatus,
    Fact,
    Precedent,
    ResolutionNote,
)

FloatMatrix = npt.NDArray[np.float64]

#: Similarity above which two complaints count as near-duplicate text.
_DUPLICATE_SIMILARITY = 0.95


class Embedder:
    """TF-IDF followed by truncated SVD — latent semantic indexing.

    A local, deterministic stand-in for a hosted embedding model: it captures
    term co-occurrence rather than meaning, and swapping it out is the whole of
    what migration requires.
    """

    def __init__(self, corpus: Sequence[str], *, dimensions: int = 64) -> None:
        vectoriser = TfidfVectorizer(
            lowercase=True,
            strip_accents="unicode",
            ngram_range=(1, 2),
            sublinear_tf=True,
        )
        tfidf = vectoriser.fit_transform(corpus)
        # SVD cannot produce more components than the feature space has rank;
        # clamping keeps a deliberately small fixture from hitting an opaque
        # scikit-learn error.
        components = max(2, min(dimensions, int(tfidf.shape[1]) - 1, len(corpus) - 1))
        # scikit-learn ships no type information, so a fitted Pipeline is Any
        # at this boundary; everything leaving this class is a typed array.
        self._pipeline: Any = Pipeline(
            [
                ("tfidf", vectoriser),
                ("svd", TruncatedSVD(n_components=components, random_state=0)),
            ]
        ).fit(corpus)

    def embed(self, texts: Sequence[str]) -> FloatMatrix:
        """Embed texts as unit-norm rows, so cosine similarity is a dot
        product."""
        vectors = np.asarray(self._pipeline.transform(texts), dtype=np.float64)
        # A text of entirely out-of-vocabulary tokens maps to the origin and
        # stays there, which makes it maximally dissimilar to everything — the
        # honest answer rather than an arbitrary direction.
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        normalised = np.divide(
            vectors, norms, out=np.zeros_like(vectors), where=norms > 0
        )
        return np.asarray(normalised, dtype=np.float64)

    def embed_one(self, text: str) -> FloatMatrix:
        return np.asarray(self.embed([text])[0], dtype=np.float64)


class Store:
    """Complaints, resolution notes and facts, with similarity search.

    One object rather than three repositories because they share a single
    embedding space; callers still depend on the narrow methods below, not on
    this class.
    """

    def __init__(
        self,
        complaints: Sequence[ComplaintEnvelope],
        resolutions: Sequence[ResolutionNote],
        facts: Sequence[Fact],
    ) -> None:
        self._complaints = tuple(complaints)
        self._by_id = {c.complaint_id: c for c in self._complaints}
        self._resolutions = {r.complaint_id: r for r in resolutions}
        self._facts = {f.id: f for f in facts}

        # One embedding space, fitted on complaint text, serving exemplar
        # retrieval, theme coherence and precedent retrieval alike. Distances
        # only mean the same thing on both sides of a comparison if both sides
        # were embedded together.
        self._embedder = Embedder([c.text for c in self._complaints])
        self._vectors = self._embedder.embed([c.text for c in self._complaints])
        self._row = {c.complaint_id: i for i, c in enumerate(self._complaints)}

    @classmethod
    def open(cls) -> Store:
        """Load the committed fixture."""
        return cls(load_complaints(), load_resolutions(), load_facts())

    # -- complaints -------------------------------------------------------

    def get_complaint(self, complaint_id: str) -> ComplaintEnvelope:
        try:
            return self._by_id[complaint_id]
        except KeyError as exc:
            msg = f"no complaint {complaint_id!r} in the store"
            raise KeyError(msg) from exc

    def exemplars(
        self,
        *,
        query_text: str,
        week: str,
        category: str | None = None,
        theme_id: str | None = None,
        limit: int = 6,
    ) -> tuple[ComplaintEnvelope, ...]:
        """Similarity search with metadata filters applied *before* ranking.

        Filtering first is a containment property, not an optimisation: an
        exemplar from the wrong week would silently misrepresent the finding it
        supports.
        """
        candidates = [
            c
            for c in self._complaints
            if c.week == week
            and (category is None or c.category == category)
            # Theme members are exactly the abstained records. A category
            # search must not pick them up: they were never counted in that
            # category's figures, so citing one under it would misattribute.
            and (
                c.candidate_theme_id == theme_id
                if theme_id is not None
                else c.candidate_theme_id is None
            )
        ]
        return self._rank(query_text, candidates, limit)

    def theme_members(self, theme_id: str) -> tuple[ComplaintEnvelope, ...]:
        return tuple(c for c in self._complaints if c.candidate_theme_id == theme_id)

    # -- measured cluster properties --------------------------------------

    def theme_coherence(self, theme_id: str) -> float:
        """Mean pairwise similarity between a cluster's members.

        Measured from the vectors rather than declared. Note that duplicated
        text scores very high here without being a real theme, which is why the
        brief carries three other signals alongside it.
        """
        similarity = self._member_similarity(theme_id)
        if similarity is None:
            return 0.0
        upper = np.triu_indices(similarity.shape[0], k=1)
        # Cosine runs to -1; the domain model constrains coherence to [0, 1],
        # and a cluster with no shared direction has zero coherence, not -0.3.
        return round(max(0.0, min(1.0, float(np.mean(similarity[upper])))), 2)

    def theme_duplicate_ratio(self, theme_id: str) -> float:
        """Share of members whose text near-duplicates another member's."""
        similarity = self._member_similarity(theme_id)
        if similarity is None:
            return 0.0
        np.fill_diagonal(similarity, 0.0)
        duplicated = int((similarity.max(axis=1) > _DUPLICATE_SIMILARITY).sum())
        return round(duplicated / int(similarity.shape[0]), 2)

    def theme_channel_concentration(self, theme_id: str) -> float:
        """Share of members arriving through the single dominant channel."""
        members = self.theme_members(theme_id)
        if not members:
            return 0.0
        counts: dict[str, int] = {}
        for member in members:
            counts[member.channel.value] = counts.get(member.channel.value, 0) + 1
        return round(max(counts.values()) / len(members), 2)

    # -- precedents -------------------------------------------------------

    def search_precedents(
        self, *, query_text: str, category: str | None = None, limit: int = 6
    ) -> tuple[Precedent, ...]:
        """Retrieve closed complaints with their resolution notes.

        Matched complaint-to-complaint and joined to the note, because a note
        read without the problem it responded to is an action with nothing to
        apply it to. Deliberately not scoped to a week: a precedent is useful
        precisely because it is historical.
        """
        candidates = [
            c
            for c in self._complaints
            if c.status is ComplaintStatus.CLOSED
            and c.complaint_id in self._resolutions
            and (category is None or c.category == category)
        ]
        return tuple(
            Precedent(complaint=c, resolution=self._resolutions[c.complaint_id])
            for c in self._rank(query_text, candidates, limit)
        )

    def get_resolution(self, complaint_id: str) -> ResolutionNote | None:
        return self._resolutions.get(complaint_id)

    # -- facts ------------------------------------------------------------

    def get_fact(self, fact_id: str) -> Fact:
        try:
            return self._facts[fact_id]
        except KeyError as exc:
            # Invariant 1 is an assertion: an unresolvable fact ID means a
            # figure was invented, and the run must fail rather than print it.
            msg = f"fact {fact_id!r} does not resolve in the fact store"
            raise KeyError(msg) from exc

    def fact_exists(self, fact_id: str) -> bool:
        return fact_id in self._facts

    def all_facts(self) -> tuple[Fact, ...]:
        return tuple(self._facts.values())

    # -- helpers ----------------------------------------------------------

    def _rank(
        self, query_text: str, candidates: Sequence[ComplaintEnvelope], limit: int
    ) -> tuple[ComplaintEnvelope, ...]:
        """Order candidates by similarity to the query, ties broken by ID so
        the result is stable for identical text."""
        if not candidates:
            return ()
        query = self._embedder.embed_one(query_text)
        scored = sorted(
            (
                (
                    -float(query @ self._vectors[self._row[c.complaint_id]]),
                    c.complaint_id,
                    c,
                )
                for c in candidates
            ),
            key=lambda row: (row[0], row[1]),
        )
        return tuple(complaint for _, _, complaint in scored[:limit])

    def _member_similarity(self, theme_id: str) -> FloatMatrix | None:
        """Member-by-member similarity matrix for a cluster, or None if the
        cluster is too small to have pairs."""
        members = self.theme_members(theme_id)
        if len(members) < 2:
            return None
        rows = np.array([self._vectors[self._row[m.complaint_id]] for m in members])
        return np.asarray(rows @ rows.T, dtype=np.float64)
