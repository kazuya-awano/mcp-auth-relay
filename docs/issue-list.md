# MCP Auth Relay Issue List

Last updated: 2026-03-13
Branch: `feature/mcp-tool-endpoint-revival`

## Open

1. User context fallback (`default_user`)
- Status: open
- Impact: preview/debug contexts may reuse fallback token unexpectedly.
- Next action: add explicit warning in tool response when fallback is used, then evaluate strict mode.

2. Tool list cache invalidation policy
- Status: open
- Impact: stale schema may remain during TTL window.
- Next action: add optional force-refresh parameter or explicit `/cache/clear` endpoint.

3. Token refresh flow
- Status: open
- Impact: expired access token requires re-login even when refresh token is available.
- Next action: implement refresh-token path in auth utility and callback/token persistence.

4. MCP multi-server scale behavior
- Status: open
- Impact: full-server listing can be slow when many servers are configured.
- Next action: recommend `server_id` in system prompt and consider parallelized listing.

## Done in this branch

1. Multi-server routing with one provider
- Added `mcp_servers_json` and `tool_ref` (`server_id::tool_name`) contract.

2. Per-server tool list retrieval
- `mcp_tool_list(server_id=...)` supported.

3. Cross-user tools/list cache
- Read-through cache by MCP URL with configurable TTL.

4. Logout cleanup
- `/logout` deletes both token entries and tools/list cache entries.

5. OAuth robustness
- PKCE enabled.
- DCR/public-client behavior handled (`token_endpoint_auth_method=none`).
