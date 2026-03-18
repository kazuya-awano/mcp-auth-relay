import json
from typing import Mapping

from werkzeug import Request, Response

from dify_plugin import Endpoint
from tools.utils.auth import (
    delete_indexed_tokens,
    delete_mcp_session_cache,
    delete_tool_list_cache,
    normalize_mcp_url,
)


class McpAuthRelayLogoutEndpoint(Endpoint):
    def _invoke(self, r: Request, values: Mapping, settings: Mapping) -> Response:
        if r.method != "GET":
            return Response("Method Not Allowed", status=405, content_type="text/plain")

        mcp_url = normalize_mcp_url((r.args or {}).get("mcp_url"))
        deleted_tokens = delete_indexed_tokens(self.session.storage, mcp_url=mcp_url or None)
        deleted_tool_list_cache = delete_tool_list_cache(
            self.session.storage,
            mcp_url=mcp_url or None,
        )
        deleted_mcp_session_cache = delete_mcp_session_cache(
            self.session.storage,
            mcp_url=mcp_url or None,
        )

        payload = {
            "status": "ok",
            "deleted_tokens": deleted_tokens,
            "deleted_tool_list_cache": deleted_tool_list_cache,
            "deleted_mcp_session_cache": deleted_mcp_session_cache,
            "deleted_total": deleted_tokens + deleted_tool_list_cache + deleted_mcp_session_cache,
            "scope": mcp_url or "all",
        }
        return Response(
            json.dumps(payload, ensure_ascii=False),
            status=200,
            content_type="application/json; charset=utf-8",
        )
