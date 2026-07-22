"""Agente de relatório: modelo premium, recebe JSON, publica HTML."""

from __future__ import annotations

import json
from typing import Any

from llm_config import ModelOption
from llm_runner import ToolLoopConfig, run_tool_loop
from report_tools import REPORT_TOOL_DEFINITIONS, execute_report_tool

REPORT_AGENT_PROMPT = """Você é o Agente de Relatórios HTML. Você recebe dados JÁ CONSULTADOS do TM1
em JSON. Sua tarefa é gerar um relatório HTML profissional e publicá-lo.

Regras:
1. Use APENAS os números do JSON fornecido. NUNCA invente valores.
2. OBRIGATÓRIO: chame create_html_report com title e html.
3. NÃO diga "vou montar" — chame a ferramenta.
4. Inclua no HTML: título, resumo executivo, KPIs, tabela e (se série temporal) gráfico Chart.js.
5. Para Chart.js use CDN e canvas com altura definida:
   <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
   <canvas id="chart" style="max-width:900px;height:420px"></canvas>
6. Depois da tool retornar a URL, responda em português com um resumo curto e o link /relatorio/{id}.

Se o JSON tiver "error" ou series vazia, explique o problema ao usuário SEM inventar dados
e NÃO chame create_html_report.
"""

MAX_REPORT_ITERATIONS = 4


def run_report_agent(
    user_messages: list[dict],
    data_payload: dict[str, Any],
    option: ModelOption,
    *,
    username: str | None = None,
) -> tuple[str, str]:
    """Gera HTML a partir do JSON do data agent. Retorna (texto, mode)."""

    last_user = next(
        (m["content"] for m in reversed(user_messages) if m["role"] == "user"),
        "",
    )
    data_json = json.dumps(data_payload, ensure_ascii=False, indent=2)

    has_error = bool(data_payload.get("error")) or not data_payload.get("series")
    needs_report = not has_error

    agent_messages = [
        {
            "role": "user",
            "content": (
                f"Pedido original do usuário:\n{last_user}\n\n"
                f"Dados obtidos do TM1 (JSON):\n{data_json}\n\n"
                + (
                    "Publique o relatório HTML agora com create_html_report."
                    if needs_report
                    else "Os dados falharam ou estão vazios. Explique o problema ao usuário."
                )
            ),
        }
    ]

    def executor(fn_name: str, fn_args: dict[str, Any]) -> str:
        if fn_name == "create_html_report":
            return execute_report_tool(fn_args, created_by=username)
        return f"Ferramenta {fn_name} não disponível neste agente."

    cfg = ToolLoopConfig(
        messages=agent_messages,
        tools=list(REPORT_TOOL_DEFINITIONS) if needs_report else [],
        system_prompt=REPORT_AGENT_PROMPT,
        mcp_client=None,
        username=username,
        force_tools=needs_report,
        needs_report=needs_report,
        max_iterations=MAX_REPORT_ITERATIONS,
        max_tokens=8192,
        temperature=0.3,
        mode_prefix="report",
        tool_executor=executor,
    )

    if not needs_report:
        # Sem tools: resposta direta explicando o erro
        from llm_runner import generate_with_model

        text, mode = generate_with_model(
            agent_messages,
            option,
            mcp_client=None,
            force_tools=False,
            needs_report=False,
            username=username,
            tools=[],
            system_prompt=REPORT_AGENT_PROMPT,
            mode_prefix="report",
        )
        return text, mode

    return run_tool_loop(option, cfg)
