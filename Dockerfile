# ─────────────────────────────────────────────────────────────────────────────
# QA Intelligence Agent – Dockerfile
# Multi-stage build: dependencies layer + application layer
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim AS base

# System dependencies required by lxml and playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2-dev libxslt1-dev curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Dependencies ──────────────────────────────────────────────────────────────
FROM base AS deps
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Install Playwright browser (Chromium) for JavaScript-heavy pages
RUN playwright install chromium --with-deps 2>/dev/null || true

# ── Application ───────────────────────────────────────────────────────────────
FROM deps AS app
COPY . .

# Create persistent data directories (override with docker volumes)
RUN mkdir -p /app/data /app/reports /app/logs

# Non-root user for security
RUN useradd -m -u 1000 agent && chown -R agent:agent /app
USER agent

# ── Runtime ───────────────────────────────────────────────────────────────────
ENV PYTHONPATH=/app
ENV DATABASE_URL=sqlite:////app/data/qa_agent.db
ENV REPORTS_DIR=/app/reports
ENV LOG_DIR=/app/logs

EXPOSE 8080

# Default: run scheduler
CMD ["python", "main.py", "schedule"]
