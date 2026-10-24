# Ingestion Pipeline Design — AI Agent Hub

**Date:** 2026-10-20  
**Status:** Implemented (2026-10-24)  
**Author:** opencode agent

---

## 1. Intent & Why

The current ingestion is two manual, hardcoded scripts (`ingest_mcp_servers.py`, `ingest_agents.py`) that hit GitHub Search API and a curated Python list. No scheduling, no source config, no audit trail, no dedup tracking beyond URL/slug.

We need a **config-driven, extensible ingestion framework** where:
- New sources are added by inserting rows in a `sources` table (no code changes)
- Each run is logged with counts (created/updated/failed)
- Existing data is refreshed (stars, descriptions) without duplicates
- Manual triggers via `make` today; scheduler can be enabled later via env var

---

## 2. Goals / Non-Goals / Anti-Goals

| Goals | Non-Goals | Anti-Goals |
|---|---|---|
| Normalized `sources` table with JSON config per source | Full ETL framework with DAGs | Scraping sites without public APIs (ToS risk) |
| Add `source`, `last_synced_at`, `external_id` to `agents` & `mcp_servers` | Real-time streaming ingestion | Replacing curated catalog for closed-source agents |
| Generic make targets: `make ingest SOURCE=<name>` / `make ingest-all` | Multi-tenant source configs | Automatic writes without dry-run option |
| Audit trail via `ingestion_runs` table | In-app scheduler now (opt-in later via APScheduler) | Hardcoding endpoints in Python |

---

## 3. Constraints

- **PostgreSQL** (via SQLAlchemy/Alembic) — migrations must be reversible
- **FastAPI** backend — scripts run inside backend container (`docker exec`)
- **Python 3.11+**, stdlib + `requests`, `httpx`, `pydantic`
- **No new external services** (Redis, Celery, etc.) for v1
- **Rate limits**: GitHub Search 10/min (unauth) → 30/min with `GITHUB_TOKEN`; MCP Registry no limit. Source configs live in the DB, so re-run `make seed-sources` after changing `SOURCE_CONFIGS` to refresh existing rows.
- **Dedup strategy**: upsert by `repository_url` (MCP) / `website_url` (agents) → `slug` fallback; `external_id` stores source-specific key

---

## 4. Data Model

### 4.1 New Table: `sources`

```sql
CREATE TABLE sources (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(64) UNIQUE NOT NULL,       -- machine name: 'mcp_registry', 'github_mcp_topic', 'github_agents_topic', 'curated_catalog'
    display_name    VARCHAR(128) NOT NULL,
    type            VARCHAR(32) NOT NULL,              -- 'api', 'github_search', 'curated'
    config          JSONB NOT NULL,                    -- endpoint, auth, pagination, parser mappings, rate limits
    status          VARCHAR(16) DEFAULT 'active',      -- 'active', 'disabled', 'error'
    last_fetched_at TIMESTAMPTZ,
    last_fetched_count INTEGER DEFAULT 0,
    last_error      TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
```

### 4.2 Tracking Columns on Existing Tables

```sql
-- agents
ALTER TABLE agents ADD COLUMN source VARCHAR(32);
ALTER TABLE agents ADD COLUMN last_synced_at TIMESTAMPTZ;
ALTER TABLE agents ADD COLUMN external_id VARCHAR(200);

-- mcp_servers
ALTER TABLE mcp_servers ADD COLUMN source VARCHAR(32);
ALTER TABLE mcp_servers ADD COLUMN last_synced_at TIMESTAMPTZ;
ALTER TABLE mcp_servers ADD COLUMN external_id VARCHAR(200);
```

No FK to `sources` — denormalized `source` string for fast filtering; `sources.name` is the canonical value.

### 4.3 Audit Table: `ingestion_runs`

```sql
CREATE TABLE ingestion_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID REFERENCES sources(id),
    started_at      TIMESTAMPTZ DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    items_seen      INTEGER DEFAULT 0,
    items_created   INTEGER DEFAULT 0,
    items_updated   INTEGER DEFAULT 0,
    items_failed    INTEGER DEFAULT 0,
    error_summary   TEXT
);
```

---

## 5. Source Configurations (JSON in `sources.config`)

### 5.1 MCP Registry (primary)

```json
{
  "endpoint": "https://registry.modelcontextprotocol.io/v0/servers",
  "method": "GET",
  "pagination": "cursor",
  "params": { "limit": 100 },
  "rate_limit": { "requests_per_minute": 60 },
  "parser": {
    "item_path": "servers",
    "mappings": {
      "name": "server.title",
      "slug": "server.name",
      "description": "server.description",
      "repository_url": "server.repository.url",
      "npm_package": "server.packages[?(@.registryType=='npm')].identifier",
      "pypi_package": "server.packages[?(@.registryType=='pypi')].identifier",
      "scope": "server.remotes && server.remotes.length > 0 ? 'cloud' : 'local'",
      "language": "server.packages[0]?.runtimeHint || 'Other'",
      "external_id": "server.name",
      "logo_url": "server.repository.url | extract_github_avatar"
    }
  }
}
```

### 5.2 GitHub MCP Topic (enrichment)

```json
{
  "endpoint": "https://api.github.com/search/repositories",
  "method": "GET",
  "pagination": "page",
  "params": { "q": "topic:mcp-server", "per_page": 100, "sort": "stars", "order": "desc" },
  "auth": { "type": "bearer", "env_var": "GITHUB_TOKEN" },
  "rate_limit": { "requests_per_minute": 5000 },
  "parser": {
    "item_path": "items",
    "mappings": {
      "name": "name",
      "slug": "name",
      "description": "description",
      "repository_url": "html_url",
      "language": "language",
      "star_count": "stargazers_count",
      "logo_url": "owner.avatar_url",
      "external_id": "full_name"
    }
  }
}
```

### 5.3 GitHub Agents Topic (open-source agents)

```json
{
  "endpoint": "https://api.github.com/search/repositories",
  "method": "GET",
  "pagination": "page",
  "params": { "q": "topic:ai-agents fork:false archived:false stars:>5", "per_page": 100 },
  "auth": { "type": "bearer", "env_var": "GITHUB_TOKEN" },
  "rate_limit": { "requests_per_minute": 5000 },
  "parser": {
    "item_path": "items",
    "mappings": {
      "name": "name",
      "slug": "name",
      "description": "description",
      "website_url": "html_url",
      "repository_url": "html_url",
      "language": "language",
      "star_count": "stargazers_count",
      "logo_url": "owner.avatar_url",
      "external_id": "full_name",
      "pricing_model": "free"
    }
  }
}
```

### 5.4 Curated Catalog (existing)

```json
{
  "type": "curated",
  "parser": {
    "item_path": "CATALOG",
    "module": "app.scripts.agent_catalog",
    "mappings": { "...": "direct field map" }
  }
}
```

---

## 6. Ingestion Engine (Core Logic)

A single generic runner `app/scripts/ingest.py`:

```python
def ingest_source(source_name: str, limit: int | None = None, dry_run: bool = False, enrich_only: bool = False) -> IngestionResult:
    source = db.query(Source).filter(Source.name == source_name).one()
    run = IngestionRun(source_id=source.id)
    db.add(run); db.commit()
    
    parser = ParserFactory.build(source.type, source.config)
    for page in paginate(source.config):
        for raw in page[parser.item_path]:
            parsed = parser.parse(raw)
            if enrich_only and not db.query(Model).filter(Model.external_id == parsed.external_id).first():
                continue
            upsert(parsed, dry_run)
            run.items_seen += 1
    
    run.finished_at = now()
    db.commit()
    return run
```

**Upsert logic (per model):**
```python
def upsert_mcp(parsed, dry_run):
    existing = db.query(MCPServer).filter(
        MCPServer.repository_url == parsed.repository_url
    ).first()
    if not existing:
        existing = db.query(MCPServer).filter(MCPServer.slug == parsed.slug).first()
    if existing:
        # refresh mutable fields
        existing.name = parsed.name
        existing.description = parsed.description
        existing.language = parsed.language
        existing.scope = parsed.scope
        existing.npm_package = parsed.npm_package
        existing.pypi_package = parsed.pypi_package
        existing.star_count = parsed.star_count
        existing.logo_url = parsed.logo_url
        existing.source = source.name
        existing.last_synced_at = now()
        existing.external_id = parsed.external_id
        action = "updated"
    else:
        existing = MCPServer(**parsed.dict(), source=source.name, last_synced_at=now(), external_id=parsed.external_id)
        db.add(existing)
        action = "created"
    if not dry_run: db.flush()
    return action
```

---

## 7. Make Targets

```makefile
# Primary targets
ingest:              # runs all active sources
    docker exec ai_agent_hub_backend python -m app.scripts.ingest --all

ingest-mcp:          # MCP Registry + GitHub enrichment
    docker exec ai_agent_hub_backend python -m app.scripts.ingest mcp_registry github_mcp_topic

ingest-agents:       # Curated + GitHub agents topic
    docker exec ai_agent_hub_backend python -m app.scripts.ingest curated_catalog github_agents_topic

# Flags
#   --limit N         stop after N items per source
#   --dry-run         parse & show diff, no DB writes
#   --enrich-only     only update existing rows (skip new creates)
#   --output json     machine-readable summary
```

---

## 8. Files to Create / Modify

| File | Action |
|---|---|
| `backend/app/models/source.py` | New: `Source`, `IngestionRun` models |
| `backend/app/models/__init__.py` | Export new models |
| `alembic/versions/xxx_add_sources_and_tracking.py` | Migration |
| `backend/app/scripts/ingest.py` | New: generic runner + parser factory |
| `backend/app/scripts/ingest_mcp_servers.py` | **Archive** → reference logic moved to parser |
| `backend/app/scripts/ingest_agents.py` | **Archive** → reference logic moved to parser |
| `backend/app/scripts/agent_catalog.py` | Keep — used by curated source |
| `Makefile` | Add `ingest`, `ingest-mcp`, `ingest-agents` targets |
| `backend/.env.example` | Add `GITHUB_TOKEN=` (optional) |

---

## 9. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| MCP Registry schema changes | Versioned `$schema` URL in response; parser reads defensively with `.get()` |
| GitHub rate limit exceeded | Respect `X-RateLimit-Remaining`; exponential backoff; `--limit` flag |
| Duplicate slugs across sources | Upsert order: registry → github → curated; `external_id` disambiguates |
| Migration on existing data | `source` defaults to `'legacy'`; backfill script for existing rows |

---

## 10. Acceptance Criteria

1. `make ingest-mcp --dry-run` shows parsed count > 0, zero DB writes
2. `make ingest-mcp` creates `sources` rows, adds/updates `mcp_servers`, logs to `ingestion_runs`
3. Re-running `make ingest-mcp` updates `star_count`/`description` on existing rows, `last_synced_at` advances
4. `make ingest-agents` adds open-source agents from GitHub topic + keeps curated entries
5. `source` column populated on all new/updated rows; `ingestion_runs` has one row per source per run
6. Migration applies cleanly on fresh DB and on existing DB with data

---

## 11. Open Questions (for Builder Check)

1. **JSONPath vs custom parser** — Use `jsonpath-ng` for mappings like `server.packages[?(@.registryType=='npm')].identifier`, or write tiny Python helpers? (Leaning: helpers — less dep, clearer)
2. **Category assignment** — Registry has no categories. Map via keyword tags in description → tag → category? Or default to "Developer Tools"?
3. **Agent pricing_model** — GitHub repos have no pricing. Default `'free'` for open-source; curated entries keep explicit values.
4. **Logo extraction from GitHub URL** — Helper: `github.com/owner/repo` → `avatars.githubusercontent.com/u/{owner_id}` (needs extra API call) or use `owner.avatar_url` from search result (already there).

---

## 12. Builder Check Resolutions

*Answers to the 10 questions from builder check:*

### 1. Parser interface contract → **Defined in §6.1**

```python
# app/scripts/parsers/base.py
class BaseParser(ABC):
    def __init__(self, config: dict):
        self.config = config
        self.item_path: str = config["parser"]["item_path"]
        self.mappings: dict = config["parser"]["mappings"]
    
    @abstractmethod
    def fetch_page(self, page_token: str | int | None) -> dict: ...
    
    @abstractmethod
    def has_next_page(self, response: dict) -> bool: ...
    
    @abstractmethod
    def next_page_token(self, response: dict) -> str | int | None: ...
    
    def parse(self, raw: dict) -> ParsedItem:
        # mapping evaluator: supports "path", "path | filter", "path || default"
        return evaluate_mappings(raw, self.mappings)

class APIParser(BaseParser): ...
class GitHubSearchParser(BaseParser): ...
class CuratedParser(BaseParser): ...

class ParserFactory:
    @staticmethod
    def build(type_: str, config: dict) -> BaseParser:
        return {"api": APIParser, "github_search": GitHubSearchParser, "curated": CuratedParser}[type_](config)
```

### 2. Conflict resolution for duplicate `external_id` across sources → **Last-writer-wins with source priority**

Sources have implicit priority by ingestion order (registry first, then github, then curated). If `external_id` matches an existing row from a *different* source:
- Update mutable fields (stars, description, logo)
- `source` column = current source (tracks freshest origin)
- `last_synced_at` = now()
- Log as `"updated_cross_source"` in `ingestion_runs.error_summary` (optional detail)

### 3. Backfill strategy for existing rows → **One-time migration script**

New migration adds columns with `DEFAULT 'legacy'` for `source` and `NULL` for `external_id`. Immediately after migration, run:

```python
# backfill_existing.py
# mcp_servers: external_id = slug (or parsed from repository_url)
# agents: external_id = slug (or parsed from website_url)
# source = 'legacy'
# last_synced_at = created_at
```

This makes existing rows match on `external_id` during first re-ingestion.

### 4. Schema version detection for MCP Registry → **Pinned schema URL + health check**

- Config stores `expected_schema_url: "https://static.modelcontextprotocol.io/schemas/2025-09-29/server.schema.json"`
- On first fetch, compare `response.servers[0].server.$schema` to expected
- Mismatch → `source.status = 'error'`, `last_error = "Schema version changed"`, stop ingestion
- Admin must review and update config `expected_schema_url` to proceed

### 5. `enrich_only` for curated source → **No-op with log**

Curated parser returns all items as "new" (no API to check existence). `enrich_only` flag causes curated parser to return empty iterator with log: `"enrich_only skipped for curated source (no external existence check)"`. Runner continues to next source.

### 6. Rate limit backoff specifics → **Token bucket in memory + config**

```python
# config.rate_limit: { "requests_per_minute": 5000, "burst": 10, "max_retries": 3, "base_delay_sec": 2 }
# Implementation: simple token bucket (thread-local), exponential backoff with jitter:
# delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
# On 429/403: sleep delay, retry up to max_retries, then raise
```

Persisted state not needed — runs are short (<5 min), in-memory bucket sufficient.

### 7. Logo URL strategy for GitHub sources → **Use `owner.avatar_url` from search result**

No extra API call. `owner.avatar_url` is the GitHub user/org avatar (serves as logo). For repo-specific logos, that's a future enhancement (would need HTML scrape of repo README or `raw.githubusercontent.com` — out of scope v1).

### 8. Category assignment for MCP servers → **Keyword→tag→category mapping in parser config**

```json
"category_mapping": {
  "keywords": {
    "filesystem": "file-systems",
    "database|sql|postgres|mysql": "database",
    "browser|playwright|puppeteer": "browser-automation",
    "github|git": "developer-tools",
    "api|rest|http": "api-integration"
  },
  "default": "developer-tools"
}
```
Parser evaluates description+name against keywords (case-insensitive regex), picks first match → looks up `Category.slug` → assigns `category_id`. If no match, uses default.

### 9. `agent_catalog.py` adapter → **Thin wrapper**

Current `agent_catalog.py` exports `CATALOG = [dict, ...]`. Curated parser imports it, wraps each dict with `external_id = slug`, `source = 'curated_catalog'`, `last_synced_at = now()`. No refactoring of `agent_catalog.py` needed.

### 10. Dry-run output format → **Structured JSON**

```json
{
  "source": "mcp_registry",
  "dry_run": true,
  "items": [
    {
      "action": "created",
      "external_id": "com.pulsemcp/remote-filesystem",
      "fields": { "name": "Remote Filesystem", "star_count": 0, ... }
    },
    {
      "action": "updated",
      "external_id": "com.github/mcp-server",
      "diff": { "star_count": { "old": 120, "new": 125 }, "description": "changed" }
    }
  ],
  "summary": { "would_create": 42, "would_update": 8, "would_skip": 0, "errors": 0 }
}
```

---

## 13. Next Steps

1. `gsd-plan-phase` → detailed task breakdown
2. Implementation in dependency order: migration → models → parser → runner → make targets → seed sources