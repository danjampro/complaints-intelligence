"""Shared fixtures.

The store is session-scoped because fitting the embedding index is the only
slow step in the suite, and nothing mutates it — it is read-only by design.
"""

from __future__ import annotations

import pytest

from complaints_intelligence.brief import build_brief
from complaints_intelligence.config import Settings
from complaints_intelligence.fixtures import load_brief_spec
from complaints_intelligence.inputs import MetricsBrief
from complaints_intelligence.store import Store


@pytest.fixture(scope="session")
def store() -> Store:
    return Store.open()


@pytest.fixture(scope="session")
def brief(store: Store) -> MetricsBrief:
    return build_brief(store, load_brief_spec())


@pytest.fixture
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    return Settings(output_dir=tmp_path_factory.mktemp("out"))
