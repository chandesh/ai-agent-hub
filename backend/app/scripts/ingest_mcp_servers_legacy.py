"""Ingest top MCP servers from GitHub into the database.

Fetches GitHub repositories matching `mcp-server in:name` sorted by stars,
filters out curated-list false positives, and upserts them into the database.
Re-runs are safe: existing servers are matched by repository URL (then slug)
and updated in place rather than duplicated.

Usage (inside the backend container):
    python app/scripts/ingest_mcp_servers.py [--limit 30]

The GitHub search API allows 10 requests/minute unauthenticated; a single
request returns up to 100 results, so the default limit is served by one call.
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models import Category, MCPServer, ServerScope, Tag

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
SEARCH_QUERY = "mcp-server in:name"

# Repos that are curated lists rather than actual servers
LIST_RE = re.compile(r"awesome|curated|collection of|list of", re.IGNORECASE)

# keyword -> tag slug used to tag servers by their description
TAG_KEYWORDS = {
    "api-integration": ["api", "rest", "http", "integration"],
    "database": ["database", "postgres", "sql", "mysql", "sqlite", "mongodb", "mongo", "query"],
    "browser-automation": ["browser", "web scraping", "crawl", "automation", "playwright", "puppeteer"],
    "file-systems": ["file", "filesystem", "storage", "s3", "document", "markdown"],
    "version-control": ["git", "version control", "github", "pull request", "commit"],
    "security": ["security", "auth", "scan", "vulnerability"],
    "knowledge-memory": ["memory", "knowledge", "rag", "vector", "embedding", "semantic"],
}


def fetch_repos(page: int = 1, per_page: int = 100) -> dict:
    """Call the GitHub search API for one page of repositories."""
    params = urllib.parse.urlencode({
        "q": SEARCH_QUERY,
        "sort": "stars",
        "order": "desc",
        "page": page,
        "per_page": per_page,
    })
    req = urllib.request.Request(
        f"{GITHUB_SEARCH_URL}?{params}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "ai-agent-hub-ingest"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def is_list_repo(repo: dict) -> bool:
    """True for awesome/curated-list repos that are not real servers."""
    name = repo.get("name") or ""
    description = repo.get("description") or ""
    return bool(LIST_RE.search(name) or LIST_RE.search(description))


def slugify(name: str) -> str:
    """Convert a repo name into a URL-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "unnamed"


def infer_scope(description: str) -> ServerScope:
    """Cloud if the description indicates a hosted/remote service."""
    if re.search(r"remote|cloud|hosted|saas|server-side", description, re.IGNORECASE):
        return ServerScope.CLOUD
    return ServerScope.LOCAL


def assign_tags(db: Session, description: str) -> list[Tag]:
    """Map description keywords to existing tags (created on demand)."""
    matched = set()
    text = description.lower()
    for tag_slug, keywords in TAG_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            matched.add(tag_slug)
    tags = []
    for tag_slug in matched:
        tag = db.query(Tag).filter(Tag.slug == tag_slug).first()
        if not tag:
            tag = Tag(name=tag_slug.replace("-", " ").title(), slug=tag_slug, description="")
            db.add(tag)
            db.flush()
        tags.append(tag)
    return tags


def get_dev_category(db: Session) -> Category:
    """Return (creating if needed) the development category."""
    category = db.query(Category).filter(Category.slug == "development").first()
    if not category:
        category = Category(
            name="Development",
            slug="development",
            description="AI tools for software development and coding",
        )
        db.add(category)
        db.flush()
    return category


def upsert_server(db: Session, repo: dict, dev_category: Category) -> tuple[MCPServer, str]:
    """Create or update a server for a GitHub repo. Returns (server, action)."""
    repo_url = repo["html_url"]
    slug = slugify(repo["name"])

    server = db.query(MCPServer).filter(MCPServer.repository_url == repo_url).first()
    if not server:
        server = db.query(MCPServer).filter(MCPServer.slug == slug).first()

    description = (repo.get("description") or f"MCP server for {repo['name']}.").strip()

    if server:
        server.name = repo["name"]
        server.description = description
        server.language = repo.get("language") or "Other"
        server.logo_url = repo["owner"]["avatar_url"]
        server.star_count = repo["stargazers_count"] or 0
        server.scope = infer_scope(description)
        server.category_id = dev_category.id
        server.tags = assign_tags(db, description)
        return server, "updated"

    server = MCPServer(
        name=repo["name"],
        slug=slug,
        description=description,
        repository_url=repo_url,
        language=repo.get("language") or "Other",
        scope=infer_scope(description),
        category_id=dev_category.id,
        logo_url=repo["owner"]["avatar_url"],
        star_count=repo["stargazers_count"] or 0,
        featured=False,
        view_count=0,
    )
    server.tags = assign_tags(db, description)
    db.add(server)
    return server, "created"


def main():
    parser = argparse.ArgumentParser(description="Ingest top MCP servers from GitHub")
    parser.add_argument("--limit", type=int, default=30, help="Maximum servers to ingest (default 30)")
    args = parser.parse_args()

    print(f"Fetching GitHub repos for '{SEARCH_QUERY}' (target {args.limit} servers)...")
    db = SessionLocal()
    created = updated = skipped = 0

    try:
        dev_category = get_dev_category(db)
        collected: list[dict] = []
        page = 1
        while len(collected) < args.limit:
            data = fetch_repos(page=page)
            items = data.get("items") or []
            if not items:
                break
            collected.extend([r for r in items if not is_list_repo(r)])
            total = data.get("total_count") or 0
            page += 1
            # Stop early when we've seen every result
            if (page - 1) * 100 >= total:
                break
            if len(collected) < args.limit:
                time.sleep(3)  # respect GitHub's search rate limit

        for repo in collected[: args.limit]:
            _, action = upsert_server(db, repo, dev_category)
            if action == "created":
                created += 1
            else:
                updated += 1
            print(f"  {action.upper():7} {repo['name']} ({repo['stargazers_count']}★)")

        db.commit()
        print(f"\nDone. Created {created}, updated {updated}, out of {len(collected[: args.limit])} processed.")
    except Exception as e:
        db.rollback()
        print(f"Error during ingest: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()