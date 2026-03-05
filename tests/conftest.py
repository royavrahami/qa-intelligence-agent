"""
Shared pytest fixtures for the QA Intelligence Agent test suite.

Provides:
  - in-memory SQLite session for isolated DB tests
  - sample Source and Article factories
  - mock OpenAI client patch
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.storage.models import Article, Base, Source


# ── Database fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    """
    Provide an isolated in-memory SQLite session for each test.
    All tables are created fresh and dropped after the test.
    """
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine)
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        Base.metadata.drop_all(engine)


# ── Object factories ───────────────────────────────────────────────────────────

@pytest.fixture
def sample_source(db_session: Session) -> Source:
    """Create and persist a standard RSS source for use in tests."""
    source = Source(
        name="Test Feed",
        url="https://example.com/feed",
        source_type="rss",
        category="qa_testing",
        relevance_boost=10,
    )
    db_session.add(source)
    db_session.flush()
    return source


@pytest.fixture
def sample_article(db_session: Session, sample_source: Source) -> Article:
    """Create and persist a raw (unprocessed) article for use in tests."""
    article = Article(
        source_id=sample_source.id,
        title="How LLMs Are Transforming Test Automation",
        url="https://example.com/article/1",
        category="qa_testing",
        raw_content=(
            "Large language models are rapidly changing how QA engineers write and "
            "maintain test suites. AI agent frameworks allow autonomous test generation, "
            "self-healing locators in Playwright, and intelligent defect triage."
        ),
        published_at=datetime.now(timezone.utc),
    )
    db_session.add(article)
    db_session.flush()
    return article


@pytest.fixture
def processed_article(db_session: Session, sample_source: Source) -> Article:
    """Create a fully processed article with AI-generated fields."""
    article = Article(
        source_id=sample_source.id,
        title="Claude 3.5 Introduces Agentic Testing Mode",
        url="https://example.com/article/2",
        category="agents",
        raw_content="Anthropic releases Claude 3.5 with native tool use for testing agents.",
        published_at=datetime.now(timezone.utc),
        summary="Anthropic's Claude 3.5 enables agentic test execution with tool-use APIs.",
        key_insights=json.dumps([
            "Claude 3.5 can autonomously generate and run test cases",
            "Native tool-use API reduces integration overhead",
            "QA teams report 40% reduction in manual test maintenance",
        ]),
        qa_relevance="Directly applicable to building AI-assisted regression suites.",
        relevance_score=87.5,
        is_processed=True,
    )
    db_session.add(article)
    db_session.flush()
    return article


# ── Mock OpenAI client ─────────────────────────────────────────────────────────

@pytest.fixture
def mock_openai():
    """
    Patch the OpenAI client to avoid real API calls in tests.
    Returns a configurable mock that mimics the chat.completions.create interface.
    """
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps({
        "summary": "Test summary of the article content.",
        "key_insights": ["Insight 1", "Insight 2", "Insight 3"],
        "qa_relevance": "Relevant for QA managers building automated pipelines.",
    })

    with patch("openai.OpenAI") as mock_client_class:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_client_class.return_value = mock_client
        yield mock_client
