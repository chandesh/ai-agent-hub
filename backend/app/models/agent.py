from sqlalchemy import Column, String, Text, DateTime, Boolean, Integer, ForeignKey, Enum as SQLEnum, Table
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum

from app.db.database import Base


class PricingModel(str, enum.Enum):
    """Pricing model options for agents."""
    FREE = "free"
    FREEMIUM = "freemium"
    PAID = "paid"


# Association table for agent-tag many-to-many relationship
agent_tags = Table(
    'agent_tags',
    Base.metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column('agent_id', UUID(as_uuid=True), ForeignKey('agents.id', ondelete='CASCADE'), nullable=False),
    Column('tag_id', UUID(as_uuid=True), ForeignKey('tags.id', ondelete='CASCADE'), nullable=False),
    Column('created_at', DateTime(timezone=True), server_default=func.now(), nullable=False)
)


class Agent(Base):
    """AI Agent model representing individual AI agents/tools.
    
    Agents are AI-powered tools, assistants, or platforms that users can
    discover and compare. Examples: ChatGPT, Claude, Midjourney, etc.
    
    Attributes:
        id: Unique identifier (UUID)
        name: Display name of the agent
        slug: URL-friendly identifier for the agent
        description: Full description with features and capabilities
        short_description: Brief description (max 160 chars) for previews
        logo_url: Optional URL to agent's logo/icon
        website_url: Official website of the agent
        category_id: Foreign key to Category
        pricing_model: Enum (free, freemium, paid)
        created_at: Timestamp when agent was added
        updated_at: Timestamp when agent info was last updated
        featured: Whether agent is featured on homepage
        view_count: Number of times agent has been viewed
    """
    __tablename__ = "agents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False, index=True)
    slug = Column(String(200), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=False)
    short_description = Column(String(160), nullable=False)
    logo_url = Column(String(500), nullable=True)
    website_url = Column(String(500), nullable=False)
    category_id = Column(UUID(as_uuid=True), ForeignKey('categories.id'), nullable=False, index=True)
    pricing_model = Column(SQLEnum(PricingModel), nullable=False, default=PricingModel.FREE)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    featured = Column(Boolean, default=False, nullable=False, index=True)
    view_count = Column(Integer, default=0, nullable=False)

    # Ingestion tracking
    source = Column(String(32), nullable=True, index=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    external_id = Column(String(200), nullable=True, index=True)

    # Relationships
    category = relationship("Category", back_populates="agents")
    tags = relationship("Tag", secondary=agent_tags, back_populates="agents")
    favorites = relationship("UserFavorite", back_populates="agent", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Agent {self.name}>"
