from sqlalchemy import Column, String, Text, DateTime, Boolean, Integer, ForeignKey, Enum as SQLEnum, Table
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum

from app.db.database import Base


class ServerScope(str, enum.Enum):
    """Scope/deployment type for MCP servers."""
    LOCAL = "local"
    CLOUD = "cloud"
    HYBRID = "hybrid"


# Association table for mcp_server-tag many-to-many relationship
mcp_server_tags = Table(
    'mcp_server_tags',
    Base.metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column('mcp_server_id', UUID(as_uuid=True), ForeignKey('mcp_servers.id', ondelete='CASCADE'), nullable=False),
    Column('tag_id', UUID(as_uuid=True), ForeignKey('tags.id', ondelete='CASCADE'), nullable=False),
    Column('created_at', DateTime(timezone=True), server_default=func.now(), nullable=False)
)


class MCPServer(Base):
    """MCP (Model Context Protocol) Server model.
    
    MCP Servers are implementations of the Model Context Protocol that enable
    AI agents to interact with external tools, data sources, and services.
    
    Attributes:
        id: Unique identifier (UUID)
        name: Display name of the MCP server
        slug: URL-friendly identifier
        description: Full description of capabilities and features
        repository_url: URL to source code repository (GitHub, GitLab, etc.)
        language: Programming language (Python, TypeScript, JavaScript, Go, Rust, etc.)
        scope: Deployment scope (local, cloud, hybrid)
        category_id: Foreign key to Category
        logo_url: Optional URL to server's logo/icon
        npm_package: NPM package name if applicable
        pypi_package: PyPI package name if applicable
        star_count: GitHub stars or similar metric
        created_at: Timestamp when server was added
        updated_at: Timestamp when server info was last updated
        featured: Whether server is featured on homepage
        view_count: Number of times server has been viewed
    """
    __tablename__ = "mcp_servers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False, index=True)
    slug = Column(String(200), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=False)
    repository_url = Column(String(500), nullable=False)
    language = Column(String(50), nullable=False, index=True)
    scope = Column(SQLEnum(ServerScope), nullable=False, default=ServerScope.LOCAL, index=True)
    category_id = Column(UUID(as_uuid=True), ForeignKey('categories.id'), nullable=False, index=True)
    logo_url = Column(String(500), nullable=True)
    npm_package = Column(String(200), nullable=True)
    pypi_package = Column(String(200), nullable=True)
    star_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    featured = Column(Boolean, default=False, nullable=False, index=True)
    view_count = Column(Integer, default=0, nullable=False)

    # Ingestion tracking
    source = Column(String(32), nullable=True, index=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    external_id = Column(String(200), nullable=True, index=True)

    # Relationships
    category = relationship("Category", back_populates="mcp_servers")
    tags = relationship("Tag", secondary=mcp_server_tags, back_populates="mcp_servers")
    favorites = relationship("UserFavorite", back_populates="mcp_server", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<MCPServer {self.name}>"
