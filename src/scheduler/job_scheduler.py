"""
Job Scheduler – drives the agent's recurring execution using APScheduler.

The scheduler runs the CoreAgent on a fixed interval (default: every 6 hours).
It also supports one-shot execution for CLI/CI use.

APScheduler is used in blocking mode (main thread sleep) for simplicity
and reliability in container deployments.
"""

from __future__ import annotations

import logging
import signal
import sys
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from rich.console import Console

from src.agent.core_agent import CoreAgent
from src.config.settings import settings

logger = logging.getLogger(__name__)
console = Console()


def _run_agent_job() -> None:
    """
    APScheduler job function – instantiates and runs the agent.
    Catches all exceptions to prevent the scheduler from dying.
    """
    try:
        agent = CoreAgent()
        report_path = agent.run()
        if report_path:
            logger.info("Job completed. Report: %s", report_path)
        else:
            logger.info("Job completed. No report generated (not enough data yet).")
    except Exception as exc:
        logger.exception("Agent job raised an unhandled exception: %s", exc)


class AgentScheduler:
    """
    Wraps APScheduler to run the QA Intelligence Agent on a schedule.

    Args:
        interval_hours: How often to run the agent (in hours).
    """

    def __init__(self, interval_hours: Optional[int] = None) -> None:
        self._interval_hours = interval_hours or settings.schedule_interval_hours
        self._scheduler = BlockingScheduler(timezone="UTC")
        self._register_signal_handlers()

    def start(self) -> None:
        """
        Start the scheduler loop.
        Runs the agent immediately on startup, then every N hours.
        """
        trigger = IntervalTrigger(hours=self._interval_hours)
        self._scheduler.add_job(
            func=_run_agent_job,
            trigger=trigger,
            id="qa_intelligence_agent",
            name="QA Intelligence Agent",
            next_run_time=datetime.now(timezone.utc),  # Run immediately on startup
            max_instances=1,  # Prevent overlapping runs
            coalesce=True,    # Skip missed runs instead of queuing them
        )

        console.print(
            f"\n[bold green]QA Intelligence Agent scheduler started[/bold green]\n"
            f"  Interval: every [bold]{self._interval_hours}[/bold] hours\n"
            f"  Next run:  [bold]now[/bold]\n"
            f"  Press Ctrl+C to stop\n"
        )
        logger.info(
            "Scheduler started. Agent will run every %d hours.", self._interval_hours
        )

        self._scheduler.start()

    def _register_signal_handlers(self) -> None:
        """Gracefully shut down the scheduler on SIGINT/SIGTERM."""
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._shutdown)

    def _shutdown(self, signum, frame) -> None:
        logger.info("Received signal %d – shutting down scheduler", signum)
        console.print("\n[yellow]Shutting down QA Intelligence Agent...[/yellow]")
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        sys.exit(0)
