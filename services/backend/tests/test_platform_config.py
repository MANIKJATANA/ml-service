"""Platform config (W-live-test) — the service (partial update + masking) + the routes.

Platform-admin-only (``school:manage``): a school-admin / teacher / student is 403. The Meta
token is stored (owner decision) but NEVER returned in full — the response exposes only
``token_set``/``token_last4``. Partial updates: saving just the token leaves the interim
settings; saving just the number/mode leaves the token.
"""

from __future__ import annotations

from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.api.schemas.platform_config import PlatformConfigResponse
from backend.domain.models import Role, User
from backend.main import create_app
from backend.services.platform_config_service import PlatformConfigService
from backend_fakes import (
    FakePlatformConfigRepo,
    FakeSchoolRepo,
    FakeUserRepo,
    SeededContainer,
    make_school,
    make_user,
)
from fastapi.testclient import TestClient

_HASHER = Argon2PasswordHasher()
_SECRET = "meta-secret-token-abcd1234"


def _user(*, id: str, role: Role, school_id: str | None, email: str) -> User:
    user: User = make_user(
        id=id, school_id=school_id, email=email,
        password_hash=_HASHER.hash("pw"), role=role,
    )
    return user


# ---- service: get default + partial update ------------------------------


async def test_get_default_when_unset() -> None:
    service = PlatformConfigService(FakePlatformConfigRepo())
    config = await service.get_config()
    assert config.meta_access_token is None
    assert config.interim_test_number is None
    assert config.interim_mode is False


async def test_set_token_only_leaves_interim_settings() -> None:
    repo = FakePlatformConfigRepo()
    service = PlatformConfigService(repo)
    # First set interim settings...
    await service.set_config(interim_test_number="919999888877", interim_mode=True)
    # ...then set only the token — the interim settings must survive (partial update).
    after = await service.set_config(meta_access_token=_SECRET)
    assert after.meta_access_token == _SECRET
    assert after.interim_test_number == "919999888877"
    assert after.interim_mode is True


async def test_set_number_only_leaves_token() -> None:
    repo = FakePlatformConfigRepo()
    service = PlatformConfigService(repo)
    await service.set_config(meta_access_token=_SECRET)
    after = await service.set_config(interim_test_number="911112223333", interim_mode=True)
    assert after.meta_access_token == _SECRET  # unchanged
    assert after.interim_test_number == "911112223333"
    assert after.interim_mode is True


async def test_blank_strings_trim_to_none() -> None:
    service = PlatformConfigService(FakePlatformConfigRepo())
    after = await service.set_config(
        meta_access_token="   ", interim_test_number="  ", interim_mode=False
    )
    assert after.meta_access_token is None
    assert after.interim_test_number is None


async def test_set_sender_number_and_partial_update() -> None:
    repo = FakePlatformConfigRepo()
    service = PlatformConfigService(repo)
    after = await service.set_config(sender_number="106540388866237")
    assert after.sender_number == "106540388866237"
    # A later token-only save keeps the sender number (partial update).
    after = await service.set_config(meta_access_token=_SECRET)
    assert after.sender_number == "106540388866237"
    assert after.meta_access_token == _SECRET


async def test_set_template_name_and_partial_update() -> None:
    # 0099: the approved template lives on the platform config now. Set it, then a token-only save
    # keeps it (partial update); a blank clears it.
    repo = FakePlatformConfigRepo()
    service = PlatformConfigService(repo)
    after = await service.set_config(template_name="event_photos_util")
    assert after.template_name == "event_photos_util"
    after = await service.set_config(meta_access_token=_SECRET)
    assert after.template_name == "event_photos_util"  # unchanged
    after = await service.set_config(template_name="")
    assert after.template_name is None  # cleared


async def test_clearing_interim_number_turns_off_and_keeps_others() -> None:
    # The gate is now the interim number's PRESENCE (no toggle) — clearing it (a provided "") must
    # NULL it (turn interim off) while leaving the sender/token untouched. `None` = unchanged.
    repo = FakePlatformConfigRepo()
    service = PlatformConfigService(repo)
    await service.set_config(
        meta_access_token=_SECRET,
        sender_number="106540388866237",
        interim_test_number="919306229596",
    )
    # An explicit blank clears ONLY the interim number; omitted fields (None) stay.
    after = await service.set_config(interim_test_number="")
    assert after.interim_test_number is None  # cleared → interim OFF
    assert after.sender_number == "106540388866237"  # unchanged
    assert after.meta_access_token == _SECRET  # unchanged


# ---- masking: the response never carries the full token -----------------


async def test_response_masks_token() -> None:
    service = PlatformConfigService(FakePlatformConfigRepo())
    config = await service.set_config(meta_access_token=_SECRET, interim_mode=True)
    resp = PlatformConfigResponse.from_config(config)
    # The full token is never present; only a boolean + the last-4 hint.
    assert resp.token_set is True
    assert resp.token_last4 == _SECRET[-4:]
    dumped = resp.model_dump()
    assert _SECRET not in str(dumped)
    assert "meta_access_token" not in dumped  # the field itself isn't on the response


def test_response_no_token_when_unset() -> None:
    from datetime import UTC, datetime

    from backend.domain.models import PlatformConfig

    now = datetime.now(UTC)
    resp = PlatformConfigResponse.from_config(
        PlatformConfig(
            id="platform",
            meta_access_token=None,
            sender_number=None,
            template_name=None,
            interim_test_number=None,
            interim_mode=False,
            created_at=now,
            updated_at=now,
        )
    )
    assert resp.token_set is False
    assert resp.token_last4 is None
    assert resp.sender_number is None
    assert resp.template_name is None


def test_short_token_has_no_last4() -> None:
    from datetime import UTC, datetime

    from backend.domain.models import PlatformConfig

    now = datetime.now(UTC)
    resp = PlatformConfigResponse.from_config(
        PlatformConfig(
            id="platform",
            meta_access_token="abc",  # < 4 chars
            sender_number=None,
            template_name=None,
            interim_test_number=None,
            interim_mode=False,
            created_at=now,
            updated_at=now,
        )
    )
    assert resp.token_set is True
    assert resp.token_last4 is None  # never expose a < 4-char tail


# ---- routes: platform-admin only + PUT-then-GET reflects -----------------


def _client() -> TestClient:
    container = SeededContainer(
        FakeUserRepo(
            [
                _user(id="pa", role=Role.PLATFORM_ADMIN, school_id=None, email="pa@x.io"),
                _user(id="sa", role=Role.SCHOOL_ADMIN, school_id="s1", email="sa@x.io"),
                _user(id="t1", role=Role.TEACHER, school_id="s1", email="t1@x.io"),
            ]
        ),
        FakeSchoolRepo([make_school(id="s1", name="Alpha", max_teachers=10)]),
    )
    app = create_app()
    app.dependency_overrides[get_container_dep] = lambda: container
    return TestClient(app)


def _auth(client: TestClient, who: str) -> dict[str, str]:
    resp = client.post("/v1/auth/login", json={"email": f"{who}@x.io", "password": "pw"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_route_get_default_masked() -> None:
    client = _client()
    resp = client.get("/v1/platform/whatsapp-config", headers=_auth(client, "pa"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_set"] is False
    assert body["token_last4"] is None
    assert body["sender_number"] is None
    assert body["template_name"] is None
    assert body["interim_test_number"] is None
    assert "meta_access_token" not in body  # the secret is never in the response
    assert "interim_mode" not in body  # the toggle was dropped from the API surface


def test_route_put_then_get_reflects_and_masks() -> None:
    client = _client()
    hdr = _auth(client, "pa")
    put = client.put(
        "/v1/platform/whatsapp-config",
        headers=hdr,
        json={
            "meta_access_token": _SECRET,
            "sender_number": "106540388866237",
            "template_name": "event_photos_util",
            "interim_test_number": "919999888877",
        },
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["token_set"] is True
    assert body["token_last4"] == _SECRET[-4:]
    assert body["sender_number"] == "106540388866237"
    assert body["template_name"] == "event_photos_util"
    assert body["interim_test_number"] == "919999888877"
    assert _SECRET not in put.text  # the full token never appears in the response body

    reread = client.get("/v1/platform/whatsapp-config", headers=hdr).json()
    assert reread["token_set"] is True
    assert reread["sender_number"] == "106540388866237"
    assert reread["template_name"] == "event_photos_util"
    assert reread["interim_test_number"] == "919999888877"


def test_route_partial_update_keeps_token() -> None:
    client = _client()
    hdr = _auth(client, "pa")
    client.put(
        "/v1/platform/whatsapp-config",
        headers=hdr,
        json={"meta_access_token": _SECRET},
    )
    # Now update only the interim number — the token stays set (partial update).
    client.put(
        "/v1/platform/whatsapp-config",
        headers=hdr,
        json={"interim_test_number": "911112223333"},
    )
    body = client.get("/v1/platform/whatsapp-config", headers=hdr).json()
    assert body["token_set"] is True  # still set
    assert body["interim_test_number"] == "911112223333"


def test_route_school_admin_is_403() -> None:
    client = _client()
    hdr = _auth(client, "sa")
    assert client.get("/v1/platform/whatsapp-config", headers=hdr).status_code == 403
    assert (
        client.put(
            "/v1/platform/whatsapp-config",
            headers=hdr,
            json={"interim_test_number": "911"},
        ).status_code
        == 403
    )


def test_route_teacher_is_403() -> None:
    client = _client()
    hdr = _auth(client, "t1")
    assert client.get("/v1/platform/whatsapp-config", headers=hdr).status_code == 403
