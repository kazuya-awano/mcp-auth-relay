# Authentication diagnostics

[日本語](auth-debugging.ja.md)

With the remote debug connection configured in `.env`, stop any existing debug
process and start the plugin with diagnostics enabled:

```bash
umask 077
MCP_AUTH_RELAY_DEBUG=1 python -m main 2>auth-debug.log
```

Diagnostics are disabled by default. `auth_debug` JSON events go to stderr and
exclude tokens, API keys, authorization codes, PKCE verifiers, login URLs, and tool
arguments/results. Identity, state, resource, and session values are hashed.

| Event | What to check |
| --- | --- |
| `server_config` | Whether server configuration hashes match across auth status, tool listing, and execution |
| `oauth_scope_selected` / `oauth_token_scope` | Requested scope source/count and whether the token response includes a nonempty scope; values are omitted |
| `oauth_state_created` → `oauth_callback_state` | Matching `state_hash`, with state found and not expired |
| `token_saved` → `token_lookup_start` | Matching `user_hash` / `user_hashes` and `resource_hash` across storage and execution |
| `token_lookup_record` | `expires_in_seconds` and `usable`; tokens with 30 seconds or less remaining are skipped |
| `token_storage_read_error` / `token_lookup_miss` | Storage exceptions versus missing/invalid records; some SDKs raise on missing keys |
| `auth_status_result` | Whether `force_reauth` or an unavailable token caused login URL issuance |
| `tool_list_cache_hit` | A cached tool list was returned; this does not verify authentication |
| `mcp_response` | HTTP status and whether authorization was present, including after redirects |
| `mcp_http_error` | Standard OAuth error names or numeric RPC codes on HTTP errors other than 401/403; free-text bodies are omitted |
| `mcp_tool_result` / `tool_error` | MCP `isError` result or the plugin exception type |
| `reauth_required` | Whether a token was present when MCP returned 401/403 |

Auth status currently checks stored tokens and expiry without contacting MCP.
Automatic refresh is not implemented. Cached tool lists also do not verify
authentication. For API tests, keep the `/chat-messages` `user` value identical
across login and execution. Tokens obtained in the web UI are not shared with a
different API user.

See the [README](../README.md#editor-preview-limitation) for the editor preview limitation.
