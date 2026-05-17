# ADR 0004: Outbox dispatcher chạy trong scheduler

## Quyết định

Webhook outbox dispatch chạy trong tiến trình `scheduler` (APScheduler) chứ không phải trong API process.

## Lý do

- Tách traffic API khỏi tác vụ I/O kéo dài (gửi webhook).
- Cho phép scale scheduler riêng.
- Tránh mất delivery khi API restart giữa request.
