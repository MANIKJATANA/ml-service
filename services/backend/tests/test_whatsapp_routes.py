"""WhatsApp config routes (W1) — GET/PUT + the permission + tenant isolation.

School-admin-only (``whatsapp:manage``): a teacher and a platform admin are 403; two schools'
admins see only their own config. Nothing secret transits these routes; W1 saves settings and
sends nothing.
"""

from __future__ import annotations

from backend.adapters.security.argon2_hasher import Argon2PasswordHasher
from backend.api.deps import get_container_dep
from backend.domain.models import Role, User
from backend.main import create_app
from backend_fakes import (
    FakeSchoolRepo,
    FakeUserRepo,
    FakeWhatsAppConfigRepo,
    SeededContainer,
    make_school,
    make_user,
)
from fastapi.testclient import TestClient

_HASHER = Argon2PasswordHasher()


def _user(*, id: str, role: Role, school_id: str | None, email: str) -> User:
    user: User = make_user(
        id=id, school_id=school_id, email=email,
        password_hash=_HASHER.hash("pw"), role=role,
    )
    return user


def _body(
    *,
    enabled: bool,
    sender_number: str | None = None,
    template_name: str | None = None,
    business_name: str | None = None,
) -> dict[str, object]:
    return {
        "enabled": enabled,
        "sender_number": sender_number,
        "template_name": template_name,
        "business_name": business_name,
    }


def _client() -> TestClient:
    container = SeededContainer(
        FakeUserRepo(
            [
                _user(id="sa1", role=Role.SCHOOL_ADMIN, school_id="s1", email="sa1@x.io"),
                _user(id="sa2", role=Role.SCHOOL_ADMIN, school_id="s2", email="sa2@x.io"),
                _user(id="t1", role=Role.TEACHER, school_id="s1", email="t1@x.io"),
                _user(id="pa", role=Role.PLATFORM_ADMIN, school_id=None, email="pa@x.io"),
            ]
        ),
        FakeSchoolRepo(
            [
                make_school(id="s1", name="Alpha", max_teachers=10),
                make_school(id="s2", name="Beta", max_teachers=10),
            ]
        ),
        whatsapp_config=FakeWhatsAppConfigRepo(),
    )
    app = create_app()
    app.dependency_overrides[get_container_dep] = lambda: container
    return TestClient(app)


def _auth(client: TestClient, who: str) -> dict[str, str]:
    resp = client.post("/v1/auth/login", json={"email": f"{who}@x.io", "password": "pw"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_get_returns_disabled_default_when_unset() -> None:
    client = _client()
    resp = client.get("/v1/schools/whatsapp-config", headers=_auth(client, "sa1"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enabled"] is False
    assert body["sender_number"] is None
    assert body["using_shared_number"] is True


def test_put_then_get_reflects_fields() -> None:
    client = _client()
    hdr = _auth(client, "sa1")
    put = client.put(
        "/v1/schools/whatsapp-config",
        headers=hdr,
        json=_body(
            enabled=True,
            sender_number="15551234567",
            template_name="photo_notice",
            business_name="Alpha School",
        ),
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["enabled"] is True
    assert body["sender_number"] == "15551234567"
    assert body["effective_sender_number"] == "15551234567"
    assert body["using_shared_number"] is False
    assert body["template_name"] == "photo_notice"
    assert body["business_name"] == "Alpha School"

    reread = client.get("/v1/schools/whatsapp-config", headers=hdr).json()
    assert reread["enabled"] is True
    assert reread["template_name"] == "photo_notice"


def test_put_blank_sender_number_becomes_null() -> None:
    client = _client()
    hdr = _auth(client, "sa1")
    resp = client.put(
        "/v1/schools/whatsapp-config",
        headers=hdr,
        json=_body(enabled=True, sender_number="  "),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["sender_number"] is None
    assert resp.json()["using_shared_number"] is True


def test_put_malformed_sender_number_is_400() -> None:
    client = _client()
    resp = client.put(
        "/v1/schools/whatsapp-config",
        headers=_auth(client, "sa1"),
        json=_body(enabled=True, sender_number="not-a-phone"),
    )
    assert resp.status_code == 400, resp.text


def test_teacher_is_403() -> None:
    client = _client()
    hdr = _auth(client, "t1")
    assert client.get("/v1/schools/whatsapp-config", headers=hdr).status_code == 403
    assert (
        client.put(
            "/v1/schools/whatsapp-config",
            headers=hdr,
            json=_body(enabled=False),
        ).status_code
        == 403
    )


def test_platform_admin_is_403() -> None:
    client = _client()
    hdr = _auth(client, "pa")
    assert client.get("/v1/schools/whatsapp-config", headers=hdr).status_code == 403


def test_tenant_isolation_two_schools() -> None:
    client = _client()
    # School s1's admin saves an enabled config; s2's admin still sees a disabled default.
    client.put(
        "/v1/schools/whatsapp-config",
        headers=_auth(client, "sa1"),
        json=_body(enabled=True, sender_number="15551111111"),
    )
    s1 = client.get("/v1/schools/whatsapp-config", headers=_auth(client, "sa1")).json()
    s2 = client.get("/v1/schools/whatsapp-config", headers=_auth(client, "sa2")).json()
    assert s1["school_id"] == "s1" and s1["enabled"] is True
    assert s1["sender_number"] == "15551111111"
    # s2 never sees s1's data — its own is still the synthesized default.
    assert s2["school_id"] == "s2" and s2["enabled"] is False
    assert s2["sender_number"] is None
