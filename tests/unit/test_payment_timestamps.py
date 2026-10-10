from datetime import UTC, datetime

import pytest

from packages.banks.mb.adapter import _parse_datetime as mb_parse
from packages.banks.mb.adapter import _reliable_timestamp as mb_reliable
from packages.banks.vietin.adapter import _parse_datetime as vietin_parse
from packages.banks.vietin.adapter import _reliable_timestamp as vietin_reliable


@pytest.mark.parametrize(
    "parse,reliable", [(mb_parse, mb_reliable), (vietin_parse, vietin_reliable)]
)
def test_bank_timestamps(parse, reliable):
    assert parse("10/10/2026 14:30:00") == datetime(2026, 10, 10, 7, 30, tzinfo=UTC)
    assert reliable("10/10/2026 14:30:00")
    assert parse("2026-10-10T14:30:00+07:00") == datetime(2026, 10, 10, 7, 30, tzinfo=UTC)
    assert reliable("2026-10-10T14:30:00+07:00")
    for invalid in ("", "invalid", "10/10/2026"):
        assert not reliable(invalid)
