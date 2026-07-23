"""Orquestrador: data agent (barato) → report agent (premium)."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

from agents.data_agent import run_data_agent
from agents.report_agent import run_report_agent
from llm_config import ModelOption, is_model_available, resolve_model_id
from tm1_mcp import TM1MCPClient

logger = logging.getLogger(__name__)

StatusCallback = Callable[[str], None] | None


def _emit(status_cb: StatusCallback, message: str) -> None:
    if status_cb:
        status_cb(message)

DEFAULT_DATA_AGENT_MODEL = "anthropic/claude-sonnet-4-6"
FALLBACK_DATA_AGENT_MODELS = [
    "anthropic/claude-sonnet-4-6",
    "openai/gpt-4o-mini",
    "anthropic/claude-haiku-4-5",
    "openai/gpt-4o",
]


def _resolve_data_agent_model() -> ModelOption | None:
    configured = os.getenv("DATA_AGENT_MODEL", "").strip() or DEFAULT_DATA_AGENT_MODEL
    candidates = [configured, *FALLBACK_DATA_AGENT_MODELS]
    seen: set[str] = set()
    for model_id in candidates:
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        if is_model_available(model_id):
            try:
                return resolve_model_id(model_id)
            except ValueError:
                continue
    return None


def _resolve_report_agent_model(user_model: ModelOption) -> ModelOption:
    """Usa REPORT_AGENT_MODEL se configurado e disponível; senão o modelo do usuário."""
    configured = os.getenv("REPORT_AGENT_MODEL", "").strip()
    if configured and is_model_available(configured):
        try:
            return resolve_model_id(configured)
        except ValueError:
            pass
    return user_model


def run_report_pipeline(
    messages: list[dict],
    report_model: ModelOption,
    *,
    mcp_client: TM1MCPClient,
    username: str | None = None,
    status_cb: StatusCallback = None,
) -> tuple[str, str]:
    """
    Pipeline em 2 fases:
    1) Agente de dados (modelo barato) consulta TM1 → JSON
    2) Agente de relatório (modelo premium) gera HTML → /relatorio/{id}
    """
    data_model = _resolve_data_agent_model()
    if not data_model:
        return (
            "Nenhum modelo disponível para o agente de dados. "
            "Configure OPENAI_API_KEY ou ANTHROPIC_API_KEY.",
            "error",
        )

    report_option = _resolve_report_agent_model(report_model)

    logger.info(
        "Report pipeline: data=%s report=%s user=%s",
        data_model.id,
        report_option.id,
        username,
    )

    _emit(status_cb, "Consultando TM1 (agente de dados)...")
    data_payload, data_mode = run_data_agent(
        messages,
        data_model,
        mcp_client=mcp_client,
        username=username,
    )

    _emit(status_cb, "Gerando relatório HTML (agente de relatório)...")
    text, report_mode = run_report_agent(
        messages,
        data_payload,
        report_option,
        username=username,
    )

    mode = f"agents({data_mode}->{report_mode})"
    return text, mode
