import json
from typing import Any

from tm1_mcp import TM1MCPClient, TM1MCPError, get_default_connection_id

# Fase 1 — somente leitura
PHASE1_TOOLS = [
  "ping",
  "list_connections",
  "list_cubes",
  "list_dimensions",
  "cube_summary",
  "dimension_summary",
]

OPENAI_TOOL_DEFINITIONS: list[dict[str, Any]] = [
  {
    "type": "function",
    "function": {
      "name": "tm1_ping",
      "description": "Testa conectividade com o servidor TM1. Retorna versão e tempo de resposta.",
      "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
      },
    },
  },
  {
    "type": "function",
    "function": {
      "name": "tm1_list_connections",
      "description": "Lista conexões TM1 disponíveis para o usuário.",
      "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
      },
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
          "cube_name": {
            "type": "string",
            "description": "Nome do cubo TM1.",
          },
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
          "dimension_name": {
            "type": "string",
            "description": "Nome da dimensão TM1.",
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
}


def _with_connection_id(args: dict[str, Any]) -> dict[str, Any]:
  connection_id = get_default_connection_id()
  if not connection_id:
    raise TM1MCPError("TM1_CONNECTION_ID não configurado")
  return {"connection_id": connection_id, **args}


def execute_tm1_tool(client: TM1MCPClient, tool_name: str, arguments: dict[str, Any]) -> str:
  mcp_tool = TOOL_TO_MCP.get(tool_name)
  if not mcp_tool:
    raise TM1MCPError(f"Tool desconhecida: {tool_name}")

  if mcp_tool == "list_connections":
    mcp_args: dict[str, Any] = {}
  else:
    mcp_args = _with_connection_id(arguments)

  result = client.call_tool(mcp_tool, mcp_args)
  if isinstance(result, (dict, list)):
    return json.dumps(result, ensure_ascii=False, indent=2)
  return str(result)
