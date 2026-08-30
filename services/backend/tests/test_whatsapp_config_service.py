"""WhatsAppConfigService + the response builder (W1).

Pure service over the fake repo: GET synthesizes a disabled default when unset; PUT upserts +
trims blanks to None; the response builder computes effective/shared-number. Tenant comes from
the route (passed as ``school_id``); nothing secret is ever touched.
"""

from __future__ import annotations

import pytest
from backend.api.schemas.whatsapp import WhatsAppConfigResponse
from backend.domain.errors import ValidationError
from backend.services.whatsapp_config_service import WhatsAppConfigService
from backend_fakes import FakeWhatsAppConfigRepo


def _svc(*, default_sender: str = "15550000000") -> WhatsAppConfigService:
    return WhatsAppConfigService(
        FakeWhatsAppConfigRepo(), default_sender_number=default_sender
    )


async def test_get_synthesizes_disabled_default_when_unset() -> None:
    config = await _svc().get_config(school_id="s1")
    assert config.school_id == "s1"
    assert config.enabled is False
    assert config.sender_number is None
    assert config.template_name is None
    assert config.business_name is None


async def test_set_upserts_and_get_returns_it() -> None:
    svc = _svc()
    saved = await svc.set_config(
        school_id="s1",
        enabled=True,
        sender_number="15551234567",
        template_name="photo_notice",
        business_name="Springfield Elementary",
    )
    assert saved.enabled is True
    assert saved.sender_number == "15551234567"
    reread = await svc.get_config(school_id="s1")
    assert reread.enabled is True
    assert reread.template_name == "photo_notice"
    assert reread.business_name == "Springfield Elementary"


async def test_set_blank_optionals_become_none() -> None:
    svc = _svc()
    saved = await svc.set_config(
        school_id="s1",
        enabled=False,
        sender_number="   ",
        template_name="",
        business_name="  ",
    )
    assert saved.sender_number is None
    assert saved.template_name is None
    assert saved.business_name is None


async def test_set_malformed_sender_number_rejected() -> None:
    with pytest.raises(ValidationError):
        await _svc().set_config(
            school_id="s1",
            enabled=True,
            sender_number="not-a-phone",
            template_name=None,
            business_name=None,
        )


async def test_set_upsert_updates_and_bumps_updated_at() -> None:
    svc = _svc()
    first = await svc.set_config(
        school_id="s1", enabled=False, sender_number=None,
        template_name=None, business_name=None,
    )
    second = await svc.set_config(
        school_id="s1", enabled=True, sender_number="15551234567",
        template_name=None, business_name=None,
    )
    assert second.created_at == first.created_at  # create time stable across a re-save
    assert second.updated_at > first.updated_at  # updated bumped


# ---- the response builder (effective / shared number) --------------------


async def test_response_uses_own_number_when_set() -> None:
    config = await _svc(default_sender="15550000000").set_config(
        school_id="s1", enabled=True, sender_number="15551234567",
        template_name=None, business_name=None,
    )
    resp = WhatsAppConfigResponse.from_config(
        config, default_sender_number="15550000000"
    )
    assert resp.using_shared_number is False
    assert resp.effective_sender_number == "15551234567"


async def test_response_falls_back_to_shared_number_when_unset() -> None:
    config = await _svc().get_config(school_id="s1")  # sender_number is None
    resp = WhatsAppConfigResponse.from_config(
        config, default_sender_number="15550000000"
    )
    assert resp.using_shared_number is True
    assert resp.effective_sender_number == "15550000000"


async def test_response_effective_none_when_no_own_and_no_shared() -> None:
    config = await _svc(default_sender="").get_config(school_id="s1")
    resp = WhatsAppConfigResponse.from_config(config, default_sender_number="")
    assert resp.using_shared_number is True  # not set its own
    assert resp.effective_sender_number is None  # and no shared platform number
