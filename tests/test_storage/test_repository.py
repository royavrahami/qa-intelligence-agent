"""
Unit tests for the storage repository layer.

Covers: SourceRepository, ArticleRepository, TrendRepository,
        AgentRunRepository, KnowledgeExpansionRepository.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from src.storage.models import Article, Source
from src.storage.repository import (
    AgentRunRepository,
    ArticleRepository,
    KnowledgeExpansionRepository,
    SourceRepository,
    TrendRepository,
)


class TestSourceRepository:
    """Tests for SourceRepository CRUD operations."""

    def test_upsert_creates_new_source(self, db_session: Session) -> None:
        repo = SourceRepository(db_session)
        source = repo.upsert(
            name="OpenAI Blog",
            url="https://openai.com/blog/rss/",
            source_type="rss",
            category="genai",
            relevance_boost=15,
        )
        assert source.id is not None
        assert source.name == "OpenAI Blog"
        assert source.relevance_boost == 15

    def test_upsert_returns_existing_on_duplicate_url(self, db_session: Session) -> None:
        repo = SourceRepository(db_session)
        url = "https://example.com/feed"
        s1 = repo.upsert(name="Feed A", url=url, source_type="rss", category="genai")
        s2 = repo.upsert(name="Feed B", url=url, source_type="rss", category="genai")
        assert s1.id == s2.id  # Same record, not a duplicate

    def test_get_all_active_returns_only_active(self, db_session: Session) -> None:
        repo = SourceRepository(db_session)
        active = repo.upsert(name="Active", url="https://a.com/feed", source_type="rss", category="genai")
        inactive = repo.upsert(name="Inactive", url="https://b.com/feed", source_type="rss", category="genai")
        inactive.is_active = False
        db_session.flush()

        results = repo.get_all_active()
        names = [s.name for s in results]
        assert "Active" in names
        assert "Inactive" not in names

    def test_mark_fetched_increments_counters(self, db_session: Session) -> None:
        repo = SourceRepository(db_session)
        source = repo.upsert(name="S", url="https://s.com/feed", source_type="rss", category="genai")
        repo.mark_fetched(source, had_error=False)
        assert source.fetch_count == 1
        assert source.error_count == 0

    def test_mark_fetched_with_error_increments_error_count(self, db_session: Session) -> None:
        repo = SourceRepository(db_session)
        source = repo.upsert(name="S", url="https://s.com/feed", source_type="rss", category="genai")
        repo.mark_fetched(source, had_error=True)
        assert source.error_count == 1


class TestArticleRepository:
    """Tests for ArticleRepository operations."""

    def test_create_stores_article(self, db_session: Session, sample_source: Source) -> None:
        repo = ArticleRepository(db_session)
        article = repo.create(
            source_id=sample_source.id,
            title="Test Article",
            url="https://example.com/test",
            category="qa_testing",
        )
        assert article.id is not None
        assert article.title == "Test Article"
        assert article.is_processed is False

    def test_exists_returns_true_for_known_url(self, db_session: Session, sample_article: Article) -> None:
        repo = ArticleRepository(db_session)
        assert repo.exists(sample_article.url) is True

    def test_exists_returns_false_for_unknown_url(self, db_session: Session) -> None:
        repo = ArticleRepository(db_session)
        assert repo.exists("https://never-seen.com/article") is False

    def test_get_unprocessed_returns_only_unprocessed(
        self, db_session: Session, sample_source: Source
    ) -> None:
        repo = ArticleRepository(db_session)
        repo.create(source_id=sample_source.id, title="Unprocessed", url="https://ex.com/1", category="genai")
        processed = repo.create(source_id=sample_source.id, title="Processed", url="https://ex.com/2", category="genai")
        processed.is_processed = True
        db_session.flush()

        unprocessed = repo.get_unprocessed(limit=10)
        titles = [a.title for a in unprocessed]
        assert "Unprocessed" in titles
        assert "Processed" not in titles

    def test_get_for_report_filters_by_score_and_date(
        self, db_session: Session, sample_source: Source
    ) -> None:
        repo = ArticleRepository(db_session)
        now = datetime.now(timezone.utc)

        # High score, recent
        repo.create(
            source_id=sample_source.id, title="A", url="https://ex.com/a",
            category="qa_testing", relevance_score=80.0,
            is_processed=True, collected_at=now,
        )
        # Low score, recent
        repo.create(
            source_id=sample_source.id, title="B", url="https://ex.com/b",
            category="qa_testing", relevance_score=20.0,
            is_processed=True, collected_at=now,
        )
        # High score, old
        repo.create(
            source_id=sample_source.id, title="C", url="https://ex.com/c",
            category="qa_testing", relevance_score=80.0,
            is_processed=True, collected_at=now - timedelta(days=10),
        )

        since = now - timedelta(hours=1)
        results = repo.get_for_report(since=since, min_score=60.0)
        titles = [a.title for a in results]
        assert "A" in titles
        assert "B" not in titles
        assert "C" not in titles


class TestTrendRepository:
    """Tests for TrendRepository operations."""

    def test_get_or_create_creates_new_trend(self, db_session: Session) -> None:
        repo = TrendRepository(db_session)
        trend, created = repo.get_or_create(name="AI Agents Rising", category="agents")
        assert created is True
        assert trend.id is not None
        assert trend.name == "AI Agents Rising"

    def test_get_or_create_returns_existing(self, db_session: Session) -> None:
        repo = TrendRepository(db_session)
        t1, _ = repo.get_or_create(name="AI Agents Rising", category="agents")
        t2, created = repo.get_or_create(name="AI Agents Rising", category="agents")
        assert created is False
        assert t1.id == t2.id

    def test_link_article_increments_count(
        self, db_session: Session, sample_article: Article
    ) -> None:
        repo = TrendRepository(db_session)
        trend, _ = repo.get_or_create(name="Test Trend", category="qa_testing")
        initial_count = trend.article_count
        repo.link_article(trend, sample_article)
        assert trend.article_count == initial_count + 1


class TestAgentRunRepository:
    """Tests for AgentRunRepository audit log operations."""

    def test_start_run_creates_running_record(self, db_session: Session) -> None:
        repo = AgentRunRepository(db_session)
        run = repo.start_run()
        assert run.id is not None
        assert run.status == "running"

    def test_finish_run_sets_success_status(self, db_session: Session) -> None:
        repo = AgentRunRepository(db_session)
        run = repo.start_run()
        repo.finish_run(run, articles_collected=10, articles_processed=8)
        assert run.status == "success"
        assert run.articles_collected == 10
        assert run.finished_at is not None

    def test_fail_run_sets_failed_status(self, db_session: Session) -> None:
        repo = AgentRunRepository(db_session)
        run = repo.start_run()
        repo.fail_run(run, error="Test error")
        assert run.status == "failed"
        assert run.error_message == "Test error"

    def test_get_last_returns_most_recent_runs(self, db_session: Session) -> None:
        repo = AgentRunRepository(db_session)
        for _ in range(5):
            repo.start_run()
        runs = repo.get_last(n=3)
        assert len(runs) == 3


class TestKnowledgeExpansionRepository:
    """Tests for KnowledgeExpansionRepository operations."""

    def test_record_creates_expansion(self, db_session: Session) -> None:
        repo = KnowledgeExpansionRepository(db_session)
        exp = repo.record(
            expansion_type="new_source",
            description="Discovered via article links",
            value="https://newblog.com/feed",
        )
        assert exp.id is not None
        assert exp.expansion_type == "new_source"

    def test_already_known_returns_true_for_existing_value(self, db_session: Session) -> None:
        repo = KnowledgeExpansionRepository(db_session)
        url = "https://known.com/feed"
        repo.record("new_source", "desc", url)
        db_session.flush()
        assert repo.already_known(url) is True

    def test_already_known_returns_false_for_new_value(self, db_session: Session) -> None:
        repo = KnowledgeExpansionRepository(db_session)
        assert repo.already_known("https://never-seen.com/feed") is False
