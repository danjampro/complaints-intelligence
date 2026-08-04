"""DuckDB implementation of the repository protocols.

Stands in for BigQuery. The SQL is real SQL against real Parquet, and the
views carry the names used in architecture section 7, so what a reviewer reads
here is close to what would run in production. Dialect deltas are recorded in
the header of ``sql/views.sql``.

Vector search uses ``array_cosine_similarity`` with metadata filters applied
before ranking — the same shape as BigQuery's ``VECTOR_SEARCH`` with a
pre-filter, so the query does not have to be rewritten to migrate.

Note what this class does *not* expose: there is no method taking SQL. The
agent's entire reach into the store is the parameterised surface declared in
``protocols.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import duckdb
import numpy as np
import pyarrow as pa

from complaints_intelligence.config import Settings
from complaints_intelligence.domain.complaint import (
    ComplaintEnvelope,
    Precedent,
    ResolutionNote,
)
from complaints_intelligence.domain.fact import Fact
from complaints_intelligence.errors import ProvenanceError
from complaints_intelligence.logging import get_logger
from complaints_intelligence.retrieval.embedder import TfidfSvdEmbedder
from complaints_intelligence.store.persistence import (
    complaint_from_row,
    fact_from_row,
    precedent_from_row,
    resolution_from_row,
)

log = get_logger(__name__)

_SQL_DIR = Path(__file__).parent / "sql"


class DuckDBStore:
    """A single connection serving all three repository protocols.

    One object rather than three because they share a connection and an
    embedding index; splitting them would mean fitting the index three times
    or introducing a shared-state object that is a connection by another name.
    Callers still depend on the narrow protocols, not on this class.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._conn = duckdb.connect(":memory:")
        self._complaint_embedder: TfidfSvdEmbedder | None = None
        self._facts_loaded = False
        self._column_cache: dict[str, tuple[str, ...]] = {}

    # -- lifecycle --------------------------------------------------------

    @classmethod
    def open(cls, settings: Settings, *, with_facts: bool = True) -> DuckDBStore:
        """Load Parquet, create views, and fit the retrieval indexes."""
        store = cls(settings)
        store._load_complaints()
        store._load_resolutions()
        if with_facts and settings.facts_path.exists():
            store._load_facts()
        store._create_views()
        store._build_indexes()
        return store

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- loading ----------------------------------------------------------

    def _load_complaints(self) -> None:
        path = self._settings.complaints_path
        if not path.exists():
            msg = f"complaint store not found at {path}; run `ci generate-data` first"
            raise FileNotFoundError(msg)
        self._conn.execute(
            "CREATE OR REPLACE TABLE complaints AS SELECT * FROM read_parquet(?)",
            [str(path)],
        )

    def _load_resolutions(self) -> None:
        path = self._settings.resolutions_path
        if not path.exists():
            msg = f"resolution notes not found at {path}; run `ci generate-data` first"
            raise FileNotFoundError(msg)
        self._conn.execute(
            "CREATE OR REPLACE TABLE resolutions AS SELECT * FROM read_parquet(?)",
            [str(path)],
        )

    def _load_facts(self) -> None:
        self._conn.execute(
            "CREATE OR REPLACE TABLE facts AS SELECT * FROM read_parquet(?)",
            [str(self._settings.facts_path)],
        )
        self._facts_loaded = True

    def _create_views(self) -> None:
        self._conn.execute((_SQL_DIR / "views.sql").read_text(encoding="utf-8"))

    def _build_indexes(self) -> None:
        """Fit the embedder and materialise vectors as DuckDB columns.

        **One embedding space, fitted on complaint text, serving every
        consumer** — exemplar retrieval, theme coherence, and precedent
        retrieval alike. In production this is a single
        ``SEMANTIC_SIMILARITY`` column; see the pipeline architecture,
        §Embedding strategy.

        A shared space is required wherever two things are compared to each
        other rather than to a query — theme centroids against category
        centroids, say — because distances have to mean the same thing on both
        sides. Precedent retrieval joins that requirement rather than
        contradicting it: it matches a complaint against the complaint text of
        closed cases and reaches the note by a join, which is a symmetric
        like-for-like comparison.

        Embedding the notes as their own corpus and searching those directly
        was the earlier approach and is worse. It is asymmetric retrieval — the
        query is a description of a problem, the documents are terse,
        jargon-heavy accounts of what a handler did about one — so the
        embedding is asked to bridge "customer could not make a payment" to
        "reversed the fee and reset the payee limit". Complaints are richer,
        more consistent, and already in the space the query is written for.
        """
        complaint_rows = self._conn.execute(
            "SELECT complaint_id, text FROM complaints ORDER BY complaint_id"
        ).fetchall()
        texts = [str(r[1]) for r in complaint_rows]
        self._complaint_embedder = TfidfSvdEmbedder(self._settings.embedding).fit(texts)
        self._register_vectors(
            table="complaint_vectors",
            ids=[str(r[0]) for r in complaint_rows],
            vectors=self._complaint_embedder.embed(texts),
        )

    def _register_vectors(
        self, *, table: str, ids: list[str], vectors: np.ndarray[Any, Any]
    ) -> None:
        """Materialise an embedding matrix as a DuckDB table of FLOAT arrays.

        Loaded via Arrow rather than row-by-row ``executemany``. Inserting a
        thousand 128-element arrays one statement at a time takes over a
        minute; a single zero-copy Arrow scan takes milliseconds. That matters
        because the reviewer's whole demo has a two-minute budget.
        """
        dimension = int(vectors.shape[1])
        flat = pa.array(vectors.ravel().astype(np.float32), type=pa.float32())
        arrow_table = pa.table(
            {
                "complaint_id": pa.array(ids, type=pa.string()),
                "vec": pa.FixedSizeListArray.from_arrays(flat, dimension),
            }
        )
        # `table` is a module-controlled literal, never caller input.
        view_name = f"_arrow_{table}"
        self._conn.register(view_name, arrow_table)
        self._conn.execute(
            f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM {view_name}"  # noqa: S608
        )
        self._conn.unregister(view_name)

    # -- ComplaintRepository ---------------------------------------------

    def get_complaint(self, complaint_id: str) -> ComplaintEnvelope:
        rows = self._conn.execute(
            "SELECT * FROM complaints WHERE complaint_id = ?", [complaint_id]
        ).fetchall()
        if not rows:
            msg = f"no complaint {complaint_id!r} in the store"
            raise KeyError(msg)
        return complaint_from_row(self._as_dict("complaints", rows[0]))

    def get_complaints(
        self, complaint_ids: Sequence[str]
    ) -> tuple[ComplaintEnvelope, ...]:
        if not complaint_ids:
            return ()
        by_id = {cid: self.get_complaint(cid) for cid in dict.fromkeys(complaint_ids)}
        return tuple(by_id[cid] for cid in complaint_ids if cid in by_id)

    def exemplars(
        self,
        *,
        query_text: str,
        week: str,
        category: str | None = None,
        theme_id: str | None = None,
        channel: str | None = None,
        limit: int = 6,
    ) -> tuple[ComplaintEnvelope, ...]:
        """Vector search with metadata pre-filter.

        Filters are applied inside the query, before ranking, so a request
        scoped to a week and category cannot return anything outside it. That
        is a containment property, not an optimisation: an exemplar from the
        wrong week would silently misrepresent the finding it supports.
        """
        assert self._complaint_embedder is not None  # noqa: S101 - set in open()
        query_vector = self._complaint_embedder.embed_one(query_text).tolist()

        predicates = ["c.week = ?"]
        params: list[Any] = [week]
        if category is not None:
            predicates.append("c.category = ?")
            params.append(category)
        if theme_id is not None:
            predicates.append("c.candidate_theme_id = ?")
            params.append(theme_id)
        if channel is not None:
            predicates.append("c.channel = ?")
            params.append(channel)

        sql = f"""
            SELECT c.*, array_cosine_similarity(v.vec, ?::FLOAT[{len(query_vector)}])
                   AS similarity
            FROM complaints c
            JOIN complaint_vectors v USING (complaint_id)
            WHERE {" AND ".join(predicates)}
            ORDER BY similarity DESC, c.complaint_id
            LIMIT ?
        """  # noqa: S608 - predicates are literals; every value is bound
        rows = self._conn.execute(sql, [query_vector, *params, limit]).fetchall()
        columns = [d[0] for d in self._conn.description or []]
        return tuple(
            complaint_from_row(dict(zip(columns, row, strict=True))) for row in rows
        )

    def theme_coherence(self, theme_id: str, week: str) -> float:
        """Mean pairwise cosine similarity between a theme's members.

        Measured from the vectors rather than declared. Coherence is one of
        the few honest signals separating a real emerging theme from a batch
        of duplicated notes, and a declared value would carry no information.

        The self-join is O(n²) in cluster size, which is fine for clusters of
        tens. At production scale this would be sampled.
        """
        row = self._conn.execute(
            """
            SELECT AVG(array_cosine_similarity(a.vec, b.vec)) AS coherence
            FROM complaints ca
            JOIN complaint_vectors a ON a.complaint_id = ca.complaint_id
            JOIN complaints cb
              ON cb.candidate_theme_id = ca.candidate_theme_id
             AND cb.week = ca.week
             AND cb.complaint_id > ca.complaint_id
            JOIN complaint_vectors b ON b.complaint_id = cb.complaint_id
            WHERE ca.candidate_theme_id = ? AND ca.week = ?
            """,
            [theme_id, week],
        ).fetchone()
        if not row or row[0] is None:
            return 0.0
        # Cosine similarity is in [-1, 1]; the domain model constrains
        # coherence to [0, 1]. Negative mean similarity means a cluster with
        # no shared direction at all, which is zero coherence, not -0.3.
        return max(0.0, min(1.0, float(row[0])))

    def category_counts(self, week: str) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT category, complaint_count FROM v_weekly_category_counts "
            "WHERE week = ? ORDER BY category",
            [week],
        ).fetchall()
        return {str(r[0]): int(r[1]) for r in rows}

    def theme_members(self, theme_id: str, week: str) -> tuple[ComplaintEnvelope, ...]:
        rows = self._conn.execute(
            "SELECT * FROM complaints WHERE candidate_theme_id = ? AND week = ? "
            "ORDER BY complaint_id",
            [theme_id, week],
        ).fetchall()
        return tuple(
            complaint_from_row(self._as_dict("complaints", row)) for row in rows
        )

    # -- PrecedentRepository ----------------------------------------------

    def search_precedents(
        self,
        *,
        query_text: str,
        category: str | None = None,
        limit: int = 6,
    ) -> tuple[Precedent, ...]:
        """Vector search over closed complaints, joined to their notes.

        Complaint-to-complaint, in the single complaint embedding space. The
        candidate set is ``v_precedent`` — closed, with a note — so the
        restriction is applied before ranking rather than as a filter over the
        results. Post-filtering would quietly return fewer precedents than
        asked for whenever the nearest complaints happened to be open.

        Deliberately not scoped to a week. A precedent is useful precisely
        because it is historical, and the remediation node widens further by
        dropping ``category`` on its second pass.
        """
        assert self._complaint_embedder is not None  # noqa: S101 - set in open()
        query_vector = self._complaint_embedder.embed_one(query_text).tolist()

        predicates = ["TRUE"]
        params: list[Any] = []
        if category is not None:
            predicates.append("p.category = ?")
            params.append(category)

        sql = f"""
            SELECT p.*, array_cosine_similarity(v.vec, ?::FLOAT[{len(query_vector)}])
                   AS similarity
            FROM v_precedent p
            JOIN complaint_vectors v USING (complaint_id)
            WHERE {" AND ".join(predicates)}
            ORDER BY similarity DESC, p.complaint_id
            LIMIT ?
        """  # noqa: S608 - predicates are literals; every value is bound
        rows = self._conn.execute(sql, [query_vector, *params, limit]).fetchall()
        columns = [d[0] for d in self._conn.description or []]
        return tuple(
            precedent_from_row(dict(zip(columns, row, strict=True))) for row in rows
        )

    def get_resolution(self, complaint_id: str) -> ResolutionNote | None:
        rows = self._conn.execute(
            "SELECT * FROM resolutions WHERE complaint_id = ?", [complaint_id]
        ).fetchall()
        if not rows:
            return None
        return resolution_from_row(self._as_dict("resolutions", rows[0]))

    # -- FactStore --------------------------------------------------------

    def get_fact(self, fact_id: str) -> Fact:
        if not self._facts_loaded:
            msg = "fact store not loaded; run `ci build-facts` first"
            raise ProvenanceError(msg)
        rows = self._conn.execute(
            "SELECT * FROM facts WHERE id = ?", [fact_id]
        ).fetchall()
        if not rows:
            # Invariant 1 is an assertion. An unresolvable fact ID means a
            # figure was invented, and the run must fail rather than print it.
            msg = f"fact {fact_id!r} does not resolve in the fact store"
            raise ProvenanceError(msg)
        return fact_from_row(self._as_dict("facts", rows[0]))

    def all_facts(self) -> tuple[Fact, ...]:
        if not self._facts_loaded:
            return ()
        rows = self._conn.execute("SELECT * FROM facts ORDER BY id").fetchall()
        return tuple(fact_from_row(self._as_dict("facts", row)) for row in rows)

    def fact_exists(self, fact_id: str) -> bool:
        if not self._facts_loaded:
            return False
        row = self._conn.execute(
            "SELECT COUNT(*) FROM facts WHERE id = ?", [fact_id]
        ).fetchone()
        return bool(row and row[0])

    # -- metrics-layer access --------------------------------------------

    def query_view(
        self, view: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Read an allowlisted view with equality filters only.

        Used by the metrics layer to derive facts, and by the ``query_metrics``
        tool. The view name is checked against the views actually defined in
        ``views.sql``, and filter values are always bound — a caller cannot
        smuggle a predicate through either the name or the values.
        """
        if view not in self.available_views():
            msg = f"view {view!r} is not available; allowed: {self.available_views()}"
            raise KeyError(msg)

        params = params or {}
        columns = self._view_columns(view)
        unknown = set(params) - set(columns)
        if unknown:
            msg = f"unknown filter columns for {view}: {sorted(unknown)}"
            raise KeyError(msg)

        # `ORDER BY ALL` is not cosmetic. Without it DuckDB returns
        # aggregate results in hash order, which varies between runs and
        # would make the derived facts — and therefore the report — differ
        # for identical input. Invariant 6 is a property of the whole
        # pipeline, and it fails here first.
        predicates = " AND ".join(f"{c} = ?" for c in params) or "TRUE"
        sql = f"SELECT * FROM {view} WHERE {predicates} ORDER BY ALL"  # noqa: S608
        rows = self._conn.execute(sql, list(params.values())).fetchall()
        names = [d[0] for d in self._conn.description or []]
        return [dict(zip(names, row, strict=True)) for row in rows]

    def available_views(self) -> tuple[str, ...]:
        rows = self._conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_type = 'VIEW' ORDER BY table_name"
        ).fetchall()
        return tuple(str(r[0]) for r in rows)

    # -- helpers ----------------------------------------------------------

    def _view_columns(self, relation: str) -> tuple[str, ...]:
        """Column names for a table or view, cached.

        Called once per reconstructed row otherwise, which turns a cheap
        lookup into an information_schema query per complaint.
        """
        cached = self._column_cache.get(relation)
        if cached is not None:
            return cached
        rows = self._conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? ORDER BY ordinal_position",
            [relation],
        ).fetchall()
        columns = tuple(str(r[0]) for r in rows)
        self._column_cache[relation] = columns
        return columns

    def _as_dict(self, table: str, row: tuple[Any, ...]) -> dict[str, Any]:
        return dict(zip(self._view_columns(table), row, strict=True))
