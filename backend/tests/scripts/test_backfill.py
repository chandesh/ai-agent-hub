"""Tests for backfilling ingestion tracking columns on legacy rows."""

from app.models import Agent, Category, MCPServer
from app.scripts.backfill_existing import backfill_existing


def _category(db_session):
    category = Category(name="Development", slug="development", description="")
    db_session.add(category)
    db_session.flush()
    return category


def test_backfill_populates_legacy(db_session):
    category = _category(db_session)
    agent = Agent(
        name="Test Agent",
        slug="test-agent",
        description="d",
        short_description="s",
        website_url="https://agent.test",
        category_id=category.id,
    )
    server = MCPServer(
        name="Test Server",
        slug="test-server",
        description="d",
        repository_url="https://github.com/x/y",
        language="Python",
        category_id=category.id,
    )
    db_session.add_all([agent, server])
    db_session.commit()

    backfill_existing(db=db_session)

    db_session.refresh(agent)
    db_session.refresh(server)
    assert agent.source == "legacy"
    assert agent.last_synced_at == agent.created_at
    assert agent.external_id == agent.slug
    assert server.source == "legacy"
    assert server.last_synced_at == server.created_at
    assert server.external_id == server.slug


def test_backfill_is_idempotent(db_session):
    category = _category(db_session)
    agent = Agent(
        name="Test Agent",
        slug="test-agent",
        description="d",
        short_description="s",
        website_url="https://agent.test",
        category_id=category.id,
    )
    db_session.add(agent)
    db_session.commit()

    backfill_existing(db=db_session)
    original = agent.last_synced_at
    backfill_existing(db=db_session)

    db_session.refresh(agent)
    assert agent.source == "legacy"
    assert agent.last_synced_at == original
