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
