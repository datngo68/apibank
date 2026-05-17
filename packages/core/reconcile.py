from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReconcileReport:
    imported_transactions: int
    matched_orders: int
    unmatched_transactions: int
    review_transactions: int

    @property
    def has_discrepancy(self) -> bool:
        return self.review_transactions > 0
