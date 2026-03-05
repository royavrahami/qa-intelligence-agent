"""
Core Agent Orchestrator – the brain of the QA Intelligence Agent.

Execution cycle (runs on schedule):
  1. Load all active sources from DB
  2. Run all collectors (RSS, GitHub, Arxiv, Web)
  3. Process collected articles (score + summarise)
  4. Analyse trends
  5. Discover new sources (self-expansion)
  6. Generate report
  7. Send notifications for alert-level trends
  8. Log run to DB

The agent is designed to be stateless per run – all state lives in the DB.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yaml

from src.collectors.arxiv_collector import ArxivCollector
from src.collectors.github_collector import GitHubCollector
from src.collectors.rss_collector import RSSCollector
from src.collectors.web_scraper import WebScraper
from src.agent.source_discoverer import SourceDiscoverer
from src.agent.trend_analyzer import TrendAnalyzer
from src.config.settings import settings
from src.notifications.notifier import Notifier
from src.processors.content_processor import ContentProcessor
from src.processors.relevance_scorer import RelevanceScorer
from src.processors.summarizer import Summarizer
from src.reports.report_generator import ReportGenerator
from src.storage.database import get_session, init_db
from src.storage.models import Source
from src.storage.repository import (
    AgentRunRepository,
    ArticleRepository,
    KnowledgeExpansionRepository,
    SourceRepository,
    TrendRepository,
)

logger = logging.getLogger(__name__)

_SOURCES_CONFIG_PATH = Path(__file__).parent.parent / "config" / "sources.yaml"


class CoreAgent:
    """
    Autonomous QA Intelligence Agent.

    Wires together all subsystems and drives a single execution cycle.
    Designed for idempotent, repeatable runs.
    """

    def __init__(self) -> None:
        init_db()
        self._load_sources_from_config()

    # ── Main Entry Point ──────────────────────────────────────────────────────

    def run(self) -> Optional[Path]:
        """
        Execute a full agent cycle.

        Returns:
            Path to the generated HTML report, or None on failure.
        """
        logger.info("=" * 70)
        logger.info("QA Intelligence Agent: starting run at %s", datetime.now(timezone.utc).isoformat())
        logger.info("=" * 70)

        with get_session() as session:
            # ── Repositories ─────────────────────────────────────────────────
            source_repo = SourceRepository(session)
            article_repo = ArticleRepository(session)
            trend_repo = TrendRepository(session)
            run_repo = AgentRunRepository(session)
            expansion_repo = KnowledgeExpansionRepository(session)

            run = run_repo.start_run()

            try:
                active_sources = source_repo.get_all_active()
                logger.info("Loaded %d active sources", len(active_sources))

                # ── Step 1: Collect ──────────────────────────────────────────
                collected = self._collect(
                    active_sources,
                    source_repo,
                    article_repo,
                )
                run.articles_collected = collected
                run.sources_checked = len(active_sources)
                session.flush()

                # ── Step 2: Process ──────────────────────────────────────────
                scored, summarised = self._process(article_repo, source_repo)
                run.articles_processed = summarised
                session.flush()

                # ── Step 3: Analyse Trends ────────────────────────────────────
                trends = self._analyse_trends(article_repo, trend_repo)
                run.trends_detected = len(trends)
                session.flush()

                # ── Step 4: Discover New Sources ──────────────────────────────
                new_sources = self._discover_sources(
                    source_repo, article_repo, expansion_repo
                )
                run.new_sources_discovered = new_sources
                session.flush()

                # ── Step 5: Generate Report ───────────────────────────────────
                report_path = self._generate_report(
                    article_repo,
                    trend_repo,
                    run.id,
                )
                run.report_path = str(report_path) if report_path else None
                session.flush()

                # ── Step 6: Notify ────────────────────────────────────────────
                alert_trends = trend_repo.get_alert_trends()
                if report_path:
                    self._notify(alert_trends, report_path)

                # ── Finish ────────────────────────────────────────────────────
                run_repo.finish_run(
                    run,
                    sources_checked=len(active_sources),
                    articles_collected=collected,
                    articles_processed=summarised,
                    trends_detected=len(trends),
                    new_sources_discovered=new_sources,
                    report_path=str(report_path) if report_path else None,
                )

                logger.info(
                    "Run complete: collected=%d, processed=%d, trends=%d, new_sources=%d",
                    collected, summarised, len(trends), new_sources,
                )
                return report_path

            except Exception as exc:
                run_repo.fail_run(run, error=str(exc))
                logger.exception("Agent run failed: %s", exc)
                raise

    # ── Collection ────────────────────────────────────────────────────────────

    def _collect(
        self,
        sources: list[Source],
        source_repo: SourceRepository,
        article_repo: ArticleRepository,
    ) -> int:
        """Run all collectors and return total new articles."""
        total = 0

        rss = RSSCollector(source_repo=source_repo, article_repo=article_repo)
        total += rss.collect_all(sources)

        github = GitHubCollector(
            source_repo=source_repo,
            article_repo=article_repo,
            github_token=settings.github_token,
        )
        total += github.collect_all(sources)

        arxiv = ArxivCollector(source_repo=source_repo, article_repo=article_repo)
        total += arxiv.collect_all()

        web = WebScraper(source_repo=source_repo, article_repo=article_repo)
        total += web.collect_all(sources)

        return total

    # ── Processing ────────────────────────────────────────────────────────────

    def _process(
        self,
        article_repo: ArticleRepository,
        source_repo: SourceRepository,
    ) -> tuple[int, int]:
        """Score and summarise unprocessed articles."""
        config = self._load_sources_config()
        keywords = config.get("keywords", {})

        scorer = RelevanceScorer(
            high_keywords=keywords.get("high_relevance", []),
            medium_keywords=keywords.get("medium_relevance", []),
            low_keywords=keywords.get("low_relevance", []),
        )

        # Only create the summarizer if an API key is configured
        summarizer = None
        if settings.openai_api_key:
            summarizer = Summarizer()
        else:
            logger.warning("No OPENAI_API_KEY – running in score-only mode (no summaries)")

        processor = ContentProcessor(
            article_repo=article_repo,
            source_repo=source_repo,
            scorer=scorer,
            summarizer=summarizer,
        )
        return processor.process_pending()

    # ── Trend Analysis ────────────────────────────────────────────────────────

    def _analyse_trends(
        self,
        article_repo: ArticleRepository,
        trend_repo: TrendRepository,
    ):
        """Run trend detection if API key is available."""
        if not settings.openai_api_key:
            logger.info("Skipping trend analysis – no OPENAI_API_KEY configured")
            return []
        analyzer = TrendAnalyzer(
            article_repo=article_repo,
            trend_repo=trend_repo,
        )
        return analyzer.analyse(lookback_days=7)

    # ── Source Discovery ──────────────────────────────────────────────────────

    def _discover_sources(
        self,
        source_repo: SourceRepository,
        article_repo: ArticleRepository,
        expansion_repo: KnowledgeExpansionRepository,
    ) -> int:
        """Discover and register new information sources."""
        discoverer = SourceDiscoverer(
            source_repo=source_repo,
            article_repo=article_repo,
            expansion_repo=expansion_repo,
        )
        return discoverer.discover()

    # ── Report Generation ─────────────────────────────────────────────────────

    def _generate_report(
        self,
        article_repo: ArticleRepository,
        trend_repo: TrendRepository,
        run_id: int,
    ) -> Optional[Path]:
        """Build the HTML+Markdown report and return its file path."""
        since = datetime.now(timezone.utc) - timedelta(hours=settings.schedule_interval_hours * 2)
        articles = article_repo.get_for_report(
            since=since,
            min_score=settings.min_relevance_score,
        )
        trends = trend_repo.get_top_trends(limit=10, days=7)

        if not articles and not trends:
            logger.info("No report generated – nothing to report")
            return None

        generator = ReportGenerator(reports_dir=settings.reports_dir)
        return generator.generate(articles=articles, trends=trends, run_id=run_id)

    # ── Notifications ─────────────────────────────────────────────────────────

    def _notify(self, alert_trends, report_path: Optional[Path]) -> None:
        """Send notifications for alert-level trends."""
        notifier = Notifier()
        notifier.send(alert_trends=alert_trends, report_path=report_path)

    # ── Config Helpers ────────────────────────────────────────────────────────

    def _load_sources_from_config(self) -> None:
        """
        Seed the database with sources from sources.yaml on first run.
        Idempotent – safe to call every time.
        """
        config = self._load_sources_config()
        with get_session() as session:
            repo = SourceRepository(session)
            for feed in config.get("rss_feeds", []):
                repo.upsert(
                    name=feed["name"],
                    url=feed["url"],
                    source_type="rss",
                    category=feed.get("category", "general"),
                    relevance_boost=feed.get("relevance_boost", 0),
                )
            for src in config.get("web_sources", []):
                repo.upsert(
                    name=src["name"],
                    url=src["url"],
                    source_type=src.get("type", "web"),
                    category=src.get("category", "general"),
                    relevance_boost=src.get("relevance_boost", 0),
                )

    @staticmethod
    def _load_sources_config() -> dict:
        """Load and return the YAML sources configuration."""
        try:
            with open(_SOURCES_CONFIG_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            logger.warning("sources.yaml not found at %s", _SOURCES_CONFIG_PATH)
            return {}
        except Exception as exc:
            logger.error("Failed to load sources config: %s", exc)
            return {}
