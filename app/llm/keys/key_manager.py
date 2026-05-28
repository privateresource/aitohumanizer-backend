import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

_NONCE_LENGTH = 12


def _get_aes_key() -> bytes:
    raw = settings.api_key_encryption_secret
    return base64.b64decode(raw)


def encrypt_key(plaintext: str) -> str:
    key = _get_aes_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(_NONCE_LENGTH)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("utf-8")


def decrypt_key(ciphertext: str) -> str:
    key = _get_aes_key()
    aesgcm = AESGCM(key)
    raw = base64.b64decode(ciphertext)
    nonce = raw[:_NONCE_LENGTH]
    ct = raw[_NONCE_LENGTH:]
    plaintext = aesgcm.decrypt(nonce, ct, None)
    return plaintext.decode("utf-8")


def mask_key(key: str) -> str:
    if len(key) <= 8:
        return key[:1] + "****" + key[-1:] if len(key) > 1 else "****"
    return key[:4] + "****" + key[-4:]
