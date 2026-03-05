#!/usr/bin/env python3
"""
QA Intelligence Agent – Main Entry Point

Usage:
  python main.py run          # Run the agent once and exit
  python main.py schedule     # Run on a recurring schedule (daemon mode)
  python main.py report       # Generate a report from existing DB data
  python main.py status       # Show last N run summaries
  python main.py --help       # Show all options

Environment:
  Copy .env.example → .env and fill in OPENAI_API_KEY at minimum.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich import box

# ── Logging setup (must happen before any src imports) ─────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, markup=True)],
)
# Silence noisy third-party loggers
for noisy in ("httpx", "httpcore", "openai._base_client", "apscheduler"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger("qa_agent")
console = Console()


def cmd_run(_args: argparse.Namespace) -> None:
    """Execute one full agent cycle and exit."""
    from src.agent.core_agent import CoreAgent

    console.print("[bold blue]Starting single agent run...[/bold blue]")
    agent = CoreAgent()
    report_path = agent.run()

    if report_path:
        console.print(f"\n[bold green]✓ Done![/bold green] Report saved to:\n  {report_path}")
    else:
        console.print("\n[yellow]Run completed – not enough data yet to generate a report.[/yellow]")


def cmd_schedule(args: argparse.Namespace) -> None:
    """Start the recurring scheduler."""
    from src.scheduler.job_scheduler import AgentScheduler

    hours = args.interval or None
    scheduler = AgentScheduler(interval_hours=hours)
    scheduler.start()


def cmd_report(_args: argparse.Namespace) -> None:
    """Generate a report from data already in the database."""
    from datetime import datetime, timedelta, timezone

    from src.config.settings import settings
    from src.reports.report_generator import ReportGenerator
    from src.storage.database import init_db, get_session
    from src.storage.repository import ArticleRepository, TrendRepository

    init_db()
    with get_session() as session:
        article_repo = ArticleRepository(session)
        trend_repo = TrendRepository(session)

        since = datetime.now(timezone.utc) - timedelta(days=7)
        articles = article_repo.get_for_report(since=since, min_score=settings.min_relevance_score)
        trends = trend_repo.get_top_trends(limit=10, days=7)

        if not articles and not trends:
            console.print("[yellow]No data available. Run the agent first with: python main.py run[/yellow]")
            return

        generator = ReportGenerator(reports_dir=settings.reports_dir)
        path = generator.generate(articles=articles, trends=trends, run_id=0)
        console.print(f"[bold green]Report generated:[/bold green] {path}")


def cmd_status(_args: argparse.Namespace) -> None:
    """Display a table of the last agent runs."""
    from src.storage.database import init_db, get_session
    from src.storage.repository import AgentRunRepository

    init_db()
    with get_session() as session:
        raw = AgentRunRepository(session).get_last(n=10)
        # Snapshot before session closes
        runs = [
            (r.id, r.started_at, r.status, r.articles_collected,
             r.articles_processed, r.trends_detected, r.new_sources_discovered)
            for r in raw
        ]

    if not runs:
        console.print("[yellow]No runs found. The agent hasn't run yet.[/yellow]")
        return

    table = Table(
        title="Recent Agent Runs",
        box=box.ROUNDED,
        header_style="bold white on #0f3460",
    )
    table.add_column("ID", justify="right", style="dim")
    table.add_column("Started", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Collected", justify="right")
    table.add_column("Processed", justify="right")
    table.add_column("Trends", justify="right")
    table.add_column("New Sources", justify="right")

    status_styles = {"success": "green", "failed": "red", "running": "yellow"}

    for run_id, started_at, status, collected, processed, trends, new_src in runs:
        status_color = status_styles.get(status, "white")
        table.add_row(
            str(run_id),
            started_at.strftime("%d %b %H:%M UTC") if started_at else "N/A",
            f"[{status_color}]{status}[/{status_color}]",
            str(collected),
            str(processed),
            str(trends),
            str(new_src),
        )

    console.print(table)


def cmd_digest(args: argparse.Namespace) -> None:
    """Run the end-of-day Daily Digest Agent."""
    from src.agent.daily_digest_agent import DailyDigestAgent

    hours = getattr(args, "hours", 24)
    min_score = getattr(args, "min_score", 30)
    console.print(f"[bold blue]Running Daily Digest Agent (last {hours}h, min score {min_score})...[/bold blue]")

    agent = DailyDigestAgent(lookback_hours=hours, min_score=min_score)
    report_path = agent.run()

    if report_path:
        console.print(f"\n[bold green]✓ Daily digest saved:[/bold green]\n  {report_path}")
    else:
        console.print("\n[yellow]No articles found for the selected time window.[/yellow]")


def cmd_sources(_args: argparse.Namespace) -> None:
    """List all registered information sources."""
    from src.storage.database import init_db, get_session
    from src.storage.repository import SourceRepository

    init_db()
    with get_session() as session:
        raw = SourceRepository(session).get_all_active()
        # Snapshot data before session closes to avoid DetachedInstanceError
        sources = [
            (s.name, s.source_type, s.category, s.fetch_count, s.relevance_boost)
            for s in raw
        ]

    if not sources:
        console.print("[yellow]No sources registered yet. Run the agent first.[/yellow]")
        return

    table = Table(
        title=f"Registered Sources ({len(sources)} active)",
        box=box.ROUNDED,
        header_style="bold white on #0f3460",
    )
    table.add_column("Name", style="bold")
    table.add_column("Type", style="cyan")
    table.add_column("Category", style="yellow")
    table.add_column("Fetched", justify="right")
    table.add_column("Boost", justify="right")

    for name, source_type, category, fetch_count, relevance_boost in sources:
        table.add_row(
            name[:50],
            source_type,
            category,
            str(fetch_count),
            str(relevance_boost),
        )

    console.print(table)


# ── CLI Parser ────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qa-intelligence-agent",
        description="Autonomous QA Intelligence Agent – stay ahead of the curve in GenAI, testing, and dev tools.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run
    subparsers.add_parser("run", help="Execute one agent cycle and exit")

    # digest
    digest = subparsers.add_parser("digest", help="Run end-of-day digest and send report by email")
    digest.add_argument("--hours",     type=int,   default=24, help="Lookback window in hours (default: 24)")
    digest.add_argument("--min-score", type=float, default=30, help="Minimum relevance score (default: 30)")

    # schedule
    sched = subparsers.add_parser("schedule", help="Start recurring scheduler")
    sched.add_argument(
        "--interval", type=int, default=None,
        help="Override schedule interval in hours (default: SCHEDULE_INTERVAL_HOURS env var)"
    )

    # report
    subparsers.add_parser("report", help="Generate a report from existing DB data")

    # status
    subparsers.add_parser("status", help="Show recent agent run history")

    # sources
    subparsers.add_parser("sources", help="List all registered information sources")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "run":      cmd_run,
        "schedule": cmd_schedule,
        "report":   cmd_report,
        "digest":   cmd_digest,
        "status":   cmd_status,
        "sources":  cmd_sources,
    }

    handler = dispatch.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
