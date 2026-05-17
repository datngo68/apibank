from packages.qr.vietqr import crc16_ccitt_false, generate_vietqr_payload


def test_crc16_ccitt_false_known_vector() -> None:
    assert crc16_ccitt_false("123456789") == "29B1"


def test_generate_vietqr_payload_contains_account_amount_and_content() -> None:
    payload = generate_vietqr_payload(
        bank_bin="970422",
        account_no="1234567890",
        amount_vnd=150000,
        content="DH4FK9A2",
    )

    assert "970422" in payload
    assert "1234567890" in payload
    assert "150000" in payload
    assert "DH4FK9A2" in payload
    assert payload.endswith(crc16_ccitt_false(payload[:-4]))
