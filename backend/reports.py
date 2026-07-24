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
    .report-header {
      display: flex;
      align-items: center;
      gap: 1rem;
      padding: 1.25rem 1.5rem;
      margin: 0 0 2rem;
      background: linear-gradient(135deg, #1a1a2e 0%, #2a1f4d 100%);
      color: #e8e8f0;
      border-radius: 12px;
    }
    .report-logo {
      width: 44px;
      height: 44px;
      object-fit: contain;
      border-radius: 8px;
      background: #000;
      padding: 4px;
    }
    .report-brand {
      font-size: 0.8rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: #9898b0;
      margin: 0 0 0.25rem;
    }
    .report-meta {
      margin: 0;
      font-size: 0.85rem;
      color: #c7c7dc;
    }
    .kpi-row {
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      margin: 1rem 0 1.5rem;
    }
    .chart-container {
      position: relative;
      height: 420px;
      max-height: 420px;
      width: 100%;
      max-width: 900px;
      margin: 1.5rem auto;
      overflow: hidden;
    }
    .chart-container--tall {
      height: 480px;
      max-height: 480px;
    }
    .chart-container--ranking {
      height: min(420px, calc(56px + var(--ranking-rows, 9) * 34px));
      max-height: 520px;
    }
    .chart-container--trend {
      height: 420px;
      max-height: 420px;
    }
    .chart-caption {
      margin: 0 0 0.75rem;
      color: #64748b;
      font-size: 0.92rem;
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
      overflow-x: auto;
    }
    .table-scroll {
      width: 100%;
      overflow-x: auto;
      margin: 1rem 0 1.5rem;
      border-radius: 8px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.08);
      background: #fff;
      -webkit-overflow-scrolling: touch;
    }
    .report-table-section {
      width: 100%;
      max-width: 100%;
    }
    .table-wide {
      width: max-content;
      min-width: 100%;
      border-collapse: collapse;
      margin: 0;
      background: #fff;
      overflow: visible;
      border-radius: 0;
      box-shadow: none;
    }
    .table-wide th,
    .table-wide td {
      padding: 0.65rem 0.85rem;
      border-bottom: 1px solid #e5e7eb;
      white-space: nowrap;
    }
    .table-wide th {
      background: #1a1a2e;
      color: #fff;
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.03em;
    }
    .table-wide td:first-child,
    .table-wide th:first-child {
      position: sticky;
      left: 0;
      z-index: 2;
      min-width: 220px;
      max-width: 280px;
      white-space: normal;
      text-align: left;
      background: #fff;
      box-shadow: 2px 0 4px rgba(0,0,0,0.04);
    }
    .table-wide th:first-child {
      background: #1a1a2e;
      z-index: 3;
    }
    .table-wide td.num,
    .table-wide th.month {
      text-align: right;
      font-variant-numeric: tabular-nums;
    }
    section {
      margin-bottom: 2rem;
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
      width: 100%;
      max-width: 1200px;
      margin: 0 auto;
      padding: 1.5rem;
      background: #f8f9fc;
      box-sizing: border-box;
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
    th {{ background: #1a1a2e; color: #fff; }}
    .kpi {{
      display: inline-block;
      background: #fff;
      border-radius: 10px;
      padding: 1rem 1.25rem;
      margin: 0.5rem 0.5rem 0.5rem 0;
      box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }}
    .kpi strong {{ display: block; font-size: 1.4rem; color: #6c63ff; }}
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
