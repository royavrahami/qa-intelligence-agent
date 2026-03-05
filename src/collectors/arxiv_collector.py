"""
Arxiv Collector – queries the Arxiv API for recent papers in AI, agents,
GenAI, and software-testing research.

Uses the official Arxiv API (atom feed) – no authentication required.
"""

from __future__ import annotations

import logging
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

import feedparser
import requests

from src.storage.models import Source
from src.storage.repository import ArticleRepository, SourceRepository

logger = logging.getLogger(__name__)

_ARXIV_API_BASE = "https://export.arxiv.org/api/query"
_REQUEST_TIMEOUT = 20
_RATE_LIMIT_DELAY = 3.0  # seconds between API calls (Arxiv ToS: 3 req/sec)

# Search queries tailored for QA Manager / AI-focused reading
_QUERIES: list[dict] = [
    {
        "search": "ti:\"large language model\" AND (ti:agent OR ti:agentic)",
        "category": "agents",
        "label": "LLM Agents",
    },
    {
        "search": "ti:\"software testing\" AND (ti:\"machine learning\" OR ti:\"large language model\")",
        "category": "qa_testing",
        "label": "AI-assisted Testing",
    },
    {
        "search": "all:\"test automation\" AND all:\"generative AI\"",
        "category": "qa_testing",
        "label": "GenAI Test Automation",
    },
    {
        "search": "ti:\"RAG\" OR ti:\"retrieval augmented generation\"",
        "category": "genai",
        "label": "RAG Techniques",
    },
    {
        "search": "ti:\"multi-agent\" AND ti:\"LLM\"",
        "category": "agents",
        "label": "Multi-Agent LLM Systems",
    },
]

_MAX_RESULTS_PER_QUERY = 10


class ArxivCollector:
    """
    Fetches recent academic papers from Arxiv and stores their abstracts.

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

    def collect_all(self) -> int:
        """Run all pre-defined Arxiv search queries."""
        total = 0
        for query_def in _QUERIES:
            try:
                new = self._run_query(query_def)
                total += new
                time.sleep(_RATE_LIMIT_DELAY)
            except Exception as exc:
                logger.warning("Arxiv query '%s' failed: %s", query_def["label"], exc)
        logger.info("Arxiv Collector: %d new papers", total)
        return total

    def _run_query(self, query_def: dict) -> int:
        """Execute a single Arxiv API query and persist results."""
        source = self._source_repo.upsert(
            name=f"Arxiv – {query_def['label']}",
            url=f"{_ARXIV_API_BASE}?search_query={urllib.parse.quote(query_def['search'])}",
            source_type="arxiv",
            category=query_def["category"],
            relevance_boost=12,
        )

        params = {
            "search_query": query_def["search"],
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": _MAX_RESULTS_PER_QUERY,
        }
        response = requests.get(_ARXIV_API_BASE, params=params, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()

        feed = feedparser.parse(response.content)

        new_count = 0
        for entry in feed.entries:
            paper_url = self._get_abs_url(entry)
            if not paper_url or self._article_repo.exists(paper_url):
                continue

            authors = self._extract_authors(entry)
            abstract = getattr(entry, "summary", "").replace("\n", " ").strip()
            published_at = self._parse_date(entry)

            content = (
                f"Arxiv Paper – {query_def['label']}\n"
                f"Authors: {authors}\n"
                f"Abstract: {abstract}"
            )

            self._article_repo.create(
                source_id=source.id,
                title=getattr(entry, "title", "Untitled").replace("\n", " ").strip(),
                url=paper_url,
                author=authors,
                published_at=published_at,
                category=query_def["category"],
                raw_content=content[:6000],
            )
            new_count += 1

        self._source_repo.mark_fetched(source)
        return new_count

    @staticmethod
    def _get_abs_url(entry: feedparser.FeedParserDict) -> Optional[str]:
        """Return the canonical abstract URL for an Arxiv entry."""
        for link in getattr(entry, "links", []):
            if link.get("type") == "text/html":
                return link.get("href")
        return getattr(entry, "link", None)

    @staticmethod
    def _extract_authors(entry: feedparser.FeedParserDict) -> str:
        """Return a comma-separated author string."""
        authors = getattr(entry, "authors", [])
        names = [a.get("name", "") for a in authors if a.get("name")]
        return ", ".join(names[:5]) + ("..." if len(names) > 5 else "")

    @staticmethod
    def _parse_date(entry: feedparser.FeedParserDict) -> Optional[datetime]:
        """Parse the published date from the entry."""
        parsed = getattr(entry, "published_parsed", None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except Exception:
                pass
        return None
