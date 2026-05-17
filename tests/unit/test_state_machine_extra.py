import pytest

from packages.core.state_machine import can_transition_order, transition_order


def test_can_transition_order_returns_true_for_valid_pairs() -> None:
    assert can_transition_order("pending", "expired")
    assert can_transition_order("review", "paid")


def test_can_transition_order_returns_false_for_unknown_state() -> None:
    assert not can_transition_order("unknown", "paid")


def test_transition_order_invalid_raises() -> None:
    with pytest.raises(ValueError):
        transition_order("expired", "paid")
