import re
from typing import Any

from tm1_mcp import TM1MCPClient, TM1MCPError


def _dim_names(summary: dict[str, Any]) -> list[str]:
    dims = summary.get("dimensions", [])
    return [d.get("Name", "") for d in dims if d.get("Name")]


def _find_measure_dim(dim_names: list[str], cube_name: str) -> str | None:
    for name in dim_names:
        if ".M." in name:
            return name
    # fallback: cubo com sufixo .M.Cubo
    prefix = cube_name.split(".")[-1] if "." in cube_name else cube_name
    for name in dim_names:
        if name.endswith(f".M.{prefix}") or name.endswith(".M." + cube_name):
            return name
    return None


def _find_dim(dim_names: list[str], *hints: str) -> str | None:
    for hint in hints:
        for name in dim_names:
            if hint.lower() in name.lower():
                return name
    return None


def _first_measure_element(client: TM1MCPClient, connection_id: str, measure_dim: str) -> str:
    elements = client.call_tool(
        "list_elements",
        {"connection_id": connection_id, "dimension_name": measure_dim, "top": 20},
    )

    if isinstance(elements, list):
        items = elements
    elif isinstance(elements, dict):
        items = [elements]
    else:
        items = []

    for item in items:
        if isinstance(item, dict) and item.get("Type") == "Numeric":
            return item.get("Name", "Valor")

    if items and isinstance(items[0], dict):
        return items[0].get("Name", "Valor")
    return "Valor"


def build_cube_data_mdx(
    client: TM1MCPClient,
    connection_id: str,
    cube_name: str,
    *,
    year: str | None = None,
    month: str | None = None,
    measure: str | None = None,
) -> str:
    summary = client.call_tool(
        "cube_summary",
        {"connection_id": connection_id, "cube_name": cube_name},
    )
    if not isinstance(summary, dict):
        raise TM1MCPError(f"Não foi possível obter estrutura do cubo {cube_name}")

    names = _dim_names(summary)
    measure_dim = _find_measure_dim(names, cube_name)
    if not measure_dim:
        raise TM1MCPError(f"Cubo {cube_name} não possui dimensão de medida (.M.)")

    measure_elem = measure or _first_measure_element(client, connection_id, measure_dim)
    ano_dim = _find_dim(names, "Ano", "Year")
    mes_dim = _find_dim(names, "Mes", "Month")

    parts = [f"SELECT {{[{measure_dim}].[{measure_elem}]}} ON 0"]
    axis = 1

    if year and ano_dim:
        parts.append(f", {{[{ano_dim}].[{year}]}} ON {axis}")
        axis += 1

    if month and mes_dim:
        parts.append(f", {{[{mes_dim}].[{month}]}} ON {axis}")
        axis += 1

    parts.append(f" FROM [{cube_name}]")
    return "".join(parts)


def simplify_mdx_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"raw": result}

    cells = result.get("cells", [])
    simplified = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        simplified.append(
            {
                "valor": cell.get("Value"),
                "formatado": cell.get("FormattedValue"),
                "status": cell.get("Status"),
            }
        )

    return {
        "cubo": result.get("cube"),
        "mdx_eixos": result.get("tuple_count_per_axis"),
        "celulas": simplified,
        "total_celulas": len(simplified),
    }


def query_cube_data(
    client: TM1MCPClient,
    connection_id: str,
    cube_name: str,
    *,
    year: str | None = None,
    month: str | None = None,
    measure: str | None = None,
    top: int = 50,
) -> dict[str, Any]:
    mdx = build_cube_data_mdx(
        client,
        connection_id,
        cube_name,
        year=year,
        month=month,
        measure=measure,
    )

    raw = client.call_tool(
        "execute_mdx",
        {"connection_id": connection_id, "mdx": mdx, "top": top, "skip": 0},
    )

    return {
        "mdx": mdx,
        "resultado": simplify_mdx_result(raw),
    }
