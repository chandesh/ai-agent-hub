"""Ingestion parsers.

Concrete parsers register themselves with :class:`ParserFactory`; importing
this package makes all supported source types available.
"""

from app.scripts.parsers.base import BaseParser, ParserFactory
from app.scripts.parsers.api import APIParser
from app.scripts.parsers.curated import CuratedParser
from app.scripts.parsers.github_search import GitHubSearchParser

ParserFactory.register("api", APIParser)
ParserFactory.register("github_search", GitHubSearchParser)
ParserFactory.register("curated", CuratedParser)

__all__ = [
    "BaseParser",
    "ParserFactory",
    "APIParser",
    "GitHubSearchParser",
    "CuratedParser",
]
