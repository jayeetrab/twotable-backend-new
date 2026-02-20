from sqlalchemy import Column, Integer, String, Text, DateTime, func
from pgvector.sqlalchemy import Vector

from app.db.session import Base


class IntentEmbedding(Base):
    """
    Logged representation of a user's booking intent at search time.
    Used for analytics, A/B testing scoring weights, and offline re-ranking.
    NOT on the hot booking path — written fire-and-forget.
    """
    __tablename__ = "intent_embeddings"

    id = Column(Integer, primary_key=True, index=True)

    # Ties the intent to a booking session or anonymous search session
    session_id = Column(String(120), nullable=True, index=True)

    intent_text = Column(Text, nullable=False)
    embedding = Column(Vector(384), nullable=False)
    model_name = Column(String(120), nullable=False)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
