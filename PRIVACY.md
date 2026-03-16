# Privacy Policy

MCP Auth Relay stores OAuth tokens and temporary OAuth state in Dify plugin storage to call remote MCP servers on behalf of the user.

Stored data:

- Access tokens returned by upstream OAuth providers
- Temporary OAuth state and PKCE verifier during the login flow
- Cached MCP `tools/list` responses

Data usage:

- Tokens are used only to call the configured MCP servers.
- Temporary OAuth state is deleted after callback handling or expiration.
- Cached tool lists are used only to reduce repeated `tools/list` requests.

The plugin does not send stored tokens to any service other than the configured MCP server and its OAuth endpoints.

If you have questions about this Privacy Policy, please contact:
- **Email:** [kazuya-awano@webfreak.jp]
