import pytest

from packages.core.state_machine import transition_order


def test_pending_can_be_paid() -> None:
    assert transition_order("pending", "paid") == "paid"


def test_paid_cannot_be_canceled() -> None:
    with pytest.raises(ValueError, match="paid -> canceled"):
        transition_order("paid", "canceled")
