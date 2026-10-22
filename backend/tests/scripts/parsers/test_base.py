"""Tests for the parser base class, factory, and mapping evaluator."""

import pytest

from app.scripts.parsers.base import BaseParser, ParserFactory
from app.scripts.parsers.mapping import evaluate_mappings


class StubParser(BaseParser):
    def fetch_page(self, page_token):
        raise NotImplementedError

    def has_next_page(self, response):
        return False

    def next_page_token(self, response):
        return None


def test_mapping_evaluation():
    raw = {
        "server": {
            "title": "Test",
            "name": "test",
            "packages": [{"registryType": "npm", "identifier": "pkg"}],
        }
    }
    mappings = {
        "name": "server.title",
        "npm_package": "server.packages[?(@.registryType=='npm')].identifier",
    }
    result = evaluate_mappings(raw, mappings)

    assert result["name"] == "Test"
    assert result["npm_package"] == "pkg"


def test_mapping_defaults_and_literals():
    raw = {"server": {"title": "Test", "packages": []}}

    result = evaluate_mappings(
        raw,
        {
            "language": "server.packages[0].runtimeHint || 'Other'",
            "pricing_model": "'free'",
            "scope": "server.remotes | scope_from_remotes",
        },
    )

    assert result["language"] == "Other"
    assert result["pricing_model"] == "free"
    assert result["scope"] == "local"


def test_mapping_handles_missing_optional_fields():
    raw = {"server": {"title": "Test"}}

    result = evaluate_mappings(
        raw,
        {
            "description": "server.description",
            "repository_url": "server.repository.url",
            "npm_package": "server.packages[?(@.registryType=='npm')].identifier",
        },
    )

    assert result == {
        "description": None,
        "repository_url": None,
        "npm_package": None,
    }


def test_extract_github_avatar_filter():
    raw = {"repository": {"url": "https://github.com/acme/tools"}}

    result = evaluate_mappings(
        raw, {"logo_url": "repository.url | extract_github_avatar"}
    )

    assert result["logo_url"] == "https://github.com/acme.png?size=200"


def test_parser_factory_builds_registered_parser():
    ParserFactory.register("stub", StubParser)
    config = {"parser": {"item_path": "items", "mappings": {}}}

    parser = ParserFactory.build("stub", config)

    assert isinstance(parser, StubParser)
    assert parser.item_path == "items"


def test_parser_factory_rejects_unknown_type():
    config = {"parser": {"item_path": "items", "mappings": {}}}

    with pytest.raises(ValueError, match="Unknown parser type"):
        ParserFactory.build("does-not-exist", config)
