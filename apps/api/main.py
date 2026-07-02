import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from starlette.middleware.sessions import SessionMiddleware

from apps.api.middleware.csrf import CsrfMiddleware
from apps.api.middleware.http_metrics import HttpMetricsMiddleware
from apps.api.middleware.rate_limit import RateLimitMiddleware
from apps.api.middleware.security_headers import SecurityHeadersMiddleware
from apps.api.middleware.system_gates import (
    IpBlocklistMiddleware,
    MaintenanceMiddleware,
)
from apps.api.middleware.usage_metering import UsageMeteringMiddleware
from apps.api.routes.admin_analytics import router as admin_analytics_router
from apps.api.routes.admin_billing import router as admin_billing_router
from apps.api.routes.admin_compliance import router as admin_compliance_router
from apps.api.routes.admin_console import router as admin_console_router
from apps.api.routes.admin_crypto import router as admin_crypto_router
from apps.api.routes.admin_ops import router as admin_ops_router
from apps.api.routes.admin_system import router as admin_system_router
from apps.api.routes.admin_users_extra import router as admin_users_extra_router
from apps.api.routes.auth import router as auth_router
from apps.api.routes.bank_accounts import router as bank_accounts_router
from apps.api.routes.content import router as content_router
from apps.api.routes.crypto import public_router as crypto_public_router
from apps.api.routes.crypto import router as crypto_router
from apps.api.routes.health import router as health_router
from apps.api.routes.me import public_router as me_public_router
from apps.api.routes.me import router as me_router
from apps.api.routes.me_extra import router as me_extra_router
from apps.api.routes.metrics import router as metrics_router
from apps.api.routes.orders import router as orders_router
from apps.api.routes.payment import router as payment_router
from apps.api.routes.qr import router as qr_router
from apps.api.routes.telegram import router as telegram_router
from apps.api.routes.topup_stream import router as topup_stream_router
from apps.api.routes.transactions import router as transactions_router
from apps.api.routes.webhooks import router as webhooks_router
from apps.api.spa import mount_spa
from packages.config.settings import get_settings
from packages.obs.logging import configure_logging
from packages.obs.sentry import init_sentry


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    init_sentry(component="api")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        stop = asyncio.Event()
        tasks: list[asyncio.Task[Any]] = []
        embedded = os.getenv("APIBANK_EMBED_WORKERS") == "1"
        if embedded:
            from apps.scheduler.main import start_scheduler
            from apps.worker.main import run_poller_loop

            tasks.append(asyncio.create_task(run_poller_loop(stop), name="poller"))
            tasks.append(asyncio.create_task(start_scheduler(stop), name="scheduler"))
            app.state.embedded_tasks = tasks
            logging.getLogger("apibank").info(
                "embedded_workers_started",
                extra={"count": len(tasks)},
            )
        try:
            yield
        finally:
            stop.set()
            for task in tasks:
                try:
                    await asyncio.wait_for(task, timeout=10)
                except TimeoutError:
                    task.cancel()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        swagger_ui_oauth2_redirect_url="/api/docs/oauth2-redirect",
    )
    cookie_secure = settings.cookie_secure_effective
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret_key,
        session_cookie="apibank_admin",
        same_site="lax",
        https_only=cookie_secure,
    )
    app.add_middleware(RateLimitMiddleware, capacity=120, window_seconds=60)
    app.add_middleware(CsrfMiddleware, secure=cookie_secure)
    app.add_middleware(SecurityHeadersMiddleware, environment=settings.environment)
    app.add_middleware(HttpMetricsMiddleware)
    app.add_middleware(UsageMeteringMiddleware)
    # System gates đặt trên cùng để chặn sớm trước RateLimit/Session.
    app.add_middleware(MaintenanceMiddleware)
    app.add_middleware(IpBlocklistMiddleware)
    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(auth_router)
    app.include_router(me_router)
    app.include_router(me_public_router)
    app.include_router(me_extra_router)
    app.include_router(orders_router, prefix="/v1")
    app.include_router(transactions_router, prefix="/v1")
    app.include_router(webhooks_router, prefix="/v1")
    app.include_router(bank_accounts_router, prefix="/v1")
    app.include_router(crypto_router, prefix="/api/v1")
    app.include_router(crypto_public_router)
    app.include_router(admin_console_router)
    app.include_router(admin_ops_router)
    app.include_router(admin_system_router)
    app.include_router(admin_billing_router)
    app.include_router(admin_users_extra_router)
    app.include_router(admin_analytics_router)
    app.include_router(admin_compliance_router)
    app.include_router(admin_crypto_router)
    app.include_router(telegram_router)
    app.include_router(topup_stream_router)
    app.include_router(payment_router)
    app.include_router(qr_router)
    app.include_router(content_router)

    # SPA static + fallback (đăng ký SAU mọi router API)
    mount_spa(app)

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description="APIBank multi-bank payment receiver",
            routes=app.routes,
        )
        schema.setdefault("components", {}).setdefault("securitySchemes", {})["BearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
        }
        for path_item in schema.get("paths", {}).values():
            for operation in path_item.values():
                if isinstance(operation, dict) and operation.get("tags"):
                    operation.setdefault("security", [{"BearerAuth": []}])
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
    return app


app = create_app()
