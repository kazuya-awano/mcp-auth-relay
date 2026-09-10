import importlib
import json
import os
import time
import unittest
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import httpx
from werkzeug import Request

from tools.utils import auth
from tools.utils.debug import debug_event
from tools.utils.mcp_client import McpAuthError, McpError, McpStreamableHttpClient


class MemoryStorage:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


class OAuthScopeTests(unittest.TestCase):
    def setUp(self):
        self.storage = MemoryStorage()
        self.server = {
            "mcp_url": "https://mcp.example.com/mcp",
            "redirect_uri": "https://dify.example.com/callback",
        }
        self.endpoints = {
            "authorization_url": "https://mcp.example.com/authorize",
            "token_url": "https://mcp.example.com/token",
            "registration_endpoint": "https://mcp.example.com/register",
            "client_id": "existing-client",
        }
        self.metadata = {
            "/.well-known/oauth-protected-resource/mcp": {
                "resource": self.server["mcp_url"],
                "authorization_servers": ["https://mcp.example.com/"],
                "scopes_supported": ["mcp:read", "mcp:write"],
            },
            "/.well-known/oauth-authorization-server": {
                "authorization_endpoint": self.endpoints["authorization_url"],
                "token_endpoint": self.endpoints["token_url"],
                "registration_endpoint": self.endpoints["registration_endpoint"],
                "token_endpoint_auth_methods_supported": ["none"],
                "scopes_supported": ["unrelated:admin"],
            },
        }
        self.requests = []

    def get_metadata(self, url, **kwargs):
        path = urlparse(url).path
        self.requests.append(path)
        return httpx.Response(200, json=self.metadata[path]) if path in self.metadata else httpx.Response(404)

    def resolve(self, **overrides):
        return auth.resolve_server_oauth_config_cached({**self.server, **overrides}, self.storage)

    def test_freee_shaped_discovery_propagates_scopes_to_login_url(self):
        with patch.object(auth.httpx, "get", side_effect=self.get_metadata), patch.object(
            auth, "_register_client", return_value={"client_id": "new-client", "token_endpoint_auth_method": "none"}
        ):
            config = self.resolve()
        query = parse_qs(urlparse(auth.build_login_url(config, "state", "v" * 64)).query)
        self.assertEqual(query["scope"], ["mcp:read mcp:write"])
        self.assertEqual(query["client_id"], ["new-client"])
        self.assertEqual(query["state"], ["state"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(self.requests[0], "/.well-known/oauth-protected-resource/mcp")
        self.assertNotIn("/.well-known/oauth-protected-resource", self.requests)

    def test_root_metadata_fallback(self):
        self.metadata["/.well-known/oauth-protected-resource"] = self.metadata.pop(
            "/.well-known/oauth-protected-resource/mcp"
        )
        with patch.object(auth.httpx, "get", side_effect=self.get_metadata):
            config = self.resolve(client_id="existing-client")
        self.assertEqual(config["scope"], "mcp:read mcp:write")
        self.assertEqual(self.requests[:2], [
            "/.well-known/oauth-protected-resource/mcp", "/.well-known/oauth-protected-resource",
        ])

    def test_nested_resource_path_ignores_query(self):
        self.metadata["/.well-known/oauth-protected-resource/team/mcp"] = self.metadata.pop(
            "/.well-known/oauth-protected-resource/mcp"
        )
        with patch.object(auth.httpx, "get", side_effect=self.get_metadata):
            config = self.resolve(mcp_url="https://mcp.example.com/team/mcp?tenant=one", client_id="existing-client")
        self.assertEqual(config["scope"], "mcp:read mcp:write")
        self.assertEqual(self.requests[0], "/.well-known/oauth-protected-resource/team/mcp")

    def test_no_resource_scopes_does_not_request_authorization_server_scopes(self):
        self.metadata["/.well-known/oauth-protected-resource/mcp"].pop("scopes_supported")
        with patch.object(auth.httpx, "get", side_effect=self.get_metadata):
            config = self.resolve(client_id="existing-client")
        self.assertNotIn("scope", parse_qs(urlparse(auth.build_login_url(config)).query))
        with patch.object(auth.httpx, "get") as get:
            self.assertEqual(self.resolve(client_id="existing-client")["scope"], "")
            get.assert_not_called()

    def test_old_endpoint_cache_discovers_scope_without_registering_again(self):
        auth._save_server_oauth_cache(self.storage, self.server["mcp_url"], self.endpoints)
        with patch.object(auth.httpx, "get", side_effect=self.get_metadata), patch.object(auth, "_register_client") as register:
            config = self.resolve()
        self.assertEqual(config["client_id"], "existing-client")
        self.assertEqual(config["scope"], "mcp:read mcp:write")
        register.assert_not_called()
        with patch.object(auth.httpx, "get") as get:
            self.assertEqual(self.resolve()["scope"], "mcp:read mcp:write")
            get.assert_not_called()

    def test_explicit_scope_overrides_discovery_without_poisoning_shared_cache(self):
        with patch.object(auth.httpx, "get", side_effect=self.get_metadata):
            config = self.resolve(client_id="existing-client", scope="mcp:read")
        self.assertEqual(config["scope"], "mcp:read")
        with patch.object(auth.httpx, "get") as get:
            self.assertEqual(self.resolve()["scope"], "mcp:read mcp:write")
            self.assertEqual(self.resolve(scope="custom:limited")["scope"], "custom:limited")
            get.assert_not_called()

    def test_fully_manual_configuration_does_not_need_discovery(self):
        with patch.object(auth.httpx, "get") as get:
            config = self.resolve(**self.endpoints, scope="mcp:read")
            get.assert_not_called()
        self.assertEqual(config["scope"], "mcp:read")
        # A subsequent provider without an explicit scope must still discover.
        with patch.object(auth.httpx, "get", side_effect=self.get_metadata):
            self.assertEqual(self.resolve()["scope"], "mcp:read mcp:write")

    def test_expired_scope_cache_is_refreshed(self):
        auth._save_server_oauth_cache(self.storage, self.server["mcp_url"], {
            **self.endpoints, "discovered_scope": "old:scope",
        })
        key = auth._server_oauth_cache_key(self.server["mcp_url"])
        cached = json.loads(self.storage.get(key))
        cached["cached_at"] = int(time.time()) - 90000
        self.storage.set(key, json.dumps(cached).encode())
        with patch.object(auth.httpx, "get", side_effect=self.get_metadata):
            config = self.resolve(client_id="existing-client")
        self.assertEqual(config["scope"], "mcp:read mcp:write")

    def test_malformed_metadata_falls_back_without_crashing(self):
        self.metadata["/.well-known/oauth-protected-resource/mcp"] = ["not an object"]
        self.metadata["/.well-known/oauth-protected-resource"] = {"scopes_supported": "not a list"}
        with patch.object(auth.httpx, "get", side_effect=self.get_metadata):
            config = self.resolve(client_id="existing-client")
        self.assertEqual(config["scope"], "")
        self.assertEqual(config["authorization_url"], self.endpoints["authorization_url"])

    def test_temporary_metadata_failure_does_not_cache_missing_scope(self):
        auth._save_server_oauth_cache(self.storage, self.server["mcp_url"], self.endpoints)
        with patch.object(auth.httpx, "get", side_effect=httpx.ConnectError("temporarily unavailable")):
            self.assertEqual(self.resolve()["scope"], "")
        with patch.object(auth.httpx, "get", side_effect=self.get_metadata):
            config = self.resolve()
        self.assertEqual(config["scope"], "mcp:read mcp:write")
        self.assertEqual(config["client_id"], "existing-client")


class AuthDiagnosticsTests(unittest.TestCase):
    def test_callback_reuses_token_only_for_original_user_and_resource_without_logging_secrets(self):
        storage = MemoryStorage()
        user_id = "private-user-sentinel"
        mcp_url = "https://private-resource.example/mcp"
        caller = SimpleNamespace(runtime=SimpleNamespace(user_id=user_id), storage=storage)
        config = {
            "token_url": "https://auth.example/token",
            "client_id": "private-client-sentinel",
            "client_secret": "private-secret-sentinel",
            "redirect_uri": "https://dify.example/callback",
        }
        token = {
            "access_token": "private-access-sentinel",
            "refresh_token": "private-refresh-sentinel",
            "scope": "private-scope-sentinel",
            "expires_in": 3600,
        }
        endpoint = importlib.import_module("endpoints.mcp-auth-relay").McpAuthRelayEndpoint
        with patch.dict(os.environ, {"MCP_AUTH_RELAY_DEBUG": "1"}), self.assertLogs("mcp_auth_relay.auth_debug") as logs:
            state, verifier = auth.create_state(caller, mcp_url, config)
            request = Request.from_values(query_string={"state": state, "code": "private-code-sentinel"})
            with patch.object(httpx, "post", return_value=httpx.Response(200, json=token)) as post:
                response = endpoint._invoke(SimpleNamespace(session=SimpleNamespace(storage=storage)), request, {}, {})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(post.call_args.kwargs["data"]["code_verifier"], verifier)
            self.assertEqual(auth.get_access_token(caller, mcp_url), token["access_token"])
            self.assertIsNone(auth.resolve_state(storage, state))
            other_user = SimpleNamespace(runtime=SimpleNamespace(user_id="other-user"), storage=storage)
            self.assertIsNone(auth.get_access_token(other_user, mcp_url))
            self.assertIsNone(auth.get_access_token(caller, "https://other-resource.example/mcp"))
        output = "\n".join(logs.output)
        self.assertIn('"has_scope": true', output)
        for secret in [user_id, mcp_url, state, verifier, "private-code-sentinel", *config.values(), *list(token.values())[:3]]:
            self.assertNotIn(secret, output)

    def test_server_error_stays_server_error_and_omits_body_from_diagnostics(self):
        client = McpStreamableHttpClient("https://mcp.example/mcp", {"Authorization": "Bearer private-access-sentinel"})
        client._client.close()
        client._client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
            500, json={"error": "server_error", "error_description": "private-error-body-sentinel"},
        )))
        try:
            with patch.dict(os.environ, {"MCP_AUTH_RELAY_DEBUG": "1"}), self.assertLogs("mcp_auth_relay.auth_debug") as logs:
                with self.assertRaises(McpError) as raised:
                    client.initialize()
            self.assertNotIsInstance(raised.exception, McpAuthError)
            output = "\n".join(logs.output)
            self.assertIn('"oauth_error": "server_error"', output)
            self.assertNotIn("private-error-body-sentinel", output)
            self.assertNotIn("private-access-sentinel", output)
        finally:
            client.close()

    def test_debug_logging_is_opt_in(self):
        with patch.dict(os.environ, {"MCP_AUTH_RELAY_DEBUG": ""}), self.assertNoLogs("mcp_auth_relay.auth_debug"):
            debug_event("test_event", harmless=True)


if __name__ == "__main__":
    unittest.main()
