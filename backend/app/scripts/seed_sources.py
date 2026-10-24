"""Seed the initial ingestion source configurations.

Idempotent: existing sources (matched by name) are refreshed from SOURCE_CONFIGS.

Usage (inside the backend container):
    python -m app.scripts.seed_sources
"""

import logging

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models import Source

logger = logging.getLogger(__name__)

CATEGORY_MAPPING = {
    "keywords": {
        "filesystem|file system|file storage": "file-systems",
        "database|sql|postgres|mysql|sqlite|mongodb": "database",
        "browser|playwright|puppeteer|selenium": "browser-automation",
        "github|git|pull request|repository": "developer-tools",
        "api|rest|http|graphql": "api-integration",
        "memory|knowledge|rag|vector|embedding": "knowledge-memory",
        "security|auth|vulnerability|scan": "security",
    },
    "default": "developer-tools",
}

SOURCE_CONFIGS = [
    {
        "name": "mcp_registry",
        "display_name": "MCP Registry",
        "type": "api",
        "config": {
            "entity": "mcp_server",
            "endpoint": "https://registry.modelcontextprotocol.io/v0/servers",
            "method": "GET",
            "pagination": "cursor",
            "params": {"limit": 100},
            "rate_limit": {"requests_per_minute": 60},
            "expected_schema_url": (
                "https://static.modelcontextprotocol.io/schemas/"
                "2025-12-11/server.schema.json"
            ),
            "parser": {
                "item_path": "servers",
                "mappings": {
                    "name": "server.title || server.name",
                    "slug": "server.name",
                    "description": "server.description || server.title || server.name",
                    "repository_url": "server.repository.url || server.websiteUrl",
                    "npm_package": (
                        "server.packages[?(@.registryType=='npm')].identifier"
                    ),
                    "pypi_package": (
                        "server.packages[?(@.registryType=='pypi')].identifier"
                    ),
                    "scope": "server.remotes | scope_from_remotes",
                    "language": "server.packages[0].runtimeHint || 'Other'",
                    "external_id": "server.name",
                    "logo_url": "server.repository.url | extract_github_avatar",
                },
            },
            "category_mapping": CATEGORY_MAPPING,
        },
    },
    {
        "name": "github_mcp_topic",
        "display_name": "GitHub MCP Topic",
        "type": "github_search",
        "config": {
            "entity": "mcp_server",
            "endpoint": "https://api.github.com/search/repositories",
            "method": "GET",
            "pagination": "page",
            "params": {
                "q": "topic:mcp-server",
                "per_page": 100,
                "sort": "stars",
                "order": "desc",
            },
            "auth": {"type": "bearer", "env_var": "GITHUB_TOKEN"},
            "rate_limit": {
                "requests_per_minute": 25,
                "burst": 1,
                "max_retries": 3,
                "base_delay_sec": 2,
            },
            "parser": {
                "item_path": "items",
                "mappings": {
                    "name": "name",
                    "slug": "full_name",
                    "description": "description || name",
                    "repository_url": "html_url",
                    "language": "language || 'Other'",
                    "star_count": "stargazers_count",
                    "logo_url": "owner.avatar_url",
                    "external_id": "full_name",
                },
            },
            "category_mapping": CATEGORY_MAPPING,
        },
    },
    {
        "name": "github_agents_topic",
        "display_name": "GitHub Agents Topic",
        "type": "github_search",
        "config": {
            "entity": "agent",
            "endpoint": "https://api.github.com/search/repositories",
            "method": "GET",
            "pagination": "page",
            "params": {
                "q": "topic:ai-agents fork:false archived:false stars:>5",
                "per_page": 100,
                "sort": "stars",
                "order": "desc",
            },
            "auth": {"type": "bearer", "env_var": "GITHUB_TOKEN"},
            "rate_limit": {
                "requests_per_minute": 25,
                "burst": 1,
                "max_retries": 3,
                "base_delay_sec": 2,
            },
            "parser": {
                "item_path": "items",
                "mappings": {
                    "name": "name",
                    "slug": "full_name",
                    "description": "description || name",
                    "website_url": "html_url",
                    "repository_url": "html_url",
                    "language": "language || 'Other'",
                    "star_count": "stargazers_count",
                    "logo_url": "owner.avatar_url",
                    "external_id": "full_name",
                    "pricing_model": "'free'",
                },
            },
            "category_mapping": {
                "keywords": CATEGORY_MAPPING["keywords"],
                "default": "development",
            },
        },
    },
    {
        "name": "curated_catalog",
        "display_name": "Curated Agent Catalog",
        "type": "curated",
        "config": {
            "entity": "agent",
            "parser": {
                "item_path": "CATALOG",
                "module": "app.scripts.agent_catalog",
                "mappings": {
                    "name": "name",
                    "slug": "slug",
                    "description": "description",
                    "short_description": "short_description",
                    "website_url": "website_url",
                    "logo_url": "logo_url",
                    "category": "category",
                    "pricing_model": "pricing_model",
                    "featured": "featured",
                    "tags": "tags",
                },
            },
        },
    },
]


def seed_sources(db: Session | None = None) -> None:
    """Insert any missing source rows."""
    owns_session = db is None
    db = db or SessionLocal()
    try:
        existing = {source.name: source for source in db.query(Source).all()}
        for config in SOURCE_CONFIGS:
            source = existing.get(config["name"])
            if source is None:
                db.add(Source(**config))
                logger.info("Seeding source %s", config["name"])
                continue
            source.display_name = config["display_name"]
            source.type = config["type"]
            source.config = config["config"]
        db.commit()
    finally:
        if owns_session:
            db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed_sources()
