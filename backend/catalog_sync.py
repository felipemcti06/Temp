"""Sincronização de glossários (métricas e produtos) a partir do TM1."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tm1_mcp import TM1MCPClient, TM1MCPError
from tm1_mdx_builder import (
    _dim_names,
    _find_dim,
    _find_total_element,
    _list_element_items,
    _list_element_names,
    _parse_element_items,
)

BACKEND_DIR = Path(__file__).resolve().parent
METRICS_CATALOG_PATH = BACKEND_DIR / "metrics_catalog.json"
PRODUCTS_CATALOG_PATH = BACKEND_DIR / "products_catalog.json"

DEFAULT_CUBE = "RTB.100.DRE_Produto"
DEFAULT_VERSION = "REAL"
DEFAULT_MEASURE = "Valor"
DEFAULT_FORMAT = "currency"

ACCOUNT_SKIP_PATTERNS = re.compile(
    r"^(total|nao_alocado|não_alocado|nao alocado|dummy|temp|teste)\b",
    re.IGNORECASE,
)
GERENCIAL_CODE_PATTERN = re.compile(r"^D\.\d", re.IGNORECASE)
STRUCTURAL_ACCOUNT_NAMES = {
    "total conta dre",
    "total_conta_dre",
}


@dataclass
class CubeDefaults:
    cube_name: str
    account_dim: str
    produto_dim: str | None
    filial_dim: str | None
    measure_dim: str | None
    version: str = DEFAULT_VERSION
    measure: str = DEFAULT_MEASURE
    filial: str | None = None
    produto: str | None = None


@dataclass
class CatalogDiff:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


@dataclass
class SyncReport:
    cube_name: str
    metrics: CatalogDiff
    products: CatalogDiff
    metrics_catalog: dict[str, Any]
    products_catalog: dict[str, Any]
    account_count: int = 0
    product_count: int = 0
    gerencial_only: bool = True


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def infer_format(account_name: str) -> str:
    if "%" in account_name or "percent" in account_name.lower():
        return "percent"
    return DEFAULT_FORMAT


def default_aliases(metric_key: str, account_name: str) -> list[str]:
    aliases: list[str] = []
    for candidate in (metric_key, account_name):
        lowered = candidate.strip().lower()
        if lowered and lowered not in aliases:
            aliases.append(lowered)
    return aliases


def discover_cube_defaults(
    client: TM1MCPClient,
    connection_id: str,
    cube_name: str,
) -> CubeDefaults:
    summary = client.call_tool(
        "cube_summary",
        {"connection_id": connection_id, "cube_name": cube_name},
    )
    if not isinstance(summary, dict):
        raise TM1MCPError(f"Não foi possível obter estrutura do cubo {cube_name}")

    names = _dim_names(summary)
    account_dim = _find_dim(names, "Conta", "Account", "Gerencial")
    produto_dim = _find_dim(names, "Produto", "Product")
    filial_dim = _find_dim(names, "Filial", "Empresa", "Entity", "Org")
    measure_dim = _find_dim(names, ".M.", "Measure", "Medida")

    if not account_dim:
        raise TM1MCPError(f"Cubo {cube_name} não possui dimensão de Conta/Gerencial")

    filial_total = None
    produto_total = None
    if filial_dim:
        filial_names = _list_element_names(client, connection_id, filial_dim, top=80)
        filial_total = _find_total_element(filial_names, "filial", "empresa")
    if produto_dim:
        produto_names = _list_element_names(client, connection_id, produto_dim, top=80)
        produto_total = _find_total_element(produto_names, "produto", "product")

    return CubeDefaults(
        cube_name=cube_name,
        account_dim=account_dim,
        produto_dim=produto_dim,
        filial_dim=filial_dim,
        measure_dim=measure_dim,
        filial=filial_total,
        produto=produto_total,
    )


def _is_structural_account_code(name: str) -> bool:
    return bool(GERENCIAL_CODE_PATTERN.match(name.strip()))


def _is_gerencial_named_account(name: str, item: dict[str, Any]) -> bool:
    """Inclui linhas gerenciais nomeadas; exclui códigos D.x.x.x e totais estruturais."""
    if _is_structural_account_code(name):
        return False

    lowered = name.strip().lower()
    if lowered in STRUCTURAL_ACCOUNT_NAMES:
        return False

    if "%" in name:
        return True

    elem_type = (item.get("Type") or "").lower()
    if elem_type == "consolidated" and re.search(r"[A-Za-zÀ-ÿ]{2,}", name):
        return True

    return False


def _should_include_account(
    name: str,
    item: dict[str, Any],
    *,
    gerencial_only: bool = True,
) -> bool:
    if not name or ACCOUNT_SKIP_PATTERNS.search(name):
        return False

    lowered = name.lower()
    if lowered.startswith("total_") or lowered.endswith("_total"):
        return False

    if gerencial_only:
        return _is_gerencial_named_account(name, item)

    elem_type = (item.get("Type") or "").lower()
    if elem_type == "numeric":
        return True
    if elem_type == "consolidated":
        return True
    if item.get("Level") == 0:
        return True
    return False


def fetch_account_elements(
    client: TM1MCPClient,
    connection_id: str,
    account_dim: str,
    *,
    top: int = 500,
    gerencial_only: bool = True,
) -> list[str]:
    items = _list_element_items(client, connection_id, account_dim, top=top)
    names: list[str] = []
    seen: set[str] = set()

    for item in items:
        name = item.get("Name", "")
        if not name or name in seen:
            continue
        if not _should_include_account(name, item, gerencial_only=gerencial_only):
            continue
        seen.add(name)
        names.append(name)

    return sorted(names, key=str.lower)


def fetch_product_leaves(
    client: TM1MCPClient,
    connection_id: str,
    produto_dim: str,
    *,
    top: int = 200,
) -> list[str]:
    items = _list_element_items(client, connection_id, produto_dim, top=top)
    excluded = {"Total_Produto", "Nao_Alocado_Produto"}
    leaves: list[str] = []
    seen: set[str] = set()

    for item in items:
        name = item.get("Name", "")
        if not name or name in excluded or name in seen:
            continue
        elem_type = (item.get("Type") or "").lower()
        if elem_type == "numeric":
            leaves.append(name)
            seen.add(name)
            continue
        if elem_type == "consolidated" or name.lower().startswith("total"):
            continue
        if item.get("Level") == 0:
            leaves.append(name)
            seen.add(name)

    if not leaves:
        for item in items:
            name = item.get("Name", "")
            if not name or name in excluded or name in seen:
                continue
            if name.lower().startswith("total"):
                continue
            leaves.append(name)
            seen.add(name)

    return sorted(leaves, key=str.lower)


def _find_existing_key(catalog: dict[str, Any], account_name: str) -> str | None:
    target = account_name.strip().lower()
    for key, cfg in catalog.items():
        account = str(cfg.get("account", "")).strip().lower()
        if account == target:
            return key
        if key.strip().lower() == target:
            return key
    return None


def _merge_aliases(existing: list[str] | None, metric_key: str, account_name: str) -> list[str]:
    merged: list[str] = []
    for alias in [*(existing or []), *default_aliases(metric_key, account_name)]:
        cleaned = alias.strip()
        if cleaned and cleaned not in merged:
            merged.append(cleaned)
    return merged


def merge_metrics_catalog(
    existing: dict[str, Any],
    accounts: list[str],
    defaults: CubeDefaults,
    *,
    prune: bool = False,
) -> tuple[dict[str, Any], CatalogDiff]:
    merged = {key: dict(value) for key, value in existing.items()}
    diff = CatalogDiff()
    seen_accounts = set()

    for account_name in accounts:
        seen_accounts.add(account_name.lower())
        existing_key = _find_existing_key(merged, account_name)
        metric_key = existing_key or account_name

        base_entry = {
            "cube": defaults.cube_name,
            "account": account_name,
            "account_dim_hint": "Conta",
            "version": defaults.version,
            "measure": defaults.measure,
            "format": infer_format(account_name),
        }
        if defaults.filial:
            base_entry["filial"] = defaults.filial
        if defaults.produto:
            base_entry["produto"] = defaults.produto

        if existing_key:
            current = merged[existing_key]
            updated_entry = dict(current)
            changed = False

            for field, value in base_entry.items():
                if updated_entry.get(field) != value:
                    updated_entry[field] = value
                    changed = True

            aliases = _merge_aliases(current.get("aliases"), existing_key, account_name)
            if aliases != current.get("aliases"):
                updated_entry["aliases"] = aliases
                changed = True

            if changed:
                merged[existing_key] = updated_entry
                diff.updated.append(existing_key)
            else:
                diff.unchanged.append(existing_key)
            continue

        merged[metric_key] = {
            **base_entry,
            "aliases": default_aliases(metric_key, account_name),
        }
        diff.added.append(metric_key)

    if prune:
        for key, cfg in list(merged.items()):
            account = str(cfg.get("account", "")).strip().lower()
            if account and account not in seen_accounts:
                diff.removed.append(key)
                merged.pop(key, None)

    return merged, diff


def merge_products_catalog(
    existing: dict[str, Any],
    cube_name: str,
    produto_dim: str,
    products: list[str],
) -> tuple[dict[str, Any], CatalogDiff]:
    merged = dict(existing)
    cube_cfg = dict(merged.get(cube_name) or {})
    previous = cube_cfg.get(produto_dim) or cube_cfg.get("ALL.D.Produto") or []

    if products == previous:
        diff = CatalogDiff(unchanged=[f"{cube_name}/{produto_dim}"])
        return merged, diff

    cube_cfg[produto_dim] = products
    merged[cube_name] = cube_cfg

    diff = CatalogDiff(updated=[f"{cube_name}/{produto_dim}"])
    if not previous:
        diff.added.append(f"{cube_name}/{produto_dim}")
    return merged, diff


def sync_catalogs_from_tm1(
    client: TM1MCPClient,
    connection_id: str,
    *,
    cube_name: str = DEFAULT_CUBE,
    prune: bool = False,
    gerencial_only: bool = True,
) -> SyncReport:
    defaults = discover_cube_defaults(client, connection_id, cube_name)
    accounts = fetch_account_elements(
        client,
        connection_id,
        defaults.account_dim,
        gerencial_only=gerencial_only,
    )

    existing_metrics = load_json(METRICS_CATALOG_PATH)
    metrics_catalog, metrics_diff = merge_metrics_catalog(
        existing_metrics,
        accounts,
        defaults,
        prune=prune,
    )

    existing_products = load_json(PRODUCTS_CATALOG_PATH)
    products_diff = CatalogDiff()
    products_catalog = existing_products

    if defaults.produto_dim:
        products = fetch_product_leaves(client, connection_id, defaults.produto_dim)
        products_catalog, products_diff = merge_products_catalog(
            existing_products,
            cube_name,
            defaults.produto_dim,
            products,
        )
        product_count = len(products)
    else:
        product_count = 0

    return SyncReport(
        cube_name=cube_name,
        metrics=metrics_diff,
        products=products_diff,
        metrics_catalog=metrics_catalog,
        products_catalog=products_catalog,
        account_count=len(accounts),
        product_count=product_count,
        gerencial_only=gerencial_only,
    )


def write_sync_report(report: SyncReport) -> None:
    save_json(METRICS_CATALOG_PATH, report.metrics_catalog)
    save_json(PRODUCTS_CATALOG_PATH, report.products_catalog)


def format_sync_report(report: SyncReport) -> str:
    lines = [
        f"Cubo: {report.cube_name}",
        f"Filtro: {'linhas gerenciais nomeadas' if report.gerencial_only else 'todas as contas'}",
        f"Contas TM1: {report.account_count}",
        f"Produtos TM1: {report.product_count}",
        "",
        "Métricas:",
        f"  + adicionadas ({len(report.metrics.added)}): {', '.join(report.metrics.added[:20]) or '—'}",
        f"  ~ atualizadas ({len(report.metrics.updated)}): {', '.join(report.metrics.updated[:20]) or '—'}",
        f"  = inalteradas ({len(report.metrics.unchanged)})",
    ]
    if report.metrics.removed:
        lines.append(f"  - removidas ({len(report.metrics.removed)}): {', '.join(report.metrics.removed[:20])}")

    lines.extend(
        [
            "",
            "Produtos:",
            f"  + adicionadas ({len(report.products.added)}): {', '.join(report.products.added[:20]) or '—'}",
            f"  ~ atualizadas ({len(report.products.updated)}): {', '.join(report.products.updated[:20]) or '—'}",
            f"  = inalteradas ({len(report.products.unchanged)})",
        ]
    )
    if report.products.removed:
        lines.append(f"  - removidas ({len(report.products.removed)}): {', '.join(report.products.removed[:20])}")

    lines.append("")
    lines.append(f"Total métricas no catálogo: {len(report.metrics_catalog)}")
    return "\n".join(lines)
