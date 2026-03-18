import logging
import json
import time
from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.config.logger_format import plugin_logger_handler
from dify_plugin.entities.tool import ToolInvokeMessage

from tools.utils.auth import (
    build_auth_headers,
    build_login_url,
    create_state,
    delete_mcp_session_id,
    find_server_by_id,
    get_access_token,
    get_mcp_session_id,
    get_tool_list_cache,
    get_servers,
    get_user_key_candidates,
    parse_mcp_servers_config,
    resolve_server_oauth_config_cached,
    set_mcp_session_id,
    set_tool_list_cache,
)
from tools.utils.mcp_client import McpAuthError, McpSessionError, create_client

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if plugin_logger_handler not in logger.handlers:
    logger.addHandler(plugin_logger_handler)


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


def _parse_server_ids(tool_parameters: dict[str, Any]) -> tuple[list[str], str | None]:
    selected_ids: list[str] = []
    raw_values = []
    if tool_parameters.get("server_id") not in (None, ""):
        raw_values.append(tool_parameters.get("server_id"))
    if tool_parameters.get("server_ids") not in (None, ""):
        raw_values.append(tool_parameters.get("server_ids"))

    for raw in raw_values:
        if isinstance(raw, list):
            candidates = raw
        elif isinstance(raw, str):
            stripped = raw.strip()
            if not stripped:
                continue
            if stripped.startswith("["):
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    return [], f"server_ids must be a JSON string array or comma-separated string: {exc}"
                if not isinstance(parsed, list):
                    return [], "server_ids JSON must be an array of server IDs."
                candidates = parsed
            else:
                candidates = [part.strip() for part in stripped.split(",")]
        else:
            return [], "server_ids must be a JSON string array, comma-separated string, or string list."

        for candidate in candidates:
            value = (candidate or "").strip() if isinstance(candidate, str) else ""
            if value and value not in selected_ids:
                selected_ids.append(value)

    return selected_ids, None


class MCPToolList(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        started_at = time.perf_counter()
        credentials = self.runtime.credentials or {}
        try:
            parsed_config = parse_mcp_servers_config(credentials)
        except ValueError as exc:
            yield self.create_text_message(str(exc))
            return

        selected_server_ids, parse_error = _parse_server_ids(tool_parameters)
        if parse_error:
            yield self.create_text_message(parse_error)
            return

        try:
            servers = get_servers(parsed_config)
        except ValueError as exc:
            yield self.create_text_message(str(exc))
            return

        if selected_server_ids:
            target_servers = []
            for selected_server_id in selected_server_ids:
                matched = find_server_by_id(servers, selected_server_id)
                if not matched:
                    yield self.create_text_message(f"Unknown server_id: {selected_server_id}")
                    return
                target_servers.append(matched)
        else:
            target_servers = [dict(server) for server in servers]

        all_tools: list[dict[str, Any]] = []
        auth_required: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        server_results: list[dict[str, Any]] = []
        storage = self.session.storage
        cache_ttl_seconds = _resolve_cache_ttl_seconds(credentials)
        user_candidates = get_user_key_candidates(self)
        user_key = user_candidates[0] if user_candidates else "default_user"

        for server in target_servers:
            server_started_at = time.perf_counter()
            oauth_resolve_ms = 0
            mcp_url = server.get("mcp_url")
            current_server_id = server.get("server_id")
            current_server_description = server.get("description") or ""
            if not mcp_url:
                errors.append({"server_id": current_server_id, "error": "Missing mcp_url"})
                continue

            cached_tools = None
            initialize_ms = 0
            list_ms = 0
            session_reused = False
            session_retry = False
            get_tool_list_cache_ms = 0
            get_access_token_ms = 0
            get_mcp_session_ms = 0
            set_mcp_session_ms = 0
            delete_mcp_session_ms = 0
            set_tool_list_cache_ms = 0
            if cache_ttl_seconds > 0:
                get_tool_list_cache_started_at = time.perf_counter()
                cached_tools = get_tool_list_cache(
                    storage,
                    mcp_url,
                    max_age_seconds=cache_ttl_seconds,
                )
                get_tool_list_cache_ms = int((time.perf_counter() - get_tool_list_cache_started_at) * 1000)
            if cached_tools is not None:
                tools = cached_tools
                source = "cache"
            else:
                source = "live"
                get_access_token_started_at = time.perf_counter()
                access_token = get_access_token(self, mcp_url)
                get_access_token_ms = int((time.perf_counter() - get_access_token_started_at) * 1000)
                headers = build_auth_headers(access_token)
                get_mcp_session_started_at = time.perf_counter()
                cached_session_id = get_mcp_session_id(
                    storage,
                    user_key,
                    mcp_url,
                    access_token,
                )
                get_mcp_session_ms = int((time.perf_counter() - get_mcp_session_started_at) * 1000)
                session_reused = bool(cached_session_id)
                try:
                    tools: list[dict[str, Any]] = []
                    attempt = 0
                    while True:
                        attempt += 1
                        use_cached_session = bool(cached_session_id) and attempt == 1
                        client = create_client(
                            mcp_url=mcp_url,
                            headers=headers,
                            timeout=credentials.get("timeout", 50),
                            session_id=cached_session_id if use_cached_session else None,
                        )
                        try:
                            if not use_cached_session:
                                initialize_started_at = time.perf_counter()
                                client.initialize()
                                initialize_ms = int((time.perf_counter() - initialize_started_at) * 1000)
                            list_started_at = time.perf_counter()
                            tools = client.list_tools()
                            list_ms = int((time.perf_counter() - list_started_at) * 1000)
                            latest_session_id = client.get_session_id()
                            if latest_session_id and latest_session_id != cached_session_id:
                                set_mcp_session_started_at = time.perf_counter()
                                set_mcp_session_id(
                                    storage,
                                    user_key,
                                    mcp_url,
                                    access_token,
                                    latest_session_id,
                                )
                                set_mcp_session_ms = int(
                                    (time.perf_counter() - set_mcp_session_started_at) * 1000
                                )
                                cached_session_id = latest_session_id
                            break
                        except McpSessionError:
                            if use_cached_session:
                                session_retry = True
                                delete_mcp_session_started_at = time.perf_counter()
                                delete_mcp_session_id(storage, user_key, mcp_url, access_token)
                                delete_mcp_session_ms = int(
                                    (time.perf_counter() - delete_mcp_session_started_at) * 1000
                                )
                                cached_session_id = None
                                continue
                            raise
                        finally:
                            try:
                                client.close()
                            except Exception:
                                pass
                    if cache_ttl_seconds > 0:
                        set_tool_list_cache_started_at = time.perf_counter()
                        set_tool_list_cache(storage, mcp_url, tools)
                        set_tool_list_cache_ms = int(
                            (time.perf_counter() - set_tool_list_cache_started_at) * 1000
                        )
                except McpAuthError:
                    resolved_server = dict(server)
                    oauth_resolve_started_at = time.perf_counter()
                    try:
                        resolved_server = resolve_server_oauth_config_cached(
                            server,
                            storage=storage,
                        )
                    except Exception:
                        logger.exception(
                            "Failed to resolve OAuth config in auth error path. server_id=%s",
                            current_server_id,
                        )
                    oauth_resolve_ms = int((time.perf_counter() - oauth_resolve_started_at) * 1000)

                    resolved_mcp_url = resolved_server.get("mcp_url") or mcp_url
                    state, code_verifier = create_state(
                        self,
                        resolved_mcp_url,
                        oauth_cfg=resolved_server,
                    )
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
                            "description": current_server_description,
                            "status": "need_auth",
                            "login_url": login_url,
                            "message": (
                                "Authentication required. Open login_url, finish sign-in, then retry mcp_tool_list."
                                if login_url
                                else "Authentication required but login URL could not be generated."
                            ),
                        }
                    )
                    total_server_ms = int((time.perf_counter() - server_started_at) * 1000)
                    tracked_server_ms = (
                        oauth_resolve_ms
                        + get_tool_list_cache_ms
                        + get_access_token_ms
                        + get_mcp_session_ms
                        + initialize_ms
                        + list_ms
                        + set_mcp_session_ms
                        + delete_mcp_session_ms
                        + set_tool_list_cache_ms
                    )
                    untracked_server_ms = max(total_server_ms - tracked_server_ms, 0)
                    logger.info(
                        "mcp_tool_list auth_required server_id=%s oauth_resolve_ms=%s get_tool_list_cache_ms=%s get_access_token_ms=%s get_mcp_session_ms=%s initialize_ms=%s list_ms=%s set_mcp_session_ms=%s delete_mcp_session_ms=%s set_tool_list_cache_ms=%s session_reused=%s session_retry=%s untracked_ms=%s total_ms=%s",
                        current_server_id,
                        oauth_resolve_ms,
                        get_tool_list_cache_ms,
                        get_access_token_ms,
                        get_mcp_session_ms,
                        initialize_ms,
                        list_ms,
                        set_mcp_session_ms,
                        delete_mcp_session_ms,
                        set_tool_list_cache_ms,
                        session_reused,
                        session_retry,
                        untracked_server_ms,
                        total_server_ms,
                    )
                    continue
                except Exception as exc:
                    logger.exception("Error listing MCP tools. server_id=%s", current_server_id)
                    errors.append({"server_id": current_server_id, "error": str(exc)})
                    continue

            tool_count = 0
            for tool in tools:
                tool_name = tool.get("name")
                if not tool_name:
                    continue
                enriched_tool = dict(tool)
                enriched_tool["server_id"] = current_server_id
                enriched_tool["server_description"] = current_server_description
                enriched_tool["tool_ref"] = f"{current_server_id}::{tool_name}"
                all_tools.append(enriched_tool)
                tool_count += 1
            server_results.append(
                {
                    "server_id": current_server_id,
                    "description": current_server_description,
                    "source": source,
                    "tool_count": tool_count,
                }
            )
            total_server_ms = int((time.perf_counter() - server_started_at) * 1000)
            tracked_server_ms = (
                oauth_resolve_ms
                + get_tool_list_cache_ms
                + get_access_token_ms
                + get_mcp_session_ms
                + initialize_ms
                + list_ms
                + set_mcp_session_ms
                + delete_mcp_session_ms
                + set_tool_list_cache_ms
            )
            untracked_server_ms = max(total_server_ms - tracked_server_ms, 0)
            logger.info(
                "mcp_tool_list timing server_id=%s source=%s oauth_resolve_ms=%s get_tool_list_cache_ms=%s get_access_token_ms=%s get_mcp_session_ms=%s initialize_ms=%s list_ms=%s set_mcp_session_ms=%s delete_mcp_session_ms=%s set_tool_list_cache_ms=%s session_reused=%s session_retry=%s untracked_ms=%s total_ms=%s",
                current_server_id,
                source,
                oauth_resolve_ms,
                get_tool_list_cache_ms,
                get_access_token_ms,
                get_mcp_session_ms,
                initialize_ms,
                list_ms,
                set_mcp_session_ms,
                delete_mcp_session_ms,
                set_tool_list_cache_ms,
                session_reused,
                session_retry,
                untracked_server_ms,
                total_server_ms,
            )

        total_ms = int((time.perf_counter() - started_at) * 1000)
        logger.info(
            "mcp_tool_list total servers=%s selected_server_ids=%s total_ms=%s",
            len(target_servers),
            len(selected_server_ids),
            total_ms,
        )

        yield self.create_json_message(
            {
                "usage": "Use mcp_tool_call with tool_ref and input JSON. If you already know the target server, call mcp_tool_list with server_id or server_ids first. Do not call MCP tool names directly as Dify tools.",
                "tools": all_tools,
                "auth_required": auth_required,
                "errors": errors,
                "servers": server_results,
            }
        )
