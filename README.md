# MCP Auth Relay

MCP Auth Relay lets Dify use remote MCP servers through three tools and two endpoints. It stores OAuth tokens per user, receives the OAuth callback inside the plugin, and exposes MCP tools through a stable Dify wrapper.

**Author:** [kazuya-awano](https://github.com/kazuya-awano)  
**Github Repository:** https://github.com/kazuya-awano/mcp-auth-relay

## Features

- `mcp_tool_list`: lists MCP tools and returns `tool_ref` values in `server_id::tool_name` format
- `mcp_tool_call`: executes an MCP tool by `tool_ref` with JSON input
- `mcp_auth_status`: returns current auth status and login URL per server, with optional forced re-auth URL issuance
- `GET /callback`: exchanges OAuth authorization code for access token
- `GET /logout`: clears stored tokens and cached tool lists
- Per-user token storage
- Per-server tool list cache
- Optional OAuth metadata discovery and DCR support

## Configure In Dify

1. Install the plugin in Dify.
2. Open the installed plugin and publish the callback endpoint.
3. Copy the issued callback URL for `/callback`.
4. Open the provider settings for `MCP Auth Relay`.
5. Build `MCP Servers Config JSON` with the issued callback URL in each server's `redirect_uri`.
6. Optionally set `Tool List Cache TTL Seconds`.
7. In your Agent or Workflow, add `mcp_auth_status`, `mcp_tool_list`, and `mcp_tool_call`.

### Step 1: Install

Install `MCP Auth Relay` as a plugin in your Dify environment.

### Step 2: Publish the endpoint

After installation, publish the plugin endpoint for `/callback`. Dify will issue a URL similar to:

```text
https://<your-dify-host>/e/<hook-id>/callback
```

Use this exact issued URL as `redirect_uri` in your MCP server JSON and in the upstream OAuth client settings if the identity provider requires pre-registered redirect URIs.

### Step 3: Configure `MCP Servers Config JSON`

Set `MCP Servers Config JSON` in the provider settings. The same issued callback URL can be reused across multiple MCP servers if that is how you want to manage the relay.

Example:

```json
{
  "servers": [
    {
      "server_id": "notion",
      "description": "Search and write to Notion workspace",
      "mcp_url": "https://mcp.notion.com/mcp",
      "redirect_uri": "https://<your-dify-host>/e/<hook-id>/callback"
    },
    {
      "server_id": "msdocs",
      "description": "Search Microsoft documentation",
      "mcp_url": "https://example.com/mcp",
      "redirect_uri": "https://<your-dify-host>/e/<hook-id>/callback",
      "client_id": "<optional>",
      "client_secret": "<optional>",
      "authorization_url": "<optional>",
      "token_url": "<optional>",
      "scope": "<optional>"
    }
  ]
}
```

Notes:

- `description` should explain what each server is for. The model uses it to decide which server to inspect.
- `redirect_uri` must be the issued callback endpoint URL from Dify.
- `authorization_url` and `token_url` can be omitted when the MCP server exposes OAuth metadata.
- Public/DCR clients are supported when the upstream server allows them.

### Step 4: Add tools to the Agent

Add these tools to the Agent or Workflow:

- `mcp_auth_status`
- `mcp_tool_list`
- `mcp_tool_call`

`mcp_auth_status` is used to branch workflow logic by current auth state and login URL. `mcp_tool_list` discovers available MCP tools. `mcp_tool_call` executes the selected MCP tool by `tool_ref`.

## Usage Flow

1. Call `mcp_auth_status` first.
2. If any server status is `need_auth`, open `login_url` and complete sign-in.
3. Optionally set `force_reauth=true` when you need account switching and a fresh login URL.
4. Call `mcp_tool_list`.
5. Call `mcp_tool_call` with the returned `tool_ref` and input JSON.

Example `mcp_auth_status` input:

```json
{
  "server_id": "notion",
  "force_reauth": "true"
}
```

Example `mcp_tool_list` input:

```json
{
  "server_ids": "[\"notion\",\"msdocs\"]"
}
```

Example `mcp_tool_call` input:

```json
{
  "tool_ref": "notion::notion-search",
  "input": "{\"query\":\"release notes\"}"
}
```

## Endpoints

- `/callback`: OAuth callback endpoint used by upstream identity providers
- `/logout`: deletes stored tokens and cached tool lists; optional query `mcp_url` limits deletion to one server

## License

Apache-2.0
