# MCP Auth Relay

MCP Auth Relay は、Dify からリモート MCP サーバーを使うためのプラグインです。3つのツールと2つのエンドポイントを提供し、OAuth トークンをユーザー単位で保存しながら、MCP ツールを Dify から安定して呼び出せる形に変換します。

**Author:** [kazuya-awano](https://github.com/kazuya-awano)  
**Github Repository:** https://github.com/kazuya-awano/mcp-auth-relay

## 機能

- `mcp_tool_list`: MCP ツール一覧を取得し、`server_id::tool_name` 形式の `tool_ref` を返します
- `mcp_tool_call`: `tool_ref` と JSON 入力で MCP ツールを実行します
- `mcp_auth_status`: サーバーごとの現在の認証状態と認証 URL を返します（再認証 URL の強制再発行可）
- `GET /callback`: OAuth 認可コードをアクセストークンへ交換します
- `GET /logout`: 保存済みトークンとツール一覧キャッシュを削除します
- ユーザー単位のトークン保存
- サーバー単位のツール一覧キャッシュ
- OAuth メタデータ発見と DCR への対応

## Dify での設定

1. プラグインをインストールします。
2. インストール後に `/callback` エンドポイントを発行します。
3. 発行された callback URL を控えます。
4. `MCP Auth Relay` のプロバイダ設定を開きます。
5. 発行した callback URL を各サーバーの `redirect_uri` に入れて `MCP Servers Config JSON` を設定します。
6. 必要であれば `Tool List Cache TTL Seconds` を設定します。
7. Agent または Workflow に `mcp_auth_status`、`mcp_tool_list`、`mcp_tool_call` を追加します。

### 手順 1: インストール

Dify 環境に `MCP Auth Relay` をプラグインとしてインストールします。

### 手順 2: エンドポイント発行

インストール後に `/callback` 用のプラグインエンドポイントを発行します。Dify からは次のような URL が払い出されます。

```text
https://<your-dify-host>/e/<hook-id>/callback
```

この URL を `redirect_uri` として使います。上流 IdP 側でリダイレクト URI の事前登録が必要な場合も、この URL を登録してください。

### 手順 3: `MCP Servers Config JSON` を設定

プロバイダ設定の `MCP Servers Config JSON` に、発行した callback URL を使って各サーバー設定を記載します。複数の MCP サーバーで同じ callback URL を共通利用して構いません。

設定例:

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

補足:

- `description` は各サーバーの用途を表す説明です。モデルが対象サーバーを判断するために使います。
- `redirect_uri` は Dify が発行した callback URL を指定してください。
- `authorization_url` と `token_url` は、MCP サーバーが OAuth メタデータを公開していれば省略できます。
- 上流が許可していれば public client / DCR にも対応できます。

### 手順 4: Agent にツールを追加

Agent または Workflow に次の3つを追加します。

- `mcp_auth_status`
- `mcp_tool_list`
- `mcp_tool_call`

`mcp_auth_status` は認証状態による分岐と認証 URL の取得に使います。`mcp_tool_list` は利用可能な MCP ツールの取得、`mcp_tool_call` は選択した `tool_ref` の実行に使います。

## 利用フロー

1. まず `mcp_auth_status` を呼び出します。
2. `status` が `need_auth` のサーバーがあれば `login_url` を開いて認証します。
3. アカウント切替などで再認証 URL が必要な場合は `force_reauth=true` を指定します。
4. `mcp_tool_list` を呼び出します。
5. 返却された `tool_ref` を使って `mcp_tool_call` を呼び出します。

`mcp_auth_status` の入力例:

```json
{
  "server_id": "notion",
  "force_reauth": "true"
}
```

`mcp_tool_list` の入力例:

```json
{
  "server_ids": "[\"notion\",\"msdocs\"]"
}
```

`mcp_tool_call` の入力例:

```json
{
  "tool_ref": "notion::notion-search",
  "input": "{\"query\":\"release notes\"}"
}
```

## エンドポイント

- `/callback`: 上流 IdP からの OAuth コールバックを受け取ります
- `/logout`: 保存済みトークンとツール一覧キャッシュを削除します。`mcp_url` クエリを付けると対象を1サーバーに限定できます

## License

Apache-2.0
