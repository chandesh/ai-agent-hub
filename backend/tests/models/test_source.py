"""Tests for Source and IngestionRun models."""

from app.models.source import IngestionRun, Source


def test_source_creation(db_session):
    source = Source(name="test", display_name="Test", type="api", config={})
    db_session.add(source)
    db_session.commit()

    assert source.id is not None
    assert source.status == "active"


def test_ingestion_run_relationship(db_session):
    source = Source(name="test", display_name="Test", type="api", config={})
    db_session.add(source)
    db_session.flush()

    run = IngestionRun(source_id=source.id)
    db_session.add(run)
    db_session.commit()

    assert run.source_id == source.id
    assert run.started_at is not None
    assert run.source is source
