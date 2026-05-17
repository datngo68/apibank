from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PollCursor:
    bank_account_id: str
    last_seen_at: datetime | None
    last_ref_no: str | None
