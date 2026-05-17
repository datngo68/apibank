"""Seed danh mục plan mặc định cho hệ thống.

Idempotent: chạy nhiều lần chỉ tạo nếu chưa có.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import Plan

DEFAULT_PLANS: list[dict[str, object]] = [
    {
        "code": "trial-day",
        "name": "Gói trải nghiệm",
        "description": "Sử dụng đầy đủ tính năng trong 24 giờ.",
        "price_vnd": Decimal(1_000),
        "duration_days": 1,
        "daily_quota": 5_000,
        "monthly_quota": 5_000,
        "features_json": {
            "highlights": [
                "Kiểm tra giao dịch không giới hạn (5k req/ngày)",
                "Hỗ trợ toàn bộ ngân hàng",
                "Webhook + giải captcha",
            ],
            "trial": True,
        },
        "sort_order": 0,
    },
    {
        "code": "monthly",
        "name": "Gói theo tháng",
        "description": "Trải nghiệm trọn vẹn không giới hạn trong 30 ngày.",
        "price_vnd": Decimal(15_000),
        "duration_days": 30,
        "daily_quota": 50_000,
        "monthly_quota": 1_000_000,
        "features_json": {
            "highlights": [
                "Kiểm tra giao dịch không giới hạn",
                "Không giới hạn số ngân hàng",
                "Hỗ trợ riêng 24/7",
                "Thông báo Telegram tự động",
            ],
        },
        "sort_order": 10,
    },
    {
        "code": "yearly",
        "name": "Gói theo năm",
        "description": "Tiết kiệm chi phí, miễn phí cập nhật & hỗ trợ.",
        "price_vnd": Decimal(150_000),
        "duration_days": 365,
        "daily_quota": 100_000,
        "monthly_quota": 3_000_000,
        "features_json": {
            "highlights": [
                "Kiểm tra giao dịch không giới hạn",
                "Hỗ trợ tích hợp miễn phí",
                "Ưu tiên xử lý sự cố",
                "Tiết kiệm 17% so với gói tháng",
            ],
            "popular": True,
        },
        "sort_order": 20,
    },
]


async def seed_plans(session: AsyncSession) -> int:
    """Insert plans nếu chưa có. Trả số plan tạo mới."""
    created = 0
    for spec in DEFAULT_PLANS:
        existing = (
            await session.scalars(select(Plan).where(Plan.code == spec["code"]))
        ).first()
        if existing is not None:
            continue
        plan = Plan(**spec)
        session.add(plan)
        created += 1
    if created:
        await session.flush()
    return created
