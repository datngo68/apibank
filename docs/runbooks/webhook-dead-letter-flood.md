# Runbook: webhook dead-letter flood

1. Mở Grafana dashboard `APIBank Overview`, kiểm tra panel `Webhook attempts`.
2. Truy vấn DB:
   ```sql
   SELECT id, webhook_id, last_status_code, last_error
   FROM webhook_attempts
   WHERE status = 'dead'
   ORDER BY sent_at DESC NULLS LAST
   LIMIT 50;
   ```
3. Nếu lỗi từ phía merchant (5xx kéo dài), liên hệ merchant.
4. Nếu lỗi do data, sửa webhook và replay:
   ```bash
   curl -X POST -H "Authorization: Bearer ${ADMIN_KEY}" \
     "${API_BASE}/v1/webhooks/attempts/${ATTEMPT_ID}:replay"
   ```
5. Bulk replay: dùng SQL set `status='pending', next_run_at=now()` cho các attempt theo điều kiện.
