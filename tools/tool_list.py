import logging
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
    get_tool_list_cache,
    get_servers,
    parse_mcp_servers_config,
    resolve_server_oauth_config,
    set_tool_list_cache,
)
from tools.utils.mcp_client import McpAuthError, create_client

logger = logging.getLogger(__name__)


def _resolve_cache_ttl_seconds(credentials: dict[str, Any]) -> int:
    raw = credentials.get("tool_list_cache_ttl_seconds")
    if raw in (None, ""):
        return 300
    try:
        ttl = int(raw)
    except Exception:
        return 300
    if ttl < 0:
        return 0
    return min(ttl, 86400)


class MCPToolList(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        credentials = self.runtime.credentials or {}
        try:
            parsed_config = parse_mcp_servers_config(credentials)
        except ValueError as exc:
            yield self.create_text_message(str(exc))
            return

        server_id = (tool_parameters.get("server_id") or "").strip() or None
        try:
            servers = get_servers(parsed_config)
        except ValueError as exc:
            yield self.create_text_message(str(exc))
            return

        if server_id:
            matched = find_server_by_id(servers, server_id)
            if not matched:
                yield self.create_text_message(f"Unknown server_id: {server_id}")
                return
            target_servers = [matched]
        else:
            target_servers = [dict(server) for server in servers]

        all_tools: list[dict[str, Any]] = []
        auth_required: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        server_results: list[dict[str, Any]] = []
        storage = self.session.storage
        cache_ttl_seconds = _resolve_cache_ttl_seconds(credentials)

        for server in target_servers:
            resolved_server = resolve_server_oauth_config(server)
            mcp_url = resolved_server.get("mcp_url")
            current_server_id = resolved_server.get("server_id")
            if not mcp_url:
                errors.append({"server_id": current_server_id, "error": "Missing mcp_url"})
                continue

            cached_tools = None
            if cache_ttl_seconds > 0:
                cached_tools = get_tool_list_cache(
                    storage,
                    mcp_url,
                    max_age_seconds=cache_ttl_seconds,
                )
            if cached_tools is not None:
                tools = cached_tools
                source = "cache"
            else:
                source = "live"
                access_token = get_access_token(self, mcp_url)
                headers = build_auth_headers(access_token)
                client = create_client(
                    mcp_url=mcp_url,
                    headers=headers,
                    timeout=credentials.get("timeout", 50),
                )
                try:
                    client.initialize()
                    tools = client.list_tools()
                    if cache_ttl_seconds > 0:
                        set_tool_list_cache(storage, mcp_url, tools)
                except McpAuthError:
                    state, code_verifier = create_state(self, mcp_url, oauth_cfg=resolved_server)
                    login_url = None
                    if state and code_verifier:
                        login_url = build_login_url(
                            resolved_server,
                            state=state,
                            code_verifier=code_verifier,
                        )
                    auth_required.append(
                        {
                            "server_id": current_server_id,
                            "status": "need_auth",
                            "login_url": login_url,
                            "message": (
                                "Authentication required. Open login_url, finish sign-in, then retry mcp_tool_list."
                                if login_url
                                else "Authentication required but login URL could not be generated."
                            ),
                        }
                    )
                    continue
                except Exception as exc:
                    logger.exception("Error listing MCP tools. server_id=%s", current_server_id)
                    errors.append({"server_id": current_server_id, "error": str(exc)})
                    continue
                finally:
                    try:
                        client.close()
                    except Exception:
                        pass

            tool_count = 0
            for tool in tools:
                tool_name = tool.get("name")
                if not tool_name:
                    continue
                enriched_tool = dict(tool)
                enriched_tool["server_id"] = current_server_id
                enriched_tool["tool_ref"] = f"{current_server_id}::{tool_name}"
                all_tools.append(enriched_tool)
                tool_count += 1
            server_results.append(
                {
                    "server_id": current_server_id,
                    "source": source,
                    "tool_count": tool_count,
                }
            )

        yield self.create_json_message(
            {
                "usage": "Use mcp_tool_call with tool_ref and input JSON. Do not call MCP tool names directly as Dify tools.",
                "tools": all_tools,
                "auth_required": auth_required,
                "errors": errors,
                "servers": server_results,
            }
        )
