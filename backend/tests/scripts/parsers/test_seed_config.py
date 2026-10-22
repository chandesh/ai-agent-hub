"""Offline checks that seeded configs map real payload shapes correctly."""

from app.scripts.parsers import ParserFactory
from app.scripts.seed_sources import SOURCE_CONFIGS

CONFIGS = {config["name"]: config for config in SOURCE_CONFIGS}


def test_github_seed_config_maps_full_name_to_slug():
    parser = ParserFactory.build("github_search", CONFIGS["github_mcp_topic"]["config"])

    parsed = parser.parse(
        {
            "name": "mcp-server",
            "full_name": "alice/mcp-server",
            "html_url": "https://github.com/alice/mcp-server",
            "description": "A server",
            "language": "Python",
            "stargazers_count": 10,
            "owner": {"avatar_url": "https://avatars.githubusercontent.com/u/1"},
        }
    )

    assert parsed["slug"] == "alice/mcp-server"
    assert parsed["external_id"] == "alice/mcp-server"
    assert parsed["star_count"] == 10


def test_registry_seed_config_parses_repository_and_remotes():
    parser = ParserFactory.build("api", CONFIGS["mcp_registry"]["config"])

    parsed = parser.parse(
        {
            "server": {
                "name": "com.example/server",
                "title": "Example",
                "description": "Does things",
                "repository": {"url": "https://github.com/example/server"},
                "remotes": [{"type": "streamable-http", "url": "https://example.test"}],
            }
        }
    )

    assert parsed["name"] == "Example"
    assert parsed["scope"] == "cloud"
    assert parsed["logo_url"] == "https://github.com/example.png?size=200"


def test_registry_seed_config_handles_missing_optional_fields():
    parser = ParserFactory.build("api", CONFIGS["mcp_registry"]["config"])

    parsed = parser.parse({"server": {"name": "com.example/minimal"}})

    assert parsed["name"] == "com.example/minimal"
    assert parsed["repository_url"] is None
    assert parsed["npm_package"] is None
