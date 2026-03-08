"""
Data Access Layer – all database interactions go through this module.
Keeps SQL logic out of business logic and makes testing easier.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.storage.models import (
    AgentRun,
    Article,
    ArticleTrendTag,
    KnowledgeExpansion,
    SeenItem,
    Source,
    Trend,
)

logger = logging.getLogger(__name__)


# ── Source Repository ──────────────────────────────────────────────────────────

class SourceRepository:
    """CRUD operations for Source records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_all_active(self) -> list[Source]:
        """Return all active sources ordered by name."""
        return list(
            self._session.execute(
                select(Source).where(Source.is_active.is_(True)).order_by(Source.name)
            ).scalars()
        )

    def get_by_url(self, url: str) -> Optional[Source]:
        return self._session.execute(
            select(Source).where(Source.url == url)
        ).scalar_one_or_none()

    def upsert(self, name: str, url: str, source_type: str, category: str, relevance_boost: int = 0) -> Source:
        """Insert a new source or return the existing one if the URL already exists."""
        existing = self.get_by_url(url)
        if existing:
            return existing
        source = Source(
            name=name,
            url=url,
            source_type=source_type,
            category=category,
            relevance_boost=relevance_boost,
        )
        self._session.add(source)
        self._session.flush()
        logger.info("New source registered: %s (%s)", name, url)
        return source

    def mark_fetched(self, source: Source, had_error: bool = False) -> None:
        source.last_fetched_at = datetime.now(timezone.utc)
        source.fetch_count += 1
        if had_error:
            source.error_count += 1


# ── Article Repository ─────────────────────────────────────────────────────────

class ArticleRepository:
    """CRUD operations for Article records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def exists(self, url: str) -> bool:
        """Check if an article with this URL has already been collected."""
        result = self._session.execute(
            select(func.count()).select_from(Article).where(Article.url == url)
        ).scalar()
        return bool(result and result > 0)

    def create(self, **kwargs) -> Article:
        article = Article(**kwargs)
        self._session.add(article)
        self._session.flush()
        return article

    def get_unprocessed(self, limit: int = 50) -> list[Article]:
        return list(
            self._session.execute(
                select(Article)
                .where(Article.is_processed.is_(False))
                .order_by(Article.collected_at.desc())
                .limit(limit)
            ).scalars()
        )

    def get_for_report(self, since: datetime, min_score: float = 60.0) -> list[Article]:
        """Return processed articles suitable for the next report."""
        return list(
            self._session.execute(
                select(Article)
                .where(
                    Article.is_processed.is_(True),
                    Article.relevance_score >= min_score,
                    Article.collected_at >= since,
                )
                .order_by(Article.relevance_score.desc())
            ).scalars()
        )

    def count_since(self, since: datetime) -> int:
        result = self._session.execute(
            select(func.count()).select_from(Article).where(Article.collected_at >= since)
        ).scalar()
        return int(result or 0)


# ── Trend Repository ───────────────────────────────────────────────────────────

class TrendRepository:
    """CRUD operations for Trend records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_or_create(self, name: str, category: str) -> tuple[Trend, bool]:
        """
        Returns (trend, created) – True if the trend was newly created.
        """
        existing = self._session.execute(
            select(Trend).where(Trend.name == name)
        ).scalar_one_or_none()
        if existing:
            return existing, False
        trend = Trend(name=name, category=category)
        self._session.add(trend)
        self._session.flush()
        return trend, True

    def link_article(self, trend: Trend, article: Article) -> None:
        """Associate an article with a trend (idempotent – safe to call multiple times)."""
        already_linked = self._session.execute(
            select(func.count()).select_from(ArticleTrendTag).where(
                ArticleTrendTag.article_id == article.id,
                ArticleTrendTag.trend_id == trend.id,
            )
        ).scalar()
        if already_linked:
            return
        tag = ArticleTrendTag(article_id=article.id, trend_id=trend.id)
        self._session.add(tag)
        self._session.flush()
        trend.article_count += 1
        trend.last_seen_at = datetime.now(timezone.utc)

    def get_top_trends(self, limit: int = 10, days: int = 7) -> list[Trend]:
        """Return most prominent trends over the last N days."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        return list(
            self._session.execute(
                select(Trend)
                .where(Trend.last_seen_at >= since)
                .order_by(Trend.momentum_score.desc())
                .limit(limit)
            ).scalars()
        )

    def get_alert_trends(self) -> list[Trend]:
        return list(
            self._session.execute(
                select(Trend).where(Trend.is_alert.is_(True))
            ).scalars()
        )


# ── AgentRun Repository ────────────────────────────────────────────────────────

class AgentRunRepository:
    """Audit log for agent execution cycles."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def start_run(self) -> AgentRun:
        run = AgentRun(started_at=datetime.now(timezone.utc), status="running")
        self._session.add(run)
        self._session.flush()
        return run

    def finish_run(self, run: AgentRun, **stats) -> None:
        run.finished_at = datetime.now(timezone.utc)
        run.status = "success"
        for key, value in stats.items():
            setattr(run, key, value)

    def fail_run(self, run: AgentRun, error: str) -> None:
        run.finished_at = datetime.now(timezone.utc)
        run.status = "failed"
        run.error_message = error

    def get_last(self, n: int = 5) -> list[AgentRun]:
        return list(
            self._session.execute(
                select(AgentRun).order_by(AgentRun.started_at.desc()).limit(n)
            ).scalars()
        )


# ── KnowledgeExpansion Repository ─────────────────────────────────────────────

class KnowledgeExpansionRepository:
    """Tracks everything the agent has learned about itself."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, expansion_type: str, description: str, value: str, confidence: float = 1.0) -> KnowledgeExpansion:
        exp = KnowledgeExpansion(
            expansion_type=expansion_type,
            description=description,
            value=value,
            confidence=confidence,
        )
        self._session.add(exp)
        self._session.flush()
        return exp

    def already_known(self, value: str) -> bool:
        result = self._session.execute(
            select(func.count())
            .select_from(KnowledgeExpansion)
            .where(KnowledgeExpansion.value == value)
        ).scalar()
        return bool(result and result > 0)


# ── Seen-Item Repository (REQ-07) ─────────────────────────────────────────────

class SeenItemRepository:
    """
    REQ-07: Persistent deduplication store.

    Every URL included in a generated report is recorded here so no article
    is ever shown to the user more than once across all past and future reports.
    Deduped articles remain in the DB and still count for trend analysis.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def is_seen(self, url: str) -> bool:
        """Return True if the URL has already been shown in a past report."""
        return bool(
            self._session.execute(
                select(func.count()).select_from(SeenItem).where(SeenItem.url == url)
            ).scalar()
        )

    def get_seen_urls(self) -> set[str]:
        """Return the full set of already-seen URLs for bulk filtering."""
        return set(self._session.execute(select(SeenItem.url)).scalars().all())

    def mark_seen(self, url: str, title: Optional[str] = None) -> None:
        """Mark a URL as seen (idempotent – increments counter on repeats)."""
        existing = self._session.execute(
            select(SeenItem).where(SeenItem.url == url)
        ).scalar_one_or_none()
        if existing:
            existing.report_count += 1
        else:
            self._session.add(SeenItem(url=url, title=title))
        self._session.flush()

    def mark_seen_bulk(self, articles: list) -> int:
        """
        Mark all articles as seen. Returns count of newly-marked items.

        Args:
            articles: ORM Article objects with .url and .title attributes.
        """
        existing_urls = self.get_seen_urls()
        new_count = 0
        for article in articles:
            if article.url not in existing_urls:
                self._session.add(SeenItem(url=article.url, title=article.title))
                new_count += 1
            else:
                existing = self._session.execute(
                    select(SeenItem).where(SeenItem.url == article.url)
                ).scalar_one_or_none()
                if existing:
                    existing.report_count += 1
        self._session.flush()
        return new_count
