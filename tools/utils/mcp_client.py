import json
from typing import Any

import httpx


class McpError(Exception):
    pass


class McpAuthError(McpError):
    pass


class McpStreamableHttpClient:
    def __init__(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: float = 50,
    ):
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self._client = httpx.Client(timeout=httpx.Timeout(timeout))
        self._session_id: str | None = None
        self._id_counter = 0
        self._protocol_version = "2025-03-26"

    def close(self) -> None:
        self._client.close()

    def _next_id(self) -> int:
        self._id_counter += 1
        return self._id_counter

    def _send(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.headers:
            headers.update(self.headers)
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        headers["Mcp-Protocol-Version"] = self._protocol_version

        response = self._client.post(
            self.url,
            json=payload,
            headers=headers,
            timeout=httpx.Timeout(self.timeout),
            follow_redirects=True,
        )
        if response.status_code in {401, 403}:
            raise McpAuthError(f"MCP auth error: {response.status_code} {response.reason_phrase}")
        if not response.is_success:
            raise McpError(f"MCP error: {response.status_code} {response.reason_phrase}")
        session_header = response.headers.get("mcp-session-id")
        if session_header:
            self._session_id = session_header
        if not response.content:
            return {}
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json() if response.content else {}
        if "text/event-stream" in content_type:
            return self._parse_sse(response.text or "")
        raise McpError(f"Unsupported Content-Type: {content_type}")

    def _parse_sse(self, text: str) -> dict[str, Any]:
        last_data = None
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data:
                last_data = data
        if not last_data:
            return {}
        try:
            return json.loads(last_data)
        except Exception:
            return {}

    def initialize(self) -> None:
        init_data = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": self._protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "MCP Client", "version": "1.0.0"},
            },
        }
        response = self._send(init_data)
        if "error" in response:
            raise McpError(f"MCP initialize error: {response['error']}")
        notify_data = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
        response = self._send(notify_data)
        if "error" in response:
            raise McpError(f"MCP notifications/initialized error: {response['error']}")

    def list_tools(self) -> list[dict[str, Any]]:
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {},
        }
        response = self._send(request)
        if "error" in response:
            raise McpError(f"MCP tools/list error: {response['error']}")
        return response.get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        request = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        response = self._send(request)
        if "error" in response:
            raise McpError(f"MCP tools/call error: {response['error']}")
        return response.get("result", {}).get("content", [])


def create_client(
    mcp_url: str,
    headers: dict[str, Any] | None = None,
    timeout: float = 50,
) -> McpStreamableHttpClient:
    return McpStreamableHttpClient(url=mcp_url, headers=headers, timeout=timeout)
