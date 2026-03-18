import json
import logging
import time
from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from tools.utils.auth import (
    build_auth_headers,
    build_login_url,
    create_state,
    find_server_by_id,
    get_access_token,
    get_servers,
    parse_mcp_servers_config,
    resolve_server_oauth_config_cached,
)
from tools.utils.mcp_client import McpAuthError, create_client

logger = logging.getLogger(__name__)


class MCPToolCall(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        started_at = time.perf_counter()
        tool_ref = (tool_parameters.get("tool_ref") or "").strip()
        if not tool_ref:
            yield self.create_text_message(
                "Please fill in tool_ref with the exact value returned by mcp_tool_list (server_id::tool_name)."
            )
            return
        if "::" not in tool_ref:
            yield self.create_text_message("tool_ref must be in server_id::tool_name format.")
            return
        server_id, tool_name = tool_ref.split("::", 1)
        server_id = server_id.strip()
        tool_name = tool_name.strip()
        if not server_id or not tool_name:
            yield self.create_text_message("tool_ref must be in server_id::tool_name format.")
            return

        input_raw = tool_parameters.get("input")
        if input_raw in (None, ""):
            # Backward compatibility for older parameter name.
            input_raw = tool_parameters.get("arguments")
        if input_raw in (None, ""):
            arguments: dict[str, Any] = {}
        elif isinstance(input_raw, str):
            try:
                arguments = json.loads(input_raw)
            except json.JSONDecodeError as exc:
                yield self.create_text_message(
                    f"Arguments must be a valid JSON object string for mcp_tool_call: {exc}"
                )
                return
            if not isinstance(arguments, dict):
                yield self.create_text_message(
                    "input JSON must be an object matching the MCP tool input schema."
                )
                return
        elif isinstance(input_raw, dict):
            arguments = input_raw
        else:
            yield self.create_text_message(
                "input must be a JSON string or object matching the MCP tool input schema."
            )
            return

        credentials = self.runtime.credentials or {}
        try:
            parsed_config = parse_mcp_servers_config(credentials)
        except ValueError as exc:
            yield self.create_text_message(str(exc))
            return

        try:
            servers = get_servers(parsed_config)
        except ValueError as exc:
            yield self.create_text_message(str(exc))
            return
        target_server = find_server_by_id(servers, server_id)
        if not target_server:
            yield self.create_text_message(f"Unknown server_id '{server_id}'.")
            return
        oauth_resolve_started_at = time.perf_counter()
        resolved_server = resolve_server_oauth_config_cached(
            target_server,
            storage=self.session.storage,
        )
        oauth_resolve_ms = int((time.perf_counter() - oauth_resolve_started_at) * 1000)
        mcp_url = resolved_server.get("mcp_url")
        if not mcp_url:
            yield self.create_text_message(f"Missing mcp_url for server_id '{server_id}'.")
            return

        access_token = get_access_token(self, mcp_url)
        headers = build_auth_headers(access_token)
        client = create_client(
            mcp_url=mcp_url,
            headers=headers,
            timeout=credentials.get("timeout", 50),
        )
        initialize_ms = 0
        call_ms = 0
        try:
            initialize_started_at = time.perf_counter()
            client.initialize()
            initialize_ms = int((time.perf_counter() - initialize_started_at) * 1000)
            call_started_at = time.perf_counter()
            content = client.call_tool(tool_name, arguments)
            call_ms = int((time.perf_counter() - call_started_at) * 1000)
            yield self.create_json_message(
                {
                    "ok": True,
                    "tool_ref": tool_ref,
                    "result": content,
                }
            )
            total_ms = int((time.perf_counter() - started_at) * 1000)
            logger.info(
                "mcp_tool_call timing server_id=%s tool=%s oauth_resolve_ms=%s initialize_ms=%s call_ms=%s total_ms=%s",
                server_id,
                tool_name,
                oauth_resolve_ms,
                initialize_ms,
                call_ms,
                total_ms,
            )
        except McpAuthError:
            state, code_verifier = create_state(self, mcp_url, oauth_cfg=resolved_server)
            login_url = None
            if state and code_verifier:
                login_url = build_login_url(
                    resolved_server,
                    state=state,
                    code_verifier=code_verifier,
                )
            if login_url:
                yield self.create_json_message(
                    {
                        "ok": False,
                        "error_code": "NOT_AUTHORIZED",
                        "status": "need_auth",
                        "tool_ref": tool_ref,
                        "server_id": server_id,
                        "login_url": login_url,
                        "message": "Authentication required. Return login_url to the user, ask them to finish sign-in in the browser, then retry the same mcp_tool_call request.",
                    }
                )
            else:
                yield self.create_json_message(
                    {
                        "ok": False,
                        "error_code": "NOT_AUTHORIZED",
                        "status": "need_auth",
                        "message": "Authentication required but login URL is not configured.",
                    }
                )
            total_ms = int((time.perf_counter() - started_at) * 1000)
            logger.info(
                "mcp_tool_call auth_required server_id=%s tool=%s oauth_resolve_ms=%s initialize_ms=%s total_ms=%s",
                server_id,
                tool_name,
                oauth_resolve_ms,
                initialize_ms,
                total_ms,
            )
        except Exception as exc:
            logger.exception("Error calling MCP Server tool.")
            yield self.create_text_message(f"Error calling MCP Server tool: {exc}")
        finally:
            try:
                client.close()
            except Exception:
                pass
