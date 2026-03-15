import html
from urllib.parse import parse_qs
from typing import Any, Mapping

import httpx
from werkzeug import Request, Response

from dify_plugin import Endpoint
from tools.utils.auth import (
    delete_state,
    is_state_expired,
    normalize_mcp_url,
    normalize_token_payload,
    resolve_state,
    set_token_payload,
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
        if is_state_expired(state_payload):
            delete_state(storage, state)
            return Response("State expired", status=400, content_type="text/plain")

        user_key = state_payload.get("user_id")
        state_mcp_url = normalize_mcp_url(state_payload.get("mcp_url"))
        if not user_key:
            return Response("Invalid user key", status=400, content_type="text/plain")
        if not state_mcp_url:
            return Response("Invalid MCP URL in state", status=400, content_type="text/plain")

        oauth_cfg = state_payload.get("oauth") or {}
        token_url = (oauth_cfg.get("token_url") or "").strip()
        client_id = (oauth_cfg.get("client_id") or "").strip()
        client_secret = (oauth_cfg.get("client_secret") or "").strip()
        token_endpoint_auth_method = (oauth_cfg.get("token_endpoint_auth_method") or "").strip()
        redirect_uri = (oauth_cfg.get("redirect_uri") or "").strip()
        if not token_url or not client_id or not redirect_uri:
            return Response(
                "Missing OAuth settings in state. Please re-run mcp_tool_list or mcp_tool_call to get a fresh login_url.",
                status=400,
                content_type="text/plain",
            )

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
        }
        code_verifier = (state_payload.get("code_verifier") or "").strip()
        if code_verifier:
            data["code_verifier"] = code_verifier
        if client_secret and token_endpoint_auth_method != "none":
            data["client_secret"] = client_secret

        try:
            response = httpx.post(token_url, data=data, timeout=10)
        except Exception as exc:
            return Response(f"Token request failed: {exc}", status=502, content_type="text/plain")

        if response.status_code >= 400:
            error_text = (response.text or "").strip()
            if len(error_text) > 400:
                error_text = f"{error_text[:400]}..."
            return Response(
                f"Token exchange failed: {response.status_code} {error_text}",
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
        if not token_payload.get("access_token"):
            return Response(
                "Token exchange succeeded but access_token was not found in response.",
                status=400,
                content_type="text/plain",
            )
        set_token_payload(storage, user_key, state_mcp_url, token_payload)
        delete_state(storage, state)

        server_url = html.escape(state_mcp_url)
        html_content = f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Authentication Complete</title>
    <style>
      :root {{
        color-scheme: light;
        --bg: #f4f8ff;
        --surface: #ffffff;
        --line: #dbe8ff;
        --text: #0f1b33;
        --muted: #4f5f7d;
        --primary: #1c64f2;
        --primary-hover: #1957d3;
      }}

      * {{
        box-sizing: border-box;
      }}

      body {{
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background:
          radial-gradient(circle at 20% 10%, #eaf2ff 0, transparent 45%),
          radial-gradient(circle at 80% 90%, #e6f0ff 0, transparent 42%),
          var(--bg);
        color: var(--text);
        font-family: "Segoe UI", "Noto Sans", sans-serif;
      }}

      .card {{
        width: min(92vw, 640px);
        background: var(--surface);
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 28px 24px;
        box-shadow: 0 16px 40px rgba(19, 74, 199, 0.08);
        text-align: center;
      }}

      .badge {{
        display: inline-block;
        margin-bottom: 10px;
        padding: 4px 10px;
        border-radius: 999px;
        border: 1px solid #c7dcff;
        color: var(--primary);
        background: #eff5ff;
        font-size: 12px;
        font-weight: 600;
      }}

      h1 {{
        margin: 0;
        font-size: 28px;
        letter-spacing: 0.01em;
        font-weight: 700;
      }}

      .desc {{
        margin: 10px 0 0;
        color: var(--muted);
        font-size: 14px;
      }}

      .server {{
        margin: 18px 0 0;
        padding: 12px 14px;
        border-radius: 10px;
        border: 1px solid var(--line);
        background: #f8fbff;
        text-align: left;
      }}

      .server-label {{
        display: block;
        margin-bottom: 6px;
        font-size: 12px;
        color: #5f6f8d;
      }}

      .server-url {{
        margin: 0;
        color: #18345f;
        font-size: 13px;
        line-height: 1.5;
        word-break: break-all;
      }}

      .actions {{
        margin-top: 22px;
      }}

      button {{
        appearance: none;
        border: 1px solid transparent;
        border-radius: 10px;
        padding: 11px 16px;
        min-width: 160px;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        color: #fff;
        background: var(--primary);
        transition: background-color 120ms ease;
      }}

      button:hover {{
        background: var(--primary-hover);
      }}

      .meta {{
        margin-top: 12px;
        color: #6b7ea0;
        font-size: 12px;
      }}

      @media (max-width: 560px) {{
        .card {{
          padding: 22px 18px;
        }}

        h1 {{
          font-size: 24px;
        }}
      }}
    </style>
  </head>
  <body>
    <main class="card">
      <span class="badge">OAuth Success</span>
      <h1>Authentication complete</h1>
      <p class="desc">You can return to Dify and continue your workflow.</p>

      <section class="server">
        <span class="server-label">Server URL</span>
        <p class="server-url">{server_url}</p>
      </section>

      <div class="actions">
        <button type="button" onclick="closeWindow()">Close now</button>
      </div>

      <p class="meta">
        This window closes automatically in <span id="countdown">5</span>s.
      </p>
    </main>

    <script>
      function closeWindow() {{
        window.close();
      }}

      let remaining = 5;
      const countdown = document.getElementById("countdown");
      const timer = setInterval(() => {{
        remaining -= 1;
        if (countdown) countdown.textContent = String(Math.max(remaining, 0));
        if (remaining <= 0) {{
          clearInterval(timer);
          closeWindow();
        }}
      }}, 1000);
    </script>
  </body>
</html>
"""
        return Response(html_content.encode("utf-8"), status=200, content_type="text/html; charset=utf-8")
