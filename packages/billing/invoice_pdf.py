"""Sinh PDF hoá đơn — implementation tối giản (text PDF).

Dùng reportlab nếu đã cài; fallback raise NotImplementedError.
File output: ``invoices/<invoice_id>.pdf`` (relative tới CWD).
"""

from __future__ import annotations

import logging
from pathlib import Path

from packages.db.models import Invoice, User

logger = logging.getLogger(__name__)


async def generate(invoice: Invoice, user: User, *, base_dir: str = "invoices") -> str:
    """Sinh PDF, trả về path. Idempotent: ghi đè file cũ.

    Implementation tối giản dùng reportlab. Nếu chưa cài → raise.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError as exc:  # pragma: no cover
        raise NotImplementedError(
            "reportlab không có sẵn. `pip install reportlab` để bật regenerate PDF."
        ) from exc

    # Path I/O đồng bộ — chấp nhận với job admin tay (không hot path).
    Path(base_dir).mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    out_path = str(Path(base_dir) / f"{invoice.id}.pdf")
    c = canvas.Canvas(out_path, pagesize=A4)
    width, height = A4
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, height - 72, "APIBank — Hoa Don")
    c.setFont("Helvetica", 11)
    y = height - 110
    lines = [
        f"Invoice ID: {invoice.id}",
        f"User: {user.email}",
        f"Plan: {invoice.plan_code or '-'}",
        f"Amount: {int(invoice.amount_vnd):,} {invoice.currency}",
        f"Discount: {int(invoice.discount_vnd or 0):,}",
        f"Coupon: {invoice.coupon_code or '-'}",
        f"Status: {invoice.status}",
        f"Issued at: {invoice.issued_at.isoformat()}",
    ]
    for line in lines:
        c.drawString(72, y, line)
        y -= 18
    c.showPage()
    c.save()
    return out_path


__all__ = ["generate"]
