"""Container wiring: adapters are built once (memoized) and disposal is clean.

No live DB — building the engine/sessionmaker/repos is lazy and does not connect.
"""

from __future__ import annotations

import pytest
from backend.domain.errors import ConfigurationError
from backend.settings import Settings
from backend.wiring.container import Container
from pydantic import SecretStr


async def test_container_memoizes_and_closes() -> None:
    container = Container(Settings(jwt_secret=SecretStr("x" * 32)))
    assert container.sessionmaker() is container.sessionmaker()
    assert container.school_repo() is container.school_repo()
    assert container.user_repo() is container.user_repo()
    assert container.password_hasher() is container.password_hasher()
    assert container.token_service() is container.token_service()
    assert container.permission_resolver() is container.permission_resolver()
    assert container.auth_service() is container.auth_service()
    await container.aclose()


async def test_container_builds_and_memoizes_student_stack() -> None:
    # local_fs + fake build without Supabase/ML creds and exercise the non-default
    # branches of object_store()/ml_enrollment_client() (decisions/0026).
    container = Container(
        Settings(
            jwt_secret=SecretStr("x" * 32),
            object_store_impl="local_fs",
            ml_enrollment_client_impl="fake",
            # Pin the sender impl so pydantic-settings can't read BE_WHATSAPP_SENDER_IMPL from a
            # local .env (e.g. =meta for a live smoke) and make the fake-branch assertion below
            # flaky — the same guard applied for faiss_lock_impl in BP8d's container test.
            whatsapp_sender_impl="fake",
        )
    )
    assert container.student_repo() is container.student_repo()
    assert container.object_store() is container.object_store()
    assert container.ml_enrollment_client() is container.ml_enrollment_client()
    assert container.student_service() is container.student_service()
    # BP28b: the admin-action audit repo + read service memoize too (lazy; no connect).
    assert container.admin_action_audit_repo() is container.admin_action_audit_repo()
    assert (
        container.admin_action_audit_service()
        is container.admin_action_audit_service()
    )
    # W1: the WhatsApp sender builds the fake under the default impl + memoizes; the config
    # service builds (repo lazy — no connect). None is wired into any service (no send yet).
    from backend.adapters.whatsapp.fake_sender import FakeWhatsAppSender

    assert isinstance(container.whatsapp_sender(), FakeWhatsAppSender)
    assert container.whatsapp_sender() is container.whatsapp_sender()
    assert container.whatsapp_config_service() is container.whatsapp_config_service()
    # W2: the send-log repo (postgres, lazy — no connect) + the share service memoize; the share
    # service is the FIRST place the sender is wired into a service.
    assert container.whatsapp_send_log_repo() is container.whatsapp_send_log_repo()
    assert container.whatsapp_share_service() is container.whatsapp_share_service()
    # W-live-test: the platform config repo (postgres, lazy — no connect) + its service memoize.
    assert container.platform_config_repo() is container.platform_config_repo()
    assert container.platform_config_service() is container.platform_config_service()
    await container.aclose()


async def test_container_builds_meta_whatsapp_sender() -> None:
    # Selecting BE_WHATSAPP_SENDER_IMPL=meta builds the Meta Cloud API adapter; the token + sender
    # phone-number ID are resolved per send from the DB (0098), not from settings/env.
    from backend.adapters.whatsapp.meta_sender import MetaWhatsAppSender

    container = Container(
        Settings(jwt_secret=SecretStr("x" * 32), whatsapp_sender_impl="meta")
    )
    sender = container.whatsapp_sender()
    assert isinstance(sender, MetaWhatsAppSender)
    assert container.whatsapp_sender() is sender  # memoized
    await container.aclose()


async def test_meta_token_resolved_from_db_only_no_env_fallback() -> None:
    # 0098: the Meta token is resolved FRESH per send by container._meta_token from the DB ONLY —
    # there is NO env fallback, so a stale .env value can never be used. Verified by swapping in a
    # fake platform-config repo (no DB / no connect).
    from datetime import UTC, datetime

    from backend.domain.models import PlatformConfig
    from backend_fakes import FakePlatformConfigRepo

    container = Container(
        Settings(jwt_secret=SecretStr("x" * 32), whatsapp_sender_impl="meta")
    )
    # No DB token → "" (never an env fallback).
    container._platform_config_repo = FakePlatformConfigRepo()
    assert await container._meta_token() == ""

    # The DB token is the only source.
    now = datetime.now(UTC)
    container._platform_config_repo = FakePlatformConfigRepo(
        PlatformConfig(
            id="platform",
            meta_access_token="db-token",
            sender_number=None,
            interim_test_number=None,
            interim_mode=False,
            created_at=now,
            updated_at=now,
        )
    )
    assert await container._meta_token() == "db-token"
    await container.aclose()


async def test_meta_phone_number_id_resolved_from_db_only_no_env_fallback() -> None:
    # 0098: the Meta sender phone-number ID is resolved FRESH per send by
    # container._meta_phone_number_id from the DB ONLY (the platform sender_number) — no env
    # fallback. Mirrors the token provider.
    from datetime import UTC, datetime

    from backend.domain.models import PlatformConfig
    from backend_fakes import FakePlatformConfigRepo

    container = Container(
        Settings(jwt_secret=SecretStr("x" * 32), whatsapp_sender_impl="meta")
    )
    # No DB sender_number → "" (never an env fallback).
    container._platform_config_repo = FakePlatformConfigRepo()
    assert await container._meta_phone_number_id() == ""

    # The DB sender_number is the only source.
    now = datetime.now(UTC)
    container._platform_config_repo = FakePlatformConfigRepo(
        PlatformConfig(
            id="platform",
            meta_access_token=None,
            sender_number="db-phone-id",
            interim_test_number=None,
            interim_mode=False,
            created_at=now,
            updated_at=now,
        )
    )
    assert await container._meta_phone_number_id() == "db-phone-id"
    await container.aclose()


async def test_container_unknown_whatsapp_impl_raises() -> None:
    # An impl not in the registry fails loud (registry.resolve) — never a silent no-op sender.
    container = Container(
        Settings(jwt_secret=SecretStr("x" * 32), whatsapp_sender_impl="bogus")
    )
    with pytest.raises(ConfigurationError):
        container.whatsapp_sender()
    await container.aclose()


async def test_container_builds_and_memoizes_event_media_stack() -> None:
    # inproc event-job producer + postgres repos build without Redis; local_fs object
    # store so media_service() builds without Supabase creds (0027).
    container = Container(
        Settings(
            jwt_secret=SecretStr("x" * 32),
            event_job_producer_impl="inproc",
            object_store_impl="local_fs",
        )
    )
    assert container.event_repo() is container.event_repo()
    assert container.media_repo() is container.media_repo()
    assert container.event_job_producer() is container.event_job_producer()
    assert container.event_service() is container.event_service()
    assert container.media_service() is container.media_service()
    await container.aclose()


async def test_container_builds_and_memoizes_gallery_stack() -> None:
    # ml-results reader (postgres, lazy — no connect) + gallery service; local_fs object
    # store so gallery_service() builds without Supabase creds (0028).
    container = Container(
        Settings(jwt_secret=SecretStr("x" * 32), object_store_impl="local_fs")
    )
    assert container.ml_results_reader() is container.ml_results_reader()
    assert container.gallery_service() is container.gallery_service()
    await container.aclose()


async def test_token_service_fails_loud_without_secret() -> None:
    # The real deploy path: no BE_JWT_SECRET -> building the token service (and thus
    # the auth service) fails loud rather than minting tokens with an empty key.
    container = Container(Settings(jwt_secret=SecretStr("")))
    with pytest.raises(ConfigurationError):
        container.token_service()
    await container.aclose()


async def test_check_readiness_empty_when_no_postgres() -> None:
    # When no postgres repo is selected there is nothing to probe -> empty map
    # (deterministic; the DB-up path is covered by gated integration tests).
    container = Container(Settings(repository_impl="none"))
    assert await container.check_readiness() == {}
    await container.aclose()
