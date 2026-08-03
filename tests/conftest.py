"""Shared fixtures.

The corpus is generated once per session into a temporary directory. It takes
a second to build and every store test needs it; regenerating per test would
dominate the suite's runtime without testing anything extra.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from complaints_intelligence.config import (
    BASELINE_WEEK,
    REPORTING_WEEK,
    TAXONOMY_VERSION,
    Settings,
)
from complaints_intelligence.domain.brief import MetricsBrief
from complaints_intelligence.metrics.brief import build_brief
from complaints_intelligence.metrics.facts import FactSet, derive_facts
from complaints_intelligence.metrics.statistics import VelocityTest
from complaints_intelligence.store.duckdb_store import DuckDBStore
from complaints_intelligence.store.persistence import (
    write_complaints,
    write_facts,
    write_resolutions,
)
from complaints_intelligence.synth.generator import Dataset, generate
from complaints_intelligence.synth.signals import THEME_SIGNALS


@pytest.fixture(scope="session")
def dataset() -> Dataset:
    """The synthetic corpus at the default seed."""
    return generate()


@pytest.fixture(scope="session")
def settings(tmp_path_factory: pytest.TempPathFactory, dataset: Dataset) -> Settings:
    """Settings pointing at a temporary data directory holding the corpus."""
    data_dir = tmp_path_factory.mktemp("data")
    built = Settings(data_dir=data_dir, output_dir=data_dir / "out")
    write_complaints(dataset.complaints, built.complaints_path)
    write_resolutions(dataset.resolutions, built.resolutions_path)
    return built


@pytest.fixture(scope="session")
def _derived(settings: Settings) -> tuple[FactSet, list[VelocityTest]]:
    """Facts and velocity tests, derived once and written to Parquet."""
    with DuckDBStore.open(settings, with_facts=False) as store:
        facts, tests = derive_facts(
            store,
            run_id=REPORTING_WEEK,
            week=REPORTING_WEEK,
            baseline_week=BASELINE_WEEK,
            taxonomy_version=TAXONOMY_VERSION,
            thresholds=settings.brief,
        )
    write_facts(facts.as_tuple(), settings.facts_path)
    return facts, tests


@pytest.fixture
def store(
    settings: Settings, _derived: tuple[FactSet, list[VelocityTest]]
) -> Iterator[DuckDBStore]:
    """An open store with facts loaded."""
    opened = DuckDBStore.open(settings)
    yield opened
    opened.close()


@pytest.fixture
def brief(
    store: DuckDBStore,
    settings: Settings,
    _derived: tuple[FactSet, list[VelocityTest]],
) -> MetricsBrief:
    """The metrics brief for the reporting week."""
    facts, tests = _derived
    return build_brief(
        store,
        facts,
        tests,
        run_id=REPORTING_WEEK,
        week=REPORTING_WEEK,
        baseline_week=BASELINE_WEEK,
        taxonomy_version=TAXONOMY_VERSION,
        thresholds=settings.brief,
        persistence={t.theme_id: t.persistence_weeks for t in THEME_SIGNALS},
    )


@pytest.fixture(scope="session")
def source_root() -> Path:
    """Root of the package source, for tests that read the code itself."""
    import complaints_intelligence

    return Path(complaints_intelligence.__file__).parent
