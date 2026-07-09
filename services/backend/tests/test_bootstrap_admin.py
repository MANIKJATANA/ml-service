"""The platform-admin bootstrap CLI (decisions/0024).

Only the pure argument/guard logic is unit-tested here; the DB-touching create path
is covered by the gated Postgres suite.
"""

from __future__ import annotations

from backend.cli.bootstrap_admin import main


def test_short_password_is_rejected_before_touching_the_db() -> None:
    # The length guard runs before _create(), so no DB/container is built.
    code = main(["--email", "ops@x.io", "--password", "short"])
    assert code == 2
