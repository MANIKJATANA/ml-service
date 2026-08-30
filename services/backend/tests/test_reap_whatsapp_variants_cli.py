"""W3a: the reaper CLI's argument guard (cli/reap_whatsapp_variants.py).

The reaper decision path is covered in test_whatsapp_variant_reaper.py; here we lock the CLI's
``--older-than-hours`` guard, which must reject a <= 0 window at argparse — BEFORE the container
is built or the store is touched (a <= 0 window would reap fresh, in-flight variants).
"""

from __future__ import annotations

import argparse

import pytest
from backend.cli.reap_whatsapp_variants import _positive_hours, main


def test_positive_hours_rejects_non_positive() -> None:
    for bad in ("0", "-1", "-0.5"):
        with pytest.raises(argparse.ArgumentTypeError):
            _positive_hours(bad)
    # A positive value parses to a float.
    assert _positive_hours("24") == 24.0
    assert _positive_hours("0.5") == 0.5


@pytest.mark.parametrize("bad", ["0", "-1"])
def test_cli_rejects_non_positive_hours_before_building_anything(
    bad: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # If the guard failed to fire at argparse, main() would reach Container(...) — make that a
    # loud failure so we prove the guard runs FIRST (argparse exits 2 before this is touched).
    def _boom(*_a: object, **_k: object) -> object:
        raise AssertionError("container built despite an invalid --older-than-hours")

    monkeypatch.setattr("backend.cli.reap_whatsapp_variants.Container", _boom)
    with pytest.raises(SystemExit) as exc:
        main(["--older-than-hours", bad])
    assert exc.value.code == 2  # argparse usage error
