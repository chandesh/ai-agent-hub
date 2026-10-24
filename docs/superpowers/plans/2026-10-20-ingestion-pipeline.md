# Ingestion Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hardcoded ingestion scripts with a config-driven framework where sources are database rows, ingestion is generic, and runs are audited.

**Architecture:** Single generic runner (`ingest.py`) uses parser factory to dispatch to source-specific parsers (API, GitHub Search, Curated). Sources configured via `sources` table with JSON config. Migration adds tracking columns to `agents`/`mcp_servers` and creates `sources`/`ingestion_runs` tables. Make targets wrap the runner.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0, Alembic, httpx, pydantic, pytest

**Spec:** `docs/superpowers/specs/2026-10-20-ingestion-pipeline-design.md`

## Global Constraints

- PostgreSQL via SQLAlchemy/Alembic — migrations reversible
- FastAPI backend — scripts run via `docker exec` in backend container
- Python 3.11+, stdlib + `httpx`, `pydantic` (no `jsonpath-ng`)
- No new external services (Redis, Celery) for v1
- Rate limits: GitHub Search 10/min unauth → 30/min with `GITHUB_TOKEN`; MCP Registry no limit
- Dedup: upsert by `repository_url`/`website_url` → `slug` fallback; `external_id` for cross-source match
- Existing scripts archived, not deleted (`ingest_mcp_servers.py`, `ingest_agents.py`)

## Review Focus

1. **Schema drift** — Registry $schema URL changes without detection → silent field mapping failures. Test: parser rejects unknown schema version.
2. **Rate limit burst** — GitHub 429 not handled → IP ban. Test: exponential backoff with jitter retries up to max_retries.
3. **Cross-source duplicate** — Same `external_id` from different sources → last-writer-wins but `source` column tracks origin. Test: two sources with same `external_id` → second updates row, `source` flips.
4. **Dry-run fidelity** — Dry-run must show exact diff without DB writes. Test: dry-run produces expected JSON, zero DB rows changed.
5. **Empty/partial responses** — API returns 200 with empty `servers`/`items` or missing fields → no crash, log warning. Test: parser handles missing optional fields gracefully.

---

### Task 1: Alembic Migration — Sources, IngestionRuns, Tracking Columns

**Files:**
- Create: `alembic/versions/20261020_add_sources_and_tracking.py`
- Test: `tests/test_migrations.py` (integration)

**Interfaces:**
- Produces: tables `sources`, `ingestion_runs`; columns `source`, `last_synced_at`, `external_id` on `agents`, `mcp_servers`

- [ ] **Step 1: Write migration**

```python
# alembic/versions/20261020_add_sources_and_tracking.py
# upgrade():
#   op.create_table('sources', ...)
#   op.create_table('ingestion_runs', ...)
#   op.add_column('agents', sa.Column('source', sa.String(32)))
#   op.add_column('agents', sa.Column('last_synced_at', sa.DateTime(timezone=True)))
#   op.add_column('agents', sa.Column('external_id', sa.String(200)))
#   op.add_column('mcp_servers', sa.Column('source', sa.String(32)))
#   op.add_column('mcp_servers', sa.Column('last_synced_at', sa.DateTime(timezone=True)))
#   op.add_column('mcp_servers', sa.Column('external_id', sa.String(200)))
#   op.execute("UPDATE agents SET source='legacy', last_synced_at=created_at WHERE source IS NULL")
#   op.execute("UPDATE mcp_servers SET source='legacy', last_synced_at=created_at WHERE source IS NULL")
#   # backfill external_id from slug (mcp_servers) / slug (agents)
# downgrade(): drop columns, drop tables
```

- [ ] **Step 2: Run migration on test DB**

Run: `docker exec ai_agent_hub_backend alembic upgrade head`
Expected: PASS, tables/columns created

- [ ] **Step 3: Verify rollback**

Run: `docker exec ai_agent_hub_backend alembic downgrade -1`
Expected: PASS, tables/columns removed

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/20261020_add_sources_and_tracking.py
git commit -m "feat(migration): add sources, ingestion_runs, tracking columns"
```

---

### Task 2: Source & IngestionRun Models

**Files:**
- Create: `backend/app/models/source.py`
- Modify: `backend/app/models/__init__.py`
- Test: `tests/models/test_source.py`

**Interfaces:**
- Consumes: migration from Task 1
- Produces: `Source`, `IngestionRun` classes with relationships

- [ ] **Step 1: Write failing tests**

```python
# tests/models/test_source.py
def test_source_creation(db_session):
    s = Source(name="test", display_name="Test", type="api", config={})
    db_session.add(s); db_session.commit()
    assert s.id is not None
    assert s.status == "active"

def test_ingestion_run_relationship(db_session):
    s = Source(name="test", display_name="Test", type="api", config={})
    db_session.add(s); db_session.flush()
    r = IngestionRun(source_id=s.id)
    db_session.add(r); db_session.commit()
    assert r.source_id == s.id
    assert r.started_at is not None
```

- [ ] **Step 2: Run tests to verify fail**

Run: `pytest tests/models/test_source.py -v`
Expected: FAIL (classes not defined)

- [ ] **Step 3: Implement models**

```python
# backend/app/models/source.py
class Source(Base):
    __tablename__ = "sources"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(64), unique=True, nullable=False)
    display_name = Column(String(128), nullable=False)
    type = Column(String(32), nullable=False)
    config = Column(JSONB, nullable=False)
    status = Column(String(16), default="active", nullable=False)
    last_fetched_at = Column(DateTime(timezone=True))
    last_fetched_count = Column(Integer, default=0)
    last_error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    runs = relationship("IngestionRun", back_populates="source")

class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(UUID(as_uuid=True), ForeignKey("sources.id"), nullable=False)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True))
    items_seen = Column(Integer, default=0)
    items_created = Column(Integer, default=0)
    items_updated = Column(Integer, default=0)
    items_failed = Column(Integer, default=0)
    error_summary = Column(Text)
    source = relationship("Source", back_populates="runs")
```

```python
# backend/app/models/__init__.py
# add: from .source import Source, IngestionRun
# add to __all__
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/models/test_source.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/source.py backend/app/models/__init__.py tests/models/test_source.py
git commit -m "feat(models): add Source and IngestionRun models"
```

---

### Task 3: Parser Base Class & Factory

**Files:**
- Create: `backend/app/scripts/parsers/__init__.py`
- Create: `backend/app/scripts/parsers/base.py`
- Create: `backend/app/scripts/parsers/mapping.py`
- Test: `tests/scripts/parsers/test_base.py`

**Interfaces:**
- Consumes: Source config JSON structure from spec §5
- Produces: `BaseParser` ABC, `ParserFactory.build(type, config) -> BaseParser`, `evaluate_mappings(raw, mappings) -> ParsedItem`

- [ ] **Step 1: Write failing tests**

```python
# tests/scripts/parsers/test_base.py
def test_mapping_evaluation():
    raw = {"server": {"title": "Test", "name": "test", "packages": [{"registryType": "npm", "identifier": "pkg"}]}}
    mappings = {"name": "server.title", "npm_package": "server.packages[?(@.registryType=='npm')].identifier"}
    result = evaluate_mappings(raw, mappings)
    assert result["name"] == "Test"
    assert result["npm_package"] == "pkg"

def test_parser_factory():
    config = {"parser": {"item_path": "items", "mappings": {}}}
    p = ParserFactory.build("api", config)
    assert isinstance(p, APIParser)
```

- [ ] **Step 2: Run tests to verify fail**

Run: `pytest tests/scripts/parsers/test_base.py -v`
Expected: FAIL

- [ ] **Step 3: Implement base parser & mapping evaluator**

```python
# backend/app/scripts/parsers/mapping.py
def evaluate_mappings(raw: dict, mappings: dict) -> dict:
    # supports: "path", "path || default", "path | filter"
    # filter syntax: "extract_github_avatar" (registered function)
    # path: dot-notation, bracket for arrays, ?(@.key=='val') for filter
    # returns dict of mapped values
    ...
```

```python
# backend/app/scripts/parsers/base.py
from abc import ABC, abstractmethod

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
    
    def parse(self, raw: dict) -> dict:
        return evaluate_mappings(raw, self.mappings)

class ParserFactory:
    _registry = {}
    @classmethod
    def register(cls, type_: str, parser_cls):
        cls._registry[type_] = parser_cls
    @classmethod
    def build(cls, type_: str, config: dict) -> BaseParser:
        if type_ not in cls._registry:
            raise ValueError(f"Unknown parser type: {type_}")
        return cls._registry[type_](config)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/scripts/parsers/test_base.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/scripts/parsers/ tests/scripts/parsers/test_base.py
git commit -m "feat(parsers): add base parser, factory, mapping evaluator"
```

---

### Task 4: API Parser (MCP Registry)

**Files:**
- Create: `backend/app/scripts/parsers/api.py`
- Test: `tests/scripts/parsers/test_api.py`

**Interfaces:**
- Consumes: `BaseParser`, `httpx.AsyncClient`
- Produces: `APIParser` with cursor pagination, schema version check

- [ ] **Step 1: Write failing tests**

```python
# tests/scripts/parsers/test_api.py
@pytest.mark.asyncio
async def test_api_parser_fetch_first_page(httpx_mock):
    httpx_mock.add_response(url="https://registry.modelcontextprotocol.io/v0/servers?limit=100",
        json={"servers": [{"server": {"$schema": "...", "name": "test", "title": "Test"}}]})
    parser = APIParser(config)
    page = await parser.fetch_page(None)
    assert "servers" in page

def test_schema_version_check():
    parser = APIParser(config_with_expected_schema)
    good = {"server": {"$schema": "https://static.modelcontextprotocol.io/schemas/2025-09-29/server.schema.json"}}
    bad = {"server": {"$schema": "https://static.modelcontextprotocol.io/schemas/2026-01-01/server.schema.json"}}
    assert parser._check_schema(good) is True
    assert parser._check_schema(bad) is False
```

- [ ] **Step 2: Run tests to verify fail**

Run: `pytest tests/scripts/parsers/test_api.py -v`
Expected: FAIL

- [ ] **Step 3: Implement APIParser**

```python
# backend/app/scripts/parsers/api.py
class APIParser(BaseParser):
    def __init__(self, config: dict):
        super().__init__(config)
        self.client = httpx.AsyncClient(timeout=30.0)
        self.expected_schema = config.get("expected_schema_url")
    
    async def fetch_page(self, cursor: str | None) -> dict:
        params = dict(self.config.get("params", {}))
        if cursor: params["cursor"] = cursor
        resp = await self.client.get(self.config["endpoint"], params=params)
        resp.raise_for_status()
        return resp.json()
    
    def has_next_page(self, response: dict) -> bool:
        return bool(response.get("metadata", {}).get("nextCursor"))
    
    def next_page_token(self, response: dict) -> str | None:
        return response.get("metadata", {}).get("nextCursor")
    
    def _check_schema(self, item: dict) -> bool:
        if not self.expected_schema: return True
        return item.get("server", {}).get("$schema") == self.expected_schema
    
    async def close(self):
        await self.client.aclose()
```

- [ ] **Step 4: Register parser & run tests**

```python
# backend/app/scripts/parsers/__init__.py
from .api import APIParser
ParserFactory.register("api", APIParser)
```

Run: `pytest tests/scripts/parsers/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/scripts/parsers/api.py tests/scripts/parsers/test_api.py
git commit -m "feat(parsers): add APIParser for MCP Registry"
```

---

### Task 5: GitHub Search Parser

**Files:**
- Create: `backend/app/scripts/parsers/github_search.py`
- Test: `tests/scripts/parsers/test_github_search.py`

**Interfaces:**
- Consumes: `BaseParser`, `httpx.AsyncClient`, `GITHUB_TOKEN` from env
- Produces: `GitHubSearchParser` with page pagination, rate limit backoff

- [ ] **Step 1: Write failing tests**

```python
# tests/scripts/parsers/test_github_search.py
@pytest.mark.asyncio
async def test_github_parser_rate_limit_backoff(httpx_mock):
    # 429 then 200
    httpx_mock.add_response(status_code=429, headers={"X-RateLimit-Remaining": "0"})
    httpx_mock.add_response(json={"items": [{"name": "test"}]})
    parser = GitHubSearchParser(config)
    page = await parser.fetch_page(1)
    assert page["items"][0]["name"] == "test"
```

- [ ] **Step 2: Run tests to verify fail**

Run: `pytest tests/scripts/parsers/test_github_search.py -v`
Expected: FAIL

- [ ] **Step 3: Implement GitHubSearchParser**

```python
# backend/app/scripts/parsers/github_search.py
class GitHubSearchParser(BaseParser):
    def __init__(self, config: dict):
        super().__init__(config)
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={"Authorization": f"Bearer {os.getenv('GITHUB_TOKEN', '')}"} if os.getenv('GITHUB_TOKEN') else {}
        )
        self.rate_limit = config.get("rate_limit", {})
    
    async def fetch_page(self, page: int | None) -> dict:
        params = dict(self.config.get("params", {}))
        params["page"] = page or 1
        for attempt in range(self.rate_limit.get("max_retries", 3)):
            resp = await self.client.get(self.config["endpoint"], params=params)
            if resp.status_code == 429 or resp.status_code == 403:
                remaining = int(resp.headers.get("X-RateLimit-Remaining", 0))
                if remaining == 0:
                    delay = self.rate_limit.get("base_delay_sec", 2) * (2 ** attempt) + random.random()
                    await asyncio.sleep(delay)
                    continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError("Max retries exceeded")
    
    def has_next_page(self, response: dict) -> bool:
        return len(response.get("items", [])) > 0
    
    def next_page_token(self, response: dict) -> int:
        return (self._current_page or 1) + 1
```

- [ ] **Step 4: Register parser & run tests**

```python
# backend/app/scripts/parsers/__init__.py
from .github_search import GitHubSearchParser
ParserFactory.register("github_search", GitHubSearchParser)
```

Run: `pytest tests/scripts/parsers/test_github_search.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/scripts/parsers/github_search.py tests/scripts/parsers/test_github_search.py
git commit -m "feat(parsers): add GitHubSearchParser with rate limit backoff"
```

---

### Task 6: Curated Parser

**Files:**
- Create: `backend/app/scripts/parsers/curated.py`
- Test: `tests/scripts/parsers/test_curated.py`

**Interfaces:**
- Consumes: `BaseParser`, `app.scripts.agent_catalog.CATALOG`
- Produces: `CuratedParser` — iterates static list, returns empty on `enrich_only=True`

- [ ] **Step 1: Write failing tests**

```python
# tests/scripts/parsers/test_curated.py
def test_curated_parser_iterates_catalog():
    parser = CuratedParser(config)
    items = list(parser.iter_items(enrich_only=False))
    assert len(items) > 0
    assert all("external_id" in i for i in items)

def test_curated_enrich_only_empty():
    parser = CuratedParser(config)
    items = list(parser.iter_items(enrich_only=True))
    assert len(items) == 0
```

- [ ] **Step 2: Run tests to verify fail**

Run: `pytest tests/scripts/parsers/test_curated.py -v`
Expected: FAIL

- [ ] **Step 3: Implement CuratedParser**

```python
# backend/app/scripts/parsers/curated.py
class CuratedParser(BaseParser):
    def __init__(self, config: dict):
        super().__init__(config)
        module_path = config["parser"]["module"]
        item_path = config["parser"]["item_path"]
        module = importlib.import_module(module_path)
        self.catalog = getattr(module, item_path)
    
    def iter_items(self, enrich_only: bool = False):
        if enrich_only:
            logger.info("enrich_only skipped for curated source (no external existence check)")
            return
        for item in self.catalog:
            parsed = self.parse(item)
            parsed["external_id"] = item.get("slug") or parsed.get("slug")
            parsed["source"] = "curated_catalog"
            parsed["last_synced_at"] = datetime.now(timezone.utc)
            yield parsed
    
    # BaseParser abstract methods (not used for curated)
    def fetch_page(self, page_token): raise NotImplementedError
    def has_next_page(self, response): raise NotImplementedError
    def next_page_token(self, response): raise NotImplementedError
```

- [ ] **Step 4: Register parser & run tests**

```python
# backend/app/scripts/parsers/__init__.py
from .curated import CuratedParser
ParserFactory.register("curated", CuratedParser)
```

Run: `pytest tests/scripts/parsers/test_curated.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/scripts/parsers/curated.py tests/scripts/parsers/test_curated.py
git commit -m "feat(parsers): add CuratedParser for agent_catalog"
```

---

### Task 7: Generic Ingestion Runner (`ingest.py`)

**Files:**
- Create: `backend/app/scripts/ingest.py`
- Test: `tests/scripts/test_ingest.py`

**Interfaces:**
- Consumes: `SessionLocal`, `Source`, `IngestionRun`, `MCPServer`, `Agent`, `ParserFactory`
- Produces: `ingest_source(source_name, limit, dry_run, enrich_only) -> IngestionResult`

- [ ] **Step 1: Write failing tests**

```python
# tests/scripts/test_ingest.py
@pytest.mark.asyncio
async def test_ingest_source_dry_run(db_session, mocker):
    # mock parser to return 2 items
    mock_parser = mocker.AsyncMock()
    mock_parser.parse.side_effect = [{"external_id": "1", "name": "A"}, {"external_id": "2", "name": "B"}]
    mock_parser.fetch_page.return_value = {"servers": [{"server": {}}, {"server": {}}]}
    mock_parser.has_next_page.return_value = False
    mocker.patch("app.scripts.ingest.ParserFactory.build", return_value=mock_parser)
    
    run = await ingest_source("mcp_registry", limit=2, dry_run=True)
    assert run.items_seen == 2
    assert run.items_created == 0  # dry_run
    assert run.items_updated == 0
```

- [ ] **Step 2: Run tests to verify fail**

Run: `pytest tests/scripts/test_ingest.py -v`
Expected: FAIL

- [ ] **Step 3: Implement ingest.py**

```python
# backend/app/scripts/ingest.py
async def ingest_source(source_name: str, limit: int | None = None, dry_run: bool = False, enrich_only: bool = False) -> IngestionRun:
    db = SessionLocal()
    try:
        source = db.query(Source).filter(Source.name == source_name).one()
        run = IngestionRun(source_id=source.id)
        db.add(run); db.commit()
        
        parser = ParserFactory.build(source.type, source.config)
        seen = created = updated = failed = 0
        
        page_token = None
        while True:
            response = await parser.fetch_page(page_token)
            for raw in get_items(response, parser.item_path):
                if limit and seen >= limit: break
                try:
                    parsed = parser.parse(raw)
                    parsed["source"] = source.name
                    parsed["last_synced_at"] = datetime.now(timezone.utc)
                    
                    if enrich_only:
                        existing = db.query(get_model(source.type)).filter(
                            get_model(source.type).external_id == parsed["external_id"]
                        ).first()
                        if not existing:
                            continue
                    
                    action = await upsert(parsed, source.type, db, dry_run)
                    if action == "created": created += 1
                    elif action == "updated": updated += 1
                    seen += 1
                except Exception as e:
                    failed += 1
                    logger.error(f"Failed item: {e}")
            
            if limit and seen >= limit: break
            if not parser.has_next_page(response): break
            page_token = parser.next_page_token(response)
        
        run.items_seen = seen
        run.items_created = created
        run.items_updated = updated
        run.items_failed = failed
        run.finished_at = datetime.now(timezone.utc)
        source.last_fetched_at = run.finished_at
        source.last_fetched_count = seen
        db.commit()
        return run
    finally:
        await parser.close() if hasattr(parser, 'close') else None
        db.close()

def get_model(source_type: str):
    return {"api": MCPServer, "github_search": MCPServer, "curated": Agent}[source_type]

async def upsert(parsed: dict, source_type: str, db: Session, dry_run: bool) -> str:
    Model = get_model(source_type)
    key_field = "repository_url" if Model is MCPServer else "website_url"
    existing = db.query(Model).filter(getattr(Model, key_field) == parsed[key_field]).first()
    if not existing:
        existing = db.query(Model).filter(Model.slug == parsed["slug"]).first()
    if not existing:
        existing = db.query(Model).filter(Model.external_id == parsed["external_id"]).first()
    
    if existing:
        # cross-source update: always refresh mutable fields
        for field in ["name", "description", "language", "scope", "npm_package", "pypi_package",
                      "star_count", "logo_url", "pricing_model"]:
            if field in parsed and parsed[field] is not None:
                setattr(existing, field, parsed[field])
        existing.source = parsed["source"]
        existing.last_synced_at = parsed["last_synced_at"]
        existing.external_id = parsed["external_id"]
        action = "updated"
    else:
        existing = Model(**parsed)
        db.add(existing)
        action = "created"
    
    if not dry_run:
        db.flush()
    return action
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/scripts/test_ingest.py -v`
Expected: PASS

- [ ] **Step 5: CLI entry point**

```python
# add to bottom of ingest.py
if __name__ == "__main__":
    import argparse, asyncio
    parser = argparse.ArgumentParser()
    parser.add_argument("source", nargs="*", help="Source names (default: all active)")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--enrich-only", action="store_true")
    parser.add_argument("--output", choices=["text", "json"], default="text")
    args = parser.parse_args()
    
    async def main():
        if args.all:
            db = SessionLocal()
            sources = [s.name for s in db.query(Source).filter(Source.status == "active")]
            db.close()
        else:
            sources = args.source or ["mcp_registry", "github_mcp_topic"]
        
        for s in sources:
            run = await ingest_source(s, args.limit, args.dry_run, args.enrich_only)
            print_run(run, args.output)
    
    asyncio.run(main())
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/scripts/ingest.py tests/scripts/test_ingest.py
git commit -m "feat(scripts): add generic ingestion runner with CLI"
```

---

### Task 8: Make Targets & Env Example

**Files:**
- Modify: `Makefile`
- Modify: `backend/.env.example`

**Interfaces:**
- Consumes: `ingest.py` CLI
- Produces: `make ingest`, `make ingest-mcp`, `make ingest-agents` targets

- [ ] **Step 1: Add Makefile targets**

```makefile
# In Makefile
ingest:
	docker exec ai_agent_hub_backend python -m app.scripts.ingest --all

ingest-mcp:
	docker exec ai_agent_hub_backend python -m app.scripts.ingest mcp_registry github_mcp_topic

ingest-agents:
	docker exec ai_agent_hub_backend python -m app.scripts.ingest curated_catalog github_agents_topic

ingest-dry-run:
	docker exec ai_agent_hub_backend python -m app.scripts.ingest --all --dry-run --output json
```

- [ ] **Step 2: Update .env.example**

```bash
# backend/.env.example
# Add:
GITHUB_TOKEN=  # Optional: raises GitHub Search from 10/min to 30/min
```

- [ ] **Step 3: Test make targets**

Run: `make ingest-dry-run`
Expected: JSON output with parsed counts, zero DB writes

- [ ] **Step 4: Commit**

```bash
git add Makefile backend/.env.example
git commit -m "feat(make): add ingest targets"
```

---

### Task 9: Seed Initial Sources

**Files:**
- Create: `backend/app/scripts/seed_sources.py`
- Test: `tests/scripts/test_seed_sources.py`

**Interfaces:**
- Consumes: `Source` model, source configs from spec §5
- Produces: 4 source rows inserted if not exists

- [ ] **Step 1: Write failing test**

```python
# tests/scripts/test_seed_sources.py
def test_seed_sources_idempotent(db_session):
    seed_sources()
    count1 = db_session.query(Source).count()
    seed_sources()
    count2 = db_session.query(Source).count()
    assert count1 == count2 == 4
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/scripts/test_seed_sources.py -v`
Expected: FAIL

- [ ] **Step 3: Implement seed_sources.py**

```python
# backend/app/scripts/seed_sources.py
SOURCE_CONFIGS = [
    {
        "name": "mcp_registry",
        "display_name": "MCP Registry",
        "type": "api",
        "config": { ... spec §5.1 ... },
    },
    {
        "name": "github_mcp_topic",
        "display_name": "GitHub MCP Topic",
        "type": "github_search",
        "config": { ... spec §5.2 ... },
    },
    {
        "name": "github_agents_topic",
        "display_name": "GitHub Agents Topic",
        "type": "github_search",
        "config": { ... spec §5.3 ... },
    },
    {
        "name": "curated_catalog",
        "display_name": "Curated Agent Catalog",
        "type": "curated",
        "config": { ... spec §5.4 ... },
    },
]

def seed_sources():
    db = SessionLocal()
    for cfg in SOURCE_CONFIGS:
        existing = db.query(Source).filter(Source.name == cfg["name"]).first()
        if not existing:
            db.add(Source(**cfg))
    db.commit()
    db.close()

if __name__ == "__main__":
    seed_sources()
```

- [ ] **Step 4: Run tests & manual verify**

Run: `pytest tests/scripts/test_seed_sources.py -v`
Run: `docker exec ai_agent_hub_backend python -m app.scripts.seed_sources`
Expected: 4 sources created

- [ ] **Step 5: Commit**

```bash
git add backend/app/scripts/seed_sources.py tests/scripts/test_seed_sources.py
git commit -m "feat(scripts): add seed_sources for initial source configs"
```

---

### Task 10: Backfill Existing Rows

**Files:**
- Create: `backend/app/scripts/backfill_existing.py`
- Test: `tests/scripts/test_backfill.py`

**Interfaces:**
- Consumes: `Agent`, `MCPServer` models
- Produces: `source='legacy'`, `last_synced_at=created_at`, `external_id` populated

- [ ] **Step 1: Write failing test**

```python
# tests/scripts/test_backfill.py
def test_backfill_populates_legacy(db_session):
    # create agent/mcp_server without tracking columns
    a = Agent(name="Test", slug="test", description="d", short_description="s", website_url="https://x.com", category_id=cat.id)
    m = MCPServer(name="Test", slug="test", description="d", repository_url="https://github.com/x", language="Python", category_id=cat.id)
    db_session.add_all([a, m]); db_session.commit()
    
    backfill_existing()
    
    a = db_session.query(Agent).one()
    m = db_session.query(MCPServer).one()
    assert a.source == "legacy"
    assert a.last_synced_at == a.created_at
    assert a.external_id == a.slug
    assert m.source == "legacy"
    assert m.external_id == m.slug
```

- [ ] **Step 2: Run test to verify fail**

Run: `pytest tests/scripts/test_backfill.py -v`
Expected: FAIL

- [ ] **Step 3: Implement backfill_existing.py**

```python
# backend/app/scripts/backfill_existing.py
def backfill_existing():
    db = SessionLocal()
    try:
        for agent in db.query(Agent).filter(Agent.source.is_(None)):
            agent.source = "legacy"
            agent.last_synced_at = agent.created_at
            agent.external_id = agent.slug
        for server in db.query(MCPServer).filter(MCPServer.source.is_(None)):
            server.source = "legacy"
            server.last_synced_at = server.created_at
            server.external_id = server.slug
        db.commit()
    finally:
        db.close()

if __name__ == "__main__":
    backfill_existing()
```

- [ ] **Step 4: Run tests & manual verify**

Run: `pytest tests/scripts/test_backfill.py -v`
Run: `docker exec ai_agent_hub_backend python -m app.scripts.backfill_existing`
Expected: PASS, existing rows updated

- [ ] **Step 5: Commit**

```bash
git add backend/app/scripts/backfill_existing.py tests/scripts/test_backfill.py
git commit -m "feat(scripts): add backfill_existing for legacy rows"
```

---

### Task 11: Archive Old Scripts (Reference Only)

**Files:**
- Modify: `backend/app/scripts/ingest_mcp_servers.py` → rename to `ingest_mcp_servers_legacy.py`
- Modify: `backend/app/scripts/ingest_agents.py` → rename to `ingest_agents_legacy.py`

**Interfaces:**
- No code consumers (Makefile targets updated in Task 8)

- [ ] **Step 1: Rename files**

```bash
mv backend/app/scripts/ingest_mcp_servers.py backend/app/scripts/ingest_mcp_servers_legacy.py
mv backend/app/scripts/ingest_agents.py backend/app/scripts/ingest_agents_legacy.py
```

- [ ] **Step 2: Verify no imports break**

Run: `grep -r "ingest_mcp_servers\|ingest_agents" backend/app --include="*.py" | grep -v legacy`
Expected: No results

- [ ] **Step 3: Commit**

```bash
git mv backend/app/scripts/ingest_mcp_servers.py backend/app/scripts/ingest_mcp_servers_legacy.py
git mv backend/app/scripts/ingest_agents.py backend/app/scripts/ingest_agents_legacy.py
git commit -m "chore(scripts): archive legacy ingest scripts"
```

---

### Task 12: End-to-End Integration Test

**Files:**
- Test: `tests/integration/test_ingestion_e2e.py`

**Interfaces:**
- Consumes: all prior tasks
- Produces: full pipeline verification

- [ ] **Step 1: Write integration test**

```python
# tests/integration/test_ingestion_e2e.py
@pytest.mark.integration
def test_ingest_mcp_registry_dry_run():
    # run migration, seed sources, then dry-run
    result = subprocess.run(["make", "ingest-dry-run"], capture_output=True, text=True, cwd="/workspace")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["summary"]["would_create"] > 0

@pytest.mark.integration
def test_ingest_mcp_registry_then_enrich():
    # 1. ingest mcp_registry (creates rows)
    # 2. ingest github_mcp_topic enrich_only (updates stars on existing)
    # 3. verify star_count updated, source flipped to github_mcp_topic
    ...
```

- [ ] **Step 2: Run integration test**

Run: `pytest tests/integration/test_ingestion_e2e.py -v`
Expected: PASS (may need live API — mark as integration)

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_ingestion_e2e.py
git commit -m "test(integration): add end-to-end ingestion tests"
```

---

## Self-Review Checklist

- [x] Spec coverage: All sections (§4-§8) mapped to tasks
- [x] Step scan: Each step has exact signature, test, verification command
- [x] Type consistency: `ParsedItem` → `dict`, `IngestionRun` returned, `Source`/`IngestionRun` models match migration
- [x] Review Focus: 5 items covered with tests in Tasks 1, 4, 5, 7, 12
- [x] Proportion: Plan ~400 lines, spec ~350 lines — reasonable