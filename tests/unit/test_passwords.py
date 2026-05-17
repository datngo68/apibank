"""Unit tests cho password hashing."""

from __future__ import annotations

import pytest

from packages.security.passwords import (
    DEFAULT_ROUNDS,
    hash_password,
    needs_rehash,
    verify_password,
)


def test_hash_and_verify_round_trip() -> None:
    h = hash_password("super-secret-1!")
    assert verify_password("super-secret-1!", h) is True


def test_wrong_password_rejected() -> None:
    h = hash_password("a-pwd-1234")
    assert verify_password("a-pwd-12345", h) is False


def test_empty_password_rejected_at_hash() -> None:
    with pytest.raises(ValueError):
        hash_password("")


def test_empty_password_rejected_at_verify() -> None:
    h = hash_password("anything")
    assert verify_password("", h) is False
    assert verify_password("anything", "") is False


def test_handles_unicode_password() -> None:
    pwd = "Mật-khẩu-😀-1"  # noqa: S105
    h = hash_password(pwd)
    assert verify_password(pwd, h) is True
    assert verify_password("Mật-khẩu-😀-2", h) is False


def test_long_password_supported() -> None:
    # bcrypt giới hạn 72 byte, nhưng SHA-prehash của ta cho phép password dài
    pwd = "x" * 200
    h = hash_password(pwd)
    assert verify_password(pwd, h) is True
    assert verify_password("x" * 199, h) is False


def test_each_call_produces_unique_hash() -> None:
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1 != h2
    assert verify_password("same", h1)
    assert verify_password("same", h2)


def test_needs_rehash_for_legacy_or_low_cost() -> None:
    h = hash_password("abc", rounds=10)
    # ta yêu cầu cost mặc định cao hơn -> cần rehash
    assert needs_rehash(h, rounds=DEFAULT_ROUNDS) is True
    assert needs_rehash(h, rounds=10) is False
    # Hash hỏng → cần rehash
    assert needs_rehash("garbage") is True
    assert needs_rehash("") is True


def test_garbage_hash_does_not_crash() -> None:
    assert verify_password("anything", "garbage") is False
