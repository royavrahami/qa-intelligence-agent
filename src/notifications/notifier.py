"""
Notifier – Quality Managers in AI World Intelligence Agent.
Sends the Intelligence Report via configured channels:
  - Email  : full, professional HTML newsletter rendered directly in the email body
  - Slack  : summary + alert trends via Bot API
  - Console: rich formatted summary (always active)

Email design:
  - Table-based layout (compatible with Gmail, Outlook, Apple Mail)
  - Inline styles only — no CSS variables, no JS, no attachments
  - Shows full report content: stats, alerts, top articles with Quality Management insights,
    category breakdown, and trend landscape

Gmail App Password setup:
  1. Enable 2-Step Verification: https://myaccount.google.com/security
  2. Create App Password: https://myaccount.google.com/apppasswords
  3. Use the 16-char password as SMTP_PASSWORD in .env
"""

from __future__ import annotations

import json
import logging
import smtplib
from collections import defaultdict
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
from src.storage.models import Article, Trend

logger = logging.getLogger(__name__)
console = Console()

# Category display metadata for Quality Management Intelligence
_CATEGORY_META: dict[str, dict[str, str]] = {
    "genai":              {"label": "GenAI & LLMs",           "icon": "🤖", "color": "#155e75", "bg": "#cffafe"},
    "agents":             {"label": "AI Agents & Automation", "icon": "🕵️", "color": "#4a1d96", "bg": "#f3e8ff"},
    "qa_testing":         {"label": "Quality Engineering",    "icon": "🧪", "color": "#065f46", "bg": "#d1fae5"},
    "devops":             {"label": "DevOps & CI/CD",         "icon": "⚙️", "color": "#92400e", "bg": "#fef3c7"},
    "tools":              {"label": "Developer Tools",        "icon": "🛠️", "color": "#1d4ed8", "bg": "#dbeafe"},
    "project_management": {"label": "Project Management",     "icon": "📋", "color": "#9f1239", "bg": "#ffe4e6"},
    "general":            {"label": "Industry News",          "icon": "📰", "color": "#374151", "bg": "#f3f4f6"},
}


def _score_color(score: float) -> str:
    if score >= 75:
        return "#059669"
    if score >= 55:
        return "#d97706"
    return "#6b7280"


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
        subject = f"📋 [{date_str}] Quality Managers in AI World – Daily Digest | {stats.total_articles} articles"

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

        email_body = f"""<!DOCTYPE html><html lang="en" dir="ltr"><head><meta charset="UTF-8"></head>
<body dir="ltr" style="font-family:system-ui,sans-serif;background:#f5f7fa;margin:0;padding:0;direction:ltr;text-align:left;">
  <div style="background:linear-gradient(135deg,#0f3460 0%,#1a237e 100%);color:white;padding:28px 32px;text-align:left;">
    <h1 style="margin:0;font-size:1.5rem;text-align:left;">🎯 Quality Managers in AI World</h1>
    <p style="margin:6px 0 0;opacity:0.75;font-size:0.88rem;text-align:left;">
      Daily Intelligence Digest &nbsp;|&nbsp; {date_str} &nbsp;|&nbsp; {stats.total_articles} articles
    </p>
  </div>
  <div style="max-width:960px;margin:0 auto;padding:24px 20px;text-align:left;">
    {alert_block}
    <div style="margin:20px 0;text-align:left;">
      <strong style="color:#0f3460;">🔤 Top Keywords:</strong><br><br>{kw_str}
    </div>
    <h2 style="color:#0f3460;border-bottom:3px solid #e94560;padding-bottom:8px;text-align:left;">📊 Article Summary Table</h2>
    <div style="overflow-x:auto;border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,0.08);">
      <table dir="ltr" style="width:100%;border-collapse:collapse;background:white;direction:ltr;text-align:left;">
        <thead>
          <tr style="background:#0f3460;color:white;">
            <th style="padding:10px;font-size:0.78em;text-align:center;">#</th>
            <th style="padding:10px;text-align:left;font-size:0.78em;">Title</th>
            <th style="padding:10px;text-align:left;font-size:0.78em;">Category</th>
            <th style="padding:10px;text-align:left;font-size:0.78em;">Keywords</th>
            <th style="padding:10px;font-size:0.78em;text-align:center;">Published</th>
            <th style="padding:10px;font-size:0.78em;text-align:center;">Collected</th>
            <th style="padding:10px;font-size:0.78em;text-align:center;">Score</th>
          </tr>
        </thead>
        <tbody>{table_rows}</tbody>
      </table>
    </div>
    <p style="margin-top:16px;color:#9ca3af;font-size:0.8em;text-align:left;">
      📎 Full interactive report attached as HTML file.
    </p>
  </div>
  <div style="text-align:center;padding:16px;color:#9ca3af;font-size:0.75em;border-top:1px solid #e5e7eb;">
    Quality Managers in AI World – Intelligence Agent – {date_str}
  </div>
</body></html>"""

        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = f"Quality Managers in AI World <{settings.smtp_user}>"
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
        all_trends: Optional[list[Trend]] = None,
        articles: Optional[list] = None,
        report_path: Optional[Path] = None,
    ) -> None:
        """
        Dispatch notifications to all configured channels.

        Args:
            alert_trends: High-momentum trends requiring immediate attention.
            all_trends:   All detected trends for the full trend landscape section.
            articles:     Scored articles to display in the email body.
            report_path:  Path to the generated HTML report file.
        """
        self._console_output(alert_trends, report_path)

        if settings.smtp_user and settings.smtp_password and settings.notify_email:
            self._send_email(
                alert_trends=alert_trends,
                all_trends=all_trends or [],
                articles=articles or [],
                report_path=report_path,
            )
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
        all_trends: list[Trend],
        articles: list[Article],
        report_path: Optional[Path] = None,
    ) -> None:
        """
        Build and send the full Quality Managers in AI World Intelligence Report as a professional HTML email.
        The full HTML report is attached so the user can open it in a browser.
        """
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%d %b %Y")
        subject = self._build_subject(alert_trends, date_str)

        email_body = self._build_professional_email(
            alert_trends=alert_trends,
            all_trends=all_trends,
            articles=articles,
            date_str=date_str,
        )

        # Use "mixed" so we can attach the HTML report file alongside the inline body
        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = f"Quality Managers in AI World <{settings.smtp_user}>"
        msg["To"] = settings.notify_email

        # Wrap the HTML body in an "alternative" part so email clients render it correctly
        alt_part = MIMEMultipart("alternative")
        alt_part.attach(MIMEText(email_body, "html", "utf-8"))
        msg.attach(alt_part)

        # Attach the full HTML report file
        if report_path and report_path.exists():
            report_html = report_path.read_text(encoding="utf-8")
            attachment = MIMEBase("text", "html")
            attachment.set_payload(report_html.encode("utf-8"))
            encoders.encode_base64(attachment)
            attachment.add_header(
                "Content-Disposition", "attachment", filename=report_path.name
            )
            msg.attach(attachment)
            logger.info("Attached full report: %s", report_path.name)

        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(settings.smtp_user, settings.notify_email, msg.as_string())
            logger.info("Intelligence report email sent to %s (subject: %s)", settings.notify_email, subject)
        except smtplib.SMTPAuthenticationError:
            logger.error(
                "Email auth failed. Use Gmail App Password: "
                "https://myaccount.google.com/apppasswords"
            )
        except Exception as exc:
            logger.error("Failed to send intelligence report email: %s", exc)

    @staticmethod
    def _build_subject(alert_trends: list[Trend], date_str: str) -> str:
        if alert_trends:
            return f"🚨 [{date_str}] Quality Managers in AI World – {len(alert_trends)} Critical Insight{'s' if len(alert_trends) != 1 else ''}"
        return f"🎯 [{date_str}] Quality Managers in AI World – Intelligence Report Ready"

    @staticmethod
    def _build_professional_email(
        alert_trends: list[Trend],
        all_trends: list[Trend],
        articles: list[Article],
        date_str: str,
    ) -> str:
        """
        Render the full professional Quality Managers in AI World Intelligence email.
        Table-based layout with inline styles – 100% compatible with all email clients.
        
        UI/UX optimizations:
        - Limited to top 5 articles (prevents email bloat)
        - Max 5 critical insights (reduces alert fatigue)
        - Compact article cards for better readability
        - CTA button for full report access
        """
        # Limit to top 5 articles for email (full list in web report)
        top_articles = sorted(articles, key=lambda a: a.relevance_score, reverse=True)[:5]
        
        # Limit critical insights to max 5 to prevent alert fatigue
        display_alerts = alert_trends[:5] if alert_trends else []
        extra_alerts = len(alert_trends) - 5 if len(alert_trends) > 5 else 0

        categorised: dict[str, list] = defaultdict(list)
        for a in articles:
            categorised[a.category or "general"].append(a)
        for cat in categorised:
            categorised[cat].sort(key=lambda a: a.relevance_score, reverse=True)

        sorted_trends = sorted(all_trends, key=lambda t: t.momentum_score, reverse=True)[:7]

        # ── Stats bar ─────────────────────────────────────────────────────────
        stats_cells = [
            (str(len(articles)),      "Articles"),
            (str(len(all_trends)),    "Trends"),
            (str(len(alert_trends)),  "Insights"),
            (str(len(categorised)),   "Categories"),
        ]
        stats_html = "".join(f"""
          <td align="center" style="padding:0 16px;">
            <div style="font-size:32px;font-weight:800;color:#ffffff;line-height:1;">{num}</div>
            <div style="font-size:11px;color:rgba(255,255,255,0.70);text-transform:uppercase;
                        letter-spacing:1px;margin-top:6px;">{lbl}</div>
          </td>""" for num, lbl in stats_cells)

        # ── Alerts section (limited to 5 max) ────────────────────────────────
        if display_alerts:
            alert_rows = ""
            for t in display_alerts:
                meta = _CATEGORY_META.get(t.category or "general", _CATEGORY_META["general"])
                desc_row = (
                    f'<tr><td style="padding:0 0 8px;">'
                    f'<span style="color:#374151;font-size:13px;">{t.description}</span>'
                    f'</td></tr>'
                ) if t.description else ""
                alert_rows += f"""
          <tr><td style="padding:0 0 10px;">
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#fff8f8;border:1px solid #fecaca;
                          border-left:5px solid #e94560;border-radius:8px;">
              <tr><td style="padding:16px 18px;">
                <span style="font-size:16px;font-weight:700;color:#1a1a2e;">
                  {meta['icon']} {t.name}
                </span>
                &nbsp;
                <span style="background:#fde68a;color:#92400e;border-radius:4px;
                             padding:2px 8px;font-size:11px;font-weight:700;">🔥 ALERT</span>
                {desc_row}
                <div style="margin-top:8px;">
                  <span style="background:#d1fae5;color:#065f46;border-radius:4px;
                               padding:3px 9px;font-size:11px;font-weight:600;">
                    📈 {t.momentum_score:.1f}
                  </span>
                  &nbsp;
                  <span style="background:#dbeafe;color:#1d4ed8;border-radius:4px;
                               padding:3px 9px;font-size:11px;font-weight:600;">
                    📰 {t.article_count} articles
                  </span>
                </div>
              </td></tr>
            </table>
          </td></tr>"""

            extra_note = f'<span style="font-size:12px;color:#78350f;margin-left:8px;">(+{extra_alerts} more in full report)</span>' if extra_alerts > 0 else ""
            alerts_section = f"""
        <tr><td style="padding:24px 36px 8px;">
          <table width="100%" cellpadding="0" cellspacing="0"
                 style="background:#fff3cd;border:1px solid #fbbf24;border-radius:8px;">
            <tr><td style="padding:12px 18px;">
              <span style="font-size:14px;font-weight:700;color:#92400e;">
                🚨 {len(alert_trends)} Critical Insight{'s' if len(alert_trends) != 1 else ''} – Action Recommended
              </span>
              {extra_note}
            </td></tr>
          </table>
        </td></tr>
        <tr><td style="padding:0 36px 8px;">
          <table width="100%" cellpadding="0" cellspacing="0">{alert_rows}</table>
        </td></tr>"""
        else:
            alerts_section = """
        <tr><td style="padding:24px 36px 12px;">
          <table width="100%" cellpadding="0" cellspacing="0"
                 style="background:#f0fdf4;border:1px solid #86efac;border-radius:8px;">
            <tr><td style="padding:14px 20px;">
              <table cellpadding="0" cellspacing="0"><tr>
                <td style="width:36px;vertical-align:middle;"><span style="font-size:22px;">✅</span></td>
                <td style="vertical-align:middle;padding-left:10px;">
                  <div style="font-size:14px;font-weight:700;color:#166534;">
                    All clear — no critical insights this cycle
                  </div>
                  <div style="font-size:12px;color:#166534;opacity:0.8;margin-top:3px;">
                    All monitored trends are within normal thresholds
                  </div>
                </td>
              </tr></table>
            </td></tr>
          </table>
        </td></tr>"""

        # ── Top 5 articles with full detail structure ───────────────────────────
        remaining_articles = len(articles) - 5 if len(articles) > 5 else 0
        top_rows = ""
        for i, article in enumerate(top_articles, 1):
            meta = _CATEGORY_META.get(article.category or "general", _CATEGORY_META["general"])
            sc = _score_color(article.relevance_score)
            stars = max(1, min(5, round(article.relevance_score / 20)))
            filled_stars = '<span style="color:#fbbf24;font-size:13px;">★</span>' * stars
            empty_stars  = '<span style="color:#e5e7eb;font-size:13px;">★</span>' * (5 - stars)
            star_html = filled_stars + empty_stars
            pub = f" &nbsp;·&nbsp; {article.published_at.strftime('%d %b %Y')}" if article.published_at else ""

            # ── Summary ────────────────────────────────────────────────────────
            summary_row = ""
            if article.summary:
                summary_row = f'''<tr><td style="padding:12px 0 0;">
                  <div style="background:#f8fafc;border-left:4px solid #0f3460;border-radius:0 8px 8px 0;padding:14px 18px;">
                    <div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;font-weight:600;">Summary</div>
                    <div style="font-size:13px;color:#374151;line-height:1.65;">{article.summary[:400]}{"…" if len(article.summary or "") > 400 else ""}</div>
                  </div>
                </td></tr>'''
            elif article.raw_content:
                snippet = article.raw_content[:200].replace('\n', ' ').strip()
                summary_row = f'''<tr><td style="padding:12px 0 0;">
                  <div style="background:#f9fafb;border-left:3px solid #9ca3af;border-radius:0 8px 8px 0;padding:12px 16px;">
                    <div style="font-size:12px;color:#6b7280;line-height:1.5;font-style:italic;">{snippet}{"…" if len(article.raw_content or "") > 200 else ""}</div>
                  </div>
                </td></tr>'''

            # ── Key Insights ───────────────────────────────────────────────────
            insights_row = ""
            insights = []
            if article.key_insights:
                try:
                    insights = json.loads(article.key_insights)
                except Exception:
                    pass
            if insights:
                items_html = "".join(
                    f'<tr><td style="padding:4px 0;"><span style="font-size:13px;color:#1e40af;">▸ {ins}</span></td></tr>'
                    for ins in insights[:3]
                )
                insights_row = f'''<tr><td style="padding:8px 0 0;">
                  <table width="100%" cellpadding="0" cellspacing="0"
                         style="background:#eff6ff;border-left:4px solid #3b82f6;border-radius:0 8px 8px 0;">
                    <tr><td style="padding:10px 14px;">
                      <div style="font-size:11px;color:#1d4ed8;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;font-weight:600;">Key Insights</div>
                      <table width="100%" cellpadding="0" cellspacing="0">{items_html}</table>
                    </td></tr>
                  </table>
                </td></tr>'''

            # ── Why This Matters ───────────────────────────────────────────────
            relevance_row = ""
            if hasattr(article, "qa_relevance") and article.qa_relevance:
                relevance_row = f'''<tr><td style="padding:8px 0 0;">
                  <table width="100%" cellpadding="0" cellspacing="0"
                         style="background:#f0fdf4;border:1px solid #86efac;border-radius:8px;">
                    <tr><td style="padding:12px 16px;">
                      <div style="font-size:11px;color:#166534;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;font-weight:600;">💼 Why This Matters for Quality Managers</div>
                      <div style="font-size:13px;color:#166534;line-height:1.55;">{article.qa_relevance[:400]}{"…" if len(article.qa_relevance or "") > 400 else ""}</div>
                    </td></tr>
                  </table>
                </td></tr>'''

            divider = '<tr><td style="padding:16px 0;"><div style="height:1px;background:linear-gradient(90deg,transparent,#e5e7eb,transparent);"></div></td></tr>' if i < len(top_articles) else ""

            top_rows += f"""
          <tr><td style="padding:8px 0;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;">
              <tr><td style="padding:20px 24px;">
                <table width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td style="width:36px;vertical-align:top;">
                      <div style="background:linear-gradient(135deg,#0f3460,#1a237e);color:#fff;width:32px;height:32px;
                                  border-radius:50%;text-align:center;line-height:32px;font-size:13px;font-weight:700;">{i}</div>
                    </td>
                    <td style="padding-left:12px;vertical-align:top;">
                      <a href="{article.url}" target="_blank" rel="noopener"
                         style="font-size:16px;font-weight:700;color:#0f3460;text-decoration:none;line-height:1.4;display:block;">
                        {article.title or "(No title)"}
                      </a>
                      <div style="margin-top:8px;">
                        <span style="background:{meta['bg']};color:{meta['color']};border-radius:6px;
                                     padding:4px 12px;font-size:12px;font-weight:600;display:inline-block;">
                          {meta['icon']} {meta['label']}
                        </span>
                        <span style="font-size:12px;color:#9ca3af;margin-left:8px;">{pub}</span>
                      </div>
                    </td>
                    <td align="right" style="width:72px;vertical-align:top;padding-left:12px;">
                      <div style="border:2px solid {sc};border-radius:8px;padding:6px 10px;text-align:center;white-space:nowrap;">
                        <div style="font-size:20px;font-weight:800;color:{sc};line-height:1;">{article.relevance_score:.0f}</div>
                        <div style="margin-top:3px;">{star_html}</div>
                      </div>
                    </td>
                  </tr>
                </table>
                <table width="100%" cellpadding="0" cellspacing="0">
                  {summary_row}{insights_row}{relevance_row}
                </table>
              </td></tr>
            </table>
          </td></tr>
          {divider}"""

        # ── Category badges (clickable, anchor-link to sections below) ─────────
        cat_badges = ""
        cat_sections = ""
        for cat, cat_articles in categorised.items():
            meta = _CATEGORY_META.get(cat, _CATEGORY_META["general"])
            cat_id = f"cat-{cat.replace('_', '-')}"
            cat_badges += (
                f'<a href="#{cat_id}" style="display:inline-block;background:{meta["bg"]};'
                f'color:{meta["color"]};border-radius:16px;padding:6px 14px;font-size:12px;'
                f'font-weight:600;margin:4px 6px 4px 0;text-decoration:none;">'
                f'{meta["icon"]} {meta["label"]} ({len(cat_articles)})</a>'
            )
            # Build compact article list for this category
            article_links = ""
            for a in cat_articles[:5]:
                sc = _score_color(a.relevance_score)
                pub = f'<span style="font-size:10px;color:#9ca3af;margin-left:6px;">{a.published_at.strftime("%d %b")}</span>' if a.published_at else ""
                article_links += f"""
                <tr><td style="padding:8px 0;border-bottom:1px solid #f3f4f6;">
                  <table width="100%" cellpadding="0" cellspacing="0"><tr>
                    <td>
                      <a href="{a.url}" target="_blank" rel="noopener"
                         style="font-size:13px;font-weight:600;color:#0f3460;text-decoration:none;line-height:1.4;">
                        {a.title or "(No title)"}
                      </a>
                      {pub}
                    </td>
                    <td align="right" style="width:36px;padding-left:8px;vertical-align:top;">
                      <span style="background:{sc};color:#fff;border-radius:4px;padding:1px 6px;font-size:11px;font-weight:700;">{a.relevance_score:.0f}</span>
                    </td>
                  </tr></table>
                </td></tr>"""
            more_note = f'<tr><td style="padding:8px 0;"><span style="font-size:11px;color:#9ca3af;font-style:italic;">+{len(cat_articles)-5} more — see attached HTML report</span></td></tr>' if len(cat_articles) > 5 else ""
            cat_sections += f"""
          <tr><td id="{cat_id}" style="padding:0 0 20px;">
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;">
              <tr><td style="background:{meta['bg']};padding:10px 18px;border-bottom:1px solid #e5e7eb;">
                <span style="font-size:14px;font-weight:700;color:{meta['color']};">{meta['icon']} {meta['label']}</span>
                <span style="font-size:11px;color:#6b7280;margin-left:8px;background:#fff;padding:1px 8px;border-radius:10px;">{len(cat_articles)} articles</span>
              </td></tr>
              <tr><td style="padding:0 18px 8px;background:#fff;">
                <table width="100%" cellpadding="0" cellspacing="0">{article_links}{more_note}</table>
              </td></tr>
            </table>
          </td></tr>"""

        # ── Trend landscape ───────────────────────────────────────────────────
        if sorted_trends:
            trend_rows = ""
            for t in sorted_trends:
                tmeta = _CATEGORY_META.get(t.category or "general", _CATEGORY_META["general"])
                bar = min(int(t.momentum_score), 100)
                badge = ' &nbsp;<span style="background:#fde68a;color:#92400e;border-radius:3px;padding:1px 6px;font-size:10px;font-weight:700;">🔥 ALERT</span>' if t.is_alert else ""
                desc = f'<div style="font-size:12px;color:#6b7280;margin-top:3px;">{t.description}</div>' if t.description else ""
                trend_rows += f"""
              <tr><td style="padding:10px 0;border-bottom:1px solid #f3f4f6;">
                <table width="100%" cellpadding="0" cellspacing="0"><tr>
                  <td style="width:32px;vertical-align:top;"><span style="font-size:18px;">{tmeta['icon']}</span></td>
                  <td style="padding-left:10px;">
                    <div style="font-size:13px;font-weight:700;color:#0f3460;">{t.name}{badge}</div>
                    {desc}
                    <div style="margin-top:6px;background:#f3f4f6;border-radius:3px;height:5px;overflow:hidden;">
                      <div style="width:{bar}%;height:100%;background:linear-gradient(90deg,#10b981,#e94560);border-radius:3px;"></div>
                    </div>
                    <div style="font-size:11px;color:#9ca3af;margin-top:4px;">
                      Momentum: {t.momentum_score:.1f} &nbsp;·&nbsp; {t.article_count} articles &nbsp;·&nbsp; {tmeta['label']}
                    </div>
                  </td>
                </tr></table>
              </td></tr>"""

            trends_section = f"""
        <tr><td style="padding:32px 36px 0;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td style="padding-bottom:16px;">
              <table cellpadding="0" cellspacing="0"><tr>
                <td style="width:4px;background:#e94560;border-radius:2px;">&nbsp;</td>
                <td style="padding-left:12px;">
                  <span style="font-size:16px;font-weight:800;color:#0f3460;text-transform:uppercase;letter-spacing:0.5px;">
                    📈 Trend Landscape
                  </span>
                </td>
              </tr></table>
            </td></tr>
          </table>
          <table width="100%" cellpadding="0" cellspacing="0"
                 style="border:1px solid #e5e7eb;border-radius:10px;background:#ffffff;">
            <tr><td style="padding:0 18px;">
              <table width="100%" cellpadding="0" cellspacing="0">{trend_rows}</table>
            </td></tr>
          </table>
        </td></tr>"""
        else:
            trends_section = """
        <tr><td style="padding:32px 36px 0;">
          <table width="100%" cellpadding="0" cellspacing="0" style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;">
            <tr><td style="padding:16px 18px;">
              <span style="font-size:13px;color:#9ca3af;font-style:italic;">
                📈 No trends detected yet — trends appear after multiple runs cluster articles around the same theme.
              </span>
            </td></tr>
          </table>
        </td></tr>"""

        alert_badge_color = "#fef2f2" if alert_trends else "#f0fdf4"
        alert_text_color  = "#b91c1c" if alert_trends else "#166534"
        alert_border      = "#fecaca" if alert_trends else "#86efac"
        alert_label = (
            f"🚨 {len(alert_trends)} Critical Insight{'s' if len(alert_trends) != 1 else ''} Detected"
            if alert_trends else "✅ All Systems Normal — No Critical Insights"
        )

        return f"""<!DOCTYPE html>
<html lang="en" dir="ltr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Quality Managers in AI World – Intelligence Report – {date_str}</title>
</head>
<body dir="ltr" style="margin:0;padding:0;background:#eef2f7;font-family:'Segoe UI',Helvetica,Arial,sans-serif;direction:ltr;">
<table width="100%" cellpadding="0" cellspacing="0" dir="ltr" style="background:#eef2f7;padding:28px 0 40px;">
  <tr><td align="center" style="padding:0 16px;">
    <table width="680" cellpadding="0" cellspacing="0" dir="ltr"
           style="max-width:680px;width:100%;background:#ffffff;border-radius:16px;overflow:hidden;
                  box-shadow:0 4px 24px rgba(15,52,96,0.12);margin:0 auto;direction:ltr;text-align:left;">

      <!-- Header -->
      <tr><td style="background:linear-gradient(135deg,#0f3460 0%,#1a237e 60%,#0f3460 100%);padding:36px 40px 32px;text-align:left;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr><td style="text-align:left;">
            <div style="font-size:26px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;line-height:1.2;text-align:left;">
              🎯 Quality Managers in AI World
            </div>
            <div style="font-size:15px;color:rgba(255,255,255,0.85);margin-top:6px;font-weight:500;text-align:left;">Intelligence Report</div>
            <div style="font-size:12px;color:rgba(255,255,255,0.60);margin-top:4px;text-align:left;">{date_str}</div>
          </td></tr>
          <tr><td style="padding-top:24px;text-align:left;">
            <table cellpadding="0" cellspacing="0"><tr>{stats_html}</tr></table>
          </td></tr>
        </table>
      </td></tr>

      <!-- Alert status pill -->
      <tr><td style="background:#f8fafc;padding:14px 36px;border-bottom:1px solid #e5e7eb;">
        <span style="background:{alert_badge_color};color:{alert_text_color};
                     border:1px solid {alert_border};border-radius:999px;
                     padding:5px 18px;font-size:13px;font-weight:600;display:inline-block;">
          {alert_label}
        </span>
      </td></tr>

      <!-- Alerts/all-clear -->
      {alerts_section}

      <!-- Top 5 Articles -->
      <tr><td style="padding:32px 36px 0;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr><td style="padding-bottom:12px;">
            <table cellpadding="0" cellspacing="0"><tr>
              <td style="width:4px;background:#e94560;border-radius:2px;">&nbsp;</td>
              <td style="padding-left:12px;">
                <span style="font-size:16px;font-weight:800;color:#0f3460;text-transform:uppercase;letter-spacing:0.5px;">
                  ⭐ Top 5 Articles
                </span>
                <span style="font-size:12px;color:#6b7280;margin-left:10px;">
                  {"(+" + str(remaining_articles) + " more — see attached report)" if remaining_articles else ""}
                </span>
              </td>
            </tr></table>
          </td></tr>
        </table>
        <table width="100%" cellpadding="0" cellspacing="0"
               style="border:1px solid #e5e7eb;border-radius:10px;background:#ffffff;padding:12px 20px;">
          <tr><td>
            <table width="100%" cellpadding="0" cellspacing="0">{top_rows}</table>
          </td></tr>
        </table>
      </td></tr>

      <!-- Category Breakdown: clickable badges + per-category article lists -->
      <tr><td style="padding:24px 36px 0;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr><td style="padding-bottom:12px;">
            <table cellpadding="0" cellspacing="0"><tr>
              <td style="width:4px;background:#e94560;border-radius:2px;">&nbsp;</td>
              <td style="padding-left:12px;">
                <span style="font-size:16px;font-weight:800;color:#0f3460;text-transform:uppercase;letter-spacing:0.5px;">
                  📂 Articles by Category
                </span>
              </td>
            </tr></table>
          </td></tr>
          <tr><td style="padding-bottom:16px;">{cat_badges}</td></tr>
          {cat_sections}
        </table>
      </td></tr>

      <!-- Trend Landscape -->
      {trends_section}

      <!-- Footer -->
      <tr><td style="background:#f8fafc;border-top:1px solid #e5e7eb;padding:24px 36px;margin-top:32px;">
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr><td style="text-align:center;padding-bottom:12px;">
            <span style="font-size:13px;font-weight:600;color:#374151;">Quality Managers in AI World</span>
            <span style="font-size:13px;color:#6b7280;"> &nbsp;·&nbsp; Intelligence Agent</span>
          </td></tr>
          <tr><td style="text-align:center;">
            <span style="font-size:11px;color:#9ca3af;">
              Report generated on {date_str} &nbsp;·&nbsp; Auto-generated daily digest
            </span>
          </td></tr>
          <tr><td style="text-align:center;padding-top:12px;">
            <span style="font-size:10px;color:#d1d5db;">
              To modify delivery preferences, update your .env configuration
            </span>
          </td></tr>
        </table>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""

    @staticmethod
    def _build_email_html(
        alert_trends: list[Trend],
        report_html: str,
        date_str: str,
    ) -> str:
        """
        Build a clean, email-client-compatible HTML body.
        The full report is sent as an attachment – NOT embedded inline
        (embedding a full HTML doc inside another breaks rendering in Gmail/Outlook).
        """
        # ── Alert cards ───────────────────────────────────────────────────
        if alert_trends:
            alert_cards_html = ""
            for t in alert_trends:
                icon = _CATEGORY_ICONS.get(t.category, "📌")
                desc = f'<p style="margin:8px 0 0;color:#374151;font-size:13px;line-height:1.5;">{t.description}</p>' if t.description else ""
                cat_label = t.category.replace("_", " ").title()
                alert_cards_html += f"""
                <tr>
                  <td style="padding:0 0 10px 0;">
                    <table width="100%" cellpadding="0" cellspacing="0"
                           style="background:#fff8f8;border:1px solid #fecaca;
                                  border-left:4px solid #e94560;border-radius:8px;">
                      <tr>
                        <td style="padding:14px 18px;">
                          <table width="100%" cellpadding="0" cellspacing="0">
                            <tr>
                              <td style="vertical-align:middle;">
                                <span style="font-size:15px;font-weight:700;color:#1a1a2e;">
                                  {icon} {t.name}
                                </span>
                              </td>
                              <td align="right" style="vertical-align:middle;white-space:nowrap;">
                                <span style="background:#fde68a;color:#92400e;border-radius:6px;
                                             padding:3px 10px;font-size:11px;font-weight:700;">
                                  🔥 ALERT
                                </span>
                              </td>
                            </tr>
                          </table>
                          {desc}
                          <table cellpadding="0" cellspacing="4" style="margin-top:10px;">
                            <tr>
                              <td>
                                <span style="background:#f0fdf4;color:#166534;border-radius:6px;
                                             padding:3px 10px;font-size:11px;font-weight:600;">
                                  📈 Momentum: {t.momentum_score:.1f}
                                </span>
                              </td>
                              <td>
                                <span style="background:#eff6ff;color:#1d4ed8;border-radius:6px;
                                             padding:3px 10px;font-size:11px;font-weight:600;">
                                  📰 {t.article_count} articles
                                </span>
                              </td>
                              <td>
                                <span style="background:#f3f4f6;color:#6b7280;border-radius:6px;
                                             padding:3px 10px;font-size:11px;">
                                  {cat_label}
                                </span>
                              </td>
                            </tr>
                          </table>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>"""

            alerts_section = f"""
            <tr>
              <td style="padding:20px 32px 8px;">
                <table width="100%" cellpadding="0" cellspacing="0"
                       style="background:#fff3cd;border:1px solid #f59e0b;border-radius:10px;">
                  <tr>
                    <td style="padding:12px 18px;">
                      <span style="font-size:14px;font-weight:700;color:#92400e;">
                        🚨 {len(alert_trends)} Active Trend Alert{'s' if len(alert_trends) != 1 else ''}
                      </span>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td style="padding:0 32px 8px;">
                <table width="100%" cellpadding="0" cellspacing="0">
                  {alert_cards_html}
                </table>
              </td>
            </tr>"""
        else:
            alerts_section = """
            <tr>
              <td style="padding:20px 32px 8px;">
                <table width="100%" cellpadding="0" cellspacing="0"
                       style="background:#f0fdf4;border:1px solid #86efac;border-radius:10px;">
                  <tr>
                    <td style="padding:14px 18px;">
                      <span style="font-size:14px;font-weight:600;color:#166534;">
                        ✅ No critical alerts this cycle
                      </span>
                      <p style="margin:4px 0 0;color:#166534;font-size:12px;opacity:0.75;">
                        All monitored trends are within normal momentum thresholds
                      </p>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>"""

        return f"""<!DOCTYPE html>
<html lang="en" dir="ltr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Quality Managers in AI World – Intelligence Report – {date_str}</title>
</head>
<body dir="ltr" style="margin:0;padding:0;background:#f0f4f8;font-family:'Segoe UI',Arial,sans-serif;direction:ltr;text-align:left;">

<table width="100%" cellpadding="0" cellspacing="0" dir="ltr" style="background:#f0f4f8;padding:24px 0;direction:ltr;text-align:left;">
  <tr>
    <td align="center" style="padding:0 12px;text-align:center;">
      <table width="600" cellpadding="0" cellspacing="0" dir="ltr"
             style="max-width:600px;width:100%;background:#ffffff;border-radius:14px;
                    box-shadow:0 2px 16px rgba(0,0,0,0.10);overflow:hidden;direction:ltr;text-align:left;">

        <!-- ── Header ─────────────────────────────────────────────── -->
        <tr>
          <td style="background:linear-gradient(135deg,#0f3460 0%,#1a237e 100%);padding:28px 32px;text-align:left;">
            <h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:700;letter-spacing:-0.3px;text-align:left;">
              🎯 Quality Managers in AI World
            </h1>
            <p style="margin:6px 0 0;color:rgba(255,255,255,0.72);font-size:13px;text-align:left;">
              Intelligence Report &nbsp;·&nbsp; {date_str}
            </p>
          </td>
        </tr>

        <!-- ── Alert status badge ─────────────────────────────────── -->
        <tr>
          <td style="padding:18px 32px 0;">
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="border-bottom:1px solid #f0f0f0;padding-bottom:18px;">
              <tr>
                <td align="center">
                  <span style="background:{'#fef2f2' if alert_trends else '#f0fdf4'};
                               color:{'#b91c1c' if alert_trends else '#166534'};
                               border:1px solid {'#fecaca' if alert_trends else '#86efac'};
                               border-radius:999px;padding:6px 20px;
                               font-size:13px;font-weight:600;display:inline-block;">
                    {'🚨 ' + str(len(alert_trends)) + ' Critical Insight' + ('s' if len(alert_trends) != 1 else '') if alert_trends else '✅ All Systems Normal'}
                  </span>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- ── Alert cards or all-clear ──────────────────────────── -->
        {alerts_section}

        <!-- ── Attachment CTA ─────────────────────────────────────── -->
        <tr>
          <td style="padding:16px 32px 24px;">
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;">
              <tr>
                <td style="padding:14px 18px;">
                  <p style="margin:0;font-size:13px;color:#1d4ed8;line-height:1.6;">
                    📎 <strong>Full interactive report is attached.</strong>
                    Open the HTML file in your browser for the complete trend landscape,
                    top articles with AI insights, and full category breakdown.
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- ── Footer ─────────────────────────────────────────────── -->
        <tr>
          <td style="background:#f8fafc;border-top:1px solid #e5e7eb;
                     padding:14px 32px;text-align:center;">
            <p style="margin:0;color:#9ca3af;font-size:11px;">
              Quality Managers in AI World &nbsp;·&nbsp; Intelligence Agent &nbsp;·&nbsp; {date_str}
            </p>
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>

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
                text="Quality Managers in AI World – Intelligence Report",
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
                "text": {"type": "plain_text", "text": "🎯 Quality Managers in AI World", "emoji": True},
            },
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"Intelligence Report | {now}"}],
            },
        ]

        if alert_trends:
            alert_text = "\n".join(
                f"• *{_CATEGORY_META.get(t.category or 'general', _CATEGORY_META['general'])['icon']} {t.name}* "
                f"({t.category}) — momentum: `{t.momentum_score:.1f}` | articles: `{t.article_count}`"
                for t in alert_trends
            )
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"🚨 *Critical Insights – Action Recommended:*\n{alert_text}"},
            })
        else:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "✅ *All Systems Normal — No Critical Insights*"},
            })

        if report_path:
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"📄 *Report file:* `{report_path.name}`"},
            })

        return blocks
