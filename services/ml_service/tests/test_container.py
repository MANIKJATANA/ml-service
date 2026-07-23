"""wiring.container: selector resolution, memoization, shared resources.

Exercises only CPU-safe adapters (local_fs media/index, opencv extractor, inproc
queue, postgres repos — which instantiate without connecting). The detector/
embedder and FAISS index (which needs the embedder version) load real models and
are covered by the Phase 2 adapter tests, so they are not built here.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from ml_service.adapters.media_store.local_fs import LocalFsMediaStore
from ml_service.adapters.queue.inproc_queue import InProcJobQueue
from ml_service.adapters.vector_index._locks import InProcLockProvider
from ml_service.adapters.vector_index._redis_locks import RedisLockProvider
from ml_service.adapters.video.opencv_extractor import OpenCvFrameExtractor
from ml_service.domain.errors import ConfigurationError
from ml_service.wiring.container import Container
from ml_service.wiring.settings import Settings


def _cpu_settings(**overrides: object) -> Settings:
    base: dict[str, object] = dict(
        media_store_impl="local_fs",
        index_store_impl="local_fs",
        video_extractor_impl="opencv",
        queue_impl="inproc",
        # Pin the impls explicitly (not via .env, which pydantic-settings would read for
        # any unset field) so the selector tests are deterministic on any host.
        faiss_lock_impl="inproc",
        media_dir="/tmp/media",
        index_store_dir="/tmp/faiss",
        database_url="postgresql+asyncpg://u:p@localhost:5432/db",
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_media_store_local_fs_memoized() -> None:
    c = Container(_cpu_settings())
    first = c.media_store()
    assert isinstance(first, LocalFsMediaStore)
    assert c.media_store() is first  # singleton


def test_extractor_and_queue_selectors() -> None:
    c = Container(_cpu_settings())
    assert isinstance(c.extractor(), OpenCvFrameExtractor)
    assert isinstance(c.job_queue(), InProcJobQueue)


def test_postgres_repos_share_one_sessionmaker() -> None:
    c = Container(_cpu_settings())
    # Instantiating the repos is lazy — no DB connection is opened here.
    assert c.match_repo() is c.match_repo()
    assert c.detection_repo() is c.detection_repo()
    sm = c.sessionmaker()
    assert c.threshold_provider() is not None
    assert c.reference_photos() is not None
    # The backend event store (roster read + status writes, 0027) shares the sessionmaker.
    assert c.backend_event_store() is c.backend_event_store()
    assert c.sessionmaker() is sm  # engine/sessionmaker built once, shared
    asyncio.run(c.aclose())


def test_unknown_media_impl_raises() -> None:
    c = Container(_cpu_settings(media_store_impl="s3"))
    with pytest.raises(ConfigurationError):
        c.media_store()


def test_write_lock_provider_inproc_default_memoized() -> None:
    c = Container(_cpu_settings())  # faiss_lock_impl defaults to "inproc"
    p = c.write_lock_provider()
    assert isinstance(p, InProcLockProvider)
    assert c.write_lock_provider() is p  # singleton — one per-school lock registry / process


def test_write_lock_provider_redis_selector() -> None:
    # redis-py builds the client lazily (no connection), so this instantiates offline.
    c = Container(_cpu_settings(faiss_lock_impl="redis"))
    assert isinstance(c.write_lock_provider(), RedisLockProvider)


def test_unknown_faiss_lock_impl_raises() -> None:
    c = Container(_cpu_settings(faiss_lock_impl="zookeeper"))
    with pytest.raises(ConfigurationError):
        c.write_lock_provider()


def test_aclose_is_idempotent() -> None:
    c = Container(_cpu_settings())
    c.match_repo()  # forces engine creation
    asyncio.run(c.aclose())
    asyncio.run(c.aclose())  # second close must not raise


def test_concurrent_build_returns_one_instance() -> None:
    # Two threads racing a cold getter (as FastAPI's threadpool would) must get
    # the same memoized instance — the container's lock prevents a double build.
    c = Container(_cpu_settings())
    with ThreadPoolExecutor(max_workers=8) as pool:
        instances = list(pool.map(lambda _: c.media_store(), range(8)))
    assert len({id(x) for x in instances}) == 1
