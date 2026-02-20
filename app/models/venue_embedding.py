from sqlalchemy import (
    Column, Integer, String, Text, DateTime,
    ForeignKey, UniqueConstraint, func,
)
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from app.db.session import Base


class VenueEmbedding(Base):
    """
    One embedding row per active venue.
    Dimension (768) is fixed to match EMBEDDING_DIM in config.
    To change dimension: write a new migration to ALTER the column,
    then re-run embed-all.
    """
    __tablename__ = "venue_embeddings"
    __table_args__ = (
        UniqueConstraint("venue_id", name="uq_venue_embeddings_venue_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    venue_id = Column(
        Integer,
        ForeignKey("venues.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Vector dimension must match EMBEDDING_DIM env var
    embedding = Column(Vector(384), nullable=False)

    model_name = Column(String(120), nullable=False)

    # source_text stored for auditing / detecting when re-embedding is needed
    source_text = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    venue = relationship("Venue", back_populates="embedding")
