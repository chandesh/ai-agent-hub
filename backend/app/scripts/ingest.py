"""Generic, config-driven ingestion runner.

Sources live in the ``sources`` table; the parser is selected from the
source's ``type``. This module handles pagination, normalization, upsert and
audit logging for every source.
"""

import argparse
import asyncio
import json
import logging
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models import (
    Agent,
    Category,
    IngestionRun,
    MCPServer,
    PricingModel,
    ServerScope,
    Source,
    Tag,
)
from app.scripts.parsers import ParserFactory
from app.scripts.parsers.curated import CuratedParser

logger = logging.getLogger(__name__)

ENTITY_MODELS = {"agent": Agent, "mcp_server": MCPServer}
DEFAULT_ENTITY = {"api": "mcp_server", "github_search": "mcp_server", "curated": "agent"}

MUTABLE_FIELDS = {
    "MCPServer": (
        "name",
        "description",
        "language",
        "scope",
        "npm_package",
        "pypi_package",
        "star_count",
        "logo_url",
    ),
    "Agent": (
        "name",
        "description",
        "short_description",
        "logo_url",
        "website_url",
        "pricing_model",
        "featured",
        "category_id",
    ),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _model_for(source: Source) -> type:
    config = source.config or {}
    entity = config.get("entity") or DEFAULT_ENTITY.get(source.type)
    if entity not in ENTITY_MODELS:
        raise ValueError(f"Unknown source entity: {entity!r} for source {source.name}")
    return ENTITY_MODELS[entity]


def _url_field(model: type) -> str:
    return "repository_url" if model is MCPServer else "website_url"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug or "unnamed"


def _find_existing(db: Session, model: type, item: dict) -> Any:
    url_field = _url_field(model)
    candidates = (
        (url_field, item.get(url_field)),
        ("slug", item.get("slug")),
        ("external_id", item.get("external_id")),
    )
    for field, value in candidates:
        if not value:
            continue
        found = db.query(model).filter(getattr(model, field) == value).first()
        if found is not None:
            return found
    return None


def _category_slug(item: dict, config: dict) -> str | None:
    explicit = item.get("category")
    if explicit:
        return explicit

    mapping = config.get("category_mapping") or {}
    slug = mapping.get("default") or "developer-tools"
    text = f"{item.get('name') or ''} {item.get('description') or ''}"
    for pattern, keyword_slug in mapping.get("keywords", {}).items():
        if re.search(pattern, text, re.IGNORECASE):
            slug = keyword_slug
            break
    return slug


def _get_or_create_category(db: Session, slug: str) -> Category:
    category = db.query(Category).filter(Category.slug == slug).first()
    if category is None:
        category = Category(
            name=slug.replace("-", " ").title(),
            slug=slug,
            description="",
        )
        db.add(category)
        db.flush()
    return category


def _get_or_create_tag(db: Session, slug: str) -> Tag:
    tag = db.query(Tag).filter(Tag.slug == slug).first()
    if tag is None:
        tag = Tag(name=slug.replace("-", " ").title(), slug=slug, description="")
        db.add(tag)
        db.flush()
    return tag


def _normalize_item(parsed: dict, model: type, config: dict) -> dict:
    """Fill required fields/defaults; raise ValueError if unusable."""
    item = {key: value for key, value in parsed.items() if value is not None}

    external_id = item.get("external_id") or item.get("slug") or item.get("name")
    if not external_id:
        raise ValueError("item has no external_id, slug, or name")
    item["external_id"] = str(external_id)

    name = item.get("name")
    if not name:
        name = str(external_id).rsplit("/", 1)[-1]
    item["name"] = str(name)
    item["slug"] = _slugify(str(item.get("slug") or external_id or name))
    item.setdefault("description", item["name"])

    if model is MCPServer:
        repository_url = item.get("repository_url")
        if not repository_url:
            if str(external_id).startswith(("http://", "https://")):
                repository_url = str(external_id)
            elif config.get("endpoint"):
                repository_url = f"{config['endpoint']}/{external_id}"
        if not repository_url:
            raise ValueError("MCP server has no repository_url")
        item["repository_url"] = repository_url
        item["language"] = item.get("language") or "Other"
        try:
            item["scope"] = ServerScope(str(item.get("scope") or "local").lower())
        except ValueError:
            item["scope"] = ServerScope.LOCAL
    elif model is Agent:
        website_url = item.get("website_url") or item.get("repository_url")
        if not website_url and str(external_id).startswith(("http://", "https://")):
            website_url = str(external_id)
        if not website_url:
            raise ValueError("agent has no website_url")
        item["website_url"] = website_url
        short_description = item.get("short_description") or item["description"]
        item["short_description"] = str(short_description)[:160]
        try:
            item["pricing_model"] = PricingModel(
                str(item.get("pricing_model") or "free").lower()
            )
        except ValueError:
            item["pricing_model"] = PricingModel.FREE

    category_slug = _category_slug(item, config)
    if category_slug:
        item["category"] = category_slug

    return item


def _model_fields(model: type) -> set[str]:
    return {
        column.key
        for column in model.__table__.columns
        if column.key not in ("id", "created_at", "updated_at")
    }


def _clean_for_model(item: dict, model: type) -> dict:
    allowed = _model_fields(model)
    return {key: value for key, value in item.items() if key in allowed}


def _sync_tags(db: Session, obj: Agent, tag_slugs: list[str] | None) -> None:
    if tag_slugs is None:
        return
    obj.tags = [_get_or_create_tag(db, slug) for slug in tag_slugs]


def _upsert(
    db: Session,
    model: type,
    item: dict,
    config: dict,
    dry_run: bool,
) -> tuple[str, dict]:
    """Create/update one item. In dry-run mode nothing is mutated."""
    existing = _find_existing(db, model, item)

    category_slug = _category_slug(item, config)
    if category_slug:
        if dry_run:
            category = db.query(Category).filter(Category.slug == category_slug).first()
            if category is not None:
                item["category_id"] = category.id
        else:
            item["category_id"] = _get_or_create_category(db, category_slug).id

    if existing is not None:
        diff: dict[str, dict] = {}
        for field in MUTABLE_FIELDS.get(model.__name__, ()):
            if field not in item or item[field] is None:
                continue
            old = getattr(existing, field)
            new = item[field]
            if old != new:
                diff[field] = {"old": old, "new": new}
                if not dry_run:
                    setattr(existing, field, new)

        if not dry_run:
            existing.source = item["source"]
            existing.last_synced_at = item["last_synced_at"]
            existing.external_id = item["external_id"]
            if model is Agent:
                _sync_tags(db, existing, item.get("tags"))
            db.flush()
        return "updated", diff

    clean = _clean_for_model(item, model)
    if dry_run:
        return "created", clean

    obj = model(**clean)
    db.add(obj)
    db.flush()
    if model is Agent:
        _sync_tags(db, obj, item.get("tags"))
    return "created", clean


def _record_error(run: IngestionRun, message: str) -> None:
    errors = getattr(run, "_errors", [])
    if len(errors) < 5:
        errors.append(message)
    run._errors = errors
    run.error_summary = "; ".join(errors)


async def ingest_source(
    source_name: str,
    limit: int | None = None,
    dry_run: bool = False,
    enrich_only: bool = False,
    db: Session | None = None,
) -> IngestionRun:
    """Run one configured source and return its (transient in dry-run) audit row."""
    owns_session = db is None
    db = db or SessionLocal()
    parser = None
    try:
        source = db.query(Source).filter(Source.name == source_name).one()
        model = _model_for(source)
        parser = ParserFactory.build(source.type, source.config)

        run = IngestionRun(source_id=source.id)
        if dry_run:
            run.started_at = _now()
        else:
            db.add(run)
            db.flush()

        summary: dict[str, Any] = {
            "would_create": 0,
            "would_update": 0,
            "would_skip": 0,
            "errors": 0,
            "items": [],
        }
        seen = created = updated = failed = 0
        schema_checked = False
        page_token: str | int | None = None

        async def process(raw: dict) -> None:
            nonlocal seen, created, updated, failed, schema_checked

            if not schema_checked and source.config.get("expected_schema_url"):
                schema_checked = True
                if hasattr(parser, "_check_schema") and not parser._check_schema(raw):
                    reason = (
                        "Schema version changed: "
                        f"{raw.get('server', {}).get('$schema')}"
                    )
                    source.status = "error"
                    source.last_error = reason
                    _record_error(run, reason)
                    raise SchemaMismatch(reason)

            if limit is not None and seen >= limit:
                return

            seen += 1
            try:
                parsed = parser.parse(raw)
                item = _normalize_item(parsed, model, source.config)
                item["source"] = source.name
                item["last_synced_at"] = _now()

                if enrich_only and _find_existing(db, model, item) is None:
                    summary["would_skip"] += 1
                    summary["items"].append(
                        {
                            "action": "skipped",
                            "external_id": item["external_id"],
                        }
                    )
                    return

                action, detail = _upsert(db, model, item, source.config, dry_run)
                if dry_run:
                    summary[
                        "would_create" if action == "created" else "would_update"
                    ] += 1
                elif action == "created":
                    created += 1
                else:
                    updated += 1
                summary["items"].append(
                    {
                        "action": action,
                        "external_id": item["external_id"],
                        "diff" if action == "updated" else "fields": detail,
                    }
                )
            except SchemaMismatch:
                raise
            except Exception as exc:  # noqa: BLE001 - one bad item must not stop a run
                failed += 1
                summary["errors"] += 1
                logger.warning("Failed item from %s: %s", source.name, exc)
                _record_error(run, str(exc))
                summary["items"].append({"action": "error", "error": str(exc)})

        try:
            if isinstance(parser, CuratedParser):
                for raw in parser.iter_items(enrich_only):
                    await process(raw)
                    if limit is not None and seen >= limit:
                        break
            else:
                while True:
                    response = await parser.fetch_page(page_token)
                    for raw in parser.get_items(response):
                        await process(raw)
                        if limit is not None and seen >= limit:
                            break

                    if limit is not None and seen >= limit:
                        break
                    if not parser.has_next_page(response):
                        break
                    page_token = parser.next_page_token(response)
        except SchemaMismatch:
            pass

        run.items_seen = seen
        run.items_created = created
        run.items_updated = updated
        run.items_failed = failed
        run.finished_at = _now()

        if not dry_run:
            source.last_fetched_at = run.finished_at
            source.last_fetched_count = seen
            if source.status != "error" and failed:
                _record_error(run, f"{failed} item(s) failed")
            db.commit()
            db.refresh(run)
        else:
            if source.status == "error":
                db.rollback()
                db.refresh(source)

        run.summary = summary
        run.dry_run = dry_run
        run.source_name = source.name
        return run
    finally:
        if parser is not None:
            try:
                await parser.close()
            except Exception:  # noqa: BLE001
                logger.debug("Parser close failed", exc_info=True)
        if owns_session:
            db.close()


class SchemaMismatch(Exception):
    """Raised when the payload schema does not match the pinned version."""


def _run_payload(run: IngestionRun) -> dict:
    summary = getattr(run, "summary", {})
    return {
        "source": getattr(run, "source_name", None),
        "dry_run": getattr(run, "dry_run", False),
        "items": summary.get("items", []),
        "summary": {
            key: value for key, value in summary.items() if key != "items"
        },
        "counts": {
            "seen": run.items_seen,
            "created": run.items_created,
            "updated": run.items_updated,
            "failed": run.items_failed,
        },
    }


def print_run(run: IngestionRun, output: str = "text") -> None:
    if output == "json":
        print(json.dumps(_run_payload(run), default=str))
        return
    summary = getattr(run, "summary", {})
    print(
        f"{getattr(run, 'source_name', '?')}: seen={run.items_seen} "
        f"created={run.items_created} updated={run.items_updated} "
        f"failed={run.items_failed} would_create={summary.get('would_create', 0)} "
        f"would_update={summary.get('would_update', 0)}"
    )


async def _main_async(args: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        if args.all:
            sources = [
                row.name for row in db.query(Source).filter(Source.status == "active")
            ]
        else:
            sources = args.source or ["mcp_registry", "github_mcp_topic"]
    finally:
        db.close()

    failures = 0
    payloads = []
    for source_name in sources:
        try:
            run = await ingest_source(
                source_name,
                limit=args.limit,
                dry_run=args.dry_run,
                enrich_only=args.enrich_only,
            )
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"{source_name}: ERROR {exc}", file=sys.stderr)
            continue

        if args.output == "json":
            payloads.append(_run_payload(run))
        else:
            print_run(run, "text")

    if args.output == "json":
        if len(payloads) == 1:
            print(json.dumps(payloads[0], default=str))
        else:
            print(json.dumps({"runs": payloads}, default=str))

    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run ingestion sources")
    parser.add_argument("source", nargs="*", help="Source names (default: MCP sources)")
    parser.add_argument("--all", action="store_true", help="Run all active sources")
    parser.add_argument("--limit", type=int, help="Max items per source")
    parser.add_argument("--dry-run", action="store_true", help="Parse without writing")
    parser.add_argument(
        "--enrich-only", action="store_true", help="Only update existing rows"
    )
    parser.add_argument("--output", choices=["text", "json"], default="text")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
