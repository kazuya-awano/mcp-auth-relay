# Privacy Policy

MCP Auth Relay authenticates users and calls configured MCP servers on their behalf.

## Data stored in Dify

- OAuth access and refresh tokens, expiry and scope information, associated with Dify user IDs and MCP servers.
- OAuth client configuration, including client secrets when required, and temporary authorization state containing user/app IDs, callback configuration, and PKCE verifiers.
- Cached MCP tool definitions, MCP session identifiers, and discovered OAuth metadata and client registrations.

This data is stored in Dify plugin storage to support authentication and reuse connections and metadata.

## Data sent to other services

OAuth requests send the information needed for sign-in, client registration, and token exchange to the configured or discovered OAuth endpoints. MCP requests send the user's access token and tool arguments to the selected MCP server. Tool results and errors are returned to the Dify app.

Tool arguments and results may contain personal, financial, or other sensitive data depending on the connected service and requested action. Configure only trusted MCP servers and OAuth endpoints, and grant only the scopes needed. Data handled by Dify and upstream services is also subject to their policies.

The plugin has no analytics or telemetry destination operated by the plugin author.

## Logging

Optional authentication diagnostics are disabled by default. When enabled, they write event names, status codes, error types, timestamps, counts, and hashed identifiers to the plugin runtime's stderr. These diagnostics do not record raw tokens, client secrets, authorization codes, user IDs, URLs, or tool payloads.

Dify, its hosting infrastructure, and upstream services may separately retain request logs, tool results, and errors according to their own settings. Log retention is controlled by the operator.

## Retention and deletion

Authorization state is valid for ten minutes. It is deleted after a successful callback or when an expired callback is received; unused state is not removed by a background cleanup task. Tokens and cached records remain in plugin storage until replaced or deleted; cache age limits control reuse, not automatic deletion.

The `/logout` endpoint deletes stored tokens, tool lists, MCP sessions, and server OAuth caches for all servers, or for the server selected by `mcp_url`. It operates across users in this plugin storage scope. It does not revoke grants at upstream services or erase their data or Dify app history. Use the upstream service's account settings to revoke consent, and contact your Dify operator for storage and log deletion.

## Contact

For questions about this policy, contact [kazuya-awano@webfreak.jp](mailto:kazuya-awano@webfreak.jp).
