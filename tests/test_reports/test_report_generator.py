"""
Unit tests for the ReportGenerator.

Verifies that HTML and Markdown reports are generated correctly,
contain expected content, and handle edge cases like empty input.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.reports.report_generator import ReportGenerator
from src.storage.models import Article, Source, Trend


@pytest.fixture
def reports_dir(tmp_path: Path) -> Path:
    """Use a temp directory for report output."""
    d = tmp_path / "reports"
    d.mkdir()
    return d


@pytest.fixture
def generator(reports_dir: Path) -> ReportGenerator:
    return ReportGenerator(reports_dir=reports_dir)


@pytest.fixture
def sample_articles() -> list[Article]:
    """Three articles covering different categories."""
    articles = []
    for i, (title, cat, score) in enumerate([
        ("LLM Agents Outperform Manual Testers", "agents", 92.0),
        ("Playwright MCP Integration Released", "qa_testing", 88.0),
        ("DORA Metrics 2025 Benchmark Report", "devops", 75.0),
    ]):
        a = MagicMock(spec=Article)
        a.id = i + 1
        a.title = title
        a.url = f"https://example.com/article/{i+1}"
        a.category = cat
        a.relevance_score = score
        a.summary = f"Summary for {title}."
        a.key_insights = json.dumps([f"Insight {i+1}A", f"Insight {i+1}B"])
        a.qa_relevance = "Relevant for QA Manager pipeline automation."
        a.published_at = datetime.now(timezone.utc)
        a.insights_list = [f"Insight {i+1}A", f"Insight {i+1}B"]
        articles.append(a)
    return articles


@pytest.fixture
def sample_trends() -> list[Trend]:
    t1 = MagicMock(spec=Trend)
    t1.name = "AI Test Agents Surge"
    t1.category = "agents"
    t1.description = "Explosive growth in autonomous test agent adoption."
    t1.momentum_score = 45.0
    t1.article_count = 12
    t1.is_alert = True
    t1.last_seen_at = datetime.now(timezone.utc)
    t1.first_seen_at = datetime.now(timezone.utc)

    t2 = MagicMock(spec=Trend)
    t2.name = "Shift-Left QA Adoption"
    t2.category = "qa_testing"
    t2.description = "Teams embedding QA earlier in the SDLC."
    t2.momentum_score = 22.0
    t2.article_count = 6
    t2.is_alert = False
    t2.last_seen_at = datetime.now(timezone.utc)
    t2.first_seen_at = datetime.now(timezone.utc)

    return [t1, t2]


class TestReportGeneratorOutput:
    """Tests that generated reports contain expected sections and content."""

    def test_generate_creates_html_file(
        self,
        generator: ReportGenerator,
        sample_articles: list[Article],
        sample_trends: list[Trend],
        reports_dir: Path,
    ) -> None:
        path = generator.generate(articles=sample_articles, trends=sample_trends, run_id=42)
        assert path is not None
        assert path.exists()
        assert path.suffix == ".html"
        assert path.parent == reports_dir

    def test_generate_creates_markdown_companion(
        self,
        generator: ReportGenerator,
        sample_articles: list[Article],
        sample_trends: list[Trend],
    ) -> None:
        path = generator.generate(articles=sample_articles, trends=sample_trends, run_id=1)
        md_path = path.with_suffix(".md")
        assert md_path.exists()

    def test_html_contains_article_titles(
        self,
        generator: ReportGenerator,
        sample_articles: list[Article],
        sample_trends: list[Trend],
    ) -> None:
        path = generator.generate(articles=sample_articles, trends=sample_trends, run_id=1)
        html = path.read_text(encoding="utf-8")
        for article in sample_articles:
            assert article.title in html

    def test_html_contains_alert_section_when_alerts_exist(
        self,
        generator: ReportGenerator,
        sample_articles: list[Article],
        sample_trends: list[Trend],
    ) -> None:
        path = generator.generate(articles=sample_articles, trends=sample_trends, run_id=1)
        html = path.read_text(encoding="utf-8")
        assert "ALERT" in html or "Immediate Attention" in html

    def test_html_contains_trend_names(
        self,
        generator: ReportGenerator,
        sample_articles: list[Article],
        sample_trends: list[Trend],
    ) -> None:
        path = generator.generate(articles=sample_articles, trends=sample_trends, run_id=1)
        html = path.read_text(encoding="utf-8")
        assert "AI Test Agents Surge" in html

    def test_markdown_contains_article_urls(
        self,
        generator: ReportGenerator,
        sample_articles: list[Article],
        sample_trends: list[Trend],
    ) -> None:
        path = generator.generate(articles=sample_articles, trends=sample_trends, run_id=1)
        md_content = path.with_suffix(".md").read_text(encoding="utf-8")
        for article in sample_articles:
            assert article.url in md_content

    def test_report_filename_contains_timestamp(
        self,
        generator: ReportGenerator,
        sample_articles: list[Article],
        sample_trends: list[Trend],
    ) -> None:
        path = generator.generate(articles=sample_articles, trends=sample_trends, run_id=1)
        assert "qa_intelligence_report_" in path.name


class TestReportGeneratorEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_articles_still_generates_report(
        self,
        generator: ReportGenerator,
        sample_trends: list[Trend],
    ) -> None:
        path = generator.generate(articles=[], trends=sample_trends, run_id=1)
        assert path is not None
        html = path.read_text(encoding="utf-8")
        assert "AI Test Agents Surge" in html

    def test_no_alert_trends_skips_alert_section(
        self,
        generator: ReportGenerator,
        sample_articles: list[Article],
    ) -> None:
        non_alert_trend = MagicMock(spec=Trend)
        non_alert_trend.name = "Quiet Trend"
        non_alert_trend.category = "general"
        non_alert_trend.description = "Low key trend."
        non_alert_trend.momentum_score = 5.0
        non_alert_trend.article_count = 1
        non_alert_trend.is_alert = False
        non_alert_trend.last_seen_at = datetime.now(timezone.utc)
        non_alert_trend.first_seen_at = datetime.now(timezone.utc)

        path = generator.generate(articles=sample_articles, trends=[non_alert_trend], run_id=1)
        html = path.read_text(encoding="utf-8")
        # The alerts section heading should not appear
        assert "Immediate Attention Required" not in html

    def test_article_without_summary_is_still_included(
        self,
        generator: ReportGenerator,
        sample_trends: list[Trend],
        sample_source,
    ) -> None:
        article = MagicMock(spec=Article)
        article.id = 99
        article.title = "Article Without Summary"
        article.url = "https://example.com/no-summary"
        article.category = "general"
        article.relevance_score = 70.0
        article.summary = None
        article.key_insights = None
        article.qa_relevance = None
        article.published_at = None
        article.insights_list = []

        path = generator.generate(articles=[article], trends=sample_trends, run_id=1)
        html = path.read_text(encoding="utf-8")
        assert "Article Without Summary" in html
