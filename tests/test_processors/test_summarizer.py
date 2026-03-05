"""
Unit tests for the Summarizer – verifies response parsing,
error handling, and output structure without real API calls.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.processors.summarizer import Summarizer


@pytest.fixture
def valid_api_response() -> dict:
    return {
        "summary": "A three-sentence summary of the article content.",
        "key_insights": [
            "LLMs can autonomously generate test cases",
            "Self-healing locators reduce maintenance by 40%",
            "Integration with CI/CD is now plug-and-play",
        ],
        "qa_relevance": "Directly useful for QA managers building AI-assisted pipelines.",
    }


@pytest.fixture
def mock_openai_client(valid_api_response: dict) -> MagicMock:
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps(valid_api_response)

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response
    return mock_client


class TestSummarizerHappyPath:
    """Tests for successful summarisation flow."""

    def test_returns_dict_with_required_keys(self, mock_openai_client: MagicMock) -> None:
        with patch("src.processors.summarizer.OpenAI", return_value=mock_openai_client):
            summarizer = Summarizer(api_key="test-key")
            result = summarizer.summarise(
                title="Test Article",
                content="Some content",
                source_name="Test Feed",
                category="qa_testing",
                url="https://example.com",
            )

        assert result is not None
        assert "summary" in result
        assert "key_insights" in result
        assert "qa_relevance" in result

    def test_key_insights_is_list(self, mock_openai_client: MagicMock) -> None:
        with patch("src.processors.summarizer.OpenAI", return_value=mock_openai_client):
            summarizer = Summarizer(api_key="test-key")
            result = summarizer.summarise(
                title="T", content="C", source_name="S", category="genai", url="https://x.com"
            )

        assert isinstance(result["key_insights"], list)
        assert len(result["key_insights"]) == 3

    def test_content_truncated_to_max_chars(self, mock_openai_client: MagicMock) -> None:
        """Verify that the content sent to the API is truncated at _MAX_CONTENT_CHARS."""
        with patch("src.processors.summarizer.OpenAI", return_value=mock_openai_client):
            summarizer = Summarizer(api_key="test-key")
            summarizer.summarise(
                title="T",
                content="X" * 10_000,  # Way over the limit
                source_name="S",
                category="genai",
                url="https://x.com",
            )

        # Inspect what was passed to the API
        call_args = mock_openai_client.chat.completions.create.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[0]
        user_message = next(m["content"] for m in messages if m["role"] == "user")
        # The content in the message should not contain more than 4000 'X' chars
        assert user_message.count("X") <= 4000


class TestSummarizerErrorHandling:
    """Tests for graceful error handling."""

    def test_returns_none_on_rate_limit_error(self) -> None:
        import openai
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = openai.RateLimitError(
            message="Rate limit", response=MagicMock(status_code=429), body={}
        )
        with patch("src.processors.summarizer.OpenAI", return_value=mock_client):
            summarizer = Summarizer(api_key="test-key")
            result = summarizer.summarise("T", "C", "S", "genai", "https://x.com")
        assert result is None

    def test_returns_none_on_generic_exception(self) -> None:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("Network error")
        with patch("src.processors.summarizer.OpenAI", return_value=mock_client):
            summarizer = Summarizer(api_key="test-key")
            result = summarizer.summarise("T", "C", "S", "genai", "https://x.com")
        assert result is None

    def test_returns_none_on_invalid_json_response(self) -> None:
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "This is not JSON"
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        with patch("src.processors.summarizer.OpenAI", return_value=mock_client):
            summarizer = Summarizer(api_key="test-key")
            result = summarizer.summarise("T", "C", "S", "genai", "https://x.com")
        assert result is None

    def test_returns_none_on_missing_required_keys(self) -> None:
        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps({"only_one_key": "value"})
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        with patch("src.processors.summarizer.OpenAI", return_value=mock_client):
            summarizer = Summarizer(api_key="test-key")
            result = summarizer.summarise("T", "C", "S", "genai", "https://x.com")
        assert result is None

    def test_non_list_key_insights_coerced_to_list(self) -> None:
        """If the LLM returns key_insights as a string, it should be wrapped in a list."""
        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps({
            "summary": "Summary text.",
            "key_insights": "Just one insight as a string",
            "qa_relevance": "Relevant.",
        })
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        with patch("src.processors.summarizer.OpenAI", return_value=mock_client):
            summarizer = Summarizer(api_key="test-key")
            result = summarizer.summarise("T", "C", "S", "genai", "https://x.com")
        assert result is not None
        assert isinstance(result["key_insights"], list)
