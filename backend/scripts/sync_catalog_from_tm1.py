#!/usr/bin/env python3
"""Sincroniza metrics_catalog.json e products_catalog.json a partir do TM1."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from catalog_sync import (  # noqa: E402
    DEFAULT_CUBE,
    format_sync_report,
    sync_catalogs_from_tm1,
    write_sync_report,
)
from tm1_mcp import TM1MCPClient, get_default_connection_id  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sincroniza glossário de métricas e produtos a partir do TM1 (via MCP).",
    )
    parser.add_argument(
        "--cube",
        default=os.getenv("SYNC_CUBE_NAME", DEFAULT_CUBE),
        help=f"Cubo TM1 de origem (default: {DEFAULT_CUBE})",
    )
    parser.add_argument(
        "--connection-id",
        default=os.getenv("TM1_CONNECTION_ID", "").strip() or None,
        help="UUID da conexão TM1 (default: TM1_CONNECTION_ID)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Grava metrics_catalog.json e products_catalog.json (default: dry-run)",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Remove entradas do catálogo cujas contas não existem mais no TM1",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Saída em JSON (diff + totais)",
    )
    args = parser.parse_args()
    dry_run = not args.write

    client = TM1MCPClient.from_env()
    connection_id = args.connection_id or get_default_connection_id()
    if not client or not connection_id:
        print(
            "Configure TM1_MCP_URL, TM1_MCP_TOKEN e TM1_CONNECTION_ID antes de sincronizar.",
            file=sys.stderr,
        )
        return 1

    report = sync_catalogs_from_tm1(
        client,
        connection_id,
        cube_name=args.cube,
        prune=args.prune,
    )

    if args.json:
        payload = {
            "cube": report.cube_name,
            "account_count": report.account_count,
            "product_count": report.product_count,
            "metrics": {
                "added": report.metrics.added,
                "updated": report.metrics.updated,
                "unchanged": report.metrics.unchanged,
                "removed": report.metrics.removed,
                "total": len(report.metrics_catalog),
            },
            "products": {
                "added": report.products.added,
                "updated": report.products.updated,
                "unchanged": report.products.unchanged,
                "removed": report.products.removed,
            },
            "dry_run": dry_run,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_sync_report(report))
        if dry_run:
            print("\n(dry-run — use --write para gravar os arquivos)")

    if not dry_run:
        write_sync_report(report)
        print("\nCatálogos gravados com sucesso.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
