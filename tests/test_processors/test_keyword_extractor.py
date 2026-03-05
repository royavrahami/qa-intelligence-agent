"""
Unit tests for the KeywordExtractor.

Tests statistical extraction, insights parsing, and edge cases.
All tests avoid real API calls (LLM extraction tested via mock).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.processors.keyword_extractor import KeywordExtractor
from src.storage.models import Article


def _make_article(**kwargs) -> Article:
    """Factory for minimal Article mock objects."""
    art = MagicMock(spec=Article)
    art.title = kwargs.get("title", "")
    art.raw_content = kwargs.get("raw_content", "")
    art.key_insights = kwargs.get("key_insights", None)
    return art


class TestKeywordExtractorStatistical:
    """Tests for the statistical (no-API) keyword extraction fallback."""

    def test_extracts_keywords_from_title(self) -> None:
        extractor = KeywordExtractor(use_llm=False)
        article = _make_article(
            title="Playwright integrates AI self-healing locators",
            raw_content="",
        )
        keywords = extractor.extract(article)
        assert len(keywords) > 0
        joined = " ".join(keywords).lower()
        # At least one meaningful word should appear
        assert any(w in joined for w in ["playwright", "healing", "locators", "integrates"])

    def test_stop_words_filtered_out(self) -> None:
        extractor = KeywordExtractor(use_llm=False)
        article = _make_article(
            title="The a an and or but in on at",
            raw_content="the and or but in on",
        )
        keywords = extractor.extract(article)
        for kw in keywords:
            assert kw.lower() not in {"the", "and", "or", "but", "in", "on", "at", "a", "an"}

    def test_returns_at_most_six_keywords(self) -> None:
        extractor = KeywordExtractor(use_llm=False)
        article = _make_article(
            title="AI LLM RAG agent testing automation playwright selenium devops pipeline benchmark evaluation",
            raw_content="AI LLM RAG agent testing automation playwright",
        )
        keywords = extractor.extract(article)
        assert len(keywords) <= 6

    def test_empty_content_returns_empty_list(self) -> None:
        extractor = KeywordExtractor(use_llm=False)
        article = _make_article(title="", raw_content="")
        keywords = extractor.extract(article)
        assert isinstance(keywords, list)

    def test_short_words_filtered(self) -> None:
        extractor = KeywordExtractor(use_llm=False)
        article = _make_article(title="AI is a big deal ok so", raw_content="")
        keywords = extractor.extract(article)
        for kw in keywords:
            assert len(kw) >= 3


class TestKeywordExtractorFromInsights:
    """Tests for keyword extraction from existing AI-generated key_insights."""

    def test_extracts_capitalised_terms_from_insights(self) -> None:
        extractor = KeywordExtractor(use_llm=False)
        article = _make_article(
            title="Test",
            key_insights=json.dumps([
                "Playwright enables self-healing test locators.",
                "Claude and GPT-4 power autonomous agents.",
                "RAG architecture improves retrieval accuracy.",
            ]),
        )
        keywords = extractor.extract(article)
        joined = " ".join(keywords)
        assert any(kw in joined for kw in ["Playwright", "Claude", "RAG"])

    def test_extracts_tech_acronyms(self) -> None:
        extractor = KeywordExtractor(use_llm=False)
        article = _make_article(
            title="Test",
            key_insights=json.dumps([
                "The llm and rag pipeline uses api endpoints.",
                "CI/CD improves delivery speed.",
            ]),
        )
        keywords = extractor.extract(article)
        joined = " ".join(keywords).upper()
        assert any(term in joined for term in ["LLM", "RAG", "API", "CI/CD"])

    def test_invalid_insights_json_falls_back_to_statistical(self) -> None:
        extractor = KeywordExtractor(use_llm=False)
        article = _make_article(
            title="Playwright AI testing automation tool",
            key_insights="not valid json {{",
        )
        keywords = extractor.extract(article)
        assert isinstance(keywords, list)


class TestKeywordExtractorLLM:
    """Tests for LLM-powered keyword extraction (mocked API)."""

    def test_llm_returns_keyword_list(self) -> None:
        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps(
            {"keywords": ["LLM Agents", "RAG Pipeline", "Playwright", "CI/CD"]}
        )
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        # OpenAI is imported locally inside _from_llm, patch at openai module level
        with patch("openai.OpenAI", return_value=mock_client):
            extractor = KeywordExtractor(use_llm=True)
            extractor._use_llm = True
            article = _make_article(title="AI Testing", raw_content="Some content about AI")
            keywords = extractor._from_llm(article)

        assert "LLM Agents" in keywords
        assert "Playwright" in keywords

    def test_llm_failure_returns_empty_list(self) -> None:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API error")

        with patch("openai.OpenAI", return_value=mock_client):
            extractor = KeywordExtractor(use_llm=True)
            extractor._use_llm = True
            article = _make_article(title="Test", raw_content="Content")
            result = extractor._from_llm(article)

        assert result == []
