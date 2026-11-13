"""FastAPI lifespan & optional live BigQuery `cymbal_retail_my` reachability tests."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from google.cloud import bigquery

from api.main import build_fastapi_app
from api.platform.config import settings


def test_lifespan_and_health_real_wire(monkeypatch: pytest.MonkeyPatch) -> None:
    """Entering TestClient executes the real FastAPI lifespan startup/shutdown hooks."""
    if not settings.GCP_PROJECT_ID.strip():
        monkeypatch.setattr(settings, "GCP_PROJECT_ID", "example-gcp-project")
    fresh_app = build_fastapi_app()
    with TestClient(fresh_app) as live_client:
        res = live_client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "healthy"


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_GCP_TESTS") != "1",
    reason="Set RUN_LIVE_GCP_TESTS=1 and GCP_PROJECT_ID after running `make seed` to verify live BigQuery dataset.",
)
def test_bigquery_cymbal_retail_my_dataset_reachable() -> None:
    """Verify the seeded `cymbal_retail_my` dataset exists in BigQuery."""
    bq = bigquery.Client(project=settings.GCP_PROJECT_ID, location="US")
    ds = bq.get_dataset(f"{settings.GCP_PROJECT_ID}.{settings.BQ_DATASET_ID}")
    assert ds.dataset_id == settings.BQ_DATASET_ID
