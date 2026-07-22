"""Glossário de métricas e parser de pedidos de relatório."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

_CATALOG_PATH = Path(__file__).with_name("metrics_catalog.json")

REPORT_KEYWORDS = re.compile(
    r"\b(html|relatório|relatorio|dashboard|executivo|gráfico|grafico)\b",
    re.IGNORECASE,
)
YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")


@dataclass(frozen=True)
class ReportRequest:
    metric_key: str
    metric_label: str
    year: str
    cube: str
    version: str
    format: str


def load_catalog() -> dict[str, Any]:
    if not _CATALOG_PATH.exists():
        return {}
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def list_catalog_metrics() -> list[str]:
    return list(load_catalog().keys())


def resolve_metric(text: str) -> tuple[str, dict[str, Any]] | None:
    """Encontra a métrica do catálogo citada no texto (alias mais longo primeiro)."""
    catalog = load_catalog()
    if not catalog:
        return None

    lowered = text.lower()
    matches: list[tuple[int, str, dict[str, Any]]] = []

    for name, cfg in catalog.items():
        aliases = [name, *cfg.get("aliases", [])]
        for alias in aliases:
            alias_lower = alias.lower().strip()
            if not alias_lower:
                continue
            pattern = rf"\b{re.escape(alias_lower)}\b"
            if re.search(pattern, lowered):
                matches.append((len(alias_lower), name, cfg))

    if not matches:
        return None

    matches.sort(key=lambda item: item[0], reverse=True)
    _, name, cfg = matches[0]
    return name, {"name": name, **cfg}


def extract_year(text: str) -> str:
    match = YEAR_PATTERN.search(text)
    if match:
        return match.group(1)
    return str(datetime.now().year)


def is_report_request(text: str) -> bool:
    return bool(REPORT_KEYWORDS.search(text))


def parse_report_request(text: str) -> ReportRequest | None:
    """
    Interpreta pedidos do tipo "relatório/gráfico de EBITDA em 2025".
    Retorna None se não houver métrica reconhecida ou palavra-chave de relatório.
    """
    if not is_report_request(text):
        return None

    resolved = resolve_metric(text)
    if not resolved:
        return None

    metric_key, cfg = resolved
    year = extract_year(text)

    return ReportRequest(
        metric_key=metric_key,
        metric_label=cfg.get("name") or metric_key,
        year=year,
        cube=cfg.get("cube", "RTB.100.DRE_Produto"),
        version=cfg.get("version", "REAL"),
        format=cfg.get("format", "currency"),
    )
