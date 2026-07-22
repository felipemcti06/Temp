"""Tool para o LLM publicar relatórios HTML."""

from __future__ import annotations

import json
from typing import Any

from reports import create_report

REPORT_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_html_report",
            "description": (
                "Publica um relatório HTML e retorna a URL para visualização em /relatorio/{id}. "
                "Use quando o usuário pedir relatório, resumo executivo, dashboard ou HTML. "
                "Primeiro consulte o TM1 para obter os dados reais; depois monte o HTML com tabelas, "
                "KPIs e texto analítico. Nunca invente valores numéricos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Título do relatório, ex: 'Evolução do EBITDA — 2025'",
                    },
                    "html": {
                        "type": "string",
                        "description": (
                            "Conteúdo HTML do relatório (corpo ou documento completo). "
                            "Inclua h1, parágrafos de resumo executivo, tabelas e destaques."
                        ),
                    },
                },
                "required": ["title", "html"],
            },
        },
    },
]


def execute_report_tool(arguments: dict[str, Any], *, created_by: str | None = None) -> str:
    result = create_report(
        arguments["title"],
        arguments["html"],
        created_by=created_by,
    )
    return json.dumps(result, ensure_ascii=False)
