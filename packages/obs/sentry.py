from __future__ import annotations

import sentry_sdk

from packages.config.settings import get_settings


def init_sentry(*, component: str) -> None:
    settings = get_settings()
    if not settings.sentry_dsn:
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=f"apibank@{settings.app_name}",
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
        send_default_pii=False,
        max_breadcrumbs=50,
        attach_stacktrace=True,
    )
    sentry_sdk.set_tag("component", component)
