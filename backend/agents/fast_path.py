"""Fast path Fase 2: TM1 direto → template Jinja2, sem LLM."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

from metrics_catalog import ReportRequest, parse_report_request
from report_renderer import (
    render_time_series_by_filial_report,
    render_time_series_by_product_report,
    render_time_series_report,
)
from reports import create_report
from tm1_cache import build_report_cache_payload, get_cached, set_cached
from tm1_mcp import TM1MCPClient, TM1MCPError, get_default_connection_id
from tm1_mdx_builder import query_time_series, query_time_series_by_filial, query_time_series_by_product

logger = logging.getLogger(__name__)

StatusCallback = Callable[[str], None] | None
RESPONSE_CACHE_NS = "fast_path_response"


def _emit(status_cb: StatusCallback, message: str) -> None:
    if status_cb:
        status_cb(message)


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
    status_cb: StatusCallback = None,
) -> tuple[str, str, dict] | None:
    """
    Tenta gerar relatório determinístico quando o pedido bate no glossário.
    Retorna (texto_resposta, mode, meta) ou None para fallback ao pipeline de agentes.
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

    meta: dict = {"cache_hit": False, "cache_layer": None}

    logger.info(
        "Fast path: metric=%s year=%s group_by=%s user=%s",
        request.metric_key,
        request.year,
        request.group_by,
        username,
    )

    try:
        connection_id = get_default_connection_id()
        response_cache_key = build_report_cache_payload(
            connection_id=connection_id,
            metric_key=request.metric_key,
            year=request.year,
            cube=request.cube,
            version=request.version,
            group_by=request.group_by,
        )
        cached_response = get_cached(RESPONSE_CACHE_NS, response_cache_key)
        if cached_response and cached_response.get("text") and cached_response.get("mode"):
            meta["cache_hit"] = True
            meta["cache_layer"] = "response"
            _emit(status_cb, "Dados recuperados do cache TM1 (até 3 min).")
            logger.info("Fast path response cache HIT metric=%s year=%s", request.metric_key, request.year)
            text = cached_response["text"]
            if "Cache TM1" not in text:
                text = f"⚡ **Cache TM1** — resposta reutilizada (até 3 min).\n\n{text}"
            return text, cached_response["mode"], meta

        _emit(status_cb, "Interpretando pedido de relatório...")

        if request.group_by == "produto":
            _emit(status_cb, f"Consultando TM1 por produto ({request.metric_label} · {request.year})...")
            payload = query_time_series_by_product(
                mcp_client,
                connection_id,
                metric=request.metric_key,
                year=request.year,
                cube_name=request.cube,
                version=request.version,
            )
        elif request.group_by == "filial":
            _emit(status_cb, f"Consultando TM1 por filial ({request.metric_label} · {request.year})...")
            payload = query_time_series_by_filial(
                mcp_client,
                connection_id,
                metric=request.metric_key,
                year=request.year,
                cube_name=request.cube,
                version=request.version,
            )
        else:
            _emit(status_cb, f"Consultando TM1 ({request.metric_label} · {request.year})...")
            payload = query_time_series(
                mcp_client,
                connection_id,
                metric=request.metric_key,
                year=request.year,
                cube_name=request.cube,
                version=request.version,
            )
        if payload.get("_cached"):
            meta["cache_hit"] = True
            meta["cache_layer"] = "tm1_query"
            _emit(status_cb, "Dados recuperados do cache TM1 (até 3 min).")
    except TM1MCPError as exc:
        logger.warning("Fast path TM1 error: %s", exc)
        return (
            f"Não foi possível consultar {request.metric_label} ({request.year}) no TM1: {exc}",
            "fast-path-error",
            meta,
        )

    if not payload.get("series") and not payload.get("series_groups"):
        return (
            f"Consulta de {request.metric_label} em {request.year} não retornou dados.",
            "fast-path-empty",
            meta,
        )

    _emit(status_cb, "Montando relatório HTML...")
    if request.group_by == "produto":
        title, html = render_time_series_by_product_report(request, payload)
    elif request.group_by == "filial":
        title, html = render_time_series_by_filial_report(request, payload)
    else:
        title, html = render_time_series_report(request, payload)
    _emit(status_cb, "Publicando relatório...")
    report = create_report(title, html, created_by=username)

    cache_line = (
        "⚡ **Cache TM1** — dados reutilizados (válido por até 3 min).\n\n"
        if meta.get("cache_hit")
        else ""
    )
    text = (
        f"Relatório **{title}** publicado via fast path (sem LLM).\n\n"
        f"{cache_line}"
        f"Resumo: {payload.get('summary', 'Série mensal obtida.')}\n\n"
        f"Abrir relatório: {report['url']}"
    )
    if request.group_by == "produto":
        mode = "fast-path-by-product"
    elif request.group_by == "filial":
        mode = "fast-path-by-filial"
    else:
        mode = "fast-path"

    set_cached(
        RESPONSE_CACHE_NS,
        response_cache_key,
        {"text": text, "mode": mode},
    )

    return text, mode, meta
