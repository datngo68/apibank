"""Unit tests cho token helpers."""

from __future__ import annotations

from packages.security.tokens import (
    constant_time_equals,
    generate_token,
    hash_token,
)


def test_generate_token_unique() -> None:
    a = generate_token()
    b = generate_token()
    assert a != b
    assert len(a) >= 30


def test_hash_token_deterministic() -> None:
    assert hash_token("abc") == hash_token("abc")
    assert hash_token("abc") != hash_token("abd")
    assert len(hash_token("abc")) == 64


def test_constant_time_equals() -> None:
    assert constant_time_equals("a", "a") is True
    assert constant_time_equals("a", "b") is False
