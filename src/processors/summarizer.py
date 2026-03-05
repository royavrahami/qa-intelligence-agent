"""
AI Summarizer – uses the OpenAI API to generate structured summaries,
key insights, and QA Manager relevance explanations for each article.

Output per article (three fields):
  summary       : 3–5 sentence summary of the content
  key_insights  : JSON array of 3 bullet-point insights
  qa_relevance  : 2–3 sentences explaining value for a QA Manager / PM
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import openai
from openai import OpenAI

from src.config.settings import settings

logger = logging.getLogger(__name__)

# System prompt that defines the agent's persona and output contract
_SYSTEM_PROMPT = """You are an expert QA Engineering Advisor with deep knowledge of:
- Generative AI, LLMs, and autonomous agents
- Software testing, QA automation, and quality engineering
- DevOps, CI/CD, and software delivery
- Project management in high-tech environments

Your job: analyse a piece of tech content and return a structured JSON object with exactly these three fields:
{
  "summary": "<3-5 sentence summary in English>",
  "key_insights": ["<insight 1>", "<insight 2>", "<insight 3>"],
  "qa_relevance": "<2-3 sentences explaining why this matters to a QA Manager / Tech Project Manager>"
}

Rules:
- Write in clear, professional English.
- Be concise and information-dense – no filler.
- key_insights must be actionable, specific bullet points.
- qa_relevance must link directly to testing, quality, team management, or project delivery.
- Always return valid JSON – no markdown, no preamble."""

_USER_PROMPT_TEMPLATE = """Analyse the following content and return the structured JSON.

Title: {title}
Source: {source_name}
Category: {category}
URL: {url}

Content:
{content}"""

_MAX_CONTENT_CHARS = 4000  # Truncate to control token usage


class Summarizer:
    """
    Generates AI-powered structured summaries via OpenAI.

    Args:
        api_key: OpenAI API key (defaults to settings).
        model:   OpenAI model name (defaults to settings).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self._client = OpenAI(api_key=api_key or settings.openai_api_key)
        self._model = model or settings.openai_model
        self._max_tokens = settings.openai_max_tokens

    def summarise(
        self,
        title: str,
        content: str,
        source_name: str,
        category: str,
        url: str,
    ) -> Optional[dict]:
        """
        Call the OpenAI API and return the parsed summary dict.

        Returns:
            Dict with keys: summary, key_insights, qa_relevance
            or None if the call fails.
        """
        truncated_content = content[:_MAX_CONTENT_CHARS] if content else "(no content)"
        user_prompt = _USER_PROMPT_TEMPLATE.format(
            title=title,
            source_name=source_name,
            category=category,
            url=url,
            content=truncated_content,
        )

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=self._max_tokens,
                temperature=0.3,  # Low temperature for factual, consistent output
                response_format={"type": "json_object"},
            )
            raw_json = response.choices[0].message.content
            return self._parse_response(raw_json)

        except openai.RateLimitError:
            logger.warning("OpenAI rate limit hit – skipping article: %s", title[:50])
        except openai.APIConnectionError as exc:
            logger.error("OpenAI connection error: %s", exc)
        except Exception as exc:
            logger.error("Summarisation failed for '%s': %s", title[:50], exc)

        return None

    @staticmethod
    def _parse_response(raw_json: str) -> Optional[dict]:
        """Validate and return the parsed JSON response."""
        try:
            data = json.loads(raw_json)
            required_keys = {"summary", "key_insights", "qa_relevance"}
            if not required_keys.issubset(data.keys()):
                logger.warning("OpenAI response missing required keys: %s", data.keys())
                return None
            # Ensure key_insights is a list
            if not isinstance(data["key_insights"], list):
                data["key_insights"] = [str(data["key_insights"])]
            return data
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Failed to parse OpenAI response: %s | raw: %.200s", exc, raw_json)
            return None
