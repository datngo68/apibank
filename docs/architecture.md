# Architecture overview

```
   ┌────────────┐   /api,/me        ┌──────────────────────────┐
   │  Browser   │ ──────────────► │ FastAPI app (apps/api)    │
   │ (React SPA)│                   │  - middleware: csrf,     │
   │  Vite/SPA  │ ◄─── /assets,SPA  │    rate-limit, headers   │
   └────────────┘                   │  - routes: auth,me,v1,   │
                                    │    plans,admin,health    │
                                    │  - SPA mount (/)          │
                                    └────┬─────────────────┬───┘
                                         │                 │
                  Postgres / SQLite ◄────┘                 │
                                                           │
              Redis (rate limit + quota) ◄─────────────────┘
                                                           │
                          ┌────────────────────────────────┴───────────────────┐
                          │ Embedded async tasks (lifespan, opt-in qua APIBANK_EMBED_WORKERS=1) │
                          │  • run_poller_loop  (apps/worker)                  │
                          │  • start_scheduler  (apps/scheduler) — APScheduler │
                          │      ├─ reconcile every 5m                         │
                          │      ├─ webhook dispatcher every 30s               │
                          │      │   + Redis pub/sub `webhook:kick`            │
                          │      │     (near-realtime, debounce 200ms)         │
                          │      ├─ notification dispatcher every 5s           │
                          │      ├─ expire-subscriptions every 1h              │
                          │      └─ subscription expiring-soon every 12h       │
                          └────────────────────────────────────────────────────┘
```

## Domain model (snapshot)

- `User` 1—n `BankAccount`, `Webhook`, `ApiKey`, `Subscription`, `Invoice`, `WalletTransaction`, `Notification`.
- `Order` —matched— `Transaction` ngân hàng. `metadata_json["kind"] == "topup"` → trigger `wallet.credit` cho user.
- `Plan` (3 gói) ↔ `Subscription` ↔ `Invoice` ↔ `WalletTransaction(type=debit)`.
- `Session` lưu token hash; `EmailToken` cho verify/reset; `TwoFactor` lưu secret + recovery codes hash.

## Data integrity

- Wallet ledger: mọi `WalletTransaction.amount_vnd` có dấu, sum theo user phải bằng `User.balance_vnd`. Đảm bảo bằng:
  - `idempotency_key` UNIQUE — re-call cùng key trả về row cũ.
  - `SELECT ... FOR UPDATE` (Postgres) hoặc serialize (SQLite) khi cập nhật cache balance.
- Order/Transaction: state machine `pending → paid/expired/canceled` (và `transaction.state ∈ {new,matched,review,unmatched,ignored}`). Match tự động + manual force-match.
- Idempotency cho `POST /v1/orders` qua header `Idempotency-Key`.

## Security in depth

- Cookie session httpOnly + SameSite=Lax + revoke server-side.
- CSRF double-submit cho mọi unsafe method ngoài Bearer.
- Brute-force lockout login sau 5 sai/15 phút.
- Bcrypt cost 12 + prehash SHA-256 (chống truncation 72-byte).
- Fernet rotate keys multi-key.
- Headers: HSTS prod, CSP, X-Frame-DENY, Permissions-Policy.

## Observability

- Logging JSON với request_id (UUID hex16) gắn vào response header `X-Request-Id`.
- Prometheus metrics: poll, match, orders, webhook, auth, billing, wallet gauge, http p95.
- Grafana dashboard mặc định + alert rules cho poller lag, webhook fail, brute-force.
- Sentry tag `component=api|worker|scheduler` + release.

## Deploy

- Multi-stage Dockerfile: Node build SPA → Python image. Container run `apimb start`.
- docker-compose: api + worker + scheduler (process tách riêng, `APIBANK_EMBED_WORKERS=0`)
  + postgres + redis + caddy + (profile `observability`) prometheus + grafana + loki + promtail
  + (profile `fallback`) node-bridge.
- Image pull mặc định từ `ghcr.io/datngo68/apibank` + `apibank-caddy`; có
  `docker-compose.build.yml` để build local khi test code chưa tag.
- GitHub Actions: ci (lint/test/build), nightly (pip-audit + npm audit, fail high+),
  release (build + push ghcr.io image trên tag).
