"""Opt-in auth diagnostics. Never pass credentials, payloads, or raw URLs here."""

import hashlib
import json
import logging
import os
from collections.abc import Mapping
from typing import Any


_logger = logging.getLogger("mcp_auth_relay.auth_debug")
_logger.setLevel(logging.INFO)
_logger.propagate = False
if not _logger.handlers:
    # stdout is reserved for the Dify plugin protocol.
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    _logger.addHandler(handler)


def fingerprint(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def debug_event(event: str, **fields: Any) -> None:
    if os.getenv("MCP_AUTH_RELAY_DEBUG", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return
    _logger.info("auth_debug %s", json.dumps({"event": event, **fields}, sort_keys=True))


def identity_context(obj: Any) -> dict[str, Any]:
    """Record which SDK identity fields exist, without exposing their values."""
    result: dict[str, Any] = {"caller": type(obj).__name__}
    runtime = getattr(obj, "runtime", None)
    for prefix, source in (
        ("self", obj),
        ("session", getattr(obj, "session", None)),
        ("runtime", runtime),
        ("runtime_session", getattr(runtime, "session", None)),
    ):
        for field in ("runtime_user_id", "user_id", "app_id", "session_id"):
            value = fingerprint(getattr(source, field, None))
            if value:
                result[f"{prefix}_{field}_hash"] = value
    return result


def debug_server_config(obj: Any, config: Mapping[str, Any]) -> None:
    """Compare provider selections across nodes without logging their credentials."""
    servers = []
    for server in config.get("servers", []):
        servers.append({
            "server_id_hash": fingerprint(server.get("server_id")),
            "resource_hash": fingerprint(server.get("mcp_url")),
            "client_id_hash": fingerprint(server.get("client_id")),
            "redirect_uri_hash": fingerprint(server.get("redirect_uri")),
            "authorization_url_hash": fingerprint(server.get("authorization_url")),
            "token_url_hash": fingerprint(server.get("token_url")),
            "has_client_secret": bool(server.get("client_secret")),
        })
    debug_event("server_config", servers=servers, **identity_context(obj))
