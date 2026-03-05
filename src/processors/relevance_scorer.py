"""
Relevance Scorer – assigns a numeric relevance score (0–100) to each article
BEFORE it is sent to the LLM, to filter noise and reduce API costs.

Scoring strategy (additive):
  1. Keyword match score  (0–50): high/medium/low keyword categories from config
  2. Source boost         (0–20): pre-configured per-source bonus
  3. Category bonus       (0–10): qa_testing / agents / genai categories get a bonus
  4. Freshness bonus      (0–10): articles < 48 h old get extra points
  5. Title heuristics     (0–10): title length, structure signals

Total cap: 100
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from src.storage.models import Article, Source

logger = logging.getLogger(__name__)

# Keyword weights loaded from config/sources.yaml
_HIGH_KW_SCORE = 8
_MEDIUM_KW_SCORE = 3
_LOW_KW_SCORE = 1

# Larger bonuses so category-relevant articles naturally exceed the threshold
_CATEGORY_BONUSES = {
    "qa_testing":         20,
    "agents":             18,
    "genai":              18,
    "devops":             8,
    "tools":              6,
    "project_management": 10,
    "arxiv":              15,
}

# Built-in keywords that supplement sources.yaml (short-form terms missed by exact phrases)
_BUILTIN_HIGH_KEYWORDS = [
    "llm", "gpt", "claude", "gemini", "agent", "agents",
    "test automation", "ai agent", "agentic", "genai", "rag",
    "playwright", "selenium", "multi-agent", "mcp", "copilot",
    "quality engineering", "shift left", "dora", "ci/cd",
    "llm testing", "ai qa", "autonomous", "generative",
]
_BUILTIN_MEDIUM_KEYWORDS = [
    "testing", "automation", "software testing", "machine learning",
    "neural", "pipeline", "benchmark", "evaluation", "fine-tuning",
    "devops", "deployment", "monitoring", "observability",
    "agile", "scrum", "sprint", "defect", "bug", "regression",
    "api testing", "performance", "load testing", "language model",
]

_FRESHNESS_HOURS = 48  # Max age in hours for freshness bonus


class RelevanceScorer:
    """
    Fast, deterministic relevance scorer that runs without an LLM call.

    Args:
        high_keywords: List of high-importance keywords.
        medium_keywords: List of medium-importance keywords.
        low_keywords: List of low-importance keywords.
    """

    def __init__(
        self,
        high_keywords: list[str],
        medium_keywords: list[str],
        low_keywords: list[str],
    ) -> None:
        # Merge caller-supplied keywords with built-in lists (deduplicated)
        self._high_kw = list({kw.lower() for kw in high_keywords + _BUILTIN_HIGH_KEYWORDS})
        self._medium_kw = list({kw.lower() for kw in medium_keywords + _BUILTIN_MEDIUM_KEYWORDS})
        self._low_kw = [kw.lower() for kw in low_keywords]

    def score(self, article: Article, source: Source) -> float:
        """
        Compute a relevance score for an article.

        Args:
            article: The article to score.
            source:  The source the article came from.

        Returns:
            Float between 0.0 and 100.0.
        """
        text = self._normalise(article.title or "", article.raw_content or "")
        score = 0.0

        # 1. Keyword scoring (cap at 50)
        kw_score = 0
        for kw in self._high_kw:
            if kw in text:
                kw_score += _HIGH_KW_SCORE
        for kw in self._medium_kw:
            if kw in text:
                kw_score += _MEDIUM_KW_SCORE
        for kw in self._low_kw:
            if kw in text:
                kw_score += _LOW_KW_SCORE
        score += min(kw_score, 50)

        # 2. Source boost (from config, max 20)
        score += min(source.relevance_boost or 0, 20)

        # 3. Category bonus (max 20)
        score += _CATEGORY_BONUSES.get(article.category, 0)

        # 4. Freshness bonus (max 10)
        score += self._freshness_bonus(article.published_at or article.collected_at)

        # 5. Title heuristics (max 10)
        score += self._title_bonus(article.title or "")

        final = min(round(score, 1), 100.0)
        logger.debug(
            "Scored article '%s': %.1f (kw=%d, src=%d, cat=%d)",
            article.title[:40],
            final,
            min(kw_score, 50),
            source.relevance_boost or 0,
            _CATEGORY_BONUSES.get(article.category, 0),
        )
        return final

    @staticmethod
    def _normalise(*texts: str) -> str:
        """Merge and lowercase all text for keyword matching."""
        combined = " ".join(texts)
        return combined.lower()

    @staticmethod
    def _freshness_bonus(published_at: Optional[datetime]) -> float:
        """Award up to 10 points for very recent articles."""
        if not published_at:
            return 0.0
        # Make timezone-aware if naive
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - published_at).total_seconds() / 3600
        if age_hours < 6:
            return 10.0
        if age_hours < 24:
            return 7.0
        if age_hours < _FRESHNESS_HOURS:
            return 4.0
        return 0.0

    @staticmethod
    def _title_bonus(title: str) -> float:
        """Heuristic title quality signals (max 10)."""
        score = 0.0
        title_lower = title.lower()

        # Titles with action / trend signals
        action_words = ["launch", "release", "introduce", "announce", "new", "2024", "2025", "2026"]
        for word in action_words:
            if word in title_lower:
                score += 1.0
                break

        # Titles mentioning specific tools the QA manager cares about
        tool_signals = ["gpt", "claude", "gemini", "copilot", "playwright", "selenium", "cursor", "mcp"]
        for sig in tool_signals:
            if sig in title_lower:
                score += 2.0
                break

        # Good title length (not too short, not too long)
        if 20 <= len(title) <= 120:
            score += 2.0

        return min(score, 10.0)
