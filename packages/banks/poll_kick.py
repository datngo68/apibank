"""Kick worker poll loop để check giao dịch ngay khi cần (không đợi tick kế).

Bối cảnh: worker poll bank theo ``poll_interval`` (mặc định 20s). Khi user
đã chuyển khoản và muốn check ngay (nút "Tôi đã chuyển khoản"), API gọi
:func:`kick` để wake worker poll loop sớm — tiết kiệm trung bình 10s chờ.

Dual path:

- In-process (default `apimb start --embed`): worker đăng ký ``asyncio.Event``
  cho từng ``bank_account_id`` qua :func:`register`. API gọi :func:`kick`
  set event ngay, worker thoát ``asyncio.wait_for`` sớm.
- Distributed (API và worker process tách): :func:`kick` cũng publish lên
  Redis channel ``bank:poll:kick`` với payload là bank_id. Worker có 1
  listener task subscribe channel này → set local event. Best-effort, nếu
  Redis down thì rơi về poll_interval bình thường.

Lưu ý: kick không thay thế poll loop — chỉ là tín hiệu "wake up sớm".
Worker vẫn có safety polling theo poll_interval khi không có kick nào.
"""

from __future__ import annotations

import asyncio
import logging

from packages.infra_pubsub import publish, subscribe, wait_for_message

logger = logging.getLogger(__name__)

_KICK_CHANNEL = "bank:poll:kick"

_events: dict[str, asyncio.Event] = {}


def register(bank_account_id: str) -> asyncio.Event:
    """Worker gọi khi bắt đầu poll 1 bank → trả event để await."""
    ev = _events.get(bank_account_id)
    if ev is None:
        ev = asyncio.Event()
        _events[bank_account_id] = ev
    return ev


def unregister(bank_account_id: str) -> None:
    """Worker gọi khi dừng poll bank đó."""
    _events.pop(bank_account_id, None)


def set_local(bank_account_id: str) -> bool:
    """Set event in-process (không publish Redis). Trả True nếu có subscriber."""
    ev = _events.get(bank_account_id)
    if ev is None:
        return False
    ev.set()
    return True


async def kick(bank_account_id: str) -> bool:
    """Wake worker poll loop cho bank này.

    Trả True nếu có ít nhất 1 đường ra tín hiệu (local event hoặc Redis
    publish thành công). False nếu cả 2 đều unavailable — caller có thể
    quyết định fallback (vd: vẫn trả response 'pending' bình thường).
    """
    delivered_local = set_local(bank_account_id)
    try:
        await publish(_KICK_CHANNEL, bank_account_id)
        delivered_remote = True
    except Exception:  # noqa: BLE001
        logger.warning("poll_kick_publish_failed", extra={"bank_account_id": bank_account_id})
        delivered_remote = False
    return delivered_local or delivered_remote


async def listen(stop: asyncio.Event) -> None:
    """Run kick listener loop tới khi ``stop`` set. Worker spawn task này.

    Subscribe Redis channel ``bank:poll:kick``, set local event khi nhận
    message. Trong embedded mode (1 process) listener vẫn vô hại — kick API
    đã set local event trực tiếp; listener chỉ phát hiện duplicate rồi no-op.
    """
    while not stop.is_set():
        try:
            async with subscribe(_KICK_CHANNEL) as pubsub:
                if pubsub is None:
                    # Redis unavailable: ngủ rồi thử lại — đừng spam log.
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=60)
                    except TimeoutError:
                        continue
                    return
                while not stop.is_set():
                    msg = await wait_for_message(pubsub, timeout=1.0)
                    if msg is None:
                        continue
                    raw = msg.get("data")
                    bank_id = (
                        raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                    )
                    if bank_id:
                        set_local(bank_id)
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            logger.exception("poll_kick_listener_error")
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except TimeoutError:
                continue
            return


__all__ = [
    "register",
    "unregister",
    "set_local",
    "kick",
    "listen",
]
