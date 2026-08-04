"""Embeddings for the RAG substrate.

``Embedder`` is the seam. The implementation used here is TF-IDF followed by
truncated SVD — latent semantic indexing — which is local, deterministic,
needs no download and fits in under a second at this corpus size. That is what
invariant 5 requires.

It is a stand-in, and worth being precise about what is lost. LSI captures
term co-occurrence, not meaning: it will not connect "double debit" to
"charged twice" unless those terms co-occur in the corpus. A hosted embedding
model would, and is the production choice. The protocol below is the whole of
what has to change to migrate.

The index is fitted on open rather than persisted. The resolution-notes index
is described in the architecture as derived and rebuildable; rebuilding it on
every open *is* that property, and it removes a class of failure where a stale
matrix silently misaligns with the text it claims to represent.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import Normalizer

from complaints_intelligence.config import EmbeddingConfig
from complaints_intelligence.logging import get_logger

log = get_logger(__name__)

FloatMatrix = npt.NDArray[np.float64]
FloatVector = npt.NDArray[np.float64]


@runtime_checkable
class Embedder(Protocol):
    """Turns text into unit-norm vectors.

    Vectors are unit-norm by contract, so cosine similarity is a dot product
    and the store's SQL does not have to normalise at query time.
    """

    @property
    def dimension(self) -> int:
        """Length of the vectors produced."""
        ...

    def embed(self, texts: Sequence[str]) -> FloatMatrix:
        """Embed a batch of texts as rows of a matrix."""
        ...


class TfidfSvdEmbedder:
    """TF-IDF + truncated SVD, fitted on a fixed corpus.

    Deterministic: the SVD's randomised solver is seeded, and nothing else
    draws randomness.
    """

    def __init__(self, config: EmbeddingConfig | None = None) -> None:
        self._config = config or EmbeddingConfig()
        # scikit-learn ships no type information, so a fitted Pipeline is Any
        # at this boundary regardless of how it is annotated. Everything
        # leaving this class is coerced to a typed array below.
        self._pipeline: Any | None = None
        self._dimension = 0

    @property
    def dimension(self) -> int:
        if self._pipeline is None:
            msg = "embedder used before fit()"
            raise RuntimeError(msg)
        return self._dimension

    def fit(self, corpus: Sequence[str]) -> TfidfSvdEmbedder:
        """Fit on the corpus. Returns self so construction can be chained."""
        cfg = self._config
        vectoriser = TfidfVectorizer(
            lowercase=True,
            strip_accents="unicode",
            ngram_range=cfg.ngram_range,
            min_df=cfg.min_df,
            max_df=cfg.max_df,
            sublinear_tf=True,
        )
        tfidf = vectoriser.fit_transform(corpus)

        # SVD cannot produce more components than the feature space has rank.
        # Clamping is preferable to failing on a small corpus: the fixtures are
        # deliberately small, and a reviewer trimming them should not hit an
        # opaque sklearn error.
        n_features = int(tfidf.shape[1])
        n_components = max(2, min(cfg.n_components, n_features - 1, len(corpus) - 1))
        if n_components < cfg.n_components:
            log.info(
                "svd_components_clamped",
                requested=cfg.n_components,
                actual=n_components,
                n_features=n_features,
                n_documents=len(corpus),
            )

        svd = TruncatedSVD(
            n_components=n_components,
            algorithm="randomized",
            random_state=cfg.seed,
        )
        normaliser = Normalizer(copy=False)

        self._pipeline = Pipeline(
            [("tfidf", vectoriser), ("svd", svd), ("norm", normaliser)]
        )
        # The vectoriser is already fitted; refitting the pipeline is the
        # simplest way to keep the three stages consistent, and costs
        # milliseconds at this size.
        self._pipeline.fit(corpus)
        self._dimension = n_components

        log.info(
            "embedder_fitted",
            documents=len(corpus),
            features=n_features,
            dimension=n_components,
        )
        return self

    def embed(self, texts: Sequence[str]) -> FloatMatrix:
        """Embed texts. Rows are unit-norm."""
        if self._pipeline is None:
            msg = "embedder used before fit()"
            raise RuntimeError(msg)
        if not texts:
            return np.zeros((0, self._dimension), dtype=np.float64)

        vectors = np.asarray(self._pipeline.transform(texts), dtype=np.float64)
        # TruncatedSVD output is not guaranteed non-zero; a text made entirely
        # of out-of-vocabulary tokens maps to the origin, which has no
        # direction. Leaving it at zero makes it maximally dissimilar to
        # everything, which is the honest answer.
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        normalised = np.divide(
            vectors, norms, out=np.zeros_like(vectors), where=norms > 0
        )
        return np.asarray(normalised, dtype=np.float64)

    def embed_one(self, text: str) -> FloatVector:
        """Embed a single text, returning a 1-D vector."""
        return np.asarray(self.embed([text])[0], dtype=np.float64)
