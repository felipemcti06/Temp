"""Fast path Fase 2: TM1 direto → template Jinja2, sem LLM."""

from __future__ import annotations

import logging
import os

from metrics_catalog import ReportRequest, parse_report_request
from report_renderer import render_time_series_report
from reports import create_report
from tm1_mcp import TM1MCPClient, TM1MCPError, get_default_connection_id
from tm1_mdx_builder import query_time_series

logger = logging.getLogger(__name__)


def fast_path_enabled() -> bool:
    return os.getenv("ENABLE_FAST_REPORT_PATH", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def try_fast_report_path(
    messages: list[dict],
    mcp_client: TM1MCPClient,
    *,
    username: str | None = None,
) -> tuple[str, str] | None:
    """
    Tenta gerar relatório determinístico quando o pedido bate no glossário.
    Retorna (texto_resposta, mode) ou None para fallback ao pipeline de agentes.
    """
    if not fast_path_enabled():
        return None

    last_user = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"),
        "",
    )
    request = parse_report_request(last_user)
    if not request:
        return None

    logger.info(
        "Fast path: metric=%s year=%s user=%s",
        request.metric_key,
        request.year,
        username,
    )

    try:
        connection_id = get_default_connection_id()
        payload = query_time_series(
            mcp_client,
            connection_id,
            metric=request.metric_key,
            year=request.year,
            cube_name=request.cube,
            version=request.version,
        )
    except TM1MCPError as exc:
        logger.warning("Fast path TM1 error: %s", exc)
        return (
            f"Não foi possível consultar {request.metric_label} ({request.year}) no TM1: {exc}",
            "fast-path-error",
        )

    if not payload.get("series"):
        return (
            f"Consulta de {request.metric_label} em {request.year} não retornou dados.",
            "fast-path-empty",
        )

    title, html = render_time_series_report(request, payload)
    report = create_report(title, html, created_by=username)

    text = (
        f"Relatório **{title}** publicado via fast path (sem LLM).\n\n"
        f"Resumo: {payload.get('summary', 'Série mensal obtida.')}\n\n"
        f"Abrir relatório: {report['url']}"
    )
    return text, "fast-path"
