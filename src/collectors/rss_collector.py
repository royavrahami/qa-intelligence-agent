"""
RSS Feed Collector – polls configured RSS/Atom feeds and stores raw articles.

Design notes:
  - Uses feedparser for robust XML/Atom parsing.
  - Deduplicates by URL before persisting.
  - Captures publish date from feed entry or falls back to collection time.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import feedparser
import requests

from src.storage.models import Source
from src.storage.repository import ArticleRepository, SourceRepository

logger = logging.getLogger(__name__)

# Timeout for HTTP requests to RSS feeds (seconds)
_REQUEST_TIMEOUT = 15

# User-Agent that identifies the agent politely
_USER_AGENT = (
    "QAIntelligenceAgent/1.0 (+https://github.com/qa-intelligence-agent; "
    "contact: qa-agent@example.com)"
)


def _parse_date(entry: feedparser.FeedParserDict) -> Optional[datetime]:
    """
    Extract and normalise a publish date from a feed entry.
    Returns a timezone-aware datetime or None if unparseable.
    """
    for attr in ("published", "updated", "created"):
        raw = getattr(entry, attr, None)
        if not raw:
            continue
        try:
            dt = parsedate_to_datetime(raw)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    # feedparser also exposes _parsed variants
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def _extract_content(entry: feedparser.FeedParserDict) -> str:
    """Extract the best available text content from a feed entry."""
    # Prefer full content over summary
    if hasattr(entry, "content") and entry.content:
        return entry.content[0].get("value", "")
    if hasattr(entry, "summary"):
        return entry.summary or ""
    return ""


class RSSCollector:
    """
    Polls a list of RSS/Atom feeds and persists new articles to the database.

    Args:
        source_repo: Repository for Source records.
        article_repo: Repository for Article records.
    """

    def __init__(
        self,
        source_repo: SourceRepository,
        article_repo: ArticleRepository,
    ) -> None:
        self._source_repo = source_repo
        self._article_repo = article_repo

    def collect_all(self, sources: list[Source]) -> int:
        """
        Iterate over all active RSS sources and collect new articles.

        Returns:
            Total number of new articles stored.
        """
        total_new = 0
        rss_sources = [s for s in sources if s.source_type == "rss"]
        logger.info("RSS Collector: checking %d feeds", len(rss_sources))

        for source in rss_sources:
            try:
                new_count = self._collect_source(source)
                total_new += new_count
                self._source_repo.mark_fetched(source, had_error=False)
            except Exception as exc:
                logger.warning("Failed to collect feed %s: %s", source.name, exc)
                self._source_repo.mark_fetched(source, had_error=True)

        logger.info("RSS Collector: collected %d new articles total", total_new)
        return total_new

    def _collect_source(self, source: Source) -> int:
        """
        Fetch and parse a single RSS feed.

        Strategy: try feedparser's built-in URL fetcher first (better encoding
        detection), then fall back to requests+feedparser if that yields nothing.

        Returns:
            Number of new articles stored from this feed.
        """
        logger.debug("Fetching RSS feed: %s", source.url)

        # Strategy 1: feedparser fetches directly – handles charset/encoding best
        feed = feedparser.parse(
            source.url,
            request_headers={"User-Agent": _USER_AGENT},
        )

        # Strategy 2: if feedparser got nothing, try via requests with a browser UA
        if feed.bozo and not feed.entries:
            try:
                response = requests.get(
                    source.url,
                    headers={"User-Agent": _USER_AGENT},
                    timeout=_REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                # Use decoded text to let feedparser detect encoding from content
                feed = feedparser.parse(response.text)
            except requests.RequestException as exc:
                logger.debug("requests fallback also failed: %s", exc)

        if feed.bozo and not feed.entries:
            raise ValueError(f"Feed parse error: {feed.bozo_exception}")

        new_count = 0
        for entry in feed.entries:
            link = getattr(entry, "link", None) or getattr(entry, "id", None)
            if not link:
                continue

            # Skip duplicates
            if self._article_repo.exists(link):
                continue

            title = getattr(entry, "title", "Untitled").strip()
            author = getattr(entry, "author", None)
            content = _extract_content(entry)
            published_at = _parse_date(entry)

            self._article_repo.create(
                source_id=source.id,
                title=title,
                url=link,
                author=author,
                published_at=published_at,
                category=source.category,
                raw_content=content[:8000],  # Cap to avoid huge blobs
            )
            new_count += 1

        logger.debug("Feed %s: %d new articles", source.name, new_count)
        return new_count
