"""Tests for the API parser used by the MCP Registry source."""

import pytest

from app.scripts.parsers.api import APIParser
from app.scripts.parsers.base import ParserFactory

CONFIG = {
    "endpoint": "https://registry.modelcontextprotocol.io/v0/servers",
    "params": {"limit": 100},
    "parser": {
        "item_path": "servers",
        "mappings": {
            "name": "server.title",
            "slug": "server.name",
        },
    },
}


@pytest.mark.asyncio
async def test_api_parser_fetch_first_page(httpx_mock):
    httpx_mock.add_response(
        url="https://registry.modelcontextprotocol.io/v0/servers?limit=100",
        json={"servers": [{"server": {"name": "test", "title": "Test"}}]},
    )
    parser = APIParser(CONFIG)

    page = await parser.fetch_page(None)

    assert "servers" in page
    await parser.close()


@pytest.mark.asyncio
async def test_api_parser_paginates_with_cursor(httpx_mock):
    httpx_mock.add_response(
        url="https://registry.modelcontextprotocol.io/v0/servers?limit=100&cursor=abc",
        json={"servers": [], "metadata": {"nextCursor": "def"}},
    )
    parser = APIParser(CONFIG)

    page = await parser.fetch_page("abc")

    assert parser.has_next_page(page) is True
    assert parser.next_page_token(page) == "def"
    await parser.close()


def test_schema_version_check():
    config = dict(CONFIG, expected_schema_url=(
        "https://static.modelcontextprotocol.io/schemas/2025-09-29/server.schema.json"
    ))
    parser = APIParser(config)
    good = {
        "server": {
            "$schema": "https://static.modelcontextprotocol.io/schemas/2025-09-29/server.schema.json"
        }
    }
    bad = {
        "server": {
            "$schema": "https://static.modelcontextprotocol.io/schemas/2026-01-01/server.schema.json"
        }
    }

    assert parser._check_schema(good) is True
    assert parser._check_schema(bad) is False


def test_api_parser_registered():
    assert isinstance(ParserFactory.build("api", CONFIG), APIParser)
