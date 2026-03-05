"""
Unit tests for the DailyDigestGenerator.

Verifies report structure, table content, keyword cloud, and edge cases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest

from src.reports.daily_digest_generator import DailyDigestGenerator
from src.storage.models import Trend


@dataclass
class _DigestArticle:
    """Minimal stand-in for DigestArticle in tests."""
    id: int
    title: str
    url: str
    category: str
    summary: Optional[str]
    keywords: list
    published_date: str
    collected_date: str
    relevance_score: float
    source_name: str = ""
    has_summary: bool = False


@dataclass
class _DigestStats:
    date_str: str
    total_articles: int = 0
    total_sources: int = 0
    avg_relevance: float = 0.0
    top_category: str = ""
    alert_count: int = 0
    category_counts: dict = field(default_factory=dict)
    top_keywords: list = field(default_factory=list)


@pytest.fixture
def reports_dir(tmp_path: Path) -> Path:
    d = tmp_path / "reports"
    d.mkdir()
    return d


@pytest.fixture
def generator(reports_dir: Path) -> DailyDigestGenerator:
    return DailyDigestGenerator(reports_dir=reports_dir)


@pytest.fixture
def sample_articles() -> list:
    return [
        _DigestArticle(
            id=1, title="LLM Agents Replace Manual Testers",
            url="https://example.com/llm-agents",
            category="agents", summary="LLMs are replacing manual QA testers.",
            keywords=["LLM", "Agents", "Testing"],
            published_date="01 Mar 2026  10:00 UTC",
            collected_date="02 Mar 2026  06:00 UTC",
            relevance_score=87.0, has_summary=True,
        ),
        _DigestArticle(
            id=2, title="Playwright 1.50 Released with AI Features",
            url="https://example.com/playwright",
            category="qa_testing", summary="New Playwright release.",
            keywords=["Playwright", "AI", "Test Automation"],
            published_date="02 Mar 2026  08:00 UTC",
            collected_date="02 Mar 2026  12:00 UTC",
            relevance_score=75.0, has_summary=True,
        ),
        _DigestArticle(
            id=3, title="GitHub Copilot Now Writes E2E Tests",
            url="https://example.com/copilot",
            category="tools", summary=None,
            keywords=["Copilot", "E2E", "GitHub"],
            published_date="N/A",
            collected_date="02 Mar 2026  18:00 UTC",
            relevance_score=60.0, has_summary=False,
        ),
    ]


@pytest.fixture
def sample_stats(sample_articles) -> _DigestStats:
    return _DigestStats(
        date_str="02 Mar 2026",
        total_articles=3,
        avg_relevance=74.0,
        alert_count=1,
        category_counts={"agents": 1, "qa_testing": 1, "tools": 1},
        top_keywords=[("LLM", 5), ("Agents", 4), ("Testing", 3), ("AI", 3)],
    )


@pytest.fixture
def alert_trend() -> Trend:
    t = MagicMock(spec=Trend)
    t.name = "AI Test Agents Surge"
    t.category = "agents"
    t.description = "Rapid growth in AI test automation agents."
    t.momentum_score = 42.0
    t.article_count = 8
    t.is_alert = True
    return t


class TestDailyDigestGeneratorOutput:
    """Tests that generated reports contain correct structure and content."""

    def test_generates_html_file(self, generator, sample_articles, sample_stats) -> None:
        path = generator.generate(sample_articles, sample_stats, [])
        assert path is not None
        assert path.exists()
        assert path.suffix == ".html"
        assert "daily_digest_" in path.name

    def test_generates_markdown_companion(self, generator, sample_articles, sample_stats) -> None:
        path = generator.generate(sample_articles, sample_stats, [])
        md = path.with_suffix(".md")
        assert md.exists()

    def test_html_contains_all_article_titles(self, generator, sample_articles, sample_stats) -> None:
        path = generator.generate(sample_articles, sample_stats, [])
        html = path.read_text(encoding="utf-8")
        for a in sample_articles:
            assert a.title[:40] in html

    def test_html_contains_article_urls(self, generator, sample_articles, sample_stats) -> None:
        path = generator.generate(sample_articles, sample_stats, [])
        html = path.read_text(encoding="utf-8")
        for a in sample_articles:
            assert a.url in html

    def test_html_contains_keywords(self, generator, sample_articles, sample_stats) -> None:
        path = generator.generate(sample_articles, sample_stats, [])
        html = path.read_text(encoding="utf-8")
        assert "LLM" in html
        assert "Playwright" in html

    def test_html_contains_dates(self, generator, sample_articles, sample_stats) -> None:
        path = generator.generate(sample_articles, sample_stats, [])
        html = path.read_text(encoding="utf-8")
        assert "01 Mar 2026" in html
        assert "02 Mar 2026" in html

    def test_html_contains_alert_section(self, generator, sample_articles, sample_stats, alert_trend) -> None:
        path = generator.generate(sample_articles, sample_stats, [alert_trend])
        html = path.read_text(encoding="utf-8")
        assert "AI Test Agents Surge" in html

    def test_html_contains_keyword_cloud(self, generator, sample_articles, sample_stats) -> None:
        path = generator.generate(sample_articles, sample_stats, [])
        html = path.read_text(encoding="utf-8")
        # Top keywords from stats should appear in cloud
        assert "LLM" in html

    def test_markdown_contains_table(self, generator, sample_articles, sample_stats) -> None:
        path = generator.generate(sample_articles, sample_stats, [])
        md = path.with_suffix(".md").read_text(encoding="utf-8")
        assert "| # |" in md
        assert "Published" in md
        assert "Collected" in md


class TestDailyDigestGeneratorEdgeCases:
    """Edge cases: empty input, missing summaries, no alerts."""

    def test_empty_articles_returns_none(self, generator, sample_stats) -> None:
        result = generator.generate([], sample_stats, [])
        assert result is None

    def test_article_without_summary_still_included(
        self, generator, sample_stats
    ) -> None:
        article = _DigestArticle(
            id=99, title="No Summary Article", url="https://x.com/no-summary",
            category="general", summary=None, keywords=["Python"],
            published_date="N/A", collected_date="02 Mar 2026  10:00 UTC",
            relevance_score=45.0, has_summary=False,
        )
        path = generator.generate([article], sample_stats, [])
        assert path is not None
        html = path.read_text(encoding="utf-8")
        assert "No Summary Article" in html

    def test_no_alert_trends_skips_alert_section(
        self, generator, sample_articles, sample_stats
    ) -> None:
        path = generator.generate(sample_articles, sample_stats, [])
        html = path.read_text(encoding="utf-8")
        assert "AI Test Agents Surge" not in html
