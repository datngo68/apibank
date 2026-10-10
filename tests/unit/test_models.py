from decimal import Decimal

from packages.db.models import Order, WebhookAttempt


def test_order_code_has_uppercase_full_name_and_lowercase_suffix() -> None:
    order = Order.new(amount_vnd=Decimal("100000"), bank_account_id="ba_1", ttl_seconds=900)

    name, suffix = order.transfer_content.rsplit(" chuyen tien", 1)
    assert suffix == ""
    assert name.isupper() and name.isascii()
    assert len(name.split()) == 3
    assert len(order.transfer_content) <= 96
    assert order.status == "pending"


def test_webhook_attempt_retry_schedule_has_seven_attempts() -> None:
    attempt = WebhookAttempt.new(
        webhook_id="wh_1", order_id="ord_1", transaction_id="tx_1", payload={}
    )

    assert attempt.max_attempts == 7
    assert attempt.status == "pending"
