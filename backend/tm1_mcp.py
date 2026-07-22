import json
import os
from typing import Any

import httpx


class TM1MCPError(Exception):
    pass


class TM1MCPClient:
    """Cliente HTTP para o MCP tm1-ide (protocolo JSON-RPC)."""

    def __init__(self, base_url: str, token: str):
        url = base_url.rstrip("/")
        self.url = url if url.endswith("/mcp") else f"{url}/mcp"
        self.token = token
        self._request_id = 0

    @classmethod
    def from_env(cls) -> "TM1MCPClient | None":
        base_url = os.getenv("TM1_MCP_URL", "").strip()
        token = os.getenv("TM1_MCP_TOKEN", "").strip()
        if not base_url or not token:
            return None
        return cls(base_url, token)

    def is_configured(self) -> bool:
        return bool(self.url and self.token)

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.token}",
        }

    def _parse_response(self, text: str) -> dict[str, Any]:
        text = text.strip()
        if not text:
            raise TM1MCPError("Resposta vazia do MCP")

        # SSE: linhas "data: {...}"
        if text.startswith("data:") or "\ndata:" in text:
            for line in text.splitlines():
                if line.startswith("data:"):
                    payload = line[5:].strip()
                    if payload and payload != "[DONE]":
                        return json.loads(payload)
            raise TM1MCPError("Nenhum evento SSE válido na resposta")

        return json.loads(text)

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params or {},
        }

        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(self.url, headers=self._headers(), json=body)
                response.raise_for_status()
                data = self._parse_response(response.text)
        except httpx.HTTPError as exc:
            raise TM1MCPError(f"Erro HTTP ao chamar MCP: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise TM1MCPError("Resposta inválida do MCP") from exc

        if "error" in data:
            err = data["error"]
            message = err.get("message", str(err))
            raise TM1MCPError(message)

        return data.get("result")

    def initialize(self) -> Any:
        return self._rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "chatbot", "version": "1.0"},
            },
        )

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        result = self._rpc(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )

        if isinstance(result, dict) and "content" in result:
            parts = []
            for item in result["content"]:
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
            if parts:
                combined = "\n".join(parts)
                try:
                    return json.loads(combined)
                except json.JSONDecodeError:
                    return combined

        return result


def get_default_connection_id() -> str | None:
    value = os.getenv("TM1_CONNECTION_ID", "").strip()
    return value or None


def tm1_is_configured() -> bool:
    client = TM1MCPClient.from_env()
    return client is not None and get_default_connection_id() is not None
