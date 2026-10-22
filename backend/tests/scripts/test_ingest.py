"""Tests for the generic ingestion runner."""

import pytest

from app.models import IngestionRun, MCPServer, Source
from app.scripts.ingest import ingest_source


def add_source(db, name="mcp_registry", type_="api", entity="mcp_server", **config):
    source = Source(
        name=name,
        display_name=name,
        type=type_,
        config={"entity": entity, "parser": {"item_path": "items"}, **config},
    )
    db.add(source)
    db.commit()
    return source


def make_parser(mocker, items, parsed_items, next_pages=None):
    parser = mocker.Mock()
    parser.get_items.return_value = items
    parser.fetch_page = mocker.AsyncMock(return_value={"items": items})
    parser.has_next_page.return_value = False
    parser.next_page_token.return_value = None
    parser.parse.side_effect = parsed_items
    parser.close = mocker.AsyncMock()
    mocker.patch("app.scripts.ingest.ParserFactory.build", return_value=parser)
    return parser


@pytest.mark.asyncio
async def test_ingest_source_dry_run(db_session, mocker):
    add_source(db_session)
    make_parser(
        mocker,
        [{"server": {}}, {"server": {}}],
        [
            {
                "external_id": "com.example/a",
                "name": "A",
                "slug": "a",
                "repository_url": "https://github.com/example/a",
                "language": "Python",
            },
            {
                "external_id": "com.example/b",
                "name": "B",
                "slug": "b",
                "repository_url": "https://github.com/example/b",
                "language": "Python",
            },
        ],
    )

    run = await ingest_source("mcp_registry", limit=2, dry_run=True, db=db_session)

    assert run.items_seen == 2
    assert run.items_created == 0
    assert run.items_updated == 0
    assert run.summary["would_create"] == 2
    assert db_session.query(MCPServer).count() == 0
    assert db_session.query(IngestionRun).count() == 0


@pytest.mark.asyncio
async def test_ingest_source_creates_rows(db_session, mocker):
    add_source(db_session)
    make_parser(
        mocker,
        [{"server": {}}],
        [
            {
                "external_id": "com.example/a",
                "name": "A",
                "slug": "a",
                "repository_url": "https://github.com/example/a",
                "language": "Python",
            }
        ],
    )

    run = await ingest_source("mcp_registry", db=db_session)

    assert run.items_created == 1
    server = db_session.query(MCPServer).one()
    assert server.source == "mcp_registry"
    assert server.external_id == "com.example/a"
    assert server.last_synced_at is not None
    assert db_session.query(IngestionRun).count() == 1


@pytest.mark.asyncio
async def test_cross_source_reingest_updates_source(db_session, mocker):
    add_source(db_session, name="mcp_registry")
    add_source(db_session, name="github_mcp_topic", type_="github_search")

    common = {
        "slug": "a",
        "repository_url": "https://github.com/example/a",
        "language": "Python",
    }
    make_parser(
        mocker,
        [{"server": {}}],
        [dict(common, external_id="com.example/a", name="A")],
    )
    await ingest_source("mcp_registry", db=db_session)

    make_parser(
        mocker,
        [{"server": {}}],
        [dict(common, external_id="example/a", name="A from GitHub", star_count=42)],
    )
    await ingest_source("github_mcp_topic", db=db_session)

    servers = db_session.query(MCPServer).all()
    assert len(servers) == 1
    assert servers[0].source == "github_mcp_topic"
    assert servers[0].external_id == "example/a"
    assert servers[0].star_count == 42


@pytest.mark.asyncio
async def test_enrich_only_skips_unknown_rows(db_session, mocker):
    add_source(db_session, name="github_mcp_topic", type_="github_search")
    make_parser(
        mocker,
        [{"server": {}}],
        [
            {
                "external_id": "unknown/a",
                "name": "A",
                "slug": "a",
                "repository_url": "https://github.com/unknown/a",
                "language": "Python",
            }
        ],
    )

    run = await ingest_source(
        "github_mcp_topic", enrich_only=True, db=db_session
    )

    assert db_session.query(MCPServer).count() == 0
    assert run.summary["would_skip"] == 1


@pytest.mark.asyncio
async def test_schema_mismatch_marks_source_error(db_session, mocker):
    source = add_source(db_session, expected_schema_url="https://example/schema")
    parser = make_parser(
        mocker,
        [{"server": {"$schema": "https://example/other"}}],
        [{"external_id": "x", "name": "X", "slug": "x"}],
    )
    parser._check_schema.return_value = False

    run = await ingest_source("mcp_registry", db=db_session)

    db_session.refresh(source)
    assert source.status == "error"
    assert "Schema" in source.last_error
    assert run.items_seen == 0


@pytest.mark.asyncio
async def test_item_missing_required_field_is_counted_not_raised(db_session, mocker):
    add_source(db_session)
    make_parser(
        mocker,
        [{"server": {}}],
        [{"external_id": "com.example/broken", "name": "Broken", "slug": "broken"}],
    )

    run = await ingest_source("mcp_registry", db=db_session)

    assert run.items_failed == 1
    assert run.items_created == 0
    assert db_session.query(MCPServer).count() == 0


@pytest.mark.asyncio
async def test_missing_repository_url_falls_back_to_endpoint(db_session, mocker):
    add_source(db_session, endpoint="https://registry.example/servers")
    make_parser(
        mocker,
        [{"server": {}}],
        [{"external_id": "com.example/a", "name": "A", "slug": "a"}],
    )

    run = await ingest_source("mcp_registry", db=db_session)

    assert run.items_created == 1
    server = db_session.query(MCPServer).one()
    assert server.repository_url == (
        "https://registry.example/servers/com.example/a"
    )


@pytest.mark.asyncio
async def test_same_name_repos_do_not_collapse(db_session, mocker):
    add_source(db_session, name="github_mcp_topic", type_="github_search")
    make_parser(
        mocker,
        [{"item": 1}, {"item": 2}],
        [
            {
                "external_id": "alice/mcp-server",
                "name": "mcp-server",
                "slug": "alice-mcp-server",
                "repository_url": "https://github.com/alice/mcp-server",
                "language": "Python",
            },
            {
                "external_id": "bob/mcp-server",
                "name": "mcp-server",
                "slug": "bob-mcp-server",
                "repository_url": "https://github.com/bob/mcp-server",
                "language": "Python",
            },
        ],
    )

    await ingest_source("github_mcp_topic", db=db_session)

    assert db_session.query(MCPServer).count() == 2


@pytest.mark.asyncio
async def test_same_external_id_matches_despite_different_url(db_session, mocker):
    add_source(db_session)
    make_parser(
        mocker,
        [{"item": 1}, {"item": 2}],
        [
            {
                "external_id": "shared/server",
                "name": "Server",
                "slug": "server-a",
                "repository_url": "https://github.com/a/server",
                "language": "Python",
            },
            {
                "external_id": "shared/server",
                "name": "Server Renamed",
                "slug": "server-b",
                "repository_url": "https://github.com/b/server",
                "language": "Python",
            },
        ],
    )

    run = await ingest_source("mcp_registry", db=db_session)

    assert db_session.query(MCPServer).count() == 1
    assert run.items_created == 1
    assert run.items_updated == 1
    assert db_session.query(MCPServer).one().name == "Server Renamed"


@pytest.mark.asyncio
async def test_fetch_error_records_failed_run(db_session, mocker):
    source = add_source(db_session)
    parser = mocker.Mock()
    parser.fetch_page = mocker.AsyncMock(side_effect=RuntimeError("boom"))
    parser.get_items.return_value = []
    parser.close = mocker.AsyncMock()
    mocker.patch("app.scripts.ingest.ParserFactory.build", return_value=parser)

    run = await ingest_source("mcp_registry", db=db_session)

    db_session.refresh(source)
    assert run.failed is True
    assert "boom" in run.error_summary
    assert source.status == "error"
    assert db_session.query(IngestionRun).count() == 1


@pytest.mark.asyncio
async def test_successful_run_clears_error_status(db_session, mocker):
    source = add_source(db_session)
    source.status = "error"
    source.last_error = "old failure"
    db_session.commit()
    make_parser(
        mocker,
        [{"server": {}}],
        [
            {
                "external_id": "com.example/a",
                "name": "A",
                "slug": "a",
                "repository_url": "https://github.com/example/a",
                "language": "Python",
            }
        ],
    )

    await ingest_source("mcp_registry", db=db_session)

    db_session.refresh(source)
    assert source.status == "active"
    assert source.last_error is None


@pytest.mark.asyncio
async def test_empty_response_marks_empty(db_session, mocker):
    add_source(db_session)
    make_parser(mocker, [], [])

    run = await ingest_source("mcp_registry", db=db_session)

    assert run.items_seen == 0
    assert run.empty is True


def test_order_sources_priority():
    from app.scripts.ingest import _order_sources

    ordered = _order_sources(
        ["curated_catalog", "github_agents_topic", "mcp_registry"]
    )

    assert ordered == ["mcp_registry", "github_agents_topic", "curated_catalog"]
