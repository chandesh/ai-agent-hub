"""End-to-end ingestion tests against live public APIs.

Skipped by default. Run with ``RUN_INTEGRATION=1``.
"""

import os

import pytest

from app.models import IngestionRun, MCPServer, Source
from app.scripts.ingest import ingest_source
from app.scripts.seed_sources import SOURCE_CONFIGS

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1",
        reason="set RUN_INTEGRATION=1 to run live integration tests",
    ),
]


def seed_source(db, name):
    config = next(item for item in SOURCE_CONFIGS if item["name"] == name)
    source = Source(**config)
    db.add(source)
    db.commit()
    return source


@pytest.mark.asyncio
async def test_ingest_mcp_registry_dry_run_live(db_session):
    seed_source(db_session, "mcp_registry")

    run = await ingest_source(
        "mcp_registry", limit=5, dry_run=True, db=db_session
    )

    assert run.items_seen == 5
    assert run.summary["would_create"] + run.summary["would_update"] == 5
    assert db_session.query(MCPServer).count() == 0
    assert db_session.query(IngestionRun).count() == 0


@pytest.mark.asyncio
async def test_ingest_mcp_registry_creates_rows_live(db_session):
    source = seed_source(db_session, "mcp_registry")

    run = await ingest_source("mcp_registry", limit=3, db=db_session)

    # The registry can return multiple versions of one server name, which
    # deduplicate onto the same row (created + updated == items seen).
    assert run.items_created >= 1
    assert run.items_created + run.items_updated == 3
    assert db_session.query(MCPServer).count() == run.items_created
    assert db_session.query(IngestionRun).count() == 1
    db_session.refresh(source)
    assert source.last_fetched_count == 3
