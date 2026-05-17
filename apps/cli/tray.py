"""Tray icon cho APIBank.

Khi chạy `apimb start` trên Windows/macOS có GUI, app sẽ thu nhỏ vào khay
hệ thống thay vì block console. Menu:
- Mở dashboard (browser)
- Copy URL
- Mở thư mục cấu hình
- Thoát (shutdown sạch sẽ — fix Ctrl+C kẹt)

Yêu cầu: pystray + Pillow (đã có trong deps). Trên Linux không có DE thì
fallback log + signal.signal(SIGINT) bình thường.
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import sys
import threading
import webbrowser
from io import BytesIO
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

logger = logging.getLogger(__name__)


def _build_icon_image() -> PILImage:
    """Tạo icon PNG đơn giản: nền cam, chữ 'A' trắng. Không cần file ngoài."""
    from PIL import Image, ImageDraw, ImageFont

    size = 64
    img = Image.new("RGBA", (size, size), (255, 88, 0, 255))  # cam APIBank
    draw = ImageDraw.Draw(img)
    font: Any
    try:
        # Windows mặc định có Segoe UI Bold
        font = ImageFont.truetype("segoeuib.ttf", 40)
    except OSError:
        font = ImageFont.load_default()
    text = "A"
    # Center text
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1] - 2),
        text,
        fill=(255, 255, 255, 255),
        font=font,
    )
    return img


def _to_bytes(img: PILImage) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def run_with_tray(
    *,
    host: str,
    port: int,
    embed_workers: bool,
    workers: int,
) -> int:
    """Khởi động uvicorn trong thread, chạy tray icon ở main thread.

    Trả exit code khi user bấm Quit.
    """
    try:
        import pystray
        from pystray import MenuItem
    except Exception:  # noqa: BLE001
        logger.warning("pystray_missing_falling_back_to_console")
        return run_console(
            host=host, port=port, embed_workers=embed_workers, workers=workers
        )

    if embed_workers:
        os.environ["APIBANK_EMBED_WORKERS"] = "1"

    base_url = (
        f"http://{'localhost' if host in ('0.0.0.0', '::') else host}:{port}"  # noqa: S104
    )

    server_state: dict[str, Any] = {"server": None, "thread": None, "stopped": False}

    def _server_target() -> None:
        try:
            import uvicorn

            from apps.api.main import app

            config = uvicorn.Config(
                app,
                host=host,
                port=port,
                workers=workers if workers > 1 else None,
                log_level="info",
                lifespan="on",
            )
            server = uvicorn.Server(config)
            server_state["server"] = server
            server.run()
        except Exception:  # noqa: BLE001
            logger.exception("uvicorn_thread_crashed")
        finally:
            server_state["stopped"] = True

    thread = threading.Thread(target=_server_target, name="uvicorn", daemon=True)
    server_state["thread"] = thread
    thread.start()

    print(f"\n  APIBank — {base_url} (đang chạy trong khay hệ thống)\n", flush=True)

    icon_image = _build_icon_image()

    def _open_dashboard(_icon: Any, _item: Any) -> None:
        webbrowser.open(base_url)

    def _open_admin(_icon: Any, _item: Any) -> None:
        webbrowser.open(f"{base_url}/app/admin")

    def _copy_url(_icon: Any, _item: Any) -> None:
        try:
            import subprocess

            subprocess.run(
                ["clip"],  # noqa: S603, S607
                input=base_url.encode("utf-16-le"),
                check=False,
                shell=False,
            )
        except Exception:  # noqa: BLE001
            logger.debug("tray_copy_url_failed", exc_info=True)

    def _quit(icon: Any, _item: Any) -> None:
        logger.info("tray_quit_requested")
        server = server_state.get("server")
        if server is not None:
            server.should_exit = True
            with contextlib.suppress(Exception):
                server.force_exit = True
        icon.stop()

    menu = (
        MenuItem(
            f"APIBank · {base_url}",
            _open_dashboard,
            default=True,
            enabled=False,
        ),
        pystray.Menu.SEPARATOR,
        MenuItem("Mở dashboard", _open_dashboard),
        MenuItem("Mở admin console", _open_admin),
        MenuItem("Copy URL", _copy_url),
        pystray.Menu.SEPARATOR,
        MenuItem("Thoát", _quit),
    )
    icon = pystray.Icon("apibank", icon_image, "APIBank", pystray.Menu(*menu))

    # Khi nhận SIGINT (Ctrl+C trong console nếu user vẫn để mở), cũng thoát sạch
    def _on_signal(*_args: Any) -> None:
        _quit(icon, None)

    try:
        signal.signal(signal.SIGINT, _on_signal)
        signal.signal(signal.SIGTERM, _on_signal)
    except (ValueError, OSError):
        # Không phải main thread (vd test), bỏ qua
        pass

    icon.run()  # block tới khi _quit gọi icon.stop()

    # Đợi thread server tắt sạch
    if thread.is_alive():
        thread.join(timeout=10)
    return 0


def run_console(
    *,
    host: str,
    port: int,
    embed_workers: bool,
    workers: int,
    reload: bool = False,
) -> int:
    """Fallback: chạy uvicorn qua subprocess giống code cũ."""
    import shlex
    import subprocess

    if embed_workers:
        os.environ["APIBANK_EMBED_WORKERS"] = "1"
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "apps.api.main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if workers > 1 and not reload:
        cmd.extend(["--workers", str(workers)])
    if reload:
        cmd.append("--reload")

    print(f"\n  APIBank — http://{host}:{port}\n", flush=True)
    print(f"$ {shlex.join(cmd)}", flush=True)
    return subprocess.call(cmd)  # noqa: S603
