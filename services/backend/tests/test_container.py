"""Container wiring: adapters are built once (memoized) and disposal is clean.

No live DB — building the engine/sessionmaker/repos is lazy and does not connect.
"""

from __future__ import annotations

from backend.settings import Settings
from backend.wiring.container import Container


async def test_container_memoizes_and_closes() -> None:
    container = Container(Settings())
    assert container.sessionmaker() is container.sessionmaker()
    assert container.school_repo() is container.school_repo()
    assert container.user_repo() is container.user_repo()
    await container.aclose()


async def test_check_readiness_empty_when_no_postgres() -> None:
    # When no postgres repo is selected there is nothing to probe -> empty map
    # (deterministic; the DB-up path is covered by gated integration tests).
    container = Container(Settings(repository_impl="none"))
    assert await container.check_readiness() == {}
    await container.aclose()
