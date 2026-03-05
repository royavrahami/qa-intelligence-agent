"""
Trend Analyzer – identifies emerging patterns and trends across collected
articles using OpenAI and persists them as Trend records.

Algorithm:
  1. Gather recent processed articles grouped by category.
  2. Submit a batch to the LLM asking it to identify themes/trends.
  3. For each identified trend, upsert a Trend record and link articles.
  4. Calculate momentum_score based on article growth rate.
  5. Flag high-momentum trends as alerts.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import openai
from openai import OpenAI

from src.config.settings import settings
from src.storage.models import Article, Trend
from src.storage.repository import ArticleRepository, TrendRepository

logger = logging.getLogger(__name__)

_TREND_DETECTION_PROMPT = """You are a senior technology analyst tracking the GenAI, AI Agents, and software quality space.

Analyse the following list of article titles and summaries collected in the last 7 days.
Identify the TOP 5 most significant trends, shifts, or emerging topics you can see.

For each trend return a JSON object:
{
  "name": "<Short trend name, max 60 chars>",
  "description": "<2-3 sentences describing the trend and why it matters>",
  "category": "<one of: genai | agents | qa_testing | devops | tools | project_management>",
  "is_alert": <true if this trend requires IMMEDIATE attention from a QA Manager / tech leader>,
  "article_indices": [<list of 0-based indices from the input that support this trend>]
}

Return a JSON array of trend objects. No markdown, no preamble.
Focus on: AI agent frameworks, new testing tools, paradigm shifts in QA, GenAI developer tools, LLM model releases."""

_MOMENTUM_ALERT_THRESHOLD = 5  # Trends with >= 5 supporting articles become alerts


class TrendAnalyzer:
    """
    Detects trends from recently collected and processed articles.

    Args:
        article_repo: Repository for Article records.
        trend_repo:   Repository for Trend records.
        api_key:      OpenAI API key (optional override).
        model:        OpenAI model name (optional override).
    """

    def __init__(
        self,
        article_repo: ArticleRepository,
        trend_repo: TrendRepository,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self._article_repo = article_repo
        self._trend_repo = trend_repo
        self._client = OpenAI(api_key=api_key or settings.openai_api_key)
        self._model = model or settings.openai_model

    def analyse(self, lookback_days: int = 7) -> list[Trend]:
        """
        Run trend detection on articles from the last N days.

        Args:
            lookback_days: How many days of articles to analyse.

        Returns:
            List of newly created or updated Trend objects.
        """
        since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        articles = self._article_repo.get_for_report(
            since=since,
            min_score=settings.min_relevance_score,
        )

        if len(articles) < 5:
            logger.info("TrendAnalyzer: not enough articles (%d) to detect trends", len(articles))
            return []

        logger.info("TrendAnalyzer: analysing %d articles for trends", len(articles))
        trend_data = self._detect_trends_with_llm(articles)

        if not trend_data:
            return []

        created_trends: list[Trend] = []
        for td in trend_data:
            try:
                trend = self._upsert_trend(td, articles)
                if trend:
                    created_trends.append(trend)
            except Exception as exc:
                logger.warning("Failed to upsert trend '%s': %s", td.get("name"), exc)

        logger.info("TrendAnalyzer: detected/updated %d trends", len(created_trends))
        return created_trends

    def _detect_trends_with_llm(self, articles: list[Article]) -> list[dict]:
        """Send article metadata to OpenAI and parse the trend response."""
        # Build a compact article list for the prompt
        article_list_str = "\n".join(
            f"[{i}] {a.title} | {a.category} | {a.summary[:120] if a.summary else a.raw_content[:120] if a.raw_content else ''}"
            for i, a in enumerate(articles[:50])  # Cap at 50 to stay within token limits
        )

        user_content = f"Articles collected (last 7 days):\n{article_list_str}"

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _TREND_DETECTION_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=1500,
                temperature=0.4,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
            data = json.loads(raw)

            # The model might return {"trends": [...]} or just [...]
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                for key in ("trends", "items", "results"):
                    if key in data and isinstance(data[key], list):
                        return data[key]

            logger.warning("Unexpected trend response format: %s", type(data))
            return []

        except openai.RateLimitError:
            logger.warning("OpenAI rate limit hit during trend analysis")
        except Exception as exc:
            logger.error("Trend LLM call failed: %s", exc)
        return []

    def _upsert_trend(self, trend_data: dict, articles: list[Article]) -> Optional[Trend]:
        """Create or update a Trend record and link supporting articles."""
        name = trend_data.get("name", "").strip()
        if not name:
            return None

        trend, created = self._trend_repo.get_or_create(
            name=name,
            category=trend_data.get("category", "general"),
        )

        trend.description = trend_data.get("description", "")
        trend.last_seen_at = datetime.now(timezone.utc)

        # Link supporting articles
        article_indices = trend_data.get("article_indices", [])
        for idx in article_indices:
            if 0 <= idx < len(articles):
                self._trend_repo.link_article(trend, articles[idx])

        # Recalculate momentum score
        trend.momentum_score = self._calculate_momentum(trend)

        # Auto-flag as alert if momentum is high or LLM flagged it
        if trend.article_count >= _MOMENTUM_ALERT_THRESHOLD or trend_data.get("is_alert"):
            trend.is_alert = True

        if created:
            logger.info("New trend detected: '%s' (category=%s)", name, trend.category)

        return trend

    @staticmethod
    def _calculate_momentum(trend: Trend) -> float:
        """
        Simple momentum = articles/day since first seen.
        Returns a float score capped at 100.
        """
        if not trend.first_seen_at:
            return float(trend.article_count)

        first = trend.first_seen_at
        if first.tzinfo is None:
            first = first.replace(tzinfo=timezone.utc)
        days_active = max(
            (datetime.now(timezone.utc) - first).total_seconds() / 86400,
            0.1,  # Avoid division by zero
        )
        return min(round((trend.article_count / days_active) * 10, 2), 100.0)
