"""
Unit tests for the RSSCollector.

Uses the `responses` library to mock HTTP requests and feedparser behaviour.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import responses as responses_lib

from src.collectors.rss_collector import RSSCollector
from src.storage.models import Source
from src.storage.repository import ArticleRepository, SourceRepository

# Minimal valid RSS XML feed for use in tests
_SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://example.com</link>
    <item>
      <title>Article about AI Agents</title>
      <link>https://example.com/ai-agents</link>
      <description>A deep dive into autonomous AI agents for QA.</description>
      <pubDate>Mon, 01 Jan 2024 12:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Playwright 1.45 Released</title>
      <link>https://example.com/playwright</link>
      <description>New features in Playwright for test automation.</description>
      <pubDate>Mon, 01 Jan 2024 12:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>"""


class TestRSSCollectorHappyPath:
    """Tests for successful RSS feed collection."""

    @responses_lib.activate
    def test_collect_new_articles_from_rss_feed(self, db_session, sample_source: Source) -> None:
        responses_lib.add(
            responses_lib.GET,
            sample_source.url,
            body=_SAMPLE_RSS,
            content_type="application/rss+xml",
        )

        source_repo = SourceRepository(db_session)
        article_repo = ArticleRepository(db_session)
        collector = RSSCollector(source_repo=source_repo, article_repo=article_repo)

        count = collector.collect_all([sample_source])
        assert count == 2

    @responses_lib.activate
    def test_deduplication_skips_existing_articles(self, db_session, sample_source: Source) -> None:
        responses_lib.add(
            responses_lib.GET,
            sample_source.url,
            body=_SAMPLE_RSS,
            content_type="application/rss+xml",
        )

        source_repo = SourceRepository(db_session)
        article_repo = ArticleRepository(db_session)
        collector = RSSCollector(source_repo=source_repo, article_repo=article_repo)

        # First run collects 2 articles
        first_count = collector.collect_all([sample_source])
        assert first_count == 2
        db_session.commit()

        # Second run with same feed should collect 0 (already seen)
        responses_lib.add(
            responses_lib.GET,
            sample_source.url,
            body=_SAMPLE_RSS,
            content_type="application/rss+xml",
        )
        second_count = collector.collect_all([sample_source])
        assert second_count == 0

    @responses_lib.activate
    def test_marks_source_as_fetched_on_success(self, db_session, sample_source: Source) -> None:
        responses_lib.add(
            responses_lib.GET,
            sample_source.url,
            body=_SAMPLE_RSS,
            content_type="application/rss+xml",
        )

        source_repo = SourceRepository(db_session)
        article_repo = ArticleRepository(db_session)
        collector = RSSCollector(source_repo=source_repo, article_repo=article_repo)
        collector.collect_all([sample_source])

        assert sample_source.fetch_count == 1
        assert sample_source.last_fetched_at is not None


class TestRSSCollectorErrorHandling:
    """Tests for resilient error handling in the RSS collector."""

    @responses_lib.activate
    def test_http_error_increments_error_count(self, db_session, sample_source: Source) -> None:
        responses_lib.add(
            responses_lib.GET,
            sample_source.url,
            status=500,
        )

        source_repo = SourceRepository(db_session)
        article_repo = ArticleRepository(db_session)

        # Patch feedparser fallback to also fail
        with patch("feedparser.parse", side_effect=Exception("parse error")):
            collector = RSSCollector(source_repo=source_repo, article_repo=article_repo)
            count = collector.collect_all([sample_source])

        assert count == 0
        assert sample_source.error_count == 1

    def test_non_rss_sources_are_skipped(self, db_session, sample_source: Source) -> None:
        """Sources with source_type != 'rss' should not be processed."""
        sample_source.source_type = "github_trending"

        source_repo = SourceRepository(db_session)
        article_repo = ArticleRepository(db_session)
        collector = RSSCollector(source_repo=source_repo, article_repo=article_repo)

        count = collector.collect_all([sample_source])
        assert count == 0

    def test_empty_feed_returns_zero(self, db_session, sample_source: Source) -> None:
        empty_rss = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Empty</title></channel></rss>"""

        with patch("requests.get") as mock_get:
            mock_get.return_value.content = empty_rss.encode()
            mock_get.return_value.raise_for_status = lambda: None

            source_repo = SourceRepository(db_session)
            article_repo = ArticleRepository(db_session)
            collector = RSSCollector(source_repo=source_repo, article_repo=article_repo)
            count = collector.collect_all([sample_source])

        assert count == 0
