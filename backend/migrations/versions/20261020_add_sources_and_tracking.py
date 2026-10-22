"""add sources, ingestion_runs, tracking columns

Revision ID: 20261020addsources
Revises: 5e6c58954215
Create Date: 2026-10-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20261020addsources"
down_revision: Union[str, None] = "5e6c58954215"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fetched_count", sa.Integer(), server_default="0", nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "ingestion_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("items_seen", sa.Integer(), server_default="0", nullable=True),
        sa.Column("items_created", sa.Integer(), server_default="0", nullable=True),
        sa.Column("items_updated", sa.Integer(), server_default="0", nullable=True),
        sa.Column("items_failed", sa.Integer(), server_default="0", nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ingestion_runs_source_id"), "ingestion_runs", ["source_id"], unique=False
    )

    for table in ("agents", "mcp_servers"):
        op.add_column(table, sa.Column("source", sa.String(length=32), nullable=True))
        op.add_column(
            table, sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True)
        )
        op.add_column(table, sa.Column("external_id", sa.String(length=200), nullable=True))
        op.execute(
            f"UPDATE {table} SET source = 'legacy', last_synced_at = created_at "
            "WHERE source IS NULL"
        )
        op.execute(f"UPDATE {table} SET external_id = slug WHERE external_id IS NULL")
        op.create_index(op.f(f"ix_{table}_source"), table, ["source"], unique=False)
        op.create_index(
            op.f(f"ix_{table}_external_id"), table, ["external_id"], unique=False
        )


def downgrade() -> None:
    for table in ("agents", "mcp_servers"):
        op.drop_index(op.f(f"ix_{table}_external_id"), table_name=table)
        op.drop_index(op.f(f"ix_{table}_source"), table_name=table)
        op.drop_column(table, "external_id")
        op.drop_column(table, "last_synced_at")
        op.drop_column(table, "source")

    op.drop_index(op.f("ix_ingestion_runs_source_id"), table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
    op.drop_table("sources")
