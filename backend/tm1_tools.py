import json
from typing import Any

from tm1_mcp import TM1MCPClient, TM1MCPError, get_default_connection_id
from tm1_mdx_builder import query_cube_data

MAX_TOOL_RESULT_CHARS = 12_000
DEFAULT_MDX_TOP = 50

# Fase 1 — leitura básica
PHASE1_TOOLS = [
    "ping",
    "list_connections",
    "list_cubes",
    "list_dimensions",
    "cube_summary",
    "dimension_summary",
]

# Fase 2 — consultas e busca
PHASE2_TOOLS = [
    "execute_mdx",
    "search",
    "search_in_rules",
    "get_cube_rules",
    "list_processes",
    "list_elements",
]

OPENAI_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "tm1_ping",
            "description": "Testa conectividade com o servidor TM1. Retorna versão e tempo de resposta.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tm1_list_connections",
            "description": "Lista conexões TM1 disponíveis para o usuário.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tm1_list_cubes",
            "description": "Lista todos os cubos do modelo TM1.",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_control": {
                        "type": "boolean",
                        "description": "Incluir cubos de controle (prefixo }). Padrão: false.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tm1_list_dimensions",
            "description": "Lista todas as dimensões do modelo TM1.",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_control": {
                        "type": "boolean",
                        "description": "Incluir dimensões de controle (prefixo }). Padrão: false.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tm1_cube_summary",
            "description": "Retorna resumo de um cubo: dimensões, regras, feeders e última atualização.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cube_name": {"type": "string", "description": "Nome do cubo TM1."},
                },
                "required": ["cube_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tm1_dimension_summary",
            "description": "Retorna resumo de uma dimensão: hierarquias, contagem de elementos e amostra.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dimension_name": {"type": "string", "description": "Nome da dimensão TM1."},
                },
                "required": ["dimension_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tm1_get_cube_data",
            "description": (
                "Consulta dados de um cubo TM1 de forma automática (monta o MDX correto). "
                "PREFERIR esta tool em vez de tm1_execute_mdx quando o usuário pedir valores, "
                "totais ou dados de um ano/mês."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cube_name": {"type": "string", "description": "Nome do cubo, ex: RTB.100.DRE_Produto"},
                    "year": {"type": "string", "description": "Ano, ex: 2025"},
                    "month": {"type": "string", "description": "Mês (opcional), ex: Jan ou 01"},
                    "measure": {
                        "type": "string",
                        "description": "Medida (opcional). Padrão: Valor ou primeira medida numérica.",
                    },
                    "top": {"type": "integer", "description": "Máximo de células. Padrão: 50."},
                },
                "required": ["cube_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tm1_execute_mdx",
            "description": (
                "Executa MDX manualmente. Use apenas se tm1_get_cube_data não atender. "
                "Sintaxe TM1: SELECT {[Dim].[Elem]} ON 0, {[Dim2].[Elem2]} ON 1 FROM [Cubo]"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mdx": {
                        "type": "string",
                        "description": "Consulta MDX completa, ex: SELECT {[Medida].[Valor]} ON 0, {[Ano].[2024]} ON 1 FROM [Cubo]",
                    },
                    "top": {
                        "type": "integer",
                        "description": "Máximo de células retornadas. Padrão: 50.",
                    },
                    "skip": {
                        "type": "integer",
                        "description": "Células a pular (paginação). Padrão: 0.",
                    },
                },
                "required": ["mdx"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tm1_search",
            "description": "Busca textual no modelo TM1 (nomes de cubos, dimensões, processos, regras).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Termo de busca, ex: 'Vendas', 'DB(', nome de processo.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tm1_search_in_rules",
            "description": (
                "Busca texto apenas nas regras e feeders dos cubos. "
                "Útil para achar referências DB(), STET, ISLEAF, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Texto ou padrão a buscar nas regras."},
                    "include_feeders": {
                        "type": "boolean",
                        "description": "Incluir seção FEEDERS. Padrão: true.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tm1_get_cube_rules",
            "description": "Retorna o texto completo das regras de um cubo TM1.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cube_name": {"type": "string", "description": "Nome do cubo."},
                },
                "required": ["cube_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tm1_list_processes",
            "description": "Lista processos TI (TurboIntegrator) do modelo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_control": {
                        "type": "boolean",
                        "description": "Incluir processos de controle. Padrão: false.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tm1_list_elements",
            "description": "Lista elementos de uma dimensão TM1 (com paginação).",
            "parameters": {
                "type": "object",
                "properties": {
                    "dimension_name": {"type": "string", "description": "Nome da dimensão."},
                    "top": {
                        "type": "integer",
                        "description": "Máximo de elementos. Padrão: 50.",
                    },
                    "skip": {
                        "type": "integer",
                        "description": "Elementos a pular. Padrão: 0.",
                    },
                },
                "required": ["dimension_name"],
            },
        },
    },
]

TOOL_TO_MCP: dict[str, str] = {
    "tm1_ping": "ping",
    "tm1_list_connections": "list_connections",
    "tm1_list_cubes": "list_cubes",
    "tm1_list_dimensions": "list_dimensions",
    "tm1_cube_summary": "cube_summary",
    "tm1_dimension_summary": "dimension_summary",
    "tm1_execute_mdx": "execute_mdx",
    "tm1_search": "search",
    "tm1_search_in_rules": "search_in_rules",
    "tm1_get_cube_rules": "get_cube_rules",
    "tm1_list_processes": "list_processes",
    "tm1_list_elements": "list_elements",
}


def _with_connection_id(args: dict[str, Any]) -> dict[str, Any]:
    connection_id = get_default_connection_id()
    if not connection_id:
        raise TM1MCPError("TM1_CONNECTION_ID não configurado")
    return {"connection_id": connection_id, **args}


def _prepare_mcp_args(mcp_tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if mcp_tool == "list_connections":
        return {}

    args = _with_connection_id(arguments)

    if mcp_tool == "execute_mdx":
        args.setdefault("top", DEFAULT_MDX_TOP)
        args.setdefault("skip", 0)
    elif mcp_tool == "list_elements":
        args.setdefault("top", 50)
        args.setdefault("skip", 0)
    elif mcp_tool == "search_in_rules":
        args.setdefault("include_feeders", True)
        args.setdefault("ignore_case", True)

    return args


def _format_result(result: Any) -> str:
    if isinstance(result, (dict, list)):
        text = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        text = str(result)

    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = (
            text[:MAX_TOOL_RESULT_CHARS]
            + f"\n\n... [resultado truncado — {len(text)} caracteres no total]"
        )
    return text



def execute_tm1_tool(client: TM1MCPClient, tool_name: str, arguments: dict[str, Any]) -> str:
    if tool_name == "tm1_get_cube_data":
        connection_id = get_default_connection_id()
        if not connection_id:
            raise TM1MCPError("TM1_CONNECTION_ID não configurado")
        result = query_cube_data(
            client,
            connection_id,
            arguments["cube_name"],
            year=arguments.get("year"),
            month=arguments.get("month"),
            measure=arguments.get("measure"),
            top=arguments.get("top", DEFAULT_MDX_TOP),
        )
        return _format_result(result)

    mcp_tool = TOOL_TO_MCP.get(tool_name)
    if not mcp_tool:
        raise TM1MCPError(f"Tool desconhecida: {tool_name}")

    mcp_args = _prepare_mcp_args(mcp_tool, arguments)
    result = client.call_tool(mcp_tool, mcp_args)
    return _format_result(result)
