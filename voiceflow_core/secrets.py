"""OS credential-store access for user secrets."""

from __future__ import annotations

from typing import Any, Optional


class CredentialStore:
    SERVICE_NAME = "VoiceFlow"
    API_KEY_ACCOUNT = "groq-api-key"

    def __init__(self, backend: Optional[Any] = None):
        if backend is None:
            try:
                import keyring
                backend = keyring
            except ImportError:
                backend = None
        self.backend = backend

    @property
    def available(self) -> bool:
        """True only when a real credential store is usable.

        On Linux without GNOME Keyring/KWallet (or when the backend is not
        bundled), keyring falls back to a backend that rejects every write.
        """
        if self.backend is None:
            return False
        get_keyring = getattr(self.backend, "get_keyring", None)
        if get_keyring is None:
            return True
        try:
            ring = get_keyring()
            return getattr(ring, "priority", 1) > 0 and type(ring).__module__ != "keyring.backends.fail"
        except Exception:
            return False

    def get_api_key(self) -> str:
        if not self.backend:
            return ""
        try:
            return self.backend.get_password(self.SERVICE_NAME, self.API_KEY_ACCOUNT) or ""
        except Exception:
            return ""

    def set_api_key(self, value: str) -> bool:
        if not self.backend or not value:
            return False
        try:
            self.backend.set_password(self.SERVICE_NAME, self.API_KEY_ACCOUNT, value)
            return True
        except Exception:
            return False

    def delete_api_key(self) -> bool:
        if not self.backend:
            return False
        try:
            self.backend.delete_password(self.SERVICE_NAME, self.API_KEY_ACCOUNT)
            return True
        except Exception:
            return False
