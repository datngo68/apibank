import logging
import sys

from pythonjsonlogger import jsonlogger

from packages.obs.context import RequestContextFilter

# Logger ồn ào nhưng ít giá trị — hạ xuống WARNING để không spam stdout.
# Nếu cần debug, set APIBANK_LOG_LEVEL=DEBUG sẽ override (xem ở dưới).
_NOISY_LOGGERS: tuple[str, ...] = (
    "apscheduler.executors.default",  # mỗi tick "Running job..." + "executed successfully"
    "apscheduler.scheduler",
    "httpx",
    "httpcore",
    "urllib3",
    "asyncio",
)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        jsonlogger.JsonFormatter(  # type: ignore[attr-defined]
            "%(asctime)s %(levelname)s %(name)s %(request_id)s %(user_id)s "
            "%(route)s %(message)s"
        )
    )
    handler.addFilter(RequestContextFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    resolved = level.upper()
    root.setLevel(resolved)

    # Khi user đã chọn DEBUG thì để các logger noisy hiện đầy đủ; còn lại
    # giữ ở WARNING để stdout chỉ thấy event quan trọng.
    quiet_level = "DEBUG" if resolved == "DEBUG" else "WARNING"
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(quiet_level)
