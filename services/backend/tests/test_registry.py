"""Registry resolution: known impls import their class; unknown/malformed fail loud."""

from __future__ import annotations

import pytest
from backend.domain.errors import ConfigurationError
from backend.wiring import registry

POSTGRES_REGISTRIES = [
    registry.SCHOOL_REPO_REGISTRY,
    registry.USER_REPO_REGISTRY,
    registry.STUDENT_REPO_REGISTRY,
    registry.EVENT_REPO_REGISTRY,
    registry.MEDIA_REPO_REGISTRY,
    registry.ML_RESULTS_READER_REGISTRY,
]

# Every (registry, impl) target must import to a class — a rename/typo fails loud here
# rather than at runtime wiring.
ALL_TARGETS = [
    (table, impl)
    for table in (
        registry.SCHOOL_REPO_REGISTRY,
        registry.USER_REPO_REGISTRY,
        registry.STUDENT_REPO_REGISTRY,
        registry.EVENT_REPO_REGISTRY,
        registry.MEDIA_REPO_REGISTRY,
        registry.ML_RESULTS_READER_REGISTRY,
        registry.EVENT_JOB_PRODUCER_REGISTRY,
        registry.OBJECT_STORE_REGISTRY,
        registry.ML_ENROLLMENT_CLIENT_REGISTRY,
        registry.WHATSAPP_SENDER_REGISTRY,
        registry.WHATSAPP_CONFIG_REPO_REGISTRY,
    )
    for impl in table
]


@pytest.mark.parametrize("table", POSTGRES_REGISTRIES)
def test_resolve_postgres_impl(table: dict[str, str]) -> None:
    cls = registry.resolve(table, "postgres")
    assert isinstance(cls, type)


@pytest.mark.parametrize("table,impl", ALL_TARGETS)
def test_every_registered_target_imports(table: dict[str, str], impl: str) -> None:
    assert isinstance(registry.resolve(table, impl), type)


def test_resolve_unknown_raises() -> None:
    with pytest.raises(ConfigurationError):
        registry.resolve(registry.SCHOOL_REPO_REGISTRY, "nope")
