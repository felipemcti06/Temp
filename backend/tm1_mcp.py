import json
import os
from typing import Any

import httpx


class TM1MCPError(Exception):
    pass


class TM1MCPClient:
    """Cliente HTTP para o MCP tm1-ide (Streamable HTTP com sessão)."""

    def __init__(self, base_url: str, token: str):
        url = base_url.rstrip("/")
        self.url = url if url.endswith("/mcp") else f"{url}/mcp"
        self.token = token
        self._request_id = 0
        self._session_id: str | None = None

    @classmethod
    def from_env(cls) -> "TM1MCPClient | None":
        base_url = os.getenv("TM1_MCP_URL", "").strip()
        token = os.getenv("TM1_MCP_TOKEN", "").strip()
        if not base_url or not token:
            return None
        return cls(base_url, token)

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _headers(self, include_session: bool = False) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.token}",
        }
        if include_session and self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _parse_body(self, text: str) -> dict[str, Any] | None:
        text = text.strip()
        if not text:
            return None

        if text.startswith("data:") or "\ndata:" in text:
            for line in text.splitlines():
                if line.startswith("data:"):
                    payload = line[5:].strip()
                    if payload and payload != "[DONE]":
                        return json.loads(payload)
            return None

        return json.loads(text)

    def _http_error_detail(self, response: httpx.Response) -> str:
        try:
            body = response.json()
            if isinstance(body, dict):
                return body.get("message") or body.get("error") or body.get("detail") or str(body)
        except Exception:
            pass
        text = response.text.strip()
        return text[:300] if text else response.reason_phrase

    def _post(
        self,
        body: dict[str, Any],
        *,
        include_session: bool = False,
        allow_empty: bool = False,
    ) -> dict[str, Any] | None:
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    self.url,
                    headers=self._headers(include_session=include_session),
                    json=body,
                )
        except httpx.HTTPError as exc:
            raise TM1MCPError(f"Erro HTTP ao chamar MCP: {exc}") from exc

        if response.status_code == 404 and include_session:
            self._session_id = None
            raise TM1MCPError("Sessão MCP expirada")

        if response.status_code >= 400:
            detail = self._http_error_detail(response)
            raise TM1MCPError(
                f"HTTP {response.status_code} ao chamar MCP: {detail}"
            )

        session_header = response.headers.get("mcp-session-id") or response.headers.get(
            "Mcp-Session-Id"
        )
        if session_header:
            self._session_id = session_header

        if allow_empty and not response.text.strip():
            return None

        try:
            data = self._parse_body(response.text)
        except json.JSONDecodeError as exc:
            raise TM1MCPError("Resposta inválida do MCP") from exc

        if data and "error" in data:
            err = data["error"]
            message = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            raise TM1MCPError(message)

        return data

    def _start_session(self) -> None:
        init_body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "chatbot", "version": "1.0"},
            },
        }

        data = self._post(init_body, include_session=False)
        if not self._session_id:
            raise TM1MCPError("MCP não retornou Mcp-Session-Id na inicialização")

        if data is None:
            raise TM1MCPError("Resposta vazia na inicialização do MCP")

        initialized_body = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
        self._post(initialized_body, include_session=True, allow_empty=True)

    def _ensure_session(self) -> None:
        if not self._session_id:
            self._start_session()

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._ensure_session()

        body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params or {},
        }

        try:
            data = self._post(body, include_session=True)
        except TM1MCPError as exc:
            if "Sessão MCP expirada" in str(exc):
                self._start_session()
                data = self._post(body, include_session=True)
            else:
                raise

        if not data:
            raise TM1MCPError("Resposta vazia do MCP")

        return data.get("result")

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        result = self._rpc(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )

        if isinstance(result, dict) and "content" in result:
            parts = []
            for item in result["content"]:
                if item.get("type") == "text":
                    text = (item.get("text") or "").strip()
                    if text:
                        parts.append(text)
            if parts:
                merged: list[Any] = []
                for part in parts:
                    parsed = self._parse_tool_payload(part)
                    if isinstance(parsed, dict):
                        merged.append(parsed)
                    elif isinstance(parsed, list):
                        merged.extend(parsed)
                if merged:
                    return merged if len(merged) > 1 else merged[0]

                combined = "\n".join(parts)
                parsed = self._parse_tool_payload(combined)
                if parsed is not None:
                    return parsed
                return combined

        return result

    @staticmethod
    def _parse_tool_payload(text: str) -> Any | None:
        text = text.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        items: list[Any] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        if len(items) > 1:
            return items
        if len(items) == 1:
            return items[0]

        # Objetos JSON concatenados: {...}{...}
        if text.startswith("{") and "}{" in text:
            chunks = text.replace("}{", "}\n{").splitlines()
            for line in chunks:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            if len(items) > 1:
                return items
            if len(items) == 1:
                return items[0]

        return None


def get_default_connection_id() -> str | None:
    value = os.getenv("TM1_CONNECTION_ID", "").strip()
    return value or None


def tm1_is_configured() -> bool:
    client = TM1MCPClient.from_env()
    return client is not None and get_default_connection_id() is not None
