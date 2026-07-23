"""Montagem de MDX e consultas estruturadas ao TM1."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tm1_mcp import TM1MCPClient, TM1MCPError
from tm1_cache import get_cached, set_cached

MONTH_LABELS = {
    "01": "Jan",
    "02": "Fev",
    "03": "Mar",
    "04": "Abr",
    "05": "Mai",
    "06": "Jun",
    "07": "Jul",
    "08": "Ago",
    "09": "Set",
    "10": "Out",
    "11": "Nov",
    "12": "Dez",
}

_CATALOG_PATH = Path(__file__).with_name("metrics_catalog.json")


def _load_catalog() -> dict[str, Any]:
    if not _CATALOG_PATH.exists():
        return {}
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def resolve_metric_catalog(metric: str | None) -> dict[str, Any] | None:
    if not metric:
        return None
    catalog = _load_catalog()
    key = metric.strip().lower()
    for name, cfg in catalog.items():
        aliases = [name.lower(), *[a.lower() for a in cfg.get("aliases", [])]]
        if key in aliases:
            return {"name": name, **cfg}
    return None


def _dim_names(summary: dict[str, Any]) -> list[str]:
    dims = summary.get("dimensions", [])
    return [d.get("Name", "") for d in dims if d.get("Name")]


def _find_measure_dim(dim_names: list[str], cube_name: str) -> str | None:
    for name in dim_names:
        if ".M." in name:
            return name
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


def _list_element_items(client: TM1MCPClient, connection_id: str, dimension: str, top: int = 200) -> list[dict]:
    elements = client.call_tool(
        "list_elements",
        {"connection_id": connection_id, "dimension_name": dimension, "top": top},
    )
    if isinstance(elements, list):
        return [i for i in elements if isinstance(i, dict)]
    if isinstance(elements, dict):
        return [elements]
    return []


def _list_element_names(client: TM1MCPClient, connection_id: str, dimension: str, top: int = 200) -> list[str]:
    return [i.get("Name", "") for i in _list_element_items(client, connection_id, dimension, top) if i.get("Name")]


def _list_product_leaves(client: TM1MCPClient, connection_id: str, produto_dim: str, *, limit: int = 12) -> list[str]:
    items = _list_element_items(client, connection_id, produto_dim, top=100)
    leaves: list[str] = []
    for item in items:
        name = item.get("Name", "")
        if not name or name in {"Total_Produto", "Nao_Alocado_Produto"}:
            continue
        if item.get("Type") == "Numeric":
            leaves.append(name)
    return leaves[:limit]


def _first_measure_element(client: TM1MCPClient, connection_id: str, measure_dim: str) -> str:
    names = _list_element_names(client, connection_id, measure_dim, top=20)
    return names[0] if names else "Valor"


def _find_total_element(names: list[str], *hints: str) -> str | None:
    lowered = [(n, n.lower()) for n in names]
    for hint in hints:
        h = hint.lower()
        for original, low in lowered:
            if h in low and ("total" in low or low.startswith("total")):
                return original
    for original, low in lowered:
        if low.startswith("total") or low.endswith("_total") or "total_" in low:
            return original
    return names[0] if names else None


def _resolve_account_element(
    client: TM1MCPClient,
    connection_id: str,
    account_dim: str,
    account: str,
) -> str:
    names = _list_element_names(client, connection_id, account_dim, top=300)
    if not names:
        return account

    target = account.strip().lower()
    for name in names:
        if name.lower() == target:
            return name

    # match parcial: "EBITDA" → "EBITDA Gerencial"
    candidates = [n for n in names if target in n.lower() or n.lower() in target]
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        # prefer exact alias containing the word as whole token
        for n in candidates:
            if re.search(rf"\b{re.escape(target)}\b", n.lower()):
                return n
        return candidates[0]

    raise TM1MCPError(
        f"Elemento '{account}' não encontrado em {account_dim}. "
        f"Exemplos: {', '.join(names[:12])}"
    )


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


def query_time_series(
    client: TM1MCPClient,
    connection_id: str,
    *,
    cube_name: str | None = None,
    metric: str | None = None,
    year: str = "2025",
    version: str | None = None,
    account: str | None = None,
    measure: str | None = None,
) -> dict[str, Any]:
    """
    Consulta série mensal (01-12) de uma métrica/conta em um cubo DRE.

    Resolve automaticamente dimensões (Ano, Mes, Versao, Conta, Filial, Produto, Medida)
    e aliases do metrics_catalog.json (ex: EBITDA → EBITDA Gerencial).
    """
    catalog = resolve_metric_catalog(metric)
    if catalog:
        cube_name = cube_name or catalog.get("cube")
        account = account or catalog.get("account")
        version = version or catalog.get("version")
        measure = measure or catalog.get("measure")
        metric_name = catalog.get("name") or metric
    else:
        metric_name = metric or account or "métrica"

    if not cube_name:
        raise TM1MCPError("Informe cube_name ou uma métrica do catálogo (ex: EBITDA)")
    if not account and metric:
        account = metric
    if not account:
        raise TM1MCPError("Informe account ou metric (ex: EBITDA / EBITDA Gerencial)")

    cache_payload = {
        "connection_id": connection_id,
        "cube_name": cube_name,
        "metric": metric,
        "year": year,
        "version": version,
        "account": account,
        "measure": measure,
        "group_by": None,
    }
    cached = get_cached("time_series", cache_payload)
    if cached:
        return cached

    summary = client.call_tool(
        "cube_summary",
        {"connection_id": connection_id, "cube_name": cube_name},
    )
    if not isinstance(summary, dict):
        raise TM1MCPError(f"Não foi possível obter estrutura do cubo {cube_name}")

    names = _dim_names(summary)
    measure_dim = _find_measure_dim(names, cube_name)
    ano_dim = _find_dim(names, "Ano", "Year")
    mes_dim = _find_dim(names, "Mes", "Month")
    versao_dim = _find_dim(names, "Versao", "Version", "Cenário", "Cenario")
    conta_dim = _find_dim(names, "Conta", "Account", "Gerencial")
    filial_dim = _find_dim(names, "Filial", "Empresa", "Entity", "Org")
    produto_dim = _find_dim(names, "Produto", "Product")

    if not measure_dim or not ano_dim or not mes_dim:
        raise TM1MCPError(
            f"Cubo {cube_name} precisa de dimensões de Medida (.M.), Ano e Mês. "
            f"Encontradas: {names}"
        )
    if not conta_dim:
        raise TM1MCPError(
            f"Cubo {cube_name} não tem dimensão de Conta/Gerencial. Dimensões: {names}"
        )

    measure_elem = measure or _first_measure_element(client, connection_id, measure_dim)
    account_elem = _resolve_account_element(client, connection_id, conta_dim, account)
    version_elem = version or "REAL"

    where_parts = [
        f"[{conta_dim}].[{account_elem}]",
        f"[{ano_dim}].[{year}]",
    ]
    if versao_dim:
        where_parts.append(f"[{versao_dim}].[{version_elem}]")

    if catalog:
        if filial_dim and catalog.get("filial"):
            where_parts.append(f"[{filial_dim}].[{catalog['filial']}]")
        if produto_dim and catalog.get("produto"):
            where_parts.append(f"[{produto_dim}].[{catalog['produto']}]")
    else:
        if filial_dim:
            filial_names = _list_element_names(client, connection_id, filial_dim, top=50)
            total = _find_total_element(filial_names, "filial", "empresa")
            if total:
                where_parts.append(f"[{filial_dim}].[{total}]")
        if produto_dim:
            produto_names = _list_element_names(client, connection_id, produto_dim, top=50)
            total = _find_total_element(produto_names, "produto", "product")
            if total:
                where_parts.append(f"[{produto_dim}].[{total}]")

    month_set = ",".join(f"[{mes_dim}].[{m}]" for m in MONTH_LABELS)
    mdx = (
        f"SELECT {{[{measure_dim}].[{measure_elem}]}} ON 0, "
        f"{{{month_set}}} ON 1 "
        f"FROM [{cube_name}] "
        f"WHERE ({','.join(where_parts)})"
    )

    raw = client.call_tool(
        "execute_mdx",
        {"connection_id": connection_id, "mdx": mdx, "top": 20, "skip": 0},
    )
    if not isinstance(raw, dict):
        raise TM1MCPError(f"Resposta MDX inválida: {raw}")

    cells = raw.get("cells") or []
    series = []
    for idx, month_code in enumerate(MONTH_LABELS):
        cell = cells[idx] if idx < len(cells) else {}
        value = cell.get("Value") if isinstance(cell, dict) else None
        series.append(
            {
                "label": MONTH_LABELS[month_code],
                "month": month_code,
                "value": value,
                "formatted": cell.get("FormattedValue") if isinstance(cell, dict) else None,
            }
        )

    numeric = [s["value"] for s in series if isinstance(s["value"], (int, float))]
    summary_text = ""
    if numeric:
        first, last = numeric[0], numeric[-1]
        if first:
            pct = ((last - first) / abs(first)) * 100
            summary_text = (
                f"{metric_name} em {year}: início {series[0]['formatted']}, "
                f"fim {series[-1]['formatted']} ({pct:+.1f}% no ano)."
            )
        else:
            summary_text = f"{metric_name} em {year}: série mensal obtida."

    result = {
        "metric": metric_name,
        "account": account_elem,
        "cube": cube_name,
        "period": year,
        "version": version_elem,
        "granularity": "monthly",
        "series": series,
        "summary": summary_text,
        "mdx": mdx,
        "sources": [{"tool": "tm1_get_time_series", "mdx": mdx}],
    }
    set_cached("time_series", cache_payload, result)
    return result


def query_time_series_by_product(
    client: TM1MCPClient,
    connection_id: str,
    *,
    cube_name: str | None = None,
    metric: str | None = None,
    year: str = "2025",
    version: str | None = None,
    account: str | None = None,
    measure: str | None = None,
    prompt_signature: str = "",
) -> dict[str, Any]:
    """Série mensal da métrica desagregada por produto (um dataset por produto)."""
    catalog = resolve_metric_catalog(metric)
    if catalog:
        cube_name = cube_name or catalog.get("cube")
        account = account or catalog.get("account")
        version = version or catalog.get("version")
        measure = measure or catalog.get("measure")
        metric_name = catalog.get("name") or metric
    else:
        metric_name = metric or account or "métrica"

    if not cube_name or not account:
        raise TM1MCPError("Informe metric/account e cube_name para consulta por produto")

    cache_payload = {
        "connection_id": connection_id,
        "cube_name": cube_name,
        "metric": metric,
        "year": year,
        "version": version,
        "account": account,
        "measure": measure,
        "group_by": "produto",
        "prompt_signature": prompt_signature,
    }
    cached = get_cached("time_series_by_product", cache_payload)
    if cached:
        return cached

    summary = client.call_tool(
        "cube_summary",
        {"connection_id": connection_id, "cube_name": cube_name},
    )
    if not isinstance(summary, dict):
        raise TM1MCPError(f"Não foi possível obter estrutura do cubo {cube_name}")

    names = _dim_names(summary)
    measure_dim = _find_measure_dim(names, cube_name)
    ano_dim = _find_dim(names, "Ano", "Year")
    mes_dim = _find_dim(names, "Mes", "Month")
    versao_dim = _find_dim(names, "Versao", "Version", "Cenário", "Cenario")
    conta_dim = _find_dim(names, "Conta", "Account", "Gerencial")
    filial_dim = _find_dim(names, "Filial", "Empresa", "Entity", "Org")
    produto_dim = _find_dim(names, "Produto", "Product")

    if not all([measure_dim, ano_dim, mes_dim, conta_dim, produto_dim]):
        raise TM1MCPError(f"Cubo {cube_name} não suporta consulta por produto. Dimensões: {names}")

    products = _list_product_leaves(client, connection_id, produto_dim, limit=12)
    if not products:
        raise TM1MCPError(f"Nenhum produto folha encontrado em {produto_dim}")

    measure_elem = measure or _first_measure_element(client, connection_id, measure_dim)
    account_elem = _resolve_account_element(client, connection_id, conta_dim, account)
    version_elem = version or "REAL"

    where_parts = [
        f"[{conta_dim}].[{account_elem}]",
        f"[{ano_dim}].[{year}]",
    ]
    if versao_dim:
        where_parts.append(f"[{versao_dim}].[{version_elem}]")
    if filial_dim and catalog and catalog.get("filial"):
        where_parts.append(f"[{filial_dim}].[{catalog['filial']}]")

    month_set = ",".join(f"[{mes_dim}].[{m}]" for m in MONTH_LABELS)
    product_set = ",".join(f"[{produto_dim}].[{p}]" for p in products)
    mdx = (
        f"SELECT {{[{measure_dim}].[{measure_elem}]}} ON 0, "
        f"{{{month_set}}} ON 1, "
        f"{{{product_set}}} ON 2 "
        f"FROM [{cube_name}] "
        f"WHERE ({','.join(where_parts)})"
    )

    raw = client.call_tool(
        "execute_mdx",
        {"connection_id": connection_id, "mdx": mdx, "top": len(products) * 12 + 5, "skip": 0},
    )
    if not isinstance(raw, dict):
        raise TM1MCPError(f"Resposta MDX inválida: {raw}")

    cells = raw.get("cells") or []
    n_months = len(MONTH_LABELS)
    series_groups: list[dict[str, Any]] = []
    for product_idx, product_name in enumerate(products):
        series = []
        for month_idx, month_code in enumerate(MONTH_LABELS):
            ordinal = product_idx * n_months + month_idx
            cell = cells[ordinal] if ordinal < len(cells) else {}
            value = cell.get("Value") if isinstance(cell, dict) else None
            series.append(
                {
                    "label": MONTH_LABELS[month_code],
                    "month": month_code,
                    "value": value,
                    "formatted": cell.get("FormattedValue") if isinstance(cell, dict) else None,
                }
            )
        series_groups.append({"name": product_name, "series": series})

    summary_text = (
        f"{metric_name} em {year} por produto: {len(products)} produtos, "
        f"série mensal Jan–Dez (versão {version_elem})."
    )

    result = {
        "metric": metric_name,
        "account": account_elem,
        "cube": cube_name,
        "period": year,
        "version": version_elem,
        "granularity": "monthly",
        "group_by": "produto",
        "products": products,
        "series_groups": series_groups,
        "summary": summary_text,
        "mdx": mdx,
        "sources": [{"tool": "query_time_series_by_product", "mdx": mdx}],
    }
    set_cached("time_series_by_product", cache_payload, result)
    return result
