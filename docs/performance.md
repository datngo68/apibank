# Performance budget — APIBank

## Backend

- p95 `/v1/orders` POST < 200ms (1 instance, db sqlite/postgres local).
- p95 `/api/v1/me/*` GET < 150ms.
- Worker poller 1 cycle (200 transactions) < 5s.
- Webhook dispatcher drain 1000 attempt < 60s.

## Indexes (đã có trong migration)

- `orders(bank_account_id, status, created_at)` — đã đảm bảo qua FK + index status/expired_at + bank_account_id.
- `transactions(bank_account_id, posted_at desc)` — qua index `posted_at` + FK bank_account_id.
- `webhook_attempts(status, next_run_at)` — đã có index status + next_run_at.
- `wallet_transactions(user_id, created_at)` — composite `ix_wallet_tx_user_created`.
- `audit_logs(action, target_id, created_at)` — đã có index action + target_id.

## Frontend

- Bundle gzip route `/`: ≤ 130 KB. Bundle gzip dashboard: ≤ 250 KB (đo bằng `npm run build`).
- Lighthouse mobile (3G fast): perf ≥ 90, a11y ≥ 95, best-practice ≥ 95.
- Code split route bằng `React.lazy` + `Suspense` cho admin (sẽ thêm ở polish round).

## Kế hoạch đo & cải thiện

1. CI bật bước `npm run build` rồi check `dist/assets/*.js` < 600KB raw qua gh-action `actions-bundle-size`.
2. Locust scenario `infra/load/locustfile.py`:
   - 100 user/s landing trong 5 phút → p95 < 200ms.
   - 50 order/s sustained 5 phút → 0 error 5xx.
3. Khi p95 vượt ngưỡng: dùng `pyinstrument` (đã pin trong dev deps tương lai) để profile route nóng.
