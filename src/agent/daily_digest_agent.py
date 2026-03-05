"""
Daily Digest Agent – end-of-day summary agent.

Runs once per day (default: 22:00 UTC) and produces a comprehensive
daily digest of everything collected during the day.

Digest content per article:
  - Title + clickable URL
  - AI summary (if available)
  - Keywords (extracted or AI-generated)
  - Published date (when the content appeared online)
  - Collected date (when this agent picked it up)
  - Relevance score
  - Category

Report structure:
  1. Day-in-numbers banner (totals, categories breakdown)
  2. Alert trends
  3. Full sortable table of all articles
  4. Category-grouped article cards (with summaries)
  5. Keyword cloud (most frequent terms of the day)
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from src.config.settings import settings
from src.notifications.notifier import Notifier
from src.processors.keyword_extractor import KeywordExtractor
from src.reports.daily_digest_generator import DailyDigestGenerator
from src.storage.database import get_session, init_db
from src.storage.models import Article
from src.storage.repository import (
    ArticleRepository,
    TrendRepository,
)

logger = logging.getLogger(__name__)


@dataclass
class DigestArticle:
    """
    Lightweight, serialisable view of an article for the digest report.
    All dates are pre-formatted strings so templates stay logic-free.
    """
    id: int
    title: str
    url: str
    category: str
    summary: Optional[str]
    keywords: list[str]
    published_date: str         # formatted: "02 Mar 2026 14:30 UTC"
    collected_date: str         # formatted: "02 Mar 2026 17:21 UTC"
    relevance_score: float
    source_name: str = ""
    has_summary: bool = False


@dataclass
class DigestStats:
    """Aggregate statistics for the daily digest banner."""
    date_str: str
    total_articles: int = 0
    total_sources: int = 0
    avg_relevance: float = 0.0
    top_category: str = ""
    alert_count: int = 0
    category_counts: dict[str, int] = field(default_factory=dict)
    top_keywords: list[tuple[str, int]] = field(default_factory=list)


class DailyDigestAgent:
    """
    End-of-day summary agent.

    Collects all articles gathered today, enriches them with keywords,
    and generates a comprehensive digest report + sends it by email.

    Args:
        lookback_hours: How many hours back to consider as "today"
                        (default 24 – previous midnight to now).
        min_score:      Minimum relevance score to include an article.
    """

    def __init__(
        self,
        lookback_hours: int = 24,
        min_score: float = 30.0,
    ) -> None:
        init_db()
        self._lookback_hours = lookback_hours
        self._min_score = min_score
        self._extractor = KeywordExtractor(use_llm=bool(settings.openai_api_key))

    def run(self) -> Optional[Path]:
        """
        Execute the daily digest cycle.

        Returns:
            Path to the generated HTML digest report, or None if no data.
        """
        logger.info("=" * 65)
        logger.info("Daily Digest Agent: starting at %s", datetime.now(timezone.utc).isoformat())
        logger.info("=" * 65)

        with get_session() as session:
            article_repo = ArticleRepository(session)
            trend_repo = TrendRepository(session)

            since = datetime.now(timezone.utc) - timedelta(hours=self._lookback_hours)

            # Pull all articles collected since midnight (or lookback window)
            raw_articles = article_repo.get_for_report(
                since=since,
                min_score=self._min_score,
            )

            if not raw_articles:
                logger.info("Daily Digest: no articles found for the past %d hours", self._lookback_hours)
                return None

            logger.info("Daily Digest: processing %d articles", len(raw_articles))

            # Build enriched digest articles
            digest_articles = self._build_digest_articles(raw_articles)

            # Build stats
            stats = self._build_stats(digest_articles)

            # Get alert trends
            alert_trends = trend_repo.get_alert_trends()
            stats.alert_count = len(alert_trends)

        # Generate report (outside session – all data already loaded)
        generator = DailyDigestGenerator(reports_dir=settings.reports_dir)
        report_path = generator.generate(
            digest_articles=digest_articles,
            stats=stats,
            alert_trends=alert_trends,
        )

        if report_path:
            logger.info("Daily digest report: %s", report_path)
            # Email the digest
            notifier = Notifier()
            notifier.send_digest(
                digest_articles=digest_articles,
                stats=stats,
                alert_trends=alert_trends,
                report_path=report_path,
            )

        return report_path

    # ── Enrichment ────────────────────────────────────────────────────────────

    def _build_digest_articles(self, articles: list[Article]) -> list[DigestArticle]:
        """Convert ORM Article objects into DigestArticle view objects."""
        result: list[DigestArticle] = []
        for art in articles:
            keywords = self._extractor.extract(art)
            result.append(DigestArticle(
                id=art.id,
                title=art.title or "Untitled",
                url=art.url,
                category=art.category or "general",
                summary=art.summary,
                keywords=keywords,
                published_date=self._fmt_dt(art.published_at),
                collected_date=self._fmt_dt(art.collected_at),
                relevance_score=round(art.relevance_score or 0, 1),
                has_summary=bool(art.summary),
            ))
        # Sort by relevance score descending
        result.sort(key=lambda a: a.relevance_score, reverse=True)
        return result

    # ── Statistics ────────────────────────────────────────────────────────────

    def _build_stats(self, articles: list[DigestArticle]) -> DigestStats:
        """Compute aggregate statistics for the digest header."""
        if not articles:
            return DigestStats(date_str=datetime.now(timezone.utc).strftime("%d %b %Y"))

        category_counts: Counter = Counter(a.category for a in articles)
        all_keywords: Counter = Counter()
        for a in articles:
            all_keywords.update(a.keywords)

        avg_score = sum(a.relevance_score for a in articles) / len(articles)
        sources = {a.source_name for a in articles if a.source_name}

        return DigestStats(
            date_str=datetime.now(timezone.utc).strftime("%d %b %Y"),
            total_articles=len(articles),
            total_sources=len(sources),
            avg_relevance=round(avg_score, 1),
            top_category=category_counts.most_common(1)[0][0] if category_counts else "",
            category_counts=dict(category_counts),
            top_keywords=all_keywords.most_common(20),
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _fmt_dt(dt: Optional[datetime]) -> str:
        """Format a datetime for display, handling None and tz-naive values."""
        if not dt:
            return "N/A"
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%d %b %Y  %H:%M UTC")
