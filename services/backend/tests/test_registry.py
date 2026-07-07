"""Registry resolution: known impls import their class; unknown/malformed fail loud."""

from __future__ import annotations

import pytest
from backend.domain.errors import ConfigurationError
from backend.wiring import registry

ALL_REGISTRIES = [registry.SCHOOL_REPO_REGISTRY, registry.USER_REPO_REGISTRY]


@pytest.mark.parametrize("table", ALL_REGISTRIES)
def test_resolve_postgres_impl(table: dict[str, str]) -> None:
    cls = registry.resolve(table, "postgres")
    assert isinstance(cls, type)


def test_resolve_unknown_raises() -> None:
    with pytest.raises(ConfigurationError):
        registry.resolve(registry.SCHOOL_REPO_REGISTRY, "nope")
