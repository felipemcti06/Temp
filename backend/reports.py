"""Armazenamento temporário de relatórios HTML."""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

REPORT_TTL_HOURS = int(os.getenv("REPORT_TTL_HOURS", "24"))
MAX_HTML_CHARS = 500_000

CHART_SAFE_CSS = """
    .chart-container {
      position: relative;
      height: 420px;
      max-height: 420px;
      width: 100%;
      max-width: 900px;
      margin: 1.5rem auto;
      overflow: hidden;
    }
    .chart-container canvas {
      display: block;
      max-width: 100%;
      max-height: 420px;
    }
    canvas[id*="chart" i] {
      display: block;
      max-width: 900px;
      max-height: 420px !important;
      height: 420px !important;
      width: 100% !important;
    }
    body {
      overflow-x: hidden;
    }
"""

_reports: dict[str, Report] = {}


@dataclass
class Report:
    id: str
    title: str
    html: str
    created_at: datetime
    expires_at: datetime
    created_by: str | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _cleanup_expired() -> None:
    now = _utcnow()
    expired = [rid for rid, report in _reports.items() if report.expires_at <= now]
    for rid in expired:
        _reports.pop(rid, None)


def wrap_html_document(title: str, body: str) -> str:
    stripped = body.strip()
    lower = stripped.lower()
    if lower.startswith("<!doctype") or lower.startswith("<html"):
        return stripped

    safe_title = re.sub(r"<[^>]+>", "", title)
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{safe_title}</title>
  <style>
    body {{
      font-family: Inter, system-ui, -apple-system, sans-serif;
      line-height: 1.6;
      color: #1a1a2e;
      max-width: 960px;
      margin: 0 auto;
      padding: 2rem 1.5rem;
      background: #f8f9fc;
    }}
    h1, h2, h3 {{ color: #111827; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 1.5rem 0;
      background: #fff;
      border-radius: 8px;
      overflow: hidden;
      box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }}
    th, td {{
      padding: 0.75rem 1rem;
      text-align: left;
      border-bottom: 1px solid #e5e7eb;
    }}
    th {{ background: #111827; color: #fff; }}
    .kpi {{
      display: inline-block;
      background: #fff;
      border-radius: 10px;
      padding: 1rem 1.25rem;
      margin: 0.5rem 0.5rem 0.5rem 0;
      box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }}
    .kpi strong {{ display: block; font-size: 1.4rem; color: #4f46e5; }}
    {CHART_SAFE_CSS}
  </style>
</head>
<body>
{body}
</body>
</html>"""


def _needs_chart_css(html: str) -> bool:
    lower = html.lower()
    return "<canvas" in lower or "chart.js" in lower or "new chart(" in lower


def _inject_chart_safe_css(html: str) -> str:
    """Evita loop de resize do Chart.js quando o LLM gera HTML completo."""
    if not _needs_chart_css(html):
        return html

    marker = 'id="chart-safe-css"'
    if marker in html:
        return html

    style_tag = f'<style {marker}>\n{CHART_SAFE_CSS}\n</style>'
    lower = html.lower()

    if "</head>" in lower:
        idx = lower.rfind("</head>")
        return html[:idx] + style_tag + "\n" + html[idx:]

    if "<body" in lower:
        body_idx = lower.find("<body")
        body_end = html.find(">", body_idx)
        if body_end != -1:
            return html[: body_end + 1] + "\n" + style_tag + html[body_end + 1 :]

    return style_tag + "\n" + html


def create_report(title: str, html: str, *, created_by: str | None = None) -> dict[str, str]:
    _cleanup_expired()

    if not title.strip():
        raise ValueError("Título do relatório é obrigatório")
    if not html.strip():
        raise ValueError("Conteúdo HTML do relatório é obrigatório")
    if len(html) > MAX_HTML_CHARS:
        raise ValueError(f"HTML excede o limite de {MAX_HTML_CHARS} caracteres")

    report_id = str(uuid.uuid4())
    now = _utcnow()
    document = _inject_chart_safe_css(wrap_html_document(title.strip(), html.strip()))

    _reports[report_id] = Report(
        id=report_id,
        title=title.strip(),
        html=document,
        created_at=now,
        expires_at=now + timedelta(hours=REPORT_TTL_HOURS),
        created_by=created_by,
    )

    return {
        "report_id": report_id,
        "title": title.strip(),
        "url": f"/relatorio/{report_id}",
        "expires_in_hours": str(REPORT_TTL_HOURS),
    }


def get_report(report_id: str) -> Report | None:
    _cleanup_expired()
    report = _reports.get(report_id)
    if not report:
        return None
    if report.expires_at <= _utcnow():
        _reports.pop(report_id, None)
        return None
    return report
