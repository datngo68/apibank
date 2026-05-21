"""Request-scoped logging context.

Set ``request_id``, ``user_id``, ``route`` qua ``ContextVar`` từ middleware,
inject vào mọi log record qua ``logging.Filter``.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
route_var: ContextVar[str | None] = ContextVar("route", default=None)


class RequestContextFilter(logging.Filter):
    """Inject request_id / user_id / route vào mỗi LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        record.request_id = request_id_var.get() or "-"
        record.user_id = user_id_var.get() or "-"
        record.route = route_var.get() or "-"
        return True


__all__ = ["RequestContextFilter", "request_id_var", "user_id_var", "route_var"]
