import base64
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


_TOKEN_INDEX_KEY = "token_index:v1"
_TOOL_LIST_CACHE_INDEX_KEY = "tool_list_cache_index:v1"
_TOOL_LIST_CACHE_PREFIX = "tool_list_cache:v1"
_DEFAULT_TOOL_LIST_CACHE_TTL_SECONDS = 300


def build_token_storage_key(user_id: str, mcp_url: str) -> str:
    return f"token:{user_id}:{_resource_key(mcp_url)}"


def _load_token_index(storage: Any) -> dict[str, str]:
    if not storage:
        return {}
    try:
        raw = storage.get(_TOKEN_INDEX_KEY)
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except Exception:
        return {}
    if isinstance(decoded, dict):
        return {str(k): str(v) for k, v in decoded.items()}
    if isinstance(decoded, list):
        # Backward compatibility with old list-based index.
        return {str(k): "" for k in decoded}
    return {}


def _save_token_index(storage: Any, index: Mapping[str, str]) -> None:
    if not storage:
        return
    storage.set(_TOKEN_INDEX_KEY, json.dumps(index).encode("utf-8"))


def _add_token_index_entry(storage: Any, token_key: str, mcp_url: str) -> None:
    if not storage or not token_key:
        return
    index = _load_token_index(storage)
    index[token_key] = _resource_key(mcp_url)
    _save_token_index(storage, index)


def _remove_token_index_entry(storage: Any, token_key: str) -> None:
    if not storage or not token_key:
        return
    index = _load_token_index(storage)
    if token_key in index:
        index.pop(token_key, None)
        _save_token_index(storage, index)


def _tool_list_cache_key(mcp_url: str) -> str:
    return f"{_TOOL_LIST_CACHE_PREFIX}:{_resource_key(mcp_url)}"


def _load_tool_list_cache_index(storage: Any) -> dict[str, str]:
    if not storage:
        return {}
    try:
        raw = storage.get(_TOOL_LIST_CACHE_INDEX_KEY)
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except Exception:
        return {}
    if isinstance(decoded, dict):
        return {str(k): str(v) for k, v in decoded.items()}
    if isinstance(decoded, list):
        return {str(k): "" for k in decoded}
    return {}


def _save_tool_list_cache_index(storage: Any, index: Mapping[str, str]) -> None:
    if not storage:
        return
    storage.set(_TOOL_LIST_CACHE_INDEX_KEY, json.dumps(index).encode("utf-8"))


def _add_tool_list_cache_index_entry(storage: Any, cache_key: str, mcp_url: str) -> None:
    if not storage or not cache_key:
        return
    index = _load_tool_list_cache_index(storage)
    index[cache_key] = _resource_key(mcp_url)
    _save_tool_list_cache_index(storage, index)


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


def _collect_user_key_candidates(obj: Any) -> list[str]:
    keys: list[str] = []

    def add_key(raw: Any) -> None:
        value = (raw or "").strip() if isinstance(raw, str) else ""
        if not value:
            return
        key = value
        if key not in keys:
            keys.append(key)

    add_key(getattr(obj, "runtime_user_id", None))
    add_key(getattr(obj, "user_id", None))

    session = getattr(obj, "session", None)
    if session:
        add_key(getattr(session, "user_id", None))

    runtime = getattr(obj, "runtime", None)
    if runtime:
        add_key(getattr(runtime, "runtime_user_id", None))
        add_key(getattr(runtime, "user_id", None))
        runtime_session = getattr(runtime, "session", None)
        if runtime_session:
            add_key(getattr(runtime_session, "user_id", None))

    if not keys:
        keys.append("default_user")
    return keys


def _get_user_key(obj: Any) -> str:
    return _collect_user_key_candidates(obj)[0]


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


def _read_token_record(raw: bytes | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        decoded = raw.decode("utf-8")
    except Exception:
        return None
    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError:
        return {"access_token": decoded, "obtained_at": 0}
    if not isinstance(payload, dict):
        return None
    access_token = payload.get("access_token") or payload.get("token")
    if not access_token:
        return None
    record = {
        "access_token": access_token,
        "obtained_at": int(payload.get("obtained_at") or 0),
    }
    if payload.get("expires_at") is not None:
        try:
            record["expires_at"] = int(payload.get("expires_at"))
        except Exception:
            pass
    return record


def get_user_key_candidates(runtime: Any) -> list[str]:
    return _collect_user_key_candidates(runtime)


def get_access_token(runtime: Any, mcp_url: str | None = None) -> str | None:
    storage = _get_storage(runtime)
    if not storage:
        return None
    resolved_mcp_url = normalize_mcp_url(mcp_url) or _get_mcp_url(runtime)
    if not resolved_mcp_url:
        return None
    now = int(time.time())
    records: list[dict[str, Any]] = []
    for user_key in _collect_user_key_candidates(runtime):
        try:
            raw = storage.get(build_token_storage_key(user_key, resolved_mcp_url))
        except Exception:
            raw = None
        record = _read_token_record(raw)
        if not record:
            continue
        expires_at = record.get("expires_at")
        if isinstance(expires_at, int) and expires_at <= (now + 30):
            continue
        records.append(record)
    if not records:
        return None
    best = sorted(records, key=lambda item: int(item.get("obtained_at") or 0), reverse=True)[0]
    return best.get("access_token")


def set_access_token(runtime: Any, access_token: str, mcp_url: str | None = None) -> None:
    storage = _get_storage(runtime)
    if not storage:
        return
    resolved_mcp_url = normalize_mcp_url(mcp_url) or _get_mcp_url(runtime)
    if not resolved_mcp_url:
        return
    token_payload = {"access_token": access_token, "obtained_at": int(time.time())}
    set_token_payload(storage, _get_user_key(runtime), resolved_mcp_url, token_payload)


def set_token_payload(
    storage: Any,
    user_id: str,
    mcp_url: str,
    token_payload: Mapping[str, Any],
) -> str:
    resolved_mcp_url = normalize_mcp_url(mcp_url)
    token_key = build_token_storage_key(user_id, resolved_mcp_url)
    storage.set(token_key, json.dumps(dict(token_payload)).encode("utf-8"))
    _add_token_index_entry(storage, token_key, resolved_mcp_url)
    return token_key


def delete_indexed_tokens(storage: Any, mcp_url: str | None = None) -> int:
    if not storage:
        return 0
    resource = _resource_key(mcp_url) if mcp_url else None
    index = _load_token_index(storage)
    target_keys: list[str] = []
    for token_key, indexed_resource in index.items():
        if resource and indexed_resource != resource:
            continue
        target_keys.append(token_key)

    deleted = 0
    for token_key in target_keys:
        try:
            storage.delete(token_key)
        except Exception:
            continue
        deleted += 1
        index.pop(token_key, None)
    _save_token_index(storage, index)
    return deleted


def get_tool_list_cache(
    storage: Any,
    mcp_url: str,
    max_age_seconds: int = _DEFAULT_TOOL_LIST_CACHE_TTL_SECONDS,
) -> list[dict[str, Any]] | None:
    if not storage:
        return None
    resolved_mcp_url = normalize_mcp_url(mcp_url)
    if not resolved_mcp_url:
        return None
    cache_key = _tool_list_cache_key(resolved_mcp_url)
    try:
        raw = storage.get(cache_key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    cached_at = payload.get("cached_at")
    try:
        cached_at_int = int(cached_at)
    except Exception:
        return None
    if max_age_seconds > 0 and (int(time.time()) - cached_at_int) > max_age_seconds:
        return None
    tools = payload.get("tools")
    if not isinstance(tools, list):
        return None
    return [dict(tool) for tool in tools if isinstance(tool, Mapping)]


def set_tool_list_cache(storage: Any, mcp_url: str, tools: list[Mapping[str, Any]]) -> str | None:
    if not storage:
        return None
    resolved_mcp_url = normalize_mcp_url(mcp_url)
    if not resolved_mcp_url:
        return None
    cache_key = _tool_list_cache_key(resolved_mcp_url)
    serializable_tools = [dict(tool) for tool in tools if isinstance(tool, Mapping)]
    payload = {
        "cached_at": int(time.time()),
        "tools": serializable_tools,
    }
    storage.set(cache_key, json.dumps(payload).encode("utf-8"))
    _add_tool_list_cache_index_entry(storage, cache_key, resolved_mcp_url)
    return cache_key


def delete_tool_list_cache(storage: Any, mcp_url: str | None = None) -> int:
    if not storage:
        return 0
    resource = _resource_key(mcp_url) if mcp_url else None
    index = _load_tool_list_cache_index(storage)
    target_keys: list[str] = []
    for cache_key, indexed_resource in index.items():
        if resource and indexed_resource != resource:
            continue
        target_keys.append(cache_key)

    deleted = 0
    for cache_key in target_keys:
        try:
            storage.delete(cache_key)
        except Exception:
            continue
        deleted += 1
        index.pop(cache_key, None)

    # Best effort: delete deterministic key even if old index was missing.
    if mcp_url:
        direct_key = _tool_list_cache_key(mcp_url)
        if direct_key not in target_keys:
            try:
                storage.delete(direct_key)
                deleted += 1
            except Exception:
                pass
            index.pop(direct_key, None)

    _save_tool_list_cache_index(storage, index)
    return deleted


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
        "token_endpoint_auth_methods_supported": auth_meta.get(
            "token_endpoint_auth_methods_supported"
        )
        or [],
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


def create_state(
    runtime: Any,
    mcp_url: str | None = None,
    oauth_cfg: Mapping[str, Any] | None = None,
) -> tuple[str | None, str | None]:
    storage = _get_storage(runtime)
    if not storage:
        return (None, None)
    resolved_mcp_url = normalize_mcp_url(mcp_url) or _get_mcp_url(runtime)
    if not resolved_mcp_url:
        return (None, None)
    state = secrets.token_urlsafe(16)
    code_verifier = secrets.token_urlsafe(64)
    payload = {
        "app_id": _get_app_id(runtime),
        "user_id": _get_user_key(runtime),
        "mcp_url": resolved_mcp_url,
        "code_verifier": code_verifier,
        "created_at": int(time.time()),
    }
    if oauth_cfg:
        payload["oauth"] = {
            "token_url": oauth_cfg.get("token_url"),
            "client_id": oauth_cfg.get("client_id"),
            "client_secret": oauth_cfg.get("client_secret"),
            "token_endpoint_auth_method": oauth_cfg.get("token_endpoint_auth_method"),
            "redirect_uri": oauth_cfg.get("redirect_uri"),
        }
    storage.set(_state_key(state), json.dumps(payload).encode("utf-8"))
    return (state, code_verifier)


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


def _to_s256_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def build_login_url(
    credentials: Mapping[str, Any],
    state: str | None = None,
    code_verifier: str | None = None,
) -> str | None:
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
    if code_verifier:
        params["code_challenge_method"] = "S256"
        params["code_challenge"] = _to_s256_challenge(code_verifier)
    return f"{auth_url}?{urlencode(params)}"


def _normalize_server_config(server: Mapping[str, Any], fallback_id: str) -> dict[str, Any]:
    cfg = dict(server or {})
    server_id = (cfg.get("server_id") or cfg.get("id") or fallback_id).strip()
    mcp_url = normalize_mcp_url(cfg.get("mcp_url") or cfg.get("url"))
    if not server_id or not mcp_url:
        raise ValueError("Each server must define server_id and mcp_url.")
    return {
        "server_id": server_id,
        "mcp_url": mcp_url,
        "authorization_url": cfg.get("authorization_url") or cfg.get("auth_url"),
        "token_url": cfg.get("token_url"),
        "client_id": cfg.get("client_id"),
        "client_secret": cfg.get("client_secret"),
        "token_endpoint_auth_method": cfg.get("token_endpoint_auth_method"),
        "redirect_uri": cfg.get("redirect_uri"),
        "scope": cfg.get("scope"),
        "client_name": cfg.get("client_name"),
        "client_uri": cfg.get("client_uri"),
    }


def parse_mcp_servers_config(credentials: Mapping[str, Any]) -> dict[str, Any]:
    raw_cfg = credentials.get("mcp_servers_json")
    if raw_cfg is None:
        # Backward compatibility: single-server fields
        legacy_url = normalize_mcp_url(credentials.get("mcp_url"))
        if legacy_url:
            return {
                "servers": [
                    _normalize_server_config(
                        {
                            "server_id": "default",
                            "mcp_url": legacy_url,
                            "authorization_url": credentials.get("authorization_url")
                            or credentials.get("auth_url"),
                            "token_url": credentials.get("token_url"),
                            "client_id": credentials.get("client_id"),
                            "client_secret": credentials.get("client_secret"),
                            "token_endpoint_auth_method": credentials.get("token_endpoint_auth_method"),
                            "redirect_uri": credentials.get("redirect_uri"),
                            "scope": credentials.get("scope"),
                            "client_name": credentials.get("client_name"),
                            "client_uri": credentials.get("client_uri"),
                        },
                        "default",
                    )
                ]
            }
        raise ValueError("Missing mcp_servers_json provider credential.")

    if isinstance(raw_cfg, str):
        try:
            data = json.loads(raw_cfg)
        except Exception as exc:
            raise ValueError(f"mcp_servers_json is not valid JSON: {exc}") from exc
    elif isinstance(raw_cfg, Mapping):
        data = dict(raw_cfg)
    else:
        raise ValueError("mcp_servers_json must be a JSON string.")

    data_mapping = data if isinstance(data, Mapping) else {}
    raw_servers = data_mapping.get("servers")
    if raw_servers is None and isinstance(data, list):
        raw_servers = data

    if raw_servers is None:
        # Backward compatibility: flatten all "sets.*.servers" entries.
        flattened: list[dict[str, Any]] = []
        raw_sets = data_mapping.get("sets")
        if isinstance(raw_sets, Mapping):
            for set_id, set_value in raw_sets.items():
                if isinstance(set_value, Mapping):
                    set_servers = set_value.get("servers")
                else:
                    set_servers = set_value
                if not isinstance(set_servers, list):
                    continue
                for idx, server in enumerate(set_servers, start=1):
                    flattened.append(_normalize_server_config(server, f"{set_id}_{idx}"))
        raw_servers = flattened

    if not isinstance(raw_servers, list):
        raise ValueError("mcp_servers_json must contain a servers list.")

    normalized_servers = [
        _normalize_server_config(server, f"server_{idx}")
        for idx, server in enumerate(raw_servers, start=1)
    ]
    if not normalized_servers:
        raise ValueError("No MCP servers configured in mcp_servers_json.")

    return {"servers": normalized_servers}


def get_servers(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    servers = config.get("servers")
    if not isinstance(servers, list) or not servers:
        raise ValueError("No MCP servers configured.")
    return [dict(server) for server in servers]


def find_server_by_id(servers: list[Mapping[str, Any]], server_id: str) -> dict[str, Any] | None:
    resolved_server_id = (server_id or "").strip()
    if not resolved_server_id:
        return None
    for server in servers:
        if (server.get("server_id") or "").strip() == resolved_server_id:
            return dict(server)
    return None


def _resolve_token_auth_method(
    config: Mapping[str, Any],
    discovered_methods: list[str] | None = None,
    registered: Mapping[str, Any] | None = None,
) -> str:
    if registered and (registered.get("token_endpoint_auth_method") or "").strip():
        return (registered.get("token_endpoint_auth_method") or "").strip()
    if (config.get("token_endpoint_auth_method") or "").strip():
        return (config.get("token_endpoint_auth_method") or "").strip()
    methods = discovered_methods or []
    if config.get("client_secret"):
        if "client_secret_post" in methods:
            return "client_secret_post"
        if "client_secret_basic" in methods:
            return "client_secret_basic"
    if "none" in methods:
        return "none"
    if methods:
        return methods[0]
    return "none"


def resolve_server_oauth_config(server: Mapping[str, Any]) -> dict[str, Any]:
    config = dict(server or {})
    config["mcp_url"] = normalize_mcp_url(config.get("mcp_url"))
    discovered_methods: list[str] = []
    registered: Mapping[str, Any] | None = None
    if not config.get("authorization_url") or not config.get("token_url"):
        discovered = _discover_from_mcp_url(config.get("mcp_url") or "") or {}
        config["authorization_url"] = config.get("authorization_url") or discovered.get("authorization_url")
        config["token_url"] = config.get("token_url") or discovered.get("token_url")
        config["registration_endpoint"] = discovered.get("registration_endpoint")
        methods = discovered.get("token_endpoint_auth_methods_supported") or []
        if isinstance(methods, list):
            discovered_methods = [str(m) for m in methods if m]

    if not config.get("client_id") and config.get("registration_endpoint"):
        registered = _register_client(
            config.get("registration_endpoint"),
            config.get("redirect_uri") or "",
            config.get("client_name"),
            config.get("client_uri"),
        ) or {}
        config["client_id"] = registered.get("client_id")
        # For DCR public clients (e.g. Notion), do not keep stale secrets.
        config["client_secret"] = registered.get("client_secret") or ""

    token_auth_method = _resolve_token_auth_method(
        config,
        discovered_methods=discovered_methods,
        registered=registered,
    )
    config["token_endpoint_auth_method"] = token_auth_method
    if token_auth_method == "none":
        config.pop("client_secret", None)
    return config
