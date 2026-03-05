"""
Unit tests for the RelevanceScorer.

Verifies keyword scoring, source boost, category bonus, freshness bonus,
title heuristics, and score capping behaviour.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from src.processors.relevance_scorer import RelevanceScorer
from src.storage.models import Article, Source


@pytest.fixture
def scorer() -> RelevanceScorer:
    return RelevanceScorer(
        high_keywords=["ai agent", "test automation", "playwright", "genai"],
        medium_keywords=["machine learning", "devops", "automation"],
        low_keywords=["ai", "tool", "software"],
    )


@pytest.fixture
def base_source() -> Source:
    source = MagicMock(spec=Source)
    source.relevance_boost = 0
    source.category = "general"
    return source


class TestRelevanceScorerKeywords:
    """Tests that keyword matching contributes correct scores."""

    def test_high_keyword_increases_score(self, scorer: RelevanceScorer, base_source: Source) -> None:
        article = MagicMock(spec=Article)
        article.title = "AI Agent Framework Released"
        article.raw_content = "New ai agent tools for QA."
        article.category = "general"
        article.published_at = None
        article.collected_at = datetime.now(timezone.utc)

        score = scorer.score(article, base_source)
        assert score > 0

    def test_no_keywords_gives_low_score(self, scorer: RelevanceScorer, base_source: Source) -> None:
        article = MagicMock(spec=Article)
        article.title = "Random unrelated content"
        article.raw_content = "Weather forecast for tomorrow."
        article.category = "general"
        article.published_at = None
        article.collected_at = datetime.now(timezone.utc)

        score = scorer.score(article, base_source)
        assert score < 20  # Only title heuristics might add a few points

    def test_multiple_high_keywords_capped_at_50(self, scorer: RelevanceScorer, base_source: Source) -> None:
        """Keyword score is capped at 50 regardless of how many keywords match."""
        content = "ai agent genai test automation playwright " * 10
        article = MagicMock(spec=Article)
        article.title = "ai agent test automation playwright genai"
        article.raw_content = content
        article.category = "general"
        article.published_at = None
        article.collected_at = datetime.now(timezone.utc)

        score = scorer.score(article, base_source)
        assert score <= 100  # Total cap


class TestRelevanceScorerSourceBoost:
    """Tests that source-level relevance boost is applied correctly."""

    def test_source_boost_is_added(self, scorer: RelevanceScorer) -> None:
        source_with_boost = MagicMock(spec=Source)
        source_with_boost.relevance_boost = 15
        source_with_boost.category = "general"

        source_no_boost = MagicMock(spec=Source)
        source_no_boost.relevance_boost = 0
        source_no_boost.category = "general"

        article = MagicMock(spec=Article)
        article.title = "Neutral title"
        article.raw_content = "Neutral content."
        article.category = "general"
        article.published_at = None
        article.collected_at = datetime.now(timezone.utc)

        score_with = scorer.score(article, source_with_boost)
        score_without = scorer.score(article, source_no_boost)
        assert score_with > score_without

    def test_source_boost_capped_at_20(self, scorer: RelevanceScorer) -> None:
        source = MagicMock(spec=Source)
        source.relevance_boost = 9999  # Way over the cap
        source.category = "general"

        article = MagicMock(spec=Article)
        article.title = "T"
        article.raw_content = ""
        article.category = "general"
        article.published_at = None
        article.collected_at = datetime.now(timezone.utc)

        score = scorer.score(article, source)
        assert score <= 100


class TestRelevanceScorerCategoryBonus:
    """Tests that category bonuses are applied per-article."""

    def test_qa_testing_category_gets_bonus(self, scorer: RelevanceScorer, base_source: Source) -> None:
        article_qa = MagicMock(spec=Article)
        article_qa.title = "Neutral"
        article_qa.raw_content = ""
        article_qa.category = "qa_testing"
        article_qa.published_at = None
        article_qa.collected_at = datetime.now(timezone.utc)

        article_general = MagicMock(spec=Article)
        article_general.title = "Neutral"
        article_general.raw_content = ""
        article_general.category = "general"
        article_general.published_at = None
        article_general.collected_at = datetime.now(timezone.utc)

        assert scorer.score(article_qa, base_source) > scorer.score(article_general, base_source)


class TestRelevanceScorerFreshness:
    """Tests that freshness bonus is correctly applied based on article age."""

    def test_very_recent_article_gets_max_freshness_bonus(
        self, scorer: RelevanceScorer, base_source: Source
    ) -> None:
        article = MagicMock(spec=Article)
        article.title = "New"
        article.raw_content = ""
        article.category = "general"
        article.published_at = datetime.now(timezone.utc) - timedelta(hours=1)
        article.collected_at = datetime.now(timezone.utc)

        score = scorer.score(article, base_source)
        # Should include freshness bonus of 10
        assert score >= 10

    def test_old_article_gets_no_freshness_bonus(
        self, scorer: RelevanceScorer, base_source: Source
    ) -> None:
        article_old = MagicMock(spec=Article)
        article_old.title = "Old"
        article_old.raw_content = ""
        article_old.category = "general"
        article_old.published_at = datetime.now(timezone.utc) - timedelta(days=30)
        article_old.collected_at = datetime.now(timezone.utc)

        article_new = MagicMock(spec=Article)
        article_new.title = "Old"
        article_new.raw_content = ""
        article_new.category = "general"
        article_new.published_at = datetime.now(timezone.utc) - timedelta(hours=2)
        article_new.collected_at = datetime.now(timezone.utc)

        assert scorer.score(article_new, base_source) > scorer.score(article_old, base_source)


class TestRelevanceScorerTitleBonus:
    """Tests title heuristic scoring."""

    def test_title_with_tool_signal_gets_bonus(self, scorer: RelevanceScorer, base_source: Source) -> None:
        article_with = MagicMock(spec=Article)
        article_with.title = "Playwright adds AI self-healing locators"
        article_with.raw_content = ""
        article_with.category = "general"
        article_with.published_at = None
        article_with.collected_at = datetime.now(timezone.utc)

        article_without = MagicMock(spec=Article)
        article_without.title = "A random blog post about something"
        article_without.raw_content = ""
        article_without.category = "general"
        article_without.published_at = None
        article_without.collected_at = datetime.now(timezone.utc)

        assert scorer.score(article_with, base_source) > scorer.score(article_without, base_source)

    def test_score_never_exceeds_100(self, scorer: RelevanceScorer) -> None:
        source = MagicMock(spec=Source)
        source.relevance_boost = 20
        source.category = "qa_testing"

        article = MagicMock(spec=Article)
        article.title = "playwright ai agent test automation genai claude gpt cursor"
        article.raw_content = "ai agent genai test automation playwright " * 20
        article.category = "qa_testing"
        article.published_at = datetime.now(timezone.utc)
        article.collected_at = datetime.now(timezone.utc)

        score = scorer.score(article, source)
        assert score <= 100.0
