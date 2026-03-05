"""
Source Discoverer – the self-expansion module.

The agent analyses existing articles to discover links to NEW sources
it hasn't monitored before, then records them in the database so they
can be activated in the next run cycle.

Discovery strategies:
  1. Link extraction: scan article URLs for known patterns (blog, rss, etc.)
  2. LLM-guided discovery: ask the LLM "what sources should I add based on what I'm reading?"
  3. GitHub README mining: repos that mention tools → link to their docs/blogs
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urljoin, urlparse

import openai
import requests
from bs4 import BeautifulSoup
from openai import OpenAI

from src.config.settings import settings
from src.storage.models import Article
from src.storage.repository import (
    ArticleRepository,
    KnowledgeExpansionRepository,
    SourceRepository,
)

logger = logging.getLogger(__name__)

_RSS_PATTERNS = [
    "/feed", "/feed/", "/rss", "/rss.xml", "/atom.xml", "/feed.xml",
    "/blog/feed", "/blog/rss", "/news/feed",
]

_KNOWN_DOMAINS_BLOCKLIST = {
    "twitter.com", "x.com", "facebook.com", "linkedin.com",
    "youtube.com", "reddit.com", "instagram.com", "google.com",
    "amazon.com", "wikipedia.org",
}

_LLM_DISCOVERY_PROMPT = """You are a research librarian specialising in AI, software testing, and developer tools.

Based on the following list of sources and topics I'm already monitoring, suggest 5 NEW, high-quality sources I should add to stay up-to-date.

Focus on:
- Newsletters, blogs, podcasts with RSS/Atom feeds
- GitHub organisations publishing relevant repos regularly
- Arxiv topic searches for AI/testing papers
- Conference proceedings or community hubs

For each suggestion, return a JSON object:
{
  "name": "<Source name>",
  "url": "<Full URL of the RSS feed or main page>",
  "source_type": "<rss | github_trending | arxiv | web>",
  "category": "<genai | agents | qa_testing | devops | tools | project_management>",
  "reason": "<1 sentence explaining why this source is valuable for a QA Manager>"
}

Return a JSON array. No markdown, no preamble."""


class SourceDiscoverer:
    """
    Autonomously discovers new information sources by:
    1. Mining article pages for embedded RSS feed links.
    2. Asking the LLM to recommend new sources based on context.
    3. Tracking all discoveries in KnowledgeExpansion records.

    Args:
        source_repo:     Source repository.
        article_repo:    Article repository.
        expansion_repo:  KnowledgeExpansion repository.
        api_key:         OpenAI API key (optional).
        model:           OpenAI model (optional).
    """

    def __init__(
        self,
        source_repo: SourceRepository,
        article_repo: ArticleRepository,
        expansion_repo: KnowledgeExpansionRepository,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self._source_repo = source_repo
        self._article_repo = article_repo
        self._expansion_repo = expansion_repo
        self._client = OpenAI(api_key=api_key or settings.openai_api_key)
        self._model = model or settings.openai_model
        self._http_session = requests.Session()
        self._http_session.headers.update({"User-Agent": "QAIntelligenceAgent/1.0"})

    def discover(self) -> int:
        """
        Run all discovery strategies and register new sources.

        Returns:
            Number of new sources discovered.
        """
        new_sources = 0
        new_sources += self._discover_from_article_pages()
        new_sources += self._discover_via_llm()
        logger.info("SourceDiscoverer: discovered %d new sources", new_sources)
        return new_sources

    # ── Strategy 1: RSS Link Mining ───────────────────────────────────────────

    def _discover_from_article_pages(self) -> int:
        """
        Scan recent article pages for <link rel='alternate' type='application/rss+xml'>.
        """
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        articles = self._article_repo.get_for_report(since=since, min_score=70.0)

        discovered_domains: set[str] = set()
        new_count = 0

        for article in articles[:20]:  # Limit to avoid too many HTTP calls
            domain = urlparse(article.url).netloc
            if domain in discovered_domains or domain in _KNOWN_DOMAINS_BLOCKLIST:
                continue
            discovered_domains.add(domain)

            feed_url = self._find_rss_on_page(article.url, domain)
            if feed_url:
                registered = self._register_new_source(
                    name=f"Auto-discovered: {domain}",
                    url=feed_url,
                    source_type="rss",
                    category=article.category,
                    reason=f"Discovered via article: {article.title[:60]}",
                )
                if registered:
                    new_count += 1

        return new_count

    def _find_rss_on_page(self, article_url: str, domain: str) -> Optional[str]:
        """
        Look for an RSS feed link on an article's page or try common RSS paths.
        """
        try:
            resp = self._http_session.get(article_url, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            # Check <link rel="alternate" type="application/rss+xml">
            for link_tag in soup.find_all("link", rel="alternate"):
                if "rss" in link_tag.get("type", "") or "atom" in link_tag.get("type", ""):
                    href = link_tag.get("href", "")
                    if href:
                        return urljoin(article_url, href)

        except Exception as exc:
            logger.debug("Page fetch failed for %s: %s", article_url, exc)

        # Try common RSS paths on the base domain
        base = f"https://{domain}"
        for path in _RSS_PATTERNS:
            candidate = base + path
            if self._is_valid_feed(candidate):
                return candidate

        return None

    def _is_valid_feed(self, url: str) -> bool:
        """Do a HEAD request to check if a feed URL returns XML-like content."""
        try:
            resp = self._http_session.head(url, timeout=5, allow_redirects=True)
            content_type = resp.headers.get("Content-Type", "")
            return resp.status_code == 200 and any(
                ct in content_type for ct in ("xml", "rss", "atom", "feed")
            )
        except Exception:
            return False

    # ── Strategy 2: LLM-Guided Discovery ─────────────────────────────────────

    def _discover_via_llm(self) -> int:
        """
        Ask the LLM to recommend new sources based on what we're already tracking.
        """
        existing_sources = self._source_repo.get_all_active()
        if not existing_sources:
            return 0

        context = "\n".join(
            f"- {s.name} ({s.category}): {s.url}"
            for s in existing_sources[:30]
        )
        user_message = f"Current sources I monitor:\n{context}"

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _LLM_DISCOVERY_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=1000,
                temperature=0.5,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
            suggestions = self._parse_suggestions(raw)

        except openai.RateLimitError:
            logger.warning("Rate limit hit during source discovery LLM call")
            return 0
        except Exception as exc:
            logger.error("LLM source discovery failed: %s", exc)
            return 0

        new_count = 0
        for suggestion in suggestions:
            registered = self._register_new_source(
                name=suggestion.get("name", "Unknown"),
                url=suggestion.get("url", ""),
                source_type=suggestion.get("source_type", "rss"),
                category=suggestion.get("category", "general"),
                reason=suggestion.get("reason", "LLM recommendation"),
            )
            if registered:
                new_count += 1

        return new_count

    @staticmethod
    def _parse_suggestions(raw_json: str) -> list[dict]:
        """Parse and validate LLM JSON response for source suggestions."""
        import json
        try:
            data = json.loads(raw_json)
            if isinstance(data, list):
                return data
            for key in ("suggestions", "sources", "items"):
                if key in data and isinstance(data[key], list):
                    return data[key]
        except Exception as exc:
            logger.warning("Failed to parse source discovery response: %s", exc)
        return []

    # ── Shared Helper ─────────────────────────────────────────────────────────

    def _register_new_source(
        self,
        name: str,
        url: str,
        source_type: str,
        category: str,
        reason: str,
    ) -> bool:
        """
        Register a newly discovered source if it's not already known.

        Returns:
            True if a new source was registered, False otherwise.
        """
        if not url or not re.match(r"^https?://", url):
            return False

        # Skip if already in the database (registered sources)
        if self._source_repo.get_by_url(url):
            return False

        # Skip if already recorded as a knowledge expansion
        if self._expansion_repo.already_known(url):
            return False

        # Register the source (starts inactive – reviewed in next run)
        # We set it active immediately since the agent owns its own expansion
        self._source_repo.upsert(
            name=name,
            url=url,
            source_type=source_type,
            category=category,
            relevance_boost=5,  # Neutral boost for new sources
        )

        # Record the expansion event for auditability
        self._expansion_repo.record(
            expansion_type="new_source",
            description=reason,
            value=url,
            confidence=0.8,
        )

        logger.info("New source discovered and registered: %s (%s)", name, url)
        return True
