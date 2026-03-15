# MCP Auth Relay Specification

Last updated: 2026-03-13

## Scope

This plugin provides a single Dify tool provider that:
- discovers/list MCP tools from one or more configured MCP servers,
- invokes MCP tools via a stable wrapper contract,
- handles OAuth callback and token persistence,
- supports cache cleanup via logout endpoint.

## Provider Credentials

The provider uses these credentials:

1. `mcp_servers_json` (required, plain text JSON)
2. `tool_list_cache_ttl_seconds` (optional, default `300`)

### `mcp_servers_json` format

```json
{
  "servers": [
    {
      "server_id": "notion",
      "mcp_url": "https://mcp.notion.com/mcp",
      "redirect_uri": "https://<dify-host>/e/<hook-id>/callback",
      "client_id": "optional",
      "client_secret": "optional",
      "scope": "optional",
      "authorization_url": "optional",
      "token_url": "optional"
    }
  ]
}
```

Notes:
- `server_id` must be unique in one provider configuration.
- `authorization_url` and `token_url` can be omitted when metadata discovery is available.
- Legacy single-server fields and legacy `sets` JSON are still accepted for backward compatibility.

## Tool Contracts

## `mcp_tool_list`

Input:
- `server_id` (optional): if set, lists tools from one server only.

Output fields:
- `tools[]`: MCP tools enriched with `server_id` and `tool_ref` (`server_id::tool_name`)
- `auth_required[]`: per-server login guidance when auth is required
- `errors[]`: per-server non-auth errors
- `servers[]`: source summary (`live` or `cache`) and `tool_count`

Behavior:
- Uses read-through cache per MCP URL.
- Cache TTL is controlled by `tool_list_cache_ttl_seconds`.
- On auth failure, returns `login_url` for user sign-in.

## `mcp_tool_call`

Input:
- `tool_ref` (required): `server_id::tool_name`
- `input` (required): JSON string (or object) for MCP tool arguments

Output:
- success: `{ "ok": true, "tool_ref": "...", "result": ... }`
- auth required: `{ "ok": false, "error_code": "NOT_AUTHORIZED", "status": "need_auth", "login_url": "..." }`

Behavior:
- Resolves target server from `tool_ref`.
- Sends MCP `tools/call` with validated object arguments.
- Returns login URL when token is missing/invalid.

## Endpoint Contracts

## `GET /callback`

Purpose:
- OAuth callback endpoint to exchange `code` for token and persist token.

Validation:
- Requires `code` and `state`.
- Validates state existence and expiration.
- Uses OAuth fields embedded in stored state payload.

Token exchange:
- Sends `code_verifier` for PKCE.
- Omits `client_secret` when `token_endpoint_auth_method=none`.

Result:
- Stores normalized token payload to plugin storage.
- Returns completion HTML page.

## `GET /logout`

Purpose:
- Cleanup endpoint for token and list-cache deletion.

Query:
- optional `mcp_url`: delete only one server scope.

Result JSON:
- `deleted_tokens`
- `deleted_tool_list_cache`
- `deleted_total`
- `scope`

## Storage Model

Token key:
- `token:{user_key}:{resource_hash(mcp_url)}`

Token index key:
- `token_index:v1`

Tool list cache key:
- `tool_list_cache:v1:{resource_hash(mcp_url)}`

Tool list cache index key:
- `tool_list_cache_index:v1`

State key:
- `state:{state}`

## Security Notes

- OAuth state stores only server-specific OAuth parameters required for callback exchange.
- OAuth state URL itself does not include client secret.
- PKCE is always used in login URL generation.
- `/logout` can clear all saved tokens and caches.
