"""Acceptance criteria:
- Archive preparation is idempotent: only one manifest exists per trading day; repeated
  after-hours worker loops do not create duplicate manifests or repeated FINNIFTY readiness alerts.
"""

import os

import pymongo


MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "app")


def test_export_manifest_is_unique_per_trading_day(client):
    first = client.get("/market-data/export-archive")
    assert first.status_code == 200, first.text
    trading_day = first.json()["trading_day"]
    prepared_at = first.json()["prepared_at"]
    assert prepared_at is not None

    # Poll the endpoint again -- it must reflect the same persisted manifest, not a fresh one.
    second = client.get("/market-data/export-archive")
    assert second.status_code == 200, second.text
    assert second.json()["prepared_at"] == prepared_at, "prepared_at must not change across repeated reads"

    # Cross-check directly against Mongo: the worker loop runs every ~30s after close and must
    # short-circuit (find_one before insert_one) rather than inserting a duplicate manifest doc.
    mongo = pymongo.MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    try:
        count = mongo[DB_NAME].export_manifests.count_documents({"trading_day": trading_day})
        assert count == 1, f"expected exactly one export_manifests doc for {trading_day}, found {count}"
    finally:
        mongo.close()


def test_finnifty_export_ready_alert_is_deduplicated(client):
    # FINNIFTY has no verified snapshot yet per seed facts, so no EXPORT_READY alert should exist;
    # if/when it fires, the worker keys it by a stable per-day id so at most one can ever be stored.
    response = client.get("/market-data/feed-status")
    assert response.status_code == 200, response.text
    alerts = response.json().get("alerts", [])
    export_ready_ids = [alert["id"] for alert in alerts if alert.get("type") == "EXPORT_READY"]
    assert len(export_ready_ids) == len(set(export_ready_ids)), "EXPORT_READY alerts must be deduplicated by id"
