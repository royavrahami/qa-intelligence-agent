"""
Content Processor – the pipeline stage that transforms raw articles
into enriched, scored, AI-summarised records ready for reporting.

Pipeline per article:
  1. Score relevance (fast, no API call)
  2. If score >= threshold → call AI summariser
  3. Persist enriched data back to the article record
  4. Mark article as processed
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from src.config.settings import settings
from src.processors.relevance_scorer import RelevanceScorer
from src.processors.summarizer import Summarizer
from src.storage.models import Article
from src.storage.repository import ArticleRepository, SourceRepository

logger = logging.getLogger(__name__)


class ContentProcessor:
    """
    Orchestrates relevance scoring + AI summarisation for raw articles.

    Args:
        article_repo:    Repository for Article records.
        source_repo:     Repository for Source records.
        scorer:          Configured RelevanceScorer instance.
        summarizer:      Configured Summarizer instance.
        min_score:       Minimum relevance score to trigger AI summarisation.
        batch_size:      How many unprocessed articles to process per run.
    """

    def __init__(
        self,
        article_repo: ArticleRepository,
        source_repo: SourceRepository,
        scorer: RelevanceScorer,
        summarizer: Optional[Summarizer] = None,
        min_score: float = None,
        batch_size: int = 200,
    ) -> None:
        self._article_repo = article_repo
        self._source_repo = source_repo
        self._scorer = scorer
        self._summarizer = summarizer
        self._min_score = min_score if min_score is not None else settings.min_relevance_score
        self._batch_size = batch_size

    def process_pending(self) -> tuple[int, int]:
        """
        Process a batch of unprocessed articles.

        Returns:
            (total_scored, total_summarised)
        """
        articles = self._article_repo.get_unprocessed(limit=self._batch_size)
        if not articles:
            logger.info("ContentProcessor: no pending articles")
            return 0, 0

        logger.info("ContentProcessor: processing %d articles", len(articles))

        # Build a source lookup to avoid N+1 queries
        source_ids = {a.source_id for a in articles}
        sources = {
            s.id: s
            for s in self._source_repo.get_all_active()
            if s.id in source_ids
        }

        total_scored = 0
        total_summarised = 0

        for article in articles:
            source = sources.get(article.source_id)
            if not source:
                article.is_processed = True
                continue

            try:
                score = self._scorer.score(article, source)
                article.relevance_score = score
                total_scored += 1

                if score >= self._min_score and self._summarizer:
                    result = self._summarizer.summarise(
                        title=article.title,
                        content=article.raw_content or "",
                        source_name=source.name,
                        category=article.category,
                        url=article.url,
                    )
                    if result:
                        article.summary = result.get("summary")
                        article.key_insights = json.dumps(result.get("key_insights", []))
                        article.qa_relevance = result.get("qa_relevance")
                        total_summarised += 1

                article.is_processed = True

            except Exception as exc:
                logger.error(
                    "Failed to process article id=%s '%s': %s",
                    article.id,
                    article.title[:40],
                    exc,
                )
                # Still mark as processed to avoid infinite retry loops
                article.is_processed = True

        logger.info(
            "ContentProcessor: scored=%d, summarised=%d",
            total_scored,
            total_summarised,
        )
        return total_scored, total_summarised
