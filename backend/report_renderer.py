"""Renderização determinística de relatórios HTML via Jinja2."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from metrics_catalog import ReportRequest

_TEMPLATES_DIR = Path(__file__).with_name("templates")
_LOGO_PATH = Path(__file__).with_name("assets") / "cti-logo.png"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def _logo_data_uri() -> str | None:
    if not _LOGO_PATH.exists():
        return None
    encoded = base64.b64encode(_LOGO_PATH.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _format_change(first: float, last: float, *, is_percent: bool) -> str:
    if first == 0:
        return "—"
    pct = ((last - first) / abs(first)) * 100
    suffix = " p.p." if is_percent else "%"
    return f"{pct:+.1f}{suffix}"


def _format_display(value: float | None, formatted: str | None, *, is_percent: bool) -> str:
    if formatted:
        return formatted
    if value is None:
        return "—"
    if is_percent:
        return f"{value:.2f}%"
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def build_kpis(series: list[dict[str, Any]], *, is_percent: bool) -> dict[str, str]:
    numeric = [
        (item, item.get("value"))
        for item in series
        if isinstance(item.get("value"), (int, float))
    ]

    if not numeric:
        empty = "—"
        return {
            "first": empty,
            "last": empty,
            "change": empty,
            "max_value": empty,
            "max_month": empty,
            "min_value": empty,
            "min_month": empty,
        }

    first_item, first_val = numeric[0]
    last_item, last_val = numeric[-1]
    max_item, max_val = max(numeric, key=lambda pair: pair[1])
    min_item, min_val = min(numeric, key=lambda pair: pair[1])

    return {
        "first": _format_display(first_val, first_item.get("formatted"), is_percent=is_percent),
        "last": _format_display(last_val, last_item.get("formatted"), is_percent=is_percent),
        "change": _format_change(first_val, last_val, is_percent=is_percent),
        "max_value": _format_display(max_val, max_item.get("formatted"), is_percent=is_percent),
        "max_month": max_item.get("label", ""),
        "min_value": _format_display(min_val, min_item.get("formatted"), is_percent=is_percent),
        "min_month": min_item.get("label", ""),
    }


def render_time_series_report(
    request: ReportRequest,
    payload: dict[str, Any],
) -> tuple[str, str]:
    """Retorna (title, html_body) prontos para create_report."""
    series = payload.get("series") or []
    is_percent = request.format == "percent"
    kpis = build_kpis(series, is_percent=is_percent)

    title = f"{request.metric_label} — Evolução mensal {request.year}"
    summary = payload.get("summary") or (
        f"Série mensal de {request.metric_label} em {request.year} "
        f"(versão {request.version})."
    )

    chart_labels = [row.get("label", "") for row in series]
    chart_values = [
        row.get("value") if isinstance(row.get("value"), (int, float)) else None
        for row in series
    ]

    template = _env.get_template("time_series_report.html.j2")
    html = template.render(
        title=title,
        metric=request.metric_label,
        period=request.year,
        version=request.version,
        cube=request.cube,
        summary=summary,
        kpis=kpis,
        series=series,
        chart_labels=chart_labels,
        chart_values=chart_values,
        generated_at=datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC"),
        logo_src=_logo_data_uri(),
        brand_name="CTI",
    )
    return title, html


CHART_COLORS = [
    "#2563eb",
    "#16a34a",
    "#ea580c",
    "#dc2626",
    "#0891b2",
    "#7c3aed",
    "#db2777",
    "#65a30d",
    "#0d9488",
    "#c2410c",
    "#4f46e5",
    "#059669",
]


def _series_group_total(group: dict[str, Any]) -> float:
    total = 0.0
    for row in group.get("series", []):
        value = row.get("value")
        if isinstance(value, (int, float)):
            total += value
    return total


def _group_has_data(group: dict[str, Any]) -> bool:
    return any(isinstance(row.get("value"), (int, float)) for row in group.get("series", []))


def _build_line_dataset(group: dict[str, Any], idx: int, *, fallback_label: str) -> dict[str, Any]:
    color = CHART_COLORS[idx % len(CHART_COLORS)]
    return {
        "label": group.get("name", fallback_label),
        "data": [
            row.get("value") if isinstance(row.get("value"), (int, float)) else None
            for row in group.get("series", [])
        ],
        "borderColor": color,
        "backgroundColor": color,
        "fill": False,
        "tension": 0,
        "pointRadius": 3,
        "pointHoverRadius": 5,
        "borderWidth": 2,
        "spanGaps": False,
    }


def render_time_series_by_product_report(
    request: ReportRequest,
    payload: dict[str, Any],
) -> tuple[str, str]:
    series_groups = payload.get("series_groups") or []
    month_labels = [row.get("label", "") for row in (series_groups[0].get("series") if series_groups else [])]

    title = f"{request.metric_label} — Evolução mensal {request.year} por produto"
    summary = payload.get("summary") or (
        f"{request.metric_label} em {request.year} desagregado por produto (versão {request.version})."
    )

    chart_datasets = []
    for idx, group in enumerate(series_groups):
        chart_datasets.append(_build_line_dataset(group, idx, fallback_label=f"Produto {idx + 1}"))

    template = _env.get_template("time_series_by_product.html.j2")
    html = template.render(
        title=title,
        metric=request.metric_label,
        period=request.year,
        version=request.version,
        cube=request.cube,
        summary=summary,
        series_groups=series_groups,
        month_labels=month_labels,
        chart_labels=month_labels,
        chart_datasets=chart_datasets,
        generated_at=datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC"),
        logo_src=_logo_data_uri(),
        brand_name="CTI",
    )
    return title, html


def render_time_series_by_filial_report(
    request: ReportRequest,
    payload: dict[str, Any],
) -> tuple[str, str]:
    series_groups = payload.get("series_groups") or []
    month_labels = [row.get("label", "") for row in (series_groups[0].get("series") if series_groups else [])]

    title = f"{request.metric_label} — Evolução mensal {request.year} por filial"
    summary = payload.get("summary") or (
        f"{request.metric_label} em {request.year} desagregado por filial (versão {request.version})."
    )

    ranked_groups = sorted(
        [group for group in series_groups if _group_has_data(group)],
        key=_series_group_total,
        reverse=True,
    )
    is_percent = request.format == "percent"
    max_total = max((_series_group_total(group) for group in ranked_groups), default=0.0)
    ranking_rows = []
    for idx, group in enumerate(ranked_groups):
        total = _series_group_total(group)
        ranking_rows.append(
            {
                "name": group.get("name", ""),
                "total": total,
                "formatted_total": _format_display(total, None, is_percent=is_percent),
                "pct": round((abs(total) / abs(max_total)) * 100, 1) if max_total else 0.0,
                "color": CHART_COLORS[idx % len(CHART_COLORS)],
            }
        )

    sparkline_charts = []
    for idx, group in enumerate(ranked_groups):
        color = CHART_COLORS[idx % len(CHART_COLORS)]
        sparkline_charts.append(
            {
                "id": f"filial-spark-{idx}",
                "name": group.get("name", f"Filial {idx + 1}"),
                "color": color,
                "values": [
                    row.get("value") if isinstance(row.get("value"), (int, float)) else None
                    for row in group.get("series", [])
                ],
            }
        )

    template = _env.get_template("time_series_by_filial.html.j2")
    html = template.render(
        title=title,
        metric=request.metric_label,
        period=request.year,
        version=request.version,
        cube=request.cube,
        summary=summary,
        series_groups=series_groups,
        month_labels=month_labels,
        chart_labels=month_labels,
        ranking_rows=ranking_rows,
        sparkline_charts=sparkline_charts,
        is_percent=is_percent,
        generated_at=datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC"),
        logo_src=_logo_data_uri(),
        brand_name="CTI",
    )
    return title, html
