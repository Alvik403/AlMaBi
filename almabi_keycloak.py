"""Вход: своя страница → Keycloak 26.5 → Active Directory → мультифактор.

Допустима только Keycloak 26.5.

AlMaBi говорит только с Keycloak. Связь с AD и второй фактор настраивает ИБ в Keycloak.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from almabi_auth_store import AuthStore, User, UserNotFoundError, normalize_username


def map_role(claims: dict[str, Any], client_id: str) -> str:
    """Роль из токена Keycloak.

    Администраторов добавляют в группу AlMaBi-Admins, сотрудников с загрузкой —
    в AlMaBi-Uploaders. Остальные сотрудники остаются зрителями.
    """
    names: set[str] = set()
    realm_roles = (claims.get("realm_access") or {}).get("roles") or []
    client_roles = ((claims.get("resource_access") or {}).get(client_id) or {}).get("roles") or []
    for value in (*realm_roles, *client_roles, *(claims.get("groups") or [])):
        text = str(value).strip().strip("/")
        if not text:
            continue
        leaf = text.split("/")[-1].casefold()
        names.add(leaf)
    if "admin" in names or "almabi-admin" in names or "almabi-admins" in names:
        return "admin"
    if "uploader" in names or "almabi-uploader" in names or "almabi-uploaders" in names:
        return "uploader"
    return "viewer"


def authorization_url(
    *,
    issuer: str,
    client_id: str,
    redirect_uri: str,
    state: str,
    nonce: str,
    code_challenge: str,
) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "scope": "openid profile email",
            "redirect_uri": redirect_uri,
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "kc_locale": "ru",
        }
    )
    return f"{issuer.rstrip('/')}/protocol/openid-connect/auth?{query}"


def end_session_url(
    *,
    issuer: str,
    client_id: str,
    post_logout_redirect_uri: str,
    id_token: str = "",
) -> str:
    """Адрес, по которому браузер закрывает сессию Keycloak."""
    params = {
        "client_id": client_id,
        "post_logout_redirect_uri": post_logout_redirect_uri,
    }
    if id_token:
        params["id_token_hint"] = id_token
    query = urllib.parse.urlencode(params)
    return f"{issuer.rstrip('/')}/protocol/openid-connect/logout?{query}"


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _b64url(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def verify_rs256(token: str, jwks: dict[str, Any], *, issuer: str, audience: str, nonce: str) -> dict[str, Any]:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError as exc:
        raise ValueError("Некорректный токен входа") from exc
    header = json.loads(_b64url(header_b64))
    if header.get("alg") != "RS256":
        raise ValueError("Ожидается подпись RS256")
    signature = _b64url(signature_b64)
    key_data = next((key for key in jwks.get("keys", []) if key.get("kid") == header.get("kid")), None)
    if key_data is None:
        raise ValueError("Ключ подписи Keycloak не найден")
    public_key = rsa.RSAPublicNumbers(
        int.from_bytes(_b64url(key_data["e"]), "big"),
        int.from_bytes(_b64url(key_data["n"]), "big"),
    ).public_key()
    public_key.verify(signature, f"{header_b64}.{payload_b64}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    claims = json.loads(_b64url(payload_b64))
    if claims.get("iss") != issuer.rstrip("/"):
        raise ValueError("Неверный издатель токена")
    aud = claims.get("aud")
    audiences = {aud} if isinstance(aud, str) else set(aud or [])
    if audience not in audiences and claims.get("azp") != audience:
        raise ValueError("Токен выдан другому клиенту")
    if claims.get("nonce") != nonce:
        raise ValueError("Несовпадение nonce")
    return claims


def fetch_json(url: str, *, data: dict[str, str] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
    body = None if data is None else urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ValueError("Keycloak отклонил запрос входа") from exc
    except urllib.error.URLError as exc:
        raise ValueError("Keycloak недоступен") from exc


def exchange_code(
    *,
    issuer: str,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict[str, Any]:
    return fetch_json(
        f"{issuer.rstrip('/')}/protocol/openid-connect/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
    )


def load_jwks(issuer: str) -> dict[str, Any]:
    return fetch_json(f"{issuer.rstrip('/')}/protocol/openid-connect/certs")


def upsert_user(store: AuthStore, username: str, role: str) -> User:
    normalized = normalize_username(username)
    existing = next((user for user in store.list_users() if user.username == normalized), None)
    if existing is None:
        return store.create_user(normalized, secrets.token_urlsafe(32), role)
    if not existing.enabled:
        raise UserNotFoundError(f"user {normalized!r} is disabled")
    if existing.role != role:
        return store.set_role(normalized, role)
    return existing
