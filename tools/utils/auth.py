import hashlib
import json
import secrets
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx


def _get_storage(obj: Any):
    if not obj:
        return None
    storage = getattr(obj, "storage", None)
    if storage:
        return storage
    session = getattr(obj, "session", None)
    if session:
        storage = getattr(session, "storage", None)
        if storage:
            return storage
    runtime = getattr(obj, "runtime", None)
    if runtime:
        return _get_storage(runtime)
    return None


def normalize_mcp_url(mcp_url: str | None) -> str:
    if not mcp_url:
        return ""
    return mcp_url.strip().rstrip("/")


def _resource_key(mcp_url: str) -> str:
    normalized = normalize_mcp_url(mcp_url)
    if not normalized:
        return "default_resource"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def build_token_storage_key(user_id: str, mcp_url: str) -> str:
    return f"token:{user_id}:{_resource_key(mcp_url)}"


def _oauth_cfg_key(app_id: str) -> str:
    return f"oauth_cfg:{app_id}"


def _state_key(state: str) -> str:
    return f"oauth_state:{state}"


def _get_app_id(obj: Any) -> str:
    app_id = (getattr(obj, "app_id", None) or "").strip()
    session = getattr(obj, "session", None)
    if session:
        app_id = app_id or (getattr(session, "app_id", None) or "").strip()
    runtime = getattr(obj, "runtime", None)
    if runtime:
        app_id = app_id or (getattr(runtime, "app_id", None) or "").strip()
        runtime_session = getattr(runtime, "session", None)
        if runtime_session:
            app_id = app_id or (getattr(runtime_session, "app_id", None) or "").strip()
    if not app_id:
        app_id = "default_app"
    return app_id


def _get_user_key(obj: Any) -> str:
    user_id = (getattr(obj, "user_id", None) or "").strip()
    session = getattr(obj, "session", None)
    if session:
        user_id = user_id or (getattr(session, "user_id", None) or "").strip()
    runtime = getattr(obj, "runtime", None)
    if runtime:
        user_id = user_id or (getattr(runtime, "user_id", None) or "").strip()
        runtime_session = getattr(runtime, "session", None)
        if runtime_session:
            user_id = user_id or (getattr(runtime_session, "user_id", None) or "").strip()
    if not user_id:
        user_id = "default_user"
    return user_id


def _get_mcp_url(obj: Any) -> str:
    credentials = getattr(obj, "credentials", None)
    if isinstance(credentials, Mapping):
        mcp_url = normalize_mcp_url(credentials.get("mcp_url"))
        if mcp_url:
            return mcp_url
    runtime = getattr(obj, "runtime", None)
    if runtime:
        return _get_mcp_url(runtime)
    return ""


def get_access_token(runtime: Any, mcp_url: str | None = None) -> str | None:
    storage = _get_storage(runtime)
    if not storage:
        return None
    resolved_mcp_url = normalize_mcp_url(mcp_url) or _get_mcp_url(runtime)
    if not resolved_mcp_url:
        return None
    try:
        raw = storage.get(build_token_storage_key(_get_user_key(runtime), resolved_mcp_url))
    except Exception:
        return None
    if not raw:
        return None
    try:
        decoded = raw.decode("utf-8")
    except Exception:
        return None
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError:
        return decoded
    if isinstance(payload, dict):
        return payload.get("access_token") or payload.get("token")
    return None


def set_access_token(runtime: Any, access_token: str, mcp_url: str | None = None) -> None:
    storage = _get_storage(runtime)
    if not storage:
        return
    resolved_mcp_url = normalize_mcp_url(mcp_url) or _get_mcp_url(runtime)
    if not resolved_mcp_url:
        return
    storage.set(
        build_token_storage_key(_get_user_key(runtime), resolved_mcp_url),
        access_token.encode("utf-8"),
    )


def normalize_token_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    now = int(time.time())
    token: dict[str, Any] = {}
    access_token = payload.get("access_token") or payload.get("token")
    if access_token:
        token["access_token"] = access_token
    refresh_token = payload.get("refresh_token")
    if refresh_token:
        token["refresh_token"] = refresh_token
    if payload.get("expires_in") is not None:
        token["expires_in"] = payload.get("expires_in")
        token["expires_at"] = now + int(payload.get("expires_in"))
    if payload.get("token_type"):
        token["token_type"] = payload.get("token_type")
    if payload.get("scope"):
        token["scope"] = payload.get("scope")
    token["obtained_at"] = now
    return token


def save_oauth_config(runtime: Any, credentials: Mapping[str, Any]) -> None:
    storage = _get_storage(runtime)
    if not storage:
        return
    app_id = (getattr(runtime, "app_id", None) or "default_app").strip()
    payload = {
        "mcp_url": normalize_mcp_url(credentials.get("mcp_url")),
        "authorization_url": credentials.get("authorization_url")
        or credentials.get("auth_url"),
        "token_url": credentials.get("token_url"),
        "client_id": credentials.get("client_id"),
        "redirect_uri": credentials.get("redirect_uri"),
        "scope": credentials.get("scope"),
        "client_name": credentials.get("client_name"),
        "client_uri": credentials.get("client_uri"),
    }
    client_secret = credentials.get("client_secret")
    if client_secret:
        payload["client_secret"] = client_secret
    storage.set(_oauth_cfg_key(app_id), json.dumps(payload).encode("utf-8"))


def load_oauth_config(storage: Any, app_id: str) -> Mapping[str, Any] | None:
    if not storage or not app_id:
        return None
    try:
        raw = storage.get(_oauth_cfg_key(app_id))
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def split_user_key(user_key: str) -> tuple[str, str] | None:
    if not user_key:
        return None
    return ("default_app", user_key)


def delete_state(storage: Any, state: str) -> None:
    if not storage or not state:
        return
    try:
        storage.delete(_state_key(state))
    except Exception:
        return


def _origin_from_url(url: str) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _fetch_json(url: str) -> dict[str, Any] | None:
    try:
        response = httpx.get(url, timeout=10)
    except Exception:
        return None
    if response.status_code >= 400:
        return None
    try:
        return response.json()
    except Exception:
        return None


def _discover_from_mcp_url(mcp_url: str) -> dict[str, Any] | None:
    origin = _origin_from_url(mcp_url)
    if not origin:
        return None
    resource_meta = _fetch_json(f"{origin}/.well-known/oauth-protected-resource") or {}
    auth_servers = resource_meta.get("authorization_servers") or []
    issuer = auth_servers[0] if auth_servers else origin
    auth_meta = _fetch_json(f"{issuer}/.well-known/oauth-authorization-server") or {}
    return {
        "authorization_url": auth_meta.get("authorization_endpoint"),
        "token_url": auth_meta.get("token_endpoint"),
        "registration_endpoint": auth_meta.get("registration_endpoint"),
    }


def _register_client(
    registration_endpoint: str,
    redirect_uri: str,
    client_name: str | None = None,
    client_uri: str | None = None,
) -> dict[str, Any] | None:
    if not registration_endpoint or not redirect_uri:
        return None
    payload: dict[str, Any] = {
        "redirect_uris": [redirect_uri],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }
    if client_name:
        payload["client_name"] = client_name
    if client_uri:
        payload["client_uri"] = client_uri
    try:
        response = httpx.post(registration_endpoint, json=payload, timeout=10)
    except Exception:
        return None
    if response.status_code >= 400:
        return None
    try:
        return response.json()
    except Exception:
        return None


def ensure_oauth_config(runtime: Any, credentials: Mapping[str, Any]) -> Mapping[str, Any]:
    storage = _get_storage(runtime)
    app_id = (getattr(runtime, "app_id", None) or "default_app").strip()
    config: dict[str, Any] = {
        "mcp_url": normalize_mcp_url(credentials.get("mcp_url")),
        "authorization_url": credentials.get("authorization_url")
        or credentials.get("auth_url"),
        "token_url": credentials.get("token_url"),
        "client_id": credentials.get("client_id"),
        "redirect_uri": credentials.get("redirect_uri"),
        "scope": credentials.get("scope"),
        "client_name": credentials.get("client_name"),
        "client_uri": credentials.get("client_uri"),
    }
    if credentials.get("client_secret"):
        config["client_secret"] = credentials.get("client_secret")

    if not config.get("authorization_url") or not config.get("token_url"):
        discovered = _discover_from_mcp_url(config.get("mcp_url") or "") or {}
        config["authorization_url"] = config.get("authorization_url") or discovered.get("authorization_url")
        config["token_url"] = config.get("token_url") or discovered.get("token_url")
        config["registration_endpoint"] = discovered.get("registration_endpoint")

    if not config.get("client_id") and config.get("registration_endpoint"):
        registered = _register_client(
            config.get("registration_endpoint"),
            config.get("redirect_uri") or "",
            config.get("client_name"),
            config.get("client_uri"),
        ) or {}
        config["client_id"] = registered.get("client_id")
        if registered.get("client_secret"):
            config["client_secret"] = registered.get("client_secret")

    if storage:
        storage.set(_oauth_cfg_key(app_id), json.dumps(config).encode("utf-8"))
    return config


def ensure_oauth_config_from_storage(storage: Any, app_id: str) -> Mapping[str, Any]:
    config = dict(load_oauth_config(storage, app_id) or {})
    if not config:
        return {}
    if not config.get("authorization_url") or not config.get("token_url"):
        discovered = _discover_from_mcp_url(config.get("mcp_url") or "") or {}
        config["authorization_url"] = config.get("authorization_url") or discovered.get("authorization_url")
        config["token_url"] = config.get("token_url") or discovered.get("token_url")
        config["registration_endpoint"] = discovered.get("registration_endpoint")
    if not config.get("client_id") and config.get("registration_endpoint"):
        registered = _register_client(
            config.get("registration_endpoint"),
            config.get("redirect_uri") or "",
            config.get("client_name"),
            config.get("client_uri"),
        ) or {}
        config["client_id"] = registered.get("client_id")
        if registered.get("client_secret"):
            config["client_secret"] = registered.get("client_secret")
    storage.set(_oauth_cfg_key(app_id), json.dumps(config).encode("utf-8"))
    return config


def build_auth_headers(access_token: str | None) -> dict[str, str]:
    if not access_token:
        return {}
    return {"Authorization": f"Bearer {access_token}"}


def create_state(runtime: Any, mcp_url: str | None = None) -> str | None:
    storage = _get_storage(runtime)
    if not storage:
        return None
    resolved_mcp_url = normalize_mcp_url(mcp_url) or _get_mcp_url(runtime)
    if not resolved_mcp_url:
        return None
    state = secrets.token_urlsafe(16)
    payload = {
        "app_id": _get_app_id(runtime),
        "user_id": _get_user_key(runtime),
        "mcp_url": resolved_mcp_url,
        "created_at": int(time.time()),
    }
    storage.set(_state_key(state), json.dumps(payload).encode("utf-8"))
    return state


def resolve_state(storage: Any, state: str) -> dict[str, Any] | None:
    if not storage or not state:
        return None
    try:
        raw = storage.get(_state_key(state))
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        try:
            return {"user_id": raw.decode("utf-8")}
        except Exception:
            return None


def is_state_expired(state_payload: Mapping[str, Any], max_age_seconds: int = 600) -> bool:
    created_at = state_payload.get("created_at")
    if not created_at:
        return True
    try:
        created_at_int = int(created_at)
    except Exception:
        return True
    return (int(time.time()) - created_at_int) > max_age_seconds


def build_login_url(credentials: Mapping[str, Any], state: str | None = None) -> str | None:
    auth_url = credentials.get("auth_url") or credentials.get("authorization_url")
    client_id = credentials.get("client_id")
    redirect_uri = credentials.get("redirect_uri")
    if not auth_url or not client_id or not redirect_uri:
        return None

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
    }
    scope = credentials.get("scope")
    if scope:
        params["scope"] = scope
    if state:
        params["state"] = state
    return f"{auth_url}?{urlencode(params)}"
