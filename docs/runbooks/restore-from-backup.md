# Runbook: restore backup

1. Dừng `api`, `worker`, `scheduler`.
2. Restore `pg_dump` mới nhất vào Postgres sạch.
3. Chạy `alembic upgrade head`.
4. Bật `scheduler` reconcile 48h gần nhất.
5. Bật `worker`, sau đó bật `api`.
