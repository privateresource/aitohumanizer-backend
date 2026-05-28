import time
import logging
from typing import Optional

import httpx
import jwt as pyjwt
from app.core.config import settings

logger = logging.getLogger(__name__)

_jwks_cache: Optional[dict] = None
_jwks_cache_at: float = 0.0

JWKS_URI = settings.neon_auth_jwks_url or (
    f"https://{settings.neon_auth_project_id}.auth.neon.tech/.well-known/jwks.json"
)


async def get_jwks() -> dict:
    global _jwks_cache, _jwks_cache_at

    now = time.time()
    if _jwks_cache and (now - _jwks_cache_at) < settings.jwks_cache_ttl:
        return _jwks_cache

    async with httpx.AsyncClient() as client:
        resp = await client.get(JWKS_URI)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        _jwks_cache_at = now
        logger.info("JWKS refreshed from %s", JWKS_URI)
        return _jwks_cache


def _build_public_key(key_data: dict) -> str:
    kty = key_data.get("kty")
    if kty == "OKP" and key_data.get("crv") == "Ed25519":
        import base64
        x_b64 = key_data["x"]
        padding = 4 - len(x_b64) % 4
        if padding != 4:
            x_b64 += "=" * padding
        x_bytes = base64.urlsafe_b64decode(x_b64)
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        pub = Ed25519PublicKey.from_public_bytes(x_bytes)
        from cryptography.hazmat.primitives import serialization
        return pub.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
    if kty == "RSA":
        from cryptography.hazmat.primitives.asymmetric import rsa
        import base64
        n_bytes = base64.urlsafe_b64decode(key_data["n"] + "==")
        e_bytes = base64.urlsafe_b64decode(key_data["e"] + "==")
        n_int = int.from_bytes(n_bytes, "big")
        e_int = int.from_bytes(e_bytes, "big")
        pub = rsa.RSAPublicNumbers(e_int, n_int).public_key()
        from cryptography.hazmat.primitives import serialization
        return pub.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
    if kty == "EC":
        from cryptography.hazmat.primitives.asymmetric import ec
        import base64
        crv = key_data.get("crv")
        x_bytes = base64.urlsafe_b64decode(key_data["x"] + "==")
        y_bytes = base64.urlsafe_b64decode(key_data["y"] + "==")
        curves = {"P-256": ec.SECP256R1(), "P-384": ec.SECP384R1(), "P-521": ec.SECP521R1()}
        curve = curves.get(crv)
        if not curve:
            raise ValueError(f"Unsupported EC curve: {crv}")
        x_int = int.from_bytes(x_bytes, "big")
        y_int = int.from_bytes(y_bytes, "big")
        pub = ec.EllipticCurvePublicNumbers(x_int, y_int, curve).public_key()
        from cryptography.hazmat.primitives import serialization
        return pub.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
    raise ValueError(f"Unsupported key type: {kty}")


async def verify_token(token: str) -> dict:
    try:
        headers = pyjwt.get_unverified_header(token)
    except pyjwt.PyJWTError as e:
        raise ValueError(f"Malformed token: {e}") from e

    kid = headers.get("kid")
    if not kid:
        raise ValueError("Missing kid in JWT header")

    jwks = await get_jwks()
    key_data = None
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            key_data = key
            break

    if not key_data:
        raise ValueError(f"No JWK found for kid: {kid}")

    alg = headers.get("alg") or key_data.get("alg")
    if not alg:
        raise ValueError("Missing algorithm in JWT header and JWK")

    pem_key = _build_public_key(key_data)

    try:
        payload = pyjwt.decode(
            token,
            pem_key,
            algorithms=[alg],
            options={"verify_exp": True, "verify_aud": False},
        )
    except pyjwt.ExpiredSignatureError as e:
        raise ValueError("Token has expired. Please sign in again.") from e
    except pyjwt.PyJWTError as e:
        raise ValueError(f"Invalid token: {e}") from e

    return payload
