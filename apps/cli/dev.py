"""`apimb dev` — chạy uvicorn --reload + vite dev song song."""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parents[2] / "apps" / "web"


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("dev", help="run api + vite dev concurrently")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--no-vite", action="store_true", help="skip vite dev (frontend hot reload)")
    p.set_defaults(func=lambda args: asyncio.run(run(args)))


async def run(args: argparse.Namespace) -> int:
    os.environ.setdefault("APIBANK_EMBED_WORKERS", "0")
    os.environ.setdefault("APIBANK_LOG_LEVEL", "INFO")

    api_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "apps.api.main:app",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--reload",
    ]

    procs: list[asyncio.subprocess.Process] = []
    procs.append(await _spawn("api", api_cmd))

    if not args.no_vite:
        if WEB_DIR.exists():
            npm = "npm.cmd" if os.name == "nt" else "npm"
            procs.append(
                await _spawn(
                    "web",
                    [npm, "run", "dev"],
                    cwd=str(WEB_DIR),
                )
            )
        else:
            print(f"[apimb] {WEB_DIR} không tồn tại — bỏ qua vite", flush=True)

    print("\n[apimb] Đã khởi động. Ctrl+C để dừng.\n", flush=True)

    stop = asyncio.Event()

    def _on_signal() -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    if os.name != "nt":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _on_signal)
    try:
        await stop.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        for proc in procs:
            if proc.returncode is None:
                proc.terminate()
        await asyncio.sleep(0.5)
        for proc in procs:
            if proc.returncode is None:
                proc.kill()
    return 0


async def _spawn(prefix: str, cmd: list[str], cwd: str | None = None) -> asyncio.subprocess.Process:
    print(f"[apimb] $ {' '.join(cmd)} (cwd={cwd or '.'})", flush=True)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=os.environ.copy(),
    )
    asyncio.create_task(_relay(prefix, proc))
    return proc


async def _relay(prefix: str, proc: asyncio.subprocess.Process) -> None:
    if proc.stdout is None:
        return
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        sys.stdout.write(f"[{prefix}] {line.decode(errors='replace').rstrip()}\n")
        sys.stdout.flush()
