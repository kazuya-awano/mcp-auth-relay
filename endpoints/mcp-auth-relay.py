import json
from urllib.parse import parse_qs
from typing import Mapping

import httpx
from werkzeug import Request, Response

from dify_plugin import Endpoint
from tools.utils.auth import (
    delete_state,
    ensure_oauth_config_from_storage,
    normalize_token_payload,
    resolve_state,
)


class McpAuthRelayEndpoint(Endpoint):
    def _invoke(self, r: Request, values: Mapping, settings: Mapping) -> Response:
        if r.method != "GET":
            return Response("Method Not Allowed", status=405, content_type="text/plain")

        args = r.args or {}
        error = (args.get("error") or "").strip()
        if error:
            return Response(f"OAuth error: {error}", status=400, content_type="text/plain")

        code = (args.get("code") or "").strip()
        state = (args.get("state") or "").strip()
        if not code or not state:
            return Response("Missing code or state", status=400, content_type="text/plain")

        storage = self.session.storage
        state_payload = resolve_state(storage, state)
        if not state_payload:
            return Response("Invalid state", status=400, content_type="text/plain")

        user_key = state_payload.get("user_id")
        app_id = state_payload.get("app_id")
        if not user_key:
            return Response("Invalid user key", status=400, content_type="text/plain")
        if not app_id:
            app_id = "default_app"
        oauth_cfg = ensure_oauth_config_from_storage(storage, app_id) or {}
        token_url = (oauth_cfg.get("token_url") or "").strip()
        client_id = (oauth_cfg.get("client_id") or "").strip()
        client_secret = (oauth_cfg.get("client_secret") or "").strip()
        redirect_uri = (oauth_cfg.get("redirect_uri") or "").strip()
        if not token_url or not client_id or not redirect_uri:
            return Response("Missing OAuth settings", status=500, content_type="text/plain")

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
        }
        if client_secret:
            data["client_secret"] = client_secret

        try:
            response = httpx.post(token_url, data=data, timeout=10)
        except Exception as exc:
            return Response(f"Token request failed: {exc}", status=502, content_type="text/plain")

        if response.status_code >= 400:
            return Response(
                f"Token exchange failed: {response.status_code}",
                status=400,
                content_type="text/plain",
            )

        token_payload: dict[str, Any] = {}
        try:
            token_payload = response.json() if response.content else {}
        except Exception:
            token_payload = {}
        if not token_payload:
            parsed = parse_qs(response.text or "")
            if parsed:
                token_payload = {key: values[0] for key, values in parsed.items() if values}
        if not token_payload and response.text:
            token_payload = {"access_token": response.text}

        token_payload = normalize_token_payload(token_payload)
        storage.set(f"token:{user_key}", json.dumps(token_payload).encode("utf-8"))
        delete_state(storage, state)

        html = """
<!doctype html>
<html lang="ja">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>認証完了</title>
    <style>
      :root { color-scheme: light; }
      body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans JP", sans-serif;
        margin: 0;
        background: linear-gradient(180deg, #f9fbff 0%, #eef3ff 100%);
        color: #1b2a4a;
      }
      .wrap {
        max-width: 680px;
        margin: 0 auto;
        padding: 48px 20px 64px;
      }
      .card {
        background: #ffffff;
        border: 1px solid #e6ecff;
        border-radius: 16px;
        box-shadow: 0 12px 30px rgba(12, 32, 80, 0.08);
        padding: 28px;
      }
      .title {
        font-size: 22px;
        font-weight: 700;
        margin: 0 0 8px;
      }
      .desc {
        font-size: 14px;
        line-height: 1.6;
        margin: 0 0 20px;
        color: #445a7a;
      }
      .actions {
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
      }
      button {
        appearance: none;
        border: 0;
        border-radius: 10px;
        padding: 12px 16px;
        font-weight: 600;
        cursor: pointer;
      }
      .primary {
        background: #2f6bff;
        color: #fff;
      }
      .ghost {
        background: #f0f4ff;
        color: #2f6bff;
      }
      .hint {
        margin-top: 18px;
        font-size: 12px;
        color: #6b7c99;
      }
      .code {
        display: inline-block;
        margin-top: 6px;
        padding: 4px 8px;
        background: #f5f7ff;
        border-radius: 6px;
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="card">
        <div class="title">認証完了</div>
        <p class="desc">Difyに戻って操作を続けてください。</p>
        <div class="actions">
          <button class="primary" onclick="window.close()">認証完了 &amp; 閉じる</button>
        </div>
      </div>
    </div>
  </body>
</html>
"""
        return Response(html.encode("utf-8"), status=200, content_type="text/html; charset=utf-8")
