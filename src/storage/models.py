"""
SQLAlchemy ORM models for persisting collected articles, trends,
source metadata, and agent run history.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Source(Base):
    """
    Represents a known information source (RSS feed, web URL, etc.).
    New sources can be discovered dynamically and added here.
    """

    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), nullable=False)
    url = Column(String(1024), nullable=False, unique=True)
    source_type = Column(String(64), nullable=False, default="rss")  # rss | web | github | arxiv
    category = Column(String(64), nullable=False, default="general")
    relevance_boost = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    discovered_at = Column(DateTime, default=_now_utc)
    last_fetched_at = Column(DateTime, nullable=True)
    fetch_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)

    articles = relationship("Article", back_populates="source", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Source name={self.name!r} type={self.source_type!r}>"


class Article(Base):
    """
    A single piece of content collected from a source – could be a blog post,
    paper abstract, GitHub trending repo description, etc.
    """

    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("url", name="uq_article_url"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)

    # Core metadata
    title = Column(String(512), nullable=False)
    url = Column(String(1024), nullable=False)
    author = Column(String(256), nullable=True)
    published_at = Column(DateTime, nullable=True)
    collected_at = Column(DateTime, default=_now_utc)
    category = Column(String(64), nullable=False, default="general")

    # Raw + processed content
    raw_content = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)         # AI-generated summary
    key_insights = Column(Text, nullable=True)    # JSON list of insight strings
    qa_relevance = Column(Text, nullable=True)    # "How this helps the QA Manager"

    # Scoring
    relevance_score = Column(Float, default=0.0)  # 0-100

    # Processing state
    is_processed = Column(Boolean, default=False)
    is_included_in_report = Column(Boolean, default=False)

    source = relationship("Source", back_populates="articles")
    trend_tags = relationship("ArticleTrendTag", back_populates="article", cascade="all, delete-orphan")

    @property
    def insights_list(self) -> list[str]:
        """Deserialise the JSON-stored key_insights field."""
        if self.key_insights:
            try:
                return json.loads(self.key_insights)
            except (json.JSONDecodeError, TypeError):
                return []
        return []

    def __repr__(self) -> str:
        return f"<Article title={self.title[:40]!r} score={self.relevance_score}>"


class Trend(Base):
    """
    A detected trend – a cluster of themes appearing across multiple articles
    in a time window.
    """

    __tablename__ = "trends"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(64), nullable=False, default="general")
    first_seen_at = Column(DateTime, default=_now_utc)
    last_seen_at = Column(DateTime, default=_now_utc)
    article_count = Column(Integer, default=1)
    momentum_score = Column(Float, default=0.0)  # How fast it's accelerating
    is_alert = Column(Boolean, default=False)    # Should user be notified?

    tags = relationship("ArticleTrendTag", back_populates="trend", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Trend name={self.name!r} momentum={self.momentum_score}>"


class ArticleTrendTag(Base):
    """Many-to-many link between Articles and Trends."""

    __tablename__ = "article_trend_tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    trend_id = Column(Integer, ForeignKey("trends.id"), nullable=False)

    article = relationship("Article", back_populates="trend_tags")
    trend = relationship("Trend", back_populates="tags")


class AgentRun(Base):
    """
    Audit log of every agent execution cycle – allows the agent to track
    its own performance and growth over time.
    """

    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime, default=_now_utc)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String(32), default="running")   # running | success | failed
    sources_checked = Column(Integer, default=0)
    articles_collected = Column(Integer, default=0)
    articles_processed = Column(Integer, default=0)
    trends_detected = Column(Integer, default=0)
    new_sources_discovered = Column(Integer, default=0)
    report_path = Column(String(512), nullable=True)
    error_message = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<AgentRun id={self.id} status={self.status!r}>"


class SeenItem(Base):
    """
    REQ-07: Persistent deduplication store.

    Tracks every URL that has been included in a generated report so it is
    never shown to the user more than once across all past and future reports.
    Collected-but-deduped articles are still available for trend analysis.
    """

    __tablename__ = "seen_items"
    __table_args__ = (UniqueConstraint("url", name="uq_seen_url"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(1024), nullable=False, unique=True)
    title = Column(String(512), nullable=True)
    first_seen_at = Column(DateTime, nullable=False, default=_now_utc)
    report_count = Column(Integer, nullable=False, default=1)

    def __repr__(self) -> str:
        return f"<SeenItem url={self.url!r:.60}>"


class KnowledgeExpansion(Base):
    """
    Records every time the agent expands its own knowledge base by learning
    about a new source, technology area, or keyword cluster.
    """

    __tablename__ = "knowledge_expansions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    expansion_type = Column(String(64), nullable=False)  # new_source | new_keyword | new_trend_area
    description = Column(Text, nullable=False)
    value = Column(Text, nullable=False)   # The actual URL / keyword / area name
    confidence = Column(Float, default=1.0)
    discovered_at = Column(DateTime, default=_now_utc)

    def __repr__(self) -> str:
        return f"<KnowledgeExpansion type={self.expansion_type!r}>"
