from __future__ import annotations

VALID_ORDER_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"paid", "review", "expired", "canceled"},
    "review": {"paid", "canceled"},
    "paid": set(),
    "expired": set(),
    "canceled": set(),
}


def can_transition_order(current: str, target: str) -> bool:
    return target in VALID_ORDER_TRANSITIONS.get(current, set())


def transition_order(current: str, target: str) -> str:
    if not can_transition_order(current, target):
        raise ValueError(f"invalid order transition: {current} -> {target}")
    return target
