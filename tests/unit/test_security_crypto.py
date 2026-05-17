from packages.security.crypto import FernetCipher


def test_fernet_cipher_roundtrip() -> None:
    key = FernetCipher.generate_key()
    cipher = FernetCipher.from_keys(f"primary:{key}")

    encrypted = cipher.encrypt("secret")

    assert encrypted != "secret"
    assert cipher.decrypt(encrypted) == "secret"
