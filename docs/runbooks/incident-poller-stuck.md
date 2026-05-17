# Incident: poller stuck

## Triệu chứng

- Alert `PollerLagHigh`: poller không cập nhật transaction trong > 2 phút.
- Dashboard wallet không thấy giao dịch mới.
- Log có `login_failed`, `rate_limited`, hoặc lặp `poll_failed`.

## Triage

```bash
apimb doctor
docker compose logs api --tail=200 | grep poll
```

1. Nếu `BankAuthError` lặp lại → adapter MB bị challenge OTP. Giải pháp:
   - Đăng nhập app banking thủ công, vượt qua thử thách.
   - Sau đó `apimb` restart container; poller tự re-login.

2. Nếu `BankRateLimited` → bank chặn truy cập. Đợi 5–15 phút.
   - Nếu vẫn fail, dùng node-bridge fallback: `docker compose --profile fallback up -d mb-bridge`.

3. Nếu lock Redis chưa release → `redis-cli DEL poller:lock:<account_id>`.

## Roll back

- Tắt account: `UPDATE bank_accounts SET polling_enabled = false WHERE id = ...`
- Bật lại sau khi sửa: cập nhật credential bằng `POST /api/v1/me/bank-accounts/{id}/rotate`.
