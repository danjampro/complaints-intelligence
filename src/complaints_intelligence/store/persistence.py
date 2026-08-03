"""Parquet persistence for the synthetic corpus and the fact store.

Domain models are flattened to columns on write and reconstructed on read.
The flattening is explicit rather than derived from the model, so a schema
change is a visible diff here rather than a silent change in file layout.

Evidence spans are held as a JSON string. They are a nested, variable-length
structure that no SQL view needs to filter on, and a JSON column round-trips
exactly without complicating every query that does not care about them.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from complaints_intelligence.domain.complaint import (
    Channel,
    ComplaintEnvelope,
    ComplaintStatus,
    Enrichment,
    EvidenceSpan,
    Outcome,
    ResolutionNote,
    RoutingDecision,
)
from complaints_intelligence.domain.fact import Fact, FactUnit, Provenance

COMPLAINT_SCHEMA = pa.schema(
    [
        ("complaint_id", pa.string()),
        ("channel", pa.string()),
        ("received_date", pa.date32()),
        ("week", pa.string()),
        ("product", pa.string()),
        ("text", pa.string()),
        ("status", pa.string()),
        ("category", pa.string()),
        ("taxonomy_version", pa.string()),
        ("confidence", pa.float64()),
        ("margin", pa.float64()),
        ("novelty", pa.float64()),
        ("sentiment", pa.float64()),
        ("vulnerability_flag", pa.bool_()),
        ("detriment_flag", pa.bool_()),
        ("routing", pa.string()),
        ("candidate_theme_id", pa.string()),
        ("evidence_spans", pa.string()),
        ("is_adversarial_fixture", pa.bool_()),
    ]
)

RESOLUTION_SCHEMA = pa.schema(
    [
        ("complaint_id", pa.string()),
        ("category", pa.string()),
        ("outcome", pa.string()),
        ("redress_gbp", pa.int64()),
        ("days_to_close", pa.int64()),
        ("text", pa.string()),
    ]
)

FACT_SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("run_id", pa.string()),
        ("label", pa.string()),
        ("value", pa.float64()),
        ("unit", pa.string()),
        ("taxonomy_version", pa.string()),
        ("provenance_view", pa.string()),
        ("provenance_params", pa.string()),
        ("category", pa.string()),
        ("channel", pa.string()),
        ("week", pa.string()),
    ]
)


#: Rows come from an untyped database driver, so values are genuinely Any.
#: Every reconstruction below coerces explicitly rather than trusting the type.
Row = Mapping[str, Any]


def _complaint_row(complaint: ComplaintEnvelope) -> dict[str, Any]:
    e = complaint.enrichment
    return {
        "complaint_id": complaint.complaint_id,
        "channel": complaint.channel.value,
        "received_date": complaint.received_date,
        "week": complaint.week,
        "product": complaint.product,
        "text": complaint.text,
        "status": complaint.status.value,
        "category": e.category,
        "taxonomy_version": e.taxonomy_version,
        "confidence": e.confidence,
        "margin": e.margin,
        "novelty": e.novelty,
        "sentiment": e.sentiment,
        "vulnerability_flag": e.vulnerability_flag,
        "detriment_flag": e.detriment_flag,
        "routing": e.routing.value,
        "candidate_theme_id": e.candidate_theme_id,
        "evidence_spans": json.dumps(
            [{"start": s.start, "end": s.end} for s in e.evidence_spans]
        ),
        "is_adversarial_fixture": complaint.is_adversarial_fixture,
    }


def complaint_from_row(row: Row) -> ComplaintEnvelope:
    """Reconstruct a complaint from a flat row.

    Used by every store implementation, so a DuckDB row and a BigQuery row
    produce identical objects.
    """
    spans = tuple(
        EvidenceSpan(start=int(s["start"]), end=int(s["end"]))
        for s in json.loads(str(row["evidence_spans"]))
    )
    enrichment = Enrichment(
        category=str(row["category"]),
        taxonomy_version=str(row["taxonomy_version"]),
        confidence=float(row["confidence"]),
        margin=float(row["margin"]),
        novelty=float(row["novelty"]),
        sentiment=float(row["sentiment"]),
        vulnerability_flag=bool(row["vulnerability_flag"]),
        detriment_flag=bool(row["detriment_flag"]),
        evidence_spans=spans,
        routing=RoutingDecision(str(row["routing"])),
        candidate_theme_id=(
            str(row["candidate_theme_id"])
            if row["candidate_theme_id"] is not None
            else None
        ),
    )
    return ComplaintEnvelope(
        complaint_id=str(row["complaint_id"]),
        channel=Channel(str(row["channel"])),
        received_date=row["received_date"],
        week=str(row["week"]),
        product=str(row["product"]),
        text=str(row["text"]),
        status=ComplaintStatus(str(row["status"])),
        enrichment=enrichment,
        is_adversarial_fixture=bool(row["is_adversarial_fixture"]),
    )


def resolution_from_row(row: Row) -> ResolutionNote:
    """Reconstruct a resolution note from a flat row."""
    return ResolutionNote(
        complaint_id=str(row["complaint_id"]),
        category=str(row["category"]),
        outcome=Outcome(str(row["outcome"])),
        redress_gbp=int(row["redress_gbp"]),
        days_to_close=int(row["days_to_close"]),
        text=str(row["text"]),
    )


def fact_from_row(row: Row) -> Fact:
    """Reconstruct a fact, including its provenance, from a flat row."""
    return Fact(
        id=str(row["id"]),
        run_id=str(row["run_id"]),
        label=str(row["label"]),
        value=float(row["value"]),
        unit=FactUnit(str(row["unit"])),
        taxonomy_version=str(row["taxonomy_version"]),
        provenance=Provenance(
            view=str(row["provenance_view"]),
            params=json.loads(str(row["provenance_params"])),
        ),
        category=str(row["category"]) if row["category"] is not None else None,
        channel=str(row["channel"]) if row["channel"] is not None else None,
        week=str(row["week"]) if row["week"] is not None else None,
    )


def write_complaints(complaints: tuple[ComplaintEnvelope, ...], path: Path) -> None:
    """Write complaints to Parquet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(
        [_complaint_row(c) for c in complaints], schema=COMPLAINT_SCHEMA
    )
    pq.write_table(table, path)


def write_resolutions(resolutions: tuple[ResolutionNote, ...], path: Path) -> None:
    """Write resolution notes to Parquet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        r.model_dump(mode="python") | {"outcome": r.outcome.value} for r in resolutions
    ]
    table = pa.Table.from_pylist(rows, schema=RESOLUTION_SCHEMA)
    pq.write_table(table, path)


def write_facts(facts: tuple[Fact, ...], path: Path) -> None:
    """Write the fact store to Parquet.

    Facts are written once per run and never mutated. A taxonomy re-projection
    produces a new run, not an edit.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "id": f.id,
            "run_id": f.run_id,
            "label": f.label,
            "value": f.value,
            "unit": f.unit.value,
            "taxonomy_version": f.taxonomy_version,
            "provenance_view": f.provenance.view,
            "provenance_params": json.dumps(f.provenance.params, sort_keys=True),
            "category": f.category,
            "channel": f.channel,
            "week": f.week,
        }
        for f in facts
    ]
    pq.write_table(pa.Table.from_pylist(rows, schema=FACT_SCHEMA), path)
