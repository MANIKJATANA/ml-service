"""The ``/metrics`` endpoint + the HTTP metrics middleware (decisions/0029).

Built without the lifespan (bare ``TestClient(create_app())``): the middleware and
the scrape endpoint need no container/DB, so this stays a fast unit test. The
collectors live on the process-global default registry, so assertions are
membership checks, not exact counts.
"""

from __future__ import annotations

from backend.main import create_app
from fastapi.testclient import TestClient


def test_metrics_endpoint_reports_requests_by_route_template() -> None:
    client = TestClient(create_app())

    assert client.get("/healthz").status_code == 200
    resp = client.get("/metrics")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    assert "backend_http_requests_total" in body
    assert "backend_http_request_duration_seconds" in body
    # The matched ROUTE TEMPLATE is the label (here it carries no path params).
    assert 'route="/healthz"' in body


def test_parametrized_route_records_template_not_concrete_id() -> None:
    client = TestClient(create_app())

    # Unauthenticated: the route still MATCHES (populating scope["route"]) before the
    # auth dependency returns 401, so metrics see the TEMPLATE — not the concrete id.
    resp = client.get("/v1/events/evt-CONCRETE-9137/status")
    assert resp.status_code == 401

    body = client.get("/metrics").text
    assert 'route="/v1/events/{event_id}/status"' in body
    assert "evt-CONCRETE-9137" not in body  # the concrete id never became a label


def test_unmatched_paths_collapse_to_one_label_no_id_leak() -> None:
    client = TestClient(create_app())

    # A concrete id in an unmatched path must NOT become its own label series.
    assert client.get("/nope/9999123").status_code == 404
    body = client.get("/metrics").text

    assert 'route="__unmatched__"' in body
    assert "9999123" not in body  # the concrete path never became a label
