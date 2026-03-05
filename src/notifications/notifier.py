"""
Notifier – sends the full QA Intelligence Report via configured channels:
  - Email  : full HTML report embedded in email body + HTML file attached
  - Slack  : summary + alert trends via Bot API
  - Console: rich formatted summary (always active)

Channels activate automatically when settings are present.
All failures are caught and logged – never crash the agent.

Gmail setup:
  1. Enable 2-Step Verification on your Google account
  2. Go to: https://myaccount.google.com/apppasswords
  3. Create an App Password (select "Mail" + your device)
  4. Use that 16-char password as SMTP_PASSWORD (not your regular password)
"""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.config.settings import settings
from src.storage.models import Trend

logger = logging.getLogger(__name__)
console = Console()

_CATEGORY_ICONS = {
    "genai": "🤖",
    "agents": "🕵️",
    "qa_testing": "🧪",
    "devops": "⚙️",
    "tools": "🛠️",
    "project_management": "📋",
}


class Notifier:
    """
    Multi-channel notification dispatcher.

    Activated channels (auto-detected from settings):
      - Email : SMTP_USER + SMTP_PASSWORD + NOTIFY_EMAIL all set
      - Slack : SLACK_BOT_TOKEN set
    """

    def send_digest(
        self,
        digest_articles: list,
        stats,
        alert_trends: list[Trend],
        report_path: Optional[Path] = None,
    ) -> None:
        """
        Send the daily digest report via all configured channels.

        Args:
            digest_articles: List of DigestArticle objects.
            stats:           DigestStats summary object.
            alert_trends:    Alert-level trends.
            report_path:     Path to the generated HTML digest file.
        """
        self._console_digest_output(stats, alert_trends, report_path)

        if settings.smtp_user and settings.smtp_password and settings.notify_email:
            self._send_digest_email(digest_articles, stats, alert_trends, report_path)
        else:
            logger.info("Email not configured – digest email skipped")

    def _console_digest_output(self, stats, alert_trends, report_path) -> None:
        """Print digest summary to terminal."""
        from rich.table import Table
        table = Table(title=f"📋 Daily Digest – {stats.date_str}", box=box.ROUNDED,
                      header_style="bold white on #0f3460")
        table.add_column("Metric"); table.add_column("Value", justify="right", style="bold")
        table.add_row("Articles collected", str(stats.total_articles))
        table.add_row("Average score", str(stats.avg_relevance))
        table.add_row("Alert trends", str(stats.alert_count))
        table.add_row("Categories", str(len(stats.category_counts)))
        console.print(table)
        if report_path:
            console.print(Panel(f"[bold blue]Digest saved:[/bold blue] {report_path}",
                                border_style="blue"))

    def _send_digest_email(self, digest_articles, stats, alert_trends, report_path) -> None:
        """Send the full digest as an HTML email with report attached."""
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%d %b %Y")
        subject = f"📋 [{date_str}] QA Daily Digest – {stats.total_articles} articles | {stats.alert_count} alerts"

        report_html = ""
        report_filename = ""
        if report_path and report_path.exists():
            report_html = report_path.read_text(encoding="utf-8")
            report_filename = report_path.name

        # Build compact summary table for email body
        table_rows = ""
        for i, a in enumerate(digest_articles[:50], 1):
            kws = ", ".join(a.keywords[:3])
            score_color = "#059669" if a.relevance_score >= 70 else "#d97706" if a.relevance_score >= 50 else "#9ca3af"
            table_rows += f"""
            <tr style="border-bottom:1px solid #f3f4f6;">
              <td style="padding:8px 10px;color:#9ca3af;font-size:0.82em;">{i}</td>
              <td style="padding:8px 10px;">
                <a href="{a.url}" style="color:#0f3460;font-weight:600;text-decoration:none;font-size:0.88em;">{a.title[:65]}</a>
              </td>
              <td style="padding:8px 10px;font-size:0.78em;color:#6b7280;">{a.category}</td>
              <td style="padding:8px 10px;font-size:0.78em;color:#374151;">{kws}</td>
              <td style="padding:8px 10px;font-size:0.76em;color:#9ca3af;white-space:nowrap;">{a.published_date}</td>
              <td style="padding:8px 10px;font-size:0.76em;color:#9ca3af;white-space:nowrap;">{a.collected_date}</td>
              <td style="padding:8px 10px;text-align:center;font-weight:700;color:{score_color};font-size:0.88em;">{a.relevance_score}</td>
            </tr>"""

        alert_block = ""
        if alert_trends:
            items = "".join(
                f"<li style='margin:6px 0;'><strong style='color:#e94560;'>{t.name}</strong> "
                f"<span style='color:#6b7280;font-size:0.85em;'>({t.category}) momentum: {t.momentum_score:.1f}</span></li>"
                for t in alert_trends
            )
            alert_block = f"""
            <div style="background:#fff8f8;border-left:4px solid #e94560;border-radius:6px;padding:14px 18px;margin:20px 0;">
              <strong style="color:#e94560;">🚨 Alert Trends</strong>
              <ul style="margin:8px 0 0 16px;">{items}</ul>
            </div>"""

        kw_str = " ".join(
            f'<span style="background:#ede9fe;color:#5b21b6;border-radius:9px;padding:2px 8px;margin:2px;font-size:0.8em;">{kw}</span>'
            for kw, _ in stats.top_keywords[:15]
        )

        email_body = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"></head>
<body style="font-family:system-ui,sans-serif;background:#f5f7fa;margin:0;padding:0;">
  <div style="background:linear-gradient(135deg,#0f3460 0%,#1a237e 100%);color:white;padding:28px 32px;">
    <h1 style="margin:0;font-size:1.5rem;">📋 Daily Digest – {date_str}</h1>
    <p style="margin:6px 0 0;opacity:0.75;font-size:0.88rem;">
      {stats.total_articles} articles &nbsp;|&nbsp; avg score: {stats.avg_relevance} &nbsp;|&nbsp; {stats.alert_count} alerts
    </p>
  </div>
  <div style="max-width:960px;margin:0 auto;padding:24px 20px;">
    {alert_block}
    <div style="margin:20px 0;">
      <strong style="color:#0f3460;">🔤 Top Keywords:</strong><br><br>{kw_str}
    </div>
    <h2 style="color:#0f3460;border-bottom:3px solid #e94560;padding-bottom:8px;">📊 Article Summary Table</h2>
    <div style="overflow-x:auto;border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,0.08);">
      <table style="width:100%;border-collapse:collapse;background:white;">
        <thead>
          <tr style="background:#0f3460;color:white;">
            <th style="padding:10px;font-size:0.78em;">#</th>
            <th style="padding:10px;text-align:left;font-size:0.78em;">Title</th>
            <th style="padding:10px;text-align:left;font-size:0.78em;">Category</th>
            <th style="padding:10px;text-align:left;font-size:0.78em;">Keywords</th>
            <th style="padding:10px;font-size:0.78em;">Published</th>
            <th style="padding:10px;font-size:0.78em;">Collected</th>
            <th style="padding:10px;font-size:0.78em;">Score</th>
          </tr>
        </thead>
        <tbody>{table_rows}</tbody>
      </table>
    </div>
    <p style="margin-top:16px;color:#9ca3af;font-size:0.8em;">
      📎 Full interactive report attached as HTML file.
    </p>
  </div>
  <div style="text-align:center;padding:16px;color:#9ca3af;font-size:0.75em;border-top:1px solid #e5e7eb;">
    QA Intelligence Agent – Daily Digest – {date_str}
  </div>
</body></html>"""

        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = f"QA Intelligence Agent <{settings.smtp_user}>"
        msg["To"] = settings.notify_email
        msg.attach(MIMEText(email_body, "html", "utf-8"))

        if report_html and report_filename:
            attachment = MIMEBase("text", "html")
            attachment.set_payload(report_html.encode("utf-8"))
            encoders.encode_base64(attachment)
            attachment.add_header("Content-Disposition", "attachment", filename=report_filename)
            msg.attach(attachment)

        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                server.ehlo(); server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(settings.smtp_user, settings.notify_email, msg.as_string())
            logger.info("Daily digest email sent to %s", settings.notify_email)
        except smtplib.SMTPAuthenticationError:
            logger.error("Email auth failed. Use Gmail App Password: https://myaccount.google.com/apppasswords")
        except Exception as exc:
            logger.error("Failed to send digest email: %s", exc)

    def send(
        self,
        alert_trends: list[Trend],
        report_path: Optional[Path] = None,
    ) -> None:
        """
        Dispatch notifications to all configured channels.

        Args:
            alert_trends: High-momentum trends requiring immediate attention.
            report_path:  Path to the generated HTML report file.
        """
        self._console_output(alert_trends, report_path)

        if settings.smtp_user and settings.smtp_password and settings.notify_email:
            self._send_email(alert_trends, report_path)
        else:
            logger.info(
                "Email not configured – set SMTP_USER, SMTP_PASSWORD, NOTIFY_EMAIL to enable"
            )

        if settings.slack_bot_token:
            self._send_slack(alert_trends, report_path)

    # ── Console ───────────────────────────────────────────────────────────────

    @staticmethod
    def _console_output(alert_trends: list[Trend], report_path: Optional[Path]) -> None:
        """Print a rich-formatted summary to the terminal."""
        console.print()

        if alert_trends:
            table = Table(
                title="🚨 ALERTS – Immediate Attention Required",
                box=box.ROUNDED,
                style="bold red",
                header_style="bold white on red",
            )
            table.add_column("Trend", style="bold white")
            table.add_column("Category", style="cyan")
            table.add_column("Momentum", style="yellow", justify="right")
            table.add_column("Articles", justify="right")
            for trend in alert_trends:
                table.add_row(
                    trend.name,
                    trend.category,
                    f"{trend.momentum_score:.1f}",
                    str(trend.article_count),
                )
            console.print(table)
        else:
            console.print(Panel(
                "[green]✓ No critical alerts this cycle[/green]",
                title="Alert Status",
                border_style="green",
            ))

        if report_path:
            console.print(Panel(
                f"[bold blue]Report:[/bold blue] {report_path}",
                title="📄 Report Generated",
                border_style="blue",
            ))
        console.print()

    # ── Email ─────────────────────────────────────────────────────────────────

    def _send_email(
        self,
        alert_trends: list[Trend],
        report_path: Optional[Path],
    ) -> None:
        """
        Build and send a rich HTML email that contains:
          - Executive summary banner
          - Alert trends section (if any)
          - Full embedded HTML report (inline in email body)
          - HTML report attached as a .html file
        """
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%d %b %Y")
        subject = self._build_subject(alert_trends, date_str)

        # Read the HTML report content
        report_html = ""
        report_filename = ""
        if report_path and report_path.exists():
            report_html = report_path.read_text(encoding="utf-8")
            report_filename = report_path.name

        # Build the email wrapper (summary + embedded report)
        email_body = self._build_email_html(
            alert_trends=alert_trends,
            report_html=report_html,
            date_str=date_str,
        )

        # Assemble multipart email: body + attachment
        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = f"QA Intelligence Agent <{settings.smtp_user}>"
        msg["To"] = settings.notify_email

        # Part 1: HTML body
        msg.attach(MIMEText(email_body, "html", "utf-8"))

        # Part 2: HTML file attachment (so the user can open it locally)
        if report_html and report_filename:
            attachment = MIMEBase("text", "html")
            attachment.set_payload(report_html.encode("utf-8"))
            encoders.encode_base64(attachment)
            attachment.add_header(
                "Content-Disposition",
                "attachment",
                filename=report_filename,
            )
            msg.attach(attachment)

        # Send
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(
                    settings.smtp_user,
                    settings.notify_email,
                    msg.as_string(),
                )
            logger.info(
                "Email report sent to %s (subject: %s)",
                settings.notify_email,
                subject,
            )
        except smtplib.SMTPAuthenticationError:
            logger.error(
                "Email authentication failed. "
                "For Gmail, use an App Password: https://myaccount.google.com/apppasswords"
            )
        except Exception as exc:
            logger.error("Failed to send email: %s", exc)

    @staticmethod
    def _build_subject(alert_trends: list[Trend], date_str: str) -> str:
        if alert_trends:
            return f"🚨 [{date_str}] QA Intelligence – {len(alert_trends)} alerts require attention"
        return f"📊 [{date_str}] QA Intelligence Report – New update ready"

    @staticmethod
    def _build_email_html(
        alert_trends: list[Trend],
        report_html: str,
        date_str: str,
    ) -> str:
        """
        Build the complete email HTML:
          header banner → alert section → full report embedded inline.
        """
        # ── Alert section ──────────────────────────────────────────────────
        if alert_trends:
            alert_items = "".join(
                f"""
                <div style="background:#fff8f8;border-left:4px solid #e94560;
                            border-radius:6px;padding:12px 16px;margin:8px 0;">
                  <strong style="color:#e94560;">
                    {_CATEGORY_ICONS.get(t.category, "📌")} {t.name}
                  </strong>
                  <span style="background:#fde68a;color:#92400e;border-radius:9px;
                               padding:2px 8px;font-size:0.75em;margin-left:8px;">ALERT</span>
                  <p style="margin:6px 0 0;color:#374151;font-size:0.9em;">
                    {t.description or ""}
                  </p>
                  <p style="margin:4px 0 0;color:#6b7280;font-size:0.8em;">
                    Momentum: <strong>{t.momentum_score:.1f}</strong> &nbsp;|&nbsp;
                    Articles: <strong>{t.article_count}</strong> &nbsp;|&nbsp;
                    Category: {t.category}
                  </p>
                </div>"""
                for t in alert_trends
            )
            alert_block = f"""
            <div style="margin:24px 0;">
              <h2 style="color:#e94560;margin-bottom:12px;">🚨 Immediate Attention Required</h2>
              {alert_items}
            </div>"""
        else:
            alert_block = """
            <div style="background:#f0fdf4;border:1px solid #86efac;border-radius:8px;
                        padding:12px 16px;margin:24px 0;">
              ✅ <strong style="color:#166534;">No critical alerts this cycle</strong>
            </div>"""

        # ── Divider before embedded report ────────────────────────────────
        report_section = ""
        if report_html:
            report_section = f"""
            <hr style="border:none;border-top:2px solid #e0e6ed;margin:32px 0;">
            <p style="color:#6b7280;font-size:0.85em;margin-bottom:16px;">
              📎 The full report is also attached as an HTML file.
              Open the attachment in your browser for the best experience.
            </p>
            <!-- ═══ EMBEDDED FULL REPORT ═══ -->
            {report_html}"""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>QA Intelligence Report – {date_str}</title>
</head>
<body style="margin:0;padding:0;background:#f5f7fa;font-family:system-ui,sans-serif;">

  <!-- Header banner -->
  <div style="background:linear-gradient(135deg,#0f3460 0%,#1a237e 100%);
              color:white;padding:28px 32px;">
    <h1 style="margin:0;font-size:1.6rem;font-weight:700;">🧪 QA Intelligence Report</h1>
    <p style="margin:6px 0 0;opacity:0.75;font-size:0.9rem;">
      {date_str} &nbsp;|&nbsp; Powered by OpenAI {settings.openai_model}
    </p>
  </div>

  <!-- Body -->
  <div style="max-width:960px;margin:0 auto;padding:24px;">
    {alert_block}
    {report_section}
  </div>

  <!-- Footer -->
  <div style="text-align:center;padding:20px;color:#9ca3af;font-size:0.75em;
              border-top:1px solid #e5e7eb;margin-top:32px;">
    QA Intelligence Agent &nbsp;|&nbsp; Auto-generated &nbsp;|&nbsp; {date_str}
  </div>

</body>
</html>"""

    # ── Slack ─────────────────────────────────────────────────────────────────

    def _send_slack(
        self,
        alert_trends: list[Trend],
        report_path: Optional[Path],
    ) -> None:
        """Post a Slack notification with alert summary."""
        try:
            from slack_sdk import WebClient
        except ImportError:
            logger.warning("slack_sdk not installed – Slack notifications disabled")
            return

        client = WebClient(token=settings.slack_bot_token)
        blocks = self._build_slack_blocks(alert_trends, report_path)

        try:
            client.chat_postMessage(
                channel=settings.slack_channel,
                blocks=blocks,
                text="QA Intelligence Report",
            )
            logger.info("Slack notification sent to %s", settings.slack_channel)
        except Exception as exc:
            logger.error("Failed to send Slack notification: %s", exc)

    @staticmethod
    def _build_slack_blocks(alert_trends: list[Trend], report_path: Optional[Path]) -> list[dict]:
        """Build Slack Block Kit payload."""
        now = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
        blocks: list[dict] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "🧪 QA Intelligence Report", "emoji": True},
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"Generated: {now}"}],
            },
        ]

        if alert_trends:
            alert_text = "\n".join(
                f"• *{_CATEGORY_ICONS.get(t.category, '')} {t.name}* "
                f"({t.category}) — momentum: `{t.momentum_score:.1f}` | articles: `{t.article_count}`"
                for t in alert_trends
            )
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"🚨 *Alert Trends – Immediate Attention:*\n{alert_text}"},
            })
        else:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "✅ *No critical alerts this cycle*"},
            })

        if report_path:
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"📄 *Report file:* `{report_path.name}`"},
            })

        return blocks
