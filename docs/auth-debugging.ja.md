# 認証のデバッグ

[English](auth-debugging.md)

`.env` のデバッグ接続設定を使い、次のコマンドで診断ログを有効にできます。
通常の起動では無効です。起動中のデバッグプロセスを終了してから起動してください。

```bash
umask 077
MCP_AUTH_RELAY_DEBUG=1 python -m main 2>auth-debug.log
```

診断ログは `auth_debug` を含む JSON で stderr に出力します。トークン、APIキー、
認可コード、PKCE verifier、認証URL、ツール引数・結果は出力しません。
ユーザーID、OAuth state、MCP URL、DifyセッションIDはハッシュで照合します。

| ログイベント | 確認する内容 |
| --- | --- |
| `server_config` | 認証確認・一覧・実行で、選択したサーバー設定のハッシュが一致するか |
| `oauth_scope_selected` / `oauth_token_scope` | 要求するスコープの取得元・個数と、トークン応答に空でないスコープがあるか。値自体は出力しない |
| `oauth_state_created` → `oauth_callback_state` | `state_hash` が一致し、stateが見つかり、有効期限内か |
| `token_saved` → `token_lookup_start` | 保存時と実行時の `user_hash` / `user_hashes` と `resource_hash` が一致するか |
| `token_lookup_record` | `expires_in_seconds` と `usable`。残り30秒以下のトークンは使わない |
| `token_storage_read_error` / `token_lookup_miss` | 読み出しの例外か、保存値の欠落・不正か。SDKによってはキー未登録も例外になる |
| `auth_status_result` | `force_reauth` による認証URL発行か、保存トークンが使えないためか |
| `tool_list_cache_hit` | 一覧がキャッシュから返されたこと。一覧の取得だけでは認証成功を判断できない |
| `mcp_response` | HTTPステータス、認証ヘッダーの有無、リダイレクト後もヘッダーがあるか |
| `mcp_http_error` | 401/403以外のHTTPエラーで返された標準OAuthエラー名や数値RPCエラーコード。自由文の本文は出力しない |
| `mcp_tool_result` / `tool_error` | MCPツール結果の `isError`、またはプラグインで発生した例外の種類 |
| `reauth_required` | MCPが401/403を返した時点で、トークンを送信していたか |

現状の `mcp_auth_status` は保存トークンの有無と期限を確認し、MCPサーバーへの検証要求は送りません。
refresh token は保存しますが、自動更新処理は未実装です。
APIで再現する場合は `/chat-messages` の `user` を固定して、認証URLを取得したユーザーと
実行ユーザーを揃えてください。Web画面で認証したトークンを別のAPIユーザーで共有することはありません。

編集画面プレビューの制約は [README](../README.ja.md#編集画面プレビューの制約) を参照してください。
