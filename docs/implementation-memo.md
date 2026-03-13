# MCP Auth Relay Implementation Memo

Last updated: 2026-03-13
Branch: `feature/mcp-tool-endpoint-revival`
See also: `docs/specification.md`, `docs/issue-list.md`

## 1) Current implementation progress

- Plugin shape
  - Tools: `mcp_tool_list`, `mcp_tool_call`
  - Endpoints: `/callback`, `/logout`
- OAuth flow
  - PKCE (`code_verifier` / `code_challenge`) enabled
  - OAuth callback exchanges code to token and stores token in plugin storage
  - DCR-aware behavior: if `token_endpoint_auth_method=none`, do not send `client_secret`
- MCP server config
  - Provider credential: `mcp_servers_json` (plain text input)
  - Primary format: `{"servers":[...]}`; legacy `sets` format is still parsed for compatibility
- Tool invocation contract
  - `mcp_tool_list` returns `tool_ref` in `server_id::tool_name` format
  - `mcp_tool_call` executes by `tool_ref` + `input` JSON string

## 1.1) Differences from the original list/call implementation (quick summary)

- Configuration model
  - Before: single MCP server fields (`mcp_url`, `redirect_uri`, `client_id`, ...)
  - Now: `mcp_servers_json` with multiple servers (`servers[]`)
- Tool call contract
  - Before: `tool_name` + `arguments`
  - Now: `tool_ref` (`server_id::tool_name`) + `input` JSON
- Multi-server routing
  - Before: one provider = one MCP server
  - Now: one provider can route to multiple MCP servers by `server_id`
- OAuth robustness
  - Before: basic auth URL/state flow
  - Now: PKCE enabled + DCR-aware token exchange (`token_endpoint_auth_method=none` handling)
- Endpoint surface
  - Before: callback endpoint only
  - Now: `/callback` + `/logout` (token cleanup)
- Token retrieval behavior
  - Before: strict single-key lookup (more mismatch-prone in preview/debug)
  - Now: user key candidates are tried and the newest valid token is selected

### Old vs New schema (list/call only)

#### `mcp_tool_list`

- Old
  - parameters: none
- New
  - `server_id?: string`
  - meaning: when set, list tools only for the specified MCP server

#### `mcp_tool_call`

- Old
  - `tool_name: string` (required)
  - `arguments?: string` (JSON string)
- New
  - `tool_ref: string` (required, format: `server_id::tool_name`)
  - `input: string` (required, JSON string)

#### Practical impact

- Old flow
  - list result gave `name` only
  - call required `tool_name`
- New flow
  - list result gives `tool_ref` (`server_id::tool_name`)
  - call requires `tool_ref` so server selection and tool name collision are handled in one field

## 2) Open issue: default user handling

Background:
- Some execution contexts (especially preview/debug flows) may not provide stable `user_id`.
- When `user_id` cannot be resolved, current fallback key is `default_user`.

Risk:
- `default_user` can blur user boundary in preview/debug scenarios.

Current behavior:
- `default_user` is used only when no user key candidates are available.

Decision options:
- Option A (current): keep `default_user` as fallback for compatibility.
- Option B: disable fallback and fail fast with explicit error (`USER_CONTEXT_MISSING`).
- Option C: add provider option for debug-only forced user key.

Recommended next step:
- Keep Option A for now, but add explicit warning in tool response when fallback is used.

## 3) Open issue: tool list retrieval by MCP server

Current behavior:
- `mcp_tool_list` supports `server_id` filter and fetches only that server's tool list.
- Without `server_id`, it iterates all configured servers.

Open point:
- Define UX convention for LLM prompts:
  - Always call `mcp_tool_list(server_id=...)` before `mcp_tool_call` for targeted servers, or
  - Keep broad list then route by `tool_ref`.

Status:
- Implemented.

## 4) Open issue: cross-user tool list cache

Goal:
- Cache MCP `tools/list` results across users to reduce repeated initialize/list calls.

Proposed cache key:
- `tool_cache:{resource_hash(mcp_url)}:{server_id}`

Proposed cache value:
- `tools` payload + metadata:
  - `fetched_at`
  - `protocol_version`
  - optional `etag`-like marker if available

TTL candidates:
- Start with 300s (5 min), evaluate 60s / 600s after measurement.

Invalidation triggers:
- Manual clear via `/logout` extension (future: add `/cache/clear`)
- MCP errors indicating schema mismatch
- Version change in plugin or MCP protocol

Risks:
- Tool schema drift during TTL window
- Server-specific capability changes not reflected immediately

Status:
- Implemented read-through cache in `mcp_tool_list`.
- Default TTL is `300s` (override by provider credential `tool_list_cache_ttl_seconds`).
- `/logout` now deletes both token entries and tool-list cache entries.
