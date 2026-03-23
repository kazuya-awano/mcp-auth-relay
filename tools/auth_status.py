import json
from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from tools.utils.auth import (
    build_login_url,
    create_state,
    find_server_by_id,
    get_access_token,
    get_servers,
    parse_mcp_servers_config,
    resolve_server_oauth_config_cached,
)


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


def _parse_force_reauth(tool_parameters: dict[str, Any]) -> tuple[bool, str | None]:
    raw = tool_parameters.get("force_reauth")
    if raw in (None, ""):
        return False, None
    if isinstance(raw, bool):
        return raw, None
    if isinstance(raw, int):
        return raw != 0, None
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True, None
        if normalized in {"0", "false", "no", "n", "off"}:
            return False, None
    return False, "force_reauth must be true/false (or 1/0)."


class MCPAuthStatus(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        force_reauth, force_reauth_error = _parse_force_reauth(tool_parameters)
        if force_reauth_error:
            yield self.create_text_message(force_reauth_error)
            return

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

        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        authorized_server_ids: list[str] = []
        need_auth_server_ids: list[str] = []

        for server in target_servers:
            server_id = server.get("server_id")
            description = server.get("description") or ""
            mcp_url = server.get("mcp_url")
            if not mcp_url:
                errors.append({"server_id": server_id, "error": "Missing mcp_url"})
                continue

            access_token = get_access_token(self, mcp_url)
            is_authorized = bool(access_token)
            status = "authorized" if is_authorized else "need_auth"
            login_url = None

            should_issue_login_url = force_reauth or not is_authorized
            if should_issue_login_url:
                resolved_server = dict(server)
                try:
                    resolved_server = resolve_server_oauth_config_cached(
                        server,
                        storage=self.session.storage,
                    )
                except Exception:
                    pass

                resolved_mcp_url = resolved_server.get("mcp_url") or mcp_url
                state, code_verifier = create_state(
                    self,
                    resolved_mcp_url,
                    oauth_cfg=resolved_server,
                )
                if state and code_verifier:
                    login_url = build_login_url(
                        resolved_server,
                        state=state,
                        code_verifier=code_verifier,
                    )

            if status == "authorized":
                authorized_server_ids.append(server_id)
            else:
                need_auth_server_ids.append(server_id)

            if status == "need_auth":
                message = (
                    "Authentication required. Open login_url, finish sign-in, then continue."
                    if login_url
                    else "Authentication required but login URL could not be generated."
                )
            elif force_reauth:
                message = (
                    "Currently authorized. Open login_url to re-authenticate or switch accounts."
                    if login_url
                    else "Currently authorized, but login URL could not be generated."
                )
            else:
                message = "Already authorized. You can continue without additional sign-in."

            results.append(
                {
                    "server_id": server_id,
                    "description": description,
                    "status": status,
                    "force_reauth": force_reauth,
                    "login_url": login_url,
                    "message": message,
                }
            )

        all_authorized = bool(results) and not need_auth_server_ids and not errors
        yield self.create_json_message(
            {
                "all_authorized": all_authorized,
                "authorized_server_ids": authorized_server_ids,
                "need_auth_server_ids": need_auth_server_ids,
                "servers": results,
                "errors": errors,
                "usage": "Branch by servers[].status. If status is need_auth, return login_url to the user. If force_reauth=true, a fresh login_url is issued even when already authorized.",
            }
        )
