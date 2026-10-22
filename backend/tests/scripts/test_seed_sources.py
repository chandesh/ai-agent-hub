"""Tests for seeding the initial source configurations."""

from app.models import Source
from app.scripts.seed_sources import SOURCE_CONFIGS, seed_sources


def test_seed_sources_idempotent(db_session):
    seed_sources(db=db_session)
    count1 = db_session.query(Source).count()
    seed_sources(db=db_session)
    count2 = db_session.query(Source).count()

    assert count1 == count2 == 4


def test_seed_sources_have_required_config():
    by_name = {config["name"]: config for config in SOURCE_CONFIGS}

    assert set(by_name) == {
        "mcp_registry",
        "github_mcp_topic",
        "github_agents_topic",
        "curated_catalog",
    }
    assert by_name["mcp_registry"]["config"]["entity"] == "mcp_server"
    assert by_name["github_agents_topic"]["config"]["entity"] == "agent"
    assert by_name["curated_catalog"]["type"] == "curated"
