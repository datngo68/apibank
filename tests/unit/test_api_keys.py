from packages.security.api_keys import generate_api_key, hash_api_key, hash_request


def test_hash_api_key_is_deterministic_with_salt() -> None:
    digest_a = hash_api_key("sk_live_abc", salt="salt-1")
    digest_b = hash_api_key("sk_live_abc", salt="salt-1")
    digest_c = hash_api_key("sk_live_abc", salt="salt-2")

    assert digest_a == digest_b
    assert digest_a != digest_c


def test_hash_request_normalizes_field_order() -> None:
    payload_a = {"a": 1, "b": [1, 2], "c": {"x": 1}}
    payload_b = {"c": {"x": 1}, "b": [1, 2], "a": 1}

    assert hash_request(payload_a) == hash_request(payload_b)


def test_generate_api_key_starts_with_prefix() -> None:
    key = generate_api_key()

    assert key.startswith("sk_live_")
    assert len(key) > 30
