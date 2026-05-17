from packages.notifications.telegram import send_telegram


async def test_send_telegram_returns_false_when_unconfigured(monkeypatch) -> None:
    monkeypatch.delenv("APIBANK_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("APIBANK_TELEGRAM_CHAT_ID", raising=False)

    from packages.config.settings import get_settings

    get_settings.cache_clear()

    sent = await send_telegram("hello")

    assert sent is False
    get_settings.cache_clear()
