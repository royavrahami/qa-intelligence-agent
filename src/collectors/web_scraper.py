"""
General-purpose web scraper for sources that don't provide RSS feeds.

Supports:
  - Static HTML scraping (requests + BeautifulSoup)
  - Heuristic article extraction: looks for <article>, <main>, og:description meta tags
  - Product Hunt "AI Tools" topic page (structured scrape)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from src.storage.models import Source
from src.storage.repository import ArticleRepository, SourceRepository

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (compatible; QAIntelligenceAgent/1.0; "
    "+https://github.com/qa-intelligence-agent)"
)
_REQUEST_TIMEOUT = 15
_MIN_CONTENT_LENGTH = 80  # Ignore articles with very short content


class WebScraper:
    """
    Scrapes web pages that lack an RSS feed.

    Strategy:
        1. Fetch the HTML page.
        2. Detect page type (Product Hunt, generic blog listing, etc.).
        3. Extract article cards/links + metadata.
        4. For each extracted item, call the appropriate extractor.

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
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _USER_AGENT})

    def collect_all(self, sources: list[Source]) -> int:
        """Collect from all web-type sources. Returns total new articles."""
        web_sources = [s for s in sources if s.source_type in ("web", "product_hunt")]
        total = 0
        for source in web_sources:
            try:
                count = self._collect_source(source)
                total += count
                self._source_repo.mark_fetched(source, had_error=False)
            except Exception as exc:
                logger.warning("WebScraper failed for %s: %s", source.name, exc)
                self._source_repo.mark_fetched(source, had_error=True)
        logger.info("WebScraper: %d new articles total", total)
        return total

    def _collect_source(self, source: Source) -> int:
        """Dispatch to the correct scraping strategy based on source type."""
        if source.source_type == "product_hunt":
            return self._scrape_product_hunt(source)
        return self._scrape_generic(source)

    # ── Product Hunt ──────────────────────────────────────────────────────────

    def _scrape_product_hunt(self, source: Source) -> int:
        """
        Extract AI tool listings from Product Hunt topic pages.
        Product Hunt renders via React, so we use meta/og tags from the listing
        page for basic data and link to each product's page.
        """
        response = self._session.get(source.url, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")

        new_count = 0
        # Product Hunt wraps each product in a <section> with data-test="post-item"
        product_cards = soup.select('[data-test="post-item"]')
        if not product_cards:
            # Fallback: look for links with /posts/ pattern
            product_cards = soup.select('a[href*="/posts/"]')

        seen_urls: set[str] = set()
        for card in product_cards[:20]:  # Limit to 20 items per run
            link = card.get("href", "") if card.name == "a" else ""
            if not link:
                link_tag = card.select_one('a[href*="/posts/"]')
                link = link_tag.get("href", "") if link_tag else ""

            if not link:
                continue

            full_url = urljoin("https://www.producthunt.com", link)
            if full_url in seen_urls or self._article_repo.exists(full_url):
                continue
            seen_urls.add(full_url)

            title_tag = card.select_one("h3, h2, [data-test='post-name']")
            title = title_tag.get_text(strip=True) if title_tag else full_url
            if not title or len(title) < 3:
                continue

            desc_tag = card.select_one("p, [data-test='post-tagline']")
            description = desc_tag.get_text(strip=True) if desc_tag else ""

            content = f"Product Hunt AI Tool\n{description}"

            self._article_repo.create(
                source_id=source.id,
                title=title,
                url=full_url,
                category=source.category,
                published_at=datetime.now(timezone.utc),
                raw_content=content,
            )
            new_count += 1

        logger.debug("Product Hunt: %d new tools", new_count)
        return new_count

    # ── Generic Page Scraper ──────────────────────────────────────────────────

    def _scrape_generic(self, source: Source) -> int:
        """
        Generic page scraper: extract all article-like links from a listing page,
        then fetch a short snippet from each linked page.
        """
        response = self._session.get(source.url, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")

        base_domain = f"{urlparse(source.url).scheme}://{urlparse(source.url).netloc}"
        article_links = self._extract_article_links(soup, base_domain)

        new_count = 0
        for link, title in article_links[:15]:
            if self._article_repo.exists(link):
                continue
            snippet = self._fetch_page_snippet(link)
            if not snippet or len(snippet) < _MIN_CONTENT_LENGTH:
                continue

            self._article_repo.create(
                source_id=source.id,
                title=title,
                url=link,
                category=source.category,
                published_at=datetime.now(timezone.utc),
                raw_content=snippet[:5000],
            )
            new_count += 1

        return new_count

    @staticmethod
    def _extract_article_links(soup: BeautifulSoup, base_domain: str) -> list[tuple[str, str]]:
        """
        Heuristically extract (url, title) pairs from a listing page.
        Prefers <article> and <h2>/<h3> anchors over generic links.
        """
        pairs: list[tuple[str, str]] = []
        seen: set[str] = set()

        # Strategy 1: <article> tags with anchors
        for article in soup.select("article"):
            link = article.select_one("a[href]")
            heading = article.select_one("h1, h2, h3")
            if link and heading:
                href = link["href"]
                if href.startswith("/"):
                    href = base_domain + href
                if href not in seen and href.startswith("http"):
                    pairs.append((href, heading.get_text(strip=True)))
                    seen.add(href)

        # Strategy 2: <h2>/<h3> anchors anywhere
        for heading in soup.select("h2 a[href], h3 a[href]"):
            href = heading.get("href", "")
            if href.startswith("/"):
                href = base_domain + href
            title = heading.get_text(strip=True)
            if href and href not in seen and href.startswith("http") and len(title) > 5:
                pairs.append((href, title))
                seen.add(href)

        return pairs

    def _fetch_page_snippet(self, url: str) -> Optional[str]:
        """Fetch a page and return a text snippet from its <main> or <article> tag."""
        try:
            resp = self._session.get(url, timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            # Try structured tags first
            for selector in ("article", "main", '[role="main"]'):
                tag = soup.select_one(selector)
                if tag:
                    text = tag.get_text(separator=" ", strip=True)
                    return re.sub(r"\s{2,}", " ", text)[:3000]

            # Fallback: og:description meta tag
            og_desc = soup.find("meta", attrs={"property": "og:description"})
            if og_desc:
                return og_desc.get("content", "")

        except Exception as exc:
            logger.debug("Snippet fetch failed for %s: %s", url, exc)
        return None
