"""Ingest the curated agent catalog into the database.

Upserts each entry from `agent_catalog.CATALOG` by slug: existing agents are
updated in place, new ones are created. Categories and tags are created on
demand. Re-runs are safe.

Usage (inside the backend container):
    python app/scripts/ingest_agents.py
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models import Agent, Category, PricingModel, Tag
from app.scripts.agent_catalog import CATALOG


def get_or_create_category(db: Session, slug: str) -> Category:
    category = db.query(Category).filter(Category.slug == slug).first()
    if not category:
        category = Category(
            name=slug.replace("-", " ").title(),
            slug=slug,
            description="",
        )
        db.add(category)
        db.flush()
    return category


def get_or_create_tag(db: Session, slug: str) -> Tag:
    tag = db.query(Tag).filter(Tag.slug == slug).first()
    if not tag:
        tag = Tag(
            name=slug.replace("-", " ").title(),
            slug=slug,
            description="",
        )
        db.add(tag)
        db.flush()
    return tag


def upsert_agent(db: Session, entry: dict) -> tuple[Agent, str]:
    """Create or update an agent from a catalog entry. Returns (agent, action)."""
    agent = db.query(Agent).filter(Agent.slug == entry["slug"]).first()
    category = get_or_create_category(db, entry["category"])
    tags = [get_or_create_tag(db, t) for t in entry.get("tags", [])]
    pricing = PricingModel(entry["pricing_model"])

    if agent:
        agent.name = entry["name"]
        agent.description = entry["description"]
        agent.short_description = entry["short_description"]
        agent.logo_url = entry["logo_url"]
        agent.website_url = entry["website_url"]
        agent.category_id = category.id
        agent.pricing_model = pricing
        agent.featured = entry.get("featured", False)
        agent.tags = tags
        return agent, "updated"

    agent = Agent(
        name=entry["name"],
        slug=entry["slug"],
        description=entry["description"],
        short_description=entry["short_description"],
        logo_url=entry["logo_url"],
        website_url=entry["website_url"],
        category_id=category.id,
        pricing_model=pricing,
        featured=entry.get("featured", False),
        view_count=0,
    )
    agent.tags = tags
    db.add(agent)
    return agent, "created"


def main():
    print(f"Ingesting {len(CATALOG)} agents from catalog...")
    db = SessionLocal()
    created = updated = 0

    try:
        for entry in CATALOG:
            _, action = upsert_agent(db, entry)
            if action == "created":
                created += 1
            else:
                updated += 1
            print(f"  {action.upper():7} {entry['name']}")

        db.commit()
        print(f"\nDone. Created {created}, updated {updated}.")
    except Exception as e:
        db.rollback()
        print(f"Error during ingest: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()