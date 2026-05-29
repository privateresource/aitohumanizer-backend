import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet

from app.core.config import settings
from app.llm.providers.base_provider import BaseLLMProvider
from app.llm.utils.logger import logger

CONSECUTIVE_FAILURE_LIMIT = 3


class CachedKey:
    __slots__ = ("encrypted_key", "label", "consecutive_failures")

    def __init__(self, encrypted_key: bytes, label: str = ""):
        self.encrypted_key = encrypted_key
        self.label = label
        self.consecutive_failures = 0


class EncryptedLLMCache:
    def __init__(self):
        raw = settings.api_key_encryption_secret.encode()
        key = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
        self._fernet = Fernet(key)
        self._providers: dict[str, BaseLLMProvider] = {}
        self._keys: dict[str, list[CachedKey]] = {}

    def set_provider(self, provider_id: str, provider: BaseLLMProvider):
        self._providers[provider_id] = provider

    def remove_provider(self, provider_id: str):
        self._providers.pop(provider_id, None)
        self._keys.pop(provider_id, None)

    def get_provider(self, provider_id: str) -> Optional[BaseLLMProvider]:
        return self._providers.get(provider_id)

    def all_providers(self) -> dict[str, BaseLLMProvider]:
        return dict(self._providers)

    def add_key(self, provider_id: str, decrypted_key: str, label: str = ""):
        encrypted = self._fernet.encrypt(decrypted_key.encode())
        self._keys.setdefault(provider_id, []).append(CachedKey(encrypted, label))

    def clear_keys(self, provider_id: str):
        self._keys.pop(provider_id, None)

    def get_active_key(self, provider_id: str) -> Optional[str]:
        keys = self._keys.get(provider_id, [])
        for ck in keys:
            if ck.consecutive_failures < CONSECUTIVE_FAILURE_LIMIT:
                return self._fernet.decrypt(ck.encrypted_key).decode()
        return None

    def record_failure(self, provider_id: str):
        keys = self._keys.get(provider_id, [])
        for ck in keys:
            if ck.consecutive_failures < CONSECUTIVE_FAILURE_LIMIT:
                ck.consecutive_failures += 1
                if ck.consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
                    logger.warning("key_parked_in_cache", provider_id=provider_id, label=ck.label)
                break

    def reset_failures(self, provider_id: str):
        for ck in self._keys.get(provider_id, []):
            ck.consecutive_failures = 0

    def clear(self):
        self._providers.clear()
        self._keys.clear()


cache = EncryptedLLMCache()
