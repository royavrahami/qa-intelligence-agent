"""
Report Generator – produces a rich HTML report and a companion Markdown file
from processed articles and detected trends.

Report structure:
  1. Executive Summary (key numbers)
  2. Alert-level Trends (immediate attention required)
  3. Top Articles by Category (with AI summary, insights, QA relevance, link)
  4. Trend Landscape (all trends with momentum)
  5. Where the Wind is Blowing (strategic direction summary via LLM)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.storage.models import Article, Trend

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"

# Category display names and emoji indicators
_CATEGORY_META = {
    "genai":              {"label": "GenAI & LLMs",          "icon": "🤖"},
    "agents":             {"label": "AI Agents",              "icon": "🕵️"},
    "qa_testing":         {"label": "QA & Testing",           "icon": "🧪"},
    "devops":             {"label": "DevOps & CI/CD",         "icon": "⚙️"},
    "tools":              {"label": "Developer Tools",        "icon": "🛠️"},
    "project_management": {"label": "Project Management",    "icon": "📋"},
    "general":            {"label": "General Tech",          "icon": "📰"},
}


class ReportGenerator:
    """
    Generates HTML and Markdown intelligence reports.

    Args:
        reports_dir: Directory where report files are saved.
    """

    def __init__(self, reports_dir: Path) -> None:
        self._reports_dir = reports_dir
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        self._jinja_env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=select_autoescape(["html"]),
        )
        # Register custom filters
        self._jinja_env.filters["category_label"] = lambda c: _CATEGORY_META.get(c, {}).get("label", c)
        self._jinja_env.filters["category_icon"] = lambda c: _CATEGORY_META.get(c, {}).get("icon", "📄")
        self._jinja_env.filters["format_dt"] = lambda dt: dt.strftime("%d %b %Y %H:%M UTC") if dt else "N/A"

    def generate(
        self,
        articles: list[Article],
        trends: list[Trend],
        run_id: int,
    ) -> Optional[Path]:
        """
        Build the full HTML report and save it to disk.

        Args:
            articles: Processed, scored articles to include.
            trends:   Detected trends to highlight.
            run_id:   Agent run ID for traceability.

        Returns:
            Path to the generated HTML report file.
        """
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        report_filename = f"qa_intelligence_report_{timestamp}.html"
        report_path = self._reports_dir / report_filename

        # Organise articles by category
        categorised = self._categorise_articles(articles)

        # Build template context
        context = {
            "generated_at": now,
            "run_id": run_id,
            "total_articles": len(articles),
            "total_trends": len(trends),
            "alert_trends": [t for t in trends if t.is_alert],
            "all_trends": sorted(trends, key=lambda t: t.momentum_score, reverse=True),
            "categorised_articles": categorised,
            "top_articles": sorted(articles, key=lambda a: a.relevance_score, reverse=True)[:10],
            "category_meta": _CATEGORY_META,
        }

        # Render and save HTML
        html_content = self._render_html(context)
        report_path.write_text(html_content, encoding="utf-8")

        # Also save a companion Markdown version
        md_path = report_path.with_suffix(".md")
        md_content = self._render_markdown(context)
        md_path.write_text(md_content, encoding="utf-8")

        logger.info("Report generated: %s (%d articles, %d trends)", report_path.name, len(articles), len(trends))
        return report_path

    def _render_html(self, context: dict) -> str:
        """Render the HTML report from the Jinja2 template."""
        try:
            template = self._jinja_env.get_template("report.html")
            return template.render(**context)
        except Exception as exc:
            logger.error("HTML template render failed: %s – falling back to inline", exc)
            return self._build_inline_html(context)

    def _render_markdown(self, context: dict) -> str:
        """Render a Markdown companion report."""
        lines: list[str] = []
        now = context["generated_at"]
        lines.append(f"# QA Intelligence Report – {now.strftime('%d %b %Y %H:%M UTC')}")
        lines.append(f"\n**Run ID:** {context['run_id']} | "
                     f"**Articles:** {context['total_articles']} | "
                     f"**Trends:** {context['total_trends']}")

        # Alert Trends
        if context["alert_trends"]:
            lines.append("\n## 🚨 Alerts – Immediate Attention Required\n")
            for trend in context["alert_trends"]:
                lines.append(f"### {trend.name}")
                lines.append(f"{trend.description or ''}")
                lines.append(f"- **Category:** {_CATEGORY_META.get(trend.category, {}).get('label', trend.category)}")
                lines.append(f"- **Momentum Score:** {trend.momentum_score:.1f}")
                lines.append("")

        # Top Articles
        lines.append("\n## Top Articles by Relevance\n")
        for article in context["top_articles"]:
            lines.append(f"### [{article.title}]({article.url})")
            cat_label = _CATEGORY_META.get(article.category, {}).get("label", article.category)
            lines.append(f"**Score:** {article.relevance_score:.0f} | **Category:** {cat_label}")
            if article.summary:
                lines.append(f"\n**Summary:** {article.summary}")
            if article.key_insights:
                try:
                    insights = json.loads(article.key_insights)
                    if insights:
                        lines.append("\n**Key Insights:**")
                        for insight in insights:
                            lines.append(f"- {insight}")
                except Exception:
                    pass
            if article.qa_relevance:
                lines.append(f"\n**For QA Manager:** {article.qa_relevance}")
            lines.append("")

        # Trend Landscape
        lines.append("\n## Trend Landscape\n")
        for trend in context["all_trends"]:
            icon = _CATEGORY_META.get(trend.category, {}).get("icon", "📄")
            alert_badge = " 🚨" if trend.is_alert else ""
            lines.append(f"- **{icon} {trend.name}**{alert_badge} — "
                         f"momentum: {trend.momentum_score:.1f}, articles: {trend.article_count}")

        return "\n".join(lines)

    @staticmethod
    def _categorise_articles(articles: list[Article]) -> dict[str, list[Article]]:
        """Group articles by category, sorted by relevance score desc."""
        result: dict[str, list[Article]] = {}
        for article in articles:
            cat = article.category or "general"
            result.setdefault(cat, []).append(article)
        # Sort each group by relevance score
        for cat in result:
            result[cat].sort(key=lambda a: a.relevance_score, reverse=True)
        return result

    @staticmethod
    def _build_inline_html(context: dict) -> str:
        """
        Fallback: build a minimal HTML report without Jinja2 templates.
        Used when the template file is missing or fails to render.
        """
        now = context["generated_at"].strftime("%d %b %Y %H:%M UTC")
        sections = [
            f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8">
<title>QA Intelligence Report – {now}</title>
<style>
  body {{font-family: system-ui, sans-serif; max-width: 960px; margin: 40px auto; padding: 0 20px; color: #1a1a2e;}}
  h1 {{color: #16213e;}} h2 {{color: #0f3460; border-bottom: 2px solid #e94560; padding-bottom: 8px;}}
  .card {{border: 1px solid #ddd; border-radius: 8px; padding: 16px; margin: 12px 0; background: #fafafa;}}
  .score {{display: inline-block; background: #e94560; color: white; border-radius: 12px; padding: 2px 10px; font-size: 0.85em;}}
  .alert {{background: #fff3cd; border-left: 4px solid #e94560;}}
  .insight {{background: #e8f4fd; border-left: 3px solid #0f3460; padding: 8px 12px; margin: 4px 0;}}
  a {{color: #0f3460;}} .meta {{color: #666; font-size: 0.85em;}}
  .trend-badge {{display: inline-block; background: #0f3460; color: white; border-radius: 12px; padding: 2px 8px; font-size: 0.8em; margin-right: 4px;}}
</style></head><body>
<h1>🧪 QA Intelligence Report</h1>
<p class="meta">Generated: {now} | Run ID: {context['run_id']} |
Articles: {context['total_articles']} | Trends: {context['total_trends']}</p>"""
        ]

        # Alert Trends
        if context["alert_trends"]:
            sections.append('<h2>🚨 Alerts – Immediate Attention Required</h2>')
            for trend in context["alert_trends"]:
                cat_label = _CATEGORY_META.get(trend.category, {}).get("label", trend.category)
                sections.append(
                    f'<div class="card alert"><strong>{trend.name}</strong> '
                    f'<span class="trend-badge">{cat_label}</span>'
                    f'<br>{trend.description or ""}'
                    f'<br><span class="meta">Momentum: {trend.momentum_score:.1f} | Articles: {trend.article_count}</span></div>'
                )

        # Top Articles
        sections.append('<h2>📰 Top Articles</h2>')
        for article in context["top_articles"]:
            cat_label = _CATEGORY_META.get(article.category, {}).get("label", article.category)
            cat_icon = _CATEGORY_META.get(article.category, {}).get("icon", "📄")
            insights_html = ""
            if article.key_insights:
                try:
                    insights = json.loads(article.key_insights)
                    insights_html = "".join(
                        f'<div class="insight">• {i}</div>' for i in insights
                    )
                except Exception:
                    pass

            qa_rel_html = f'<p><strong>For QA Manager:</strong> {article.qa_relevance}</p>' if article.qa_relevance else ""

            sections.append(
                f'<div class="card">'
                f'<a href="{article.url}" target="_blank"><strong>{article.title}</strong></a>'
                f' <span class="score">{article.relevance_score:.0f}</span>'
                f'<br><span class="meta">{cat_icon} {cat_label}'
                + (f' | {article.published_at.strftime("%d %b %Y") if article.published_at else ""}' )
                + f'</span>'
                f'<p>{article.summary or ""}</p>'
                + insights_html
                + qa_rel_html
                + '</div>'
            )

        # Trend Landscape
        sections.append('<h2>📈 Trend Landscape</h2>')
        for trend in context["all_trends"]:
            icon = _CATEGORY_META.get(trend.category, {}).get("icon", "📄")
            alert_icon = " 🚨" if trend.is_alert else ""
            sections.append(
                f'<div class="card">'
                f'<strong>{icon} {trend.name}</strong>{alert_icon}'
                f' <span class="trend-badge">momentum: {trend.momentum_score:.1f}</span>'
                f'<br>{trend.description or ""}'
                f'<br><span class="meta">Articles: {trend.article_count} | Category: {trend.category}</span>'
                f'</div>'
            )

        sections.append('</body></html>')
        return "\n".join(sections)
