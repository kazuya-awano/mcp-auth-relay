# Privacy Policy

MCP Auth Relay stores OAuth-related information in Dify plugin storage to authenticate users and call configured MCP servers on their behalf.

Stored data:

- OAuth credentials and temporary authorization state
- OAuth configuration and session metadata required for OAuth/MCP flows
- Cached responses used to reduce repeated MCP requests

Data usage:

- Stored OAuth-related information is used only for authentication and calls to configured MCP servers.
- Temporary authorization state is deleted after callback handling or expiration.
- Cached data is used only for reliability/performance optimization of repeated requests.

The plugin does not send stored OAuth-related information to any service other than the configured MCP servers and their OAuth endpoints.

If you have questions about this Privacy Policy, please contact:
- **Email:** [kazuya-awano@webfreak.jp]
