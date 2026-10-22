"""Tests for the GitHub Search parser."""

import pytest

from app.scripts.parsers.base import ParserFactory
from app.scripts.parsers.github_search import GitHubSearchParser

CONFIG = {
    "endpoint": "https://api.github.com/search/repositories",
    "params": {"q": "topic:mcp-server", "per_page": 100},
    "rate_limit": {"max_retries": 2, "base_delay_sec": 0},
    "parser": {"item_path": "items", "mappings": {"name": "name"}},
}


@pytest.mark.asyncio
async def test_github_parser_rate_limit_backoff(httpx_mock):
    httpx_mock.add_response(
        status_code=429, headers={"X-RateLimit-Remaining": "0"}
    )
    httpx_mock.add_response(json={"items": [{"name": "test"}]})
    parser = GitHubSearchParser(CONFIG)

    page = await parser.fetch_page(1)

    assert page["items"][0]["name"] == "test"
    await parser.close()


@pytest.mark.asyncio
async def test_github_parser_raises_after_max_retries(httpx_mock):
    for _ in range(3):
        httpx_mock.add_response(
            status_code=429, headers={"X-RateLimit-Remaining": "0"}
        )
    parser = GitHubSearchParser(CONFIG)

    with pytest.raises(RuntimeError, match="Max retries exceeded"):
        await parser.fetch_page(1)

    await parser.close()


@pytest.mark.asyncio
async def test_github_parser_tracks_page_token(httpx_mock):
    httpx_mock.add_response(json={"items": [{"name": "a"}]})
    httpx_mock.add_response(json={"items": []})
    parser = GitHubSearchParser(CONFIG)

    first = await parser.fetch_page(1)
    assert parser.next_page_token(first) == 2
    assert parser.has_next_page(first) is True

    second = await parser.fetch_page(2)
    assert parser.has_next_page(second) is False
    await parser.close()


def test_github_parser_registered():
    assert isinstance(ParserFactory.build("github_search", CONFIG), GitHubSearchParser)
