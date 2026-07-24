"""Agente de dados: modelo barato, só tools TM1, saída JSON estruturada."""

from __future__ import annotations

import json
import re
from typing import Any

from llm_config import ModelOption
from llm_runner import ToolLoopConfig, run_tool_loop
from tm1_mcp import TM1MCPClient
from tm1_tools import OPENAI_TOOL_DEFINITIONS, execute_tm1_tool

DATA_AGENT_PROMPT = """Você é o Agente de Dados TM1. Sua ÚNICA tarefa é consultar o IBM Planning Analytics
e devolver um JSON estruturado com os dados reais.

Regras:
1. Use APENAS as ferramentas TM1 disponíveis.
2. NÃO gere HTML, Markdown de relatório ou texto longo para o usuário.
3. NÃO invente valores — só use o que as tools retornarem.
4. Para evolução MENSAL / EBITDA / DRE ao longo do ano:
   - Total consolidado: tm1_get_time_series(metric="EBITDA", year="2025")
   - Por produto: tm1_get_time_series(metric="EBITDA", year="2025", group_by="produto")
   - Por filial: tm1_get_time_series(metric="EBITDA", year="2025", group_by="filial")
   NÃO use tm1_get_cube_data para séries mensais (ela não retorna meses).
5. O catálogo resolve aliases (ex: "EBITDA" → "EBITDA Gerencial") e inclui:
   EBITDA, EBITDA %, Receita Operacional, Margem Financeira Bruta/Líquida,
   Resultado Operacional, Sobra do Exercício, Despesas Administrativas/Pessoal e %.
6. Versão padrão do realizado: REAL. Meses no modelo: 01..12.
7. Se o usuário citar um cubo, passe cube_name. Senão, o catálogo usa o cubo padrão da métrica.
8. Ao terminar, responda COM UM ÚNICO objeto JSON (sem markdown, sem ```), no formato:

{
  "metric": "EBITDA",
  "cube": "RTB.100.DRE_Produto",
  "period": "2025",
  "granularity": "monthly",
  "series": [{"label": "Jan", "value": 123.45, "formatted": "123,45"}],
  "summary": "Uma frase objetiva sobre a tendência",
  "notes": ["observações técnicas se houver"],
  "sources": [{"tool": "tm1_get_time_series", "mdx": "SELECT ..."}]
}

Você pode copiar/adaptar o JSON retornado por tm1_get_time_series.

Se não conseguir dados, retorne:
{"error": "motivo", "metric": null, "series": []}
"""

MAX_DATA_ITERATIONS = 8


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    return {
        "error": "Agente de dados não retornou JSON válido",
        "raw": text[:2000],
        "series": [],
    }


def run_data_agent(
    messages: list[dict],
    option: ModelOption,
    *,
    mcp_client: TM1MCPClient,
    username: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Consulta TM1 e retorna (payload_json, mode)."""

    def executor(fn_name: str, fn_args: dict[str, Any]) -> str:
        return execute_tm1_tool(mcp_client, fn_name, fn_args)

    cfg = ToolLoopConfig(
        messages=messages,
        tools=list(OPENAI_TOOL_DEFINITIONS),
        system_prompt=DATA_AGENT_PROMPT,
        mcp_client=mcp_client,
        username=username,
        force_tools=True,
        needs_report=False,
        max_iterations=MAX_DATA_ITERATIONS,
        max_tokens=4096,
        temperature=0.1,
        mode_prefix="data",
        tool_executor=executor,
    )

    text, mode = run_tool_loop(option, cfg)

    # Preferir resultado estruturado de tm1_get_time_series quando disponível
    for entry in reversed(cfg.tool_trace):
        if entry.get("tool") != "tm1_get_time_series":
            continue
        raw = entry.get("result") or entry.get("result_preview") or ""
        try:
            tool_payload = json.loads(raw)
        except json.JSONDecodeError:
            break
        if isinstance(tool_payload, dict) and tool_payload.get("series"):
            tool_payload["_mode"] = mode
            tool_payload["_tool_trace_count"] = len(cfg.tool_trace)
            tool_payload["_source"] = "tm1_get_time_series"
            return tool_payload, mode

    payload = _extract_json(text)
    payload["_mode"] = mode
    payload["_tool_trace_count"] = len(cfg.tool_trace)
    return payload, mode
