import json
import logging
from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from tools.utils.auth import (
    build_auth_headers,
    build_login_url,
    create_state,
    ensure_oauth_config,
    get_access_token,
)
from tools.utils.mcp_client import McpAuthError, create_client

logger = logging.getLogger(__name__)


class MCPToolCall(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        tool_name = (tool_parameters.get("tool_name") or "").strip()
        if not tool_name:
            yield self.create_text_message(
                "Please fill in tool_name with the exact MCP tool name returned by list_mcp_tool."
            )
            return

        arguments_raw = tool_parameters.get("arguments")
        if arguments_raw in (None, ""):
            arguments: dict[str, Any] = {}
        elif isinstance(arguments_raw, str):
            try:
                arguments = json.loads(arguments_raw)
            except json.JSONDecodeError as exc:
                yield self.create_text_message(
                    f"Arguments must be a valid JSON object string for call_mcp_tool: {exc}"
                )
                return
        elif isinstance(arguments_raw, dict):
            arguments = arguments_raw
        else:
            yield self.create_text_message(
                "Arguments must be a JSON string or object matching the MCP tool input schema."
            )
            return

        credentials = self.runtime.credentials or {}
        mcp_url = credentials.get("mcp_url")
        if not mcp_url:
            yield self.create_text_message("Missing MCP server URL (mcp_url).")
            return
        oauth_cfg = ensure_oauth_config(self, credentials)

        access_token = get_access_token(self, mcp_url)
        headers = build_auth_headers(access_token)
        client = create_client(
            mcp_url=mcp_url,
            headers=headers,
            timeout=credentials.get("timeout", 50),
        )
        try:
            client.initialize()
            content = client.call_tool(tool_name, arguments)
            yield self.create_json_message({"content": content})
        except McpAuthError:
            state = create_state(self, mcp_url)
            login_url = build_login_url(oauth_cfg or credentials, state)
            if login_url:
                yield self.create_json_message(
                    {
                        "status": "need_auth",
                        "login_url": login_url,
                        "message": "Authentication required. Return the login_url to the user, ask them to finish sign-in in the browser, then retry the same call_mcp_tool request.",
                    }
                )
            else:
                yield self.create_json_message(
                    {
                        "status": "need_auth",
                        "message": "Authentication required but login URL is not configured.",
                    }
                )
        except Exception as exc:
            logger.exception("Error calling MCP Server tool.")
            yield self.create_text_message(f"Error calling MCP Server tool: {exc}")
        finally:
            client.close()
