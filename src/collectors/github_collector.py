"""
GitHub Collector – scrapes GitHub Trending and uses the GitHub REST API
to surface hot repositories in AI, testing, and automation spaces.

Data collected per repo:
  title   : "{owner}/{repo}"
  url     : repo URL
  content : description + topics + star count + language
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.config.settings import settings
from src.storage.models import Source
from src.storage.repository import ArticleRepository, SourceRepository

logger = logging.getLogger(__name__)

_USER_AGENT = "QAIntelligenceAgent/1.0"
_REQUEST_TIMEOUT = 15

# Topics to query via GitHub search API
_GITHUB_TOPICS = [
    "ai-agent",
    "llm",
    "test-automation",
    "generative-ai",
    "rag",
    "playwright",
    "quality-engineering",
]


class GitHubCollector:
    """
    Collects trending and topic-filtered GitHub repositories.

    Args:
        source_repo: Repository for Source records.
        article_repo: Repository for Article records.
        github_token: Optional personal access token (increases rate limit).
    """

    def __init__(
        self,
        source_repo: SourceRepository,
        article_repo: ArticleRepository,
        github_token: Optional[str] = None,
    ) -> None:
        self._source_repo = source_repo
        self._article_repo = article_repo
        self._token = github_token or settings.github_token
        self._headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "application/vnd.github+json",
        }
        if self._token:
            self._headers["Authorization"] = f"Bearer {self._token}"

    def collect_all(self, sources: list[Source]) -> int:
        """Run all GitHub collection strategies and return total new articles."""
        total = 0
        total += self._collect_trending_page(sources)
        total += self._collect_topic_search(sources)
        logger.info("GitHub Collector: %d new items total", total)
        return total

    # ── Trending Page Scraper ──────────────────────────────────────────────────

    def _collect_trending_page(self, sources: list[Source]) -> int:
        """Scrape github.com/trending for repositories trending in AI/testing."""
        trending_sources = [s for s in sources if s.source_type == "github_trending"]
        new_count = 0

        for source in trending_sources:
            try:
                new_count += self._scrape_trending(source)
                self._source_repo.mark_fetched(source, had_error=False)
            except Exception as exc:
                logger.warning("GitHub trending scrape failed for %s: %s", source.url, exc)
                self._source_repo.mark_fetched(source, had_error=True)

        return new_count

    def _scrape_trending(self, source: Source) -> int:
        """Parse the GitHub trending HTML page and extract repository cards."""
        response = requests.get(
            source.url,
            headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")
        # GitHub renders each trending repo as an <article> element
        repo_cards = soup.select("article.Box-row")

        new_count = 0
        for card in repo_cards:
            link_tag = card.select_one("h2 a")
            if not link_tag:
                continue

            repo_path = link_tag.get("href", "").strip("/")  # e.g. "owner/repo"
            repo_url = f"https://github.com/{repo_path}"

            if self._article_repo.exists(repo_url):
                continue

            description_tag = card.select_one("p")
            description = description_tag.get_text(strip=True) if description_tag else ""

            stars_tag = card.select_one("a[href$='/stargazers']")
            stars = stars_tag.get_text(strip=True) if stars_tag else "N/A"

            language_tag = card.select_one("[itemprop='programmingLanguage']")
            language = language_tag.get_text(strip=True) if language_tag else "N/A"

            content = (
                f"GitHub Trending Repository\n"
                f"Stars: {stars} | Language: {language}\n"
                f"Description: {description}"
            )

            self._article_repo.create(
                source_id=source.id,
                title=repo_path,
                url=repo_url,
                category=source.category,
                published_at=datetime.now(timezone.utc),
                raw_content=content,
            )
            new_count += 1

        logger.debug("GitHub trending %s: %d new repos", source.url, new_count)
        return new_count

    # ── GitHub API Topic Search ────────────────────────────────────────────────

    def _collect_topic_search(self, sources: list[Source]) -> int:
        """
        Use GitHub search API to find recently updated repos for key topics.
        Requires a synthetic Source record for the API endpoint.
        """
        # Find or create a synthetic source for the API
        api_source = self._source_repo.upsert(
            name="GitHub API – Topic Search",
            url="https://api.github.com/search/repositories",
            source_type="github_api",
            category="tools",
            relevance_boost=8,
        )

        new_count = 0
        for topic in _GITHUB_TOPICS:
            try:
                new_count += self._search_topic(api_source, topic)
            except Exception as exc:
                logger.warning("GitHub API topic '%s' failed: %s", topic, exc)

        return new_count

    def _search_topic(self, source: Source, topic: str) -> int:
        """Query the GitHub search API for a single topic."""
        params = {
            "q": f"topic:{topic} pushed:>2024-01-01",
            "sort": "updated",
            "order": "desc",
            "per_page": 5,
        }
        response = requests.get(
            "https://api.github.com/search/repositories",
            headers=self._headers,
            params=params,
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

        new_count = 0
        for repo in data.get("items", []):
            repo_url = repo.get("html_url", "")
            if not repo_url or self._article_repo.exists(repo_url):
                continue

            topics_str = ", ".join(repo.get("topics", []))
            content = (
                f"GitHub Repository (Topic: {topic})\n"
                f"Stars: {repo.get('stargazers_count', 0):,} | "
                f"Language: {repo.get('language', 'N/A')}\n"
                f"Topics: {topics_str}\n"
                f"Description: {repo.get('description', '')}"
            )

            category = "qa_testing" if "test" in topic else "tools"
            self._article_repo.create(
                source_id=source.id,
                title=repo.get("full_name", repo_url),
                url=repo_url,
                category=category,
                published_at=datetime.now(timezone.utc),
                raw_content=content,
            )
            new_count += 1

        return new_count
