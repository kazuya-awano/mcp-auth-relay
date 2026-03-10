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


class MCPToolList(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
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
            tools = client.list_tools()
            yield self.create_json_message(
                {
                    "usage": "Use the Dify tool call_mcp_tool to execute one of the MCP tools below. Set tool_name to tools[].name exactly, and pass arguments as a JSON string matching tools[].inputSchema. Do not call the MCP tool names directly as Dify tools.",
                    "tools": tools,
                }
            )
        except McpAuthError:
            state = create_state(self, mcp_url)
            login_url = build_login_url(oauth_cfg or credentials, state)
            if login_url:
                yield self.create_json_message(
                    {
                        "status": "need_auth",
                        "login_url": login_url,
                        "message": "Authentication required. Return the login_url to the user, ask them to finish sign-in in the browser, then retry list_mcp_tool.",
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
            logger.exception("Error listing MCP tools.")
            yield self.create_text_message(f"Error listing MCP tools: {exc}")
        finally:
            client.close()
