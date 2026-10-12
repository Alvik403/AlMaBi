from __future__ import annotations

import base64
import json
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from almabi_keycloak import authorization_url, code_challenge, end_session_url, map_role, verify_rs256


def test_map_role_prefers_admin_over_uploader():
    claims = {"realm_access": {"roles": ["viewer", "uploader", "admin"]}}
    assert map_role(claims, "almabi") == "admin"


def test_map_role_reads_keycloak_groups():
    assert map_role({"groups": ["/AlMaBi-Admins"]}, "almabi") == "admin"
    assert map_role({"groups": ["AlMaBi-Uploaders"]}, "almabi") == "uploader"
    assert map_role({"groups": ["AlMaBi-Viewers"]}, "almabi") == "viewer"
    assert map_role({"preferred_username": "user"}, "almabi") == "viewer"


def test_authorization_url_points_at_keycloak():
    url = authorization_url(
        issuer="https://keycloak.example/realms/alabuga",
        client_id="almabi",
        redirect_uri="https://almabi.example/login/callback",
        state="state",
        nonce="nonce",
        code_challenge=code_challenge("verifier"),
    )
    assert url.startswith("https://keycloak.example/realms/alabuga/protocol/openid-connect/auth?")
    assert "client_id=almabi" in url
    assert "code_challenge_method=S256" in url
    assert "kc_locale=ru" in url


def test_end_session_url_targets_keycloak_logout():
    url = end_session_url(
        issuer="https://keycloak.example/realms/alabuga",
        client_id="almabi",
        post_logout_redirect_uri="https://almabi.example/login",
        id_token="header.payload.sig",
    )
    assert url.startswith("https://keycloak.example/realms/alabuga/protocol/openid-connect/logout?")
    assert "client_id=almabi" in url
    assert "post_logout_redirect_uri=https%3A%2F%2Falmabi.example%2Flogin" in url
    assert "id_token_hint=header.payload.sig" in url


def test_verify_rs256_accepts_matching_token():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_numbers()
    jwks = {
        "keys": [
            {
                "kid": "test",
                "kty": "RSA",
                "alg": "RS256",
                "e": base64.urlsafe_b64encode(public.e.to_bytes(3, "big")).decode().rstrip("="),
                "n": base64.urlsafe_b64encode(public.n.to_bytes((public.n.bit_length() + 7) // 8, "big")).decode().rstrip("="),
            }
        ]
    }

    def segment(value: dict) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    header = segment({"alg": "RS256", "kid": "test"})
    payload = segment(
        {
            "iss": "https://keycloak.example/realms/alabuga",
            "aud": "almabi",
            "nonce": "nonce",
            "exp": int(time.time()) + 60,
            "preferred_username": "user",
        }
    )
    signature = key.sign(f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256())
    token = f"{header}.{payload}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"
    claims = verify_rs256(
        token,
        jwks,
        issuer="https://keycloak.example/realms/alabuga",
        audience="almabi",
        nonce="nonce",
    )
    assert claims["preferred_username"] == "user"
