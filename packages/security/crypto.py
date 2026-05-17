from __future__ import annotations

from dataclasses import dataclass

from cryptography.fernet import Fernet, MultiFernet


@dataclass(frozen=True)
class FernetCipher:
    primary_name: str
    _fernet: MultiFernet

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode()

    @classmethod
    def from_keys(cls, keys_spec: str) -> FernetCipher:
        key_pairs = [part.split(":", 1) for part in keys_spec.split(",") if part.strip()]
        if not key_pairs:
            raise ValueError("at least one fernet key is required")
        return cls(
            primary_name=key_pairs[0][0],
            _fernet=MultiFernet([Fernet(key.encode()) for _, key in key_pairs]),
        )

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode()).decode()
