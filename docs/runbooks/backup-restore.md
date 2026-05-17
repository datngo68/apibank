# Runbook: backup & restore

## Mục tiêu

- RTO ≤ 30 phút, RPO ≤ 1 giờ với DB Postgres.
- Backup hằng đêm về S3-compatible (Minio/Wasabi).

## Backup script (Postgres)

```bash
#!/usr/bin/env bash
set -euo pipefail
TS=$(date -u +%Y%m%dT%H%M%S)
BACKUP=/var/backups/apibank-$TS.sql.gz
pg_dump --format=custom --no-owner --compress=9 \
  "$APIBANK_DB_URL" \
  | gzip > "$BACKUP"
aws s3 cp "$BACKUP" "s3://apibank-backups/" --only-show-errors
# rotate: giữ 14 ngày
find /var/backups -name 'apibank-*.sql.gz' -mtime +14 -delete
```

Đặt cron `0 18 * * *` (01:00 GMT+7).

## Restore drill (mỗi quý)

```bash
docker compose exec postgres dropdb apibank
docker compose exec postgres createdb apibank -O apibank
gunzip -c apibank-LATEST.sql.gz | docker compose exec -T postgres psql apibank
docker compose exec api apimb migrate
docker compose exec api apimb doctor
```

Sau drill, smoke test:

1. Đăng nhập admin.
2. Tạo order test 1.000 đ.
3. Confirm webhook attempt được tạo.
4. Verify số dư ví không bị âm.

## Fernet key rotation

```bash
# 1. Sinh key mới
NEW=$(apimb fernet generate)
# 2. Bổ sung vào .env phía TRƯỚC key cũ:
#    APIBANK_FERNET_KEYS=secondary:$NEW,primary:OLD
# 3. Restart API.
# 4. Re-encrypt batch (script tự viết, đọc credentials_enc rồi ghi lại với key mới).
# 5. Sau 30 ngày, đổi role thành: APIBANK_FERNET_KEYS=primary:$NEW
# 6. Restart và verify đăng nhập bank vẫn ok; xoá key cũ khỏi env.
```

## GDPR data export & delete

- Export: `apimb user export --email <email>` (sẽ thêm trong polish round). Hiện tại có thể chạy trực tiếp:
  ```sql
  COPY (SELECT row_to_json(u) FROM users u WHERE email = $1) TO 'export.json';
  ```
- Delete: `apimb user delete --email <email>` (anonymize, giữ ledger 7 năm theo quy định kế toán).
