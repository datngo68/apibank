# APIBank

Cổng nhận tiền tự host, đa người dùng, cho nhiều ngân hàng Việt Nam (MB chính,
BIDV/ACB/VCB qua adapter). Đóng gói thành SaaS hoàn chỉnh: landing page,
đăng ký/đăng nhập, ví số dư, gói cước, webhook, API key, dashboard, admin
console — tất cả khởi động chỉ bằng `apimb start`.

## Quickstart (đã có Python 3.12+)

```powershell
pip install -e ".[dev]"
apimb start
```

Sau khi chạy, APIBank xuất hiện ở **khay hệ thống** (system tray) với menu
mở dashboard, mở admin console, copy URL, và nút **Thoát** (shutdown sạch sẽ
— không bị Ctrl+C kẹt). Mặc định lắng nghe `http://localhost:8000`.

Cờ phụ:

- `apimb start --no-tray` — chạy console (Linux server / CI / SSH).
- `apimb start --port 9000 --host 127.0.0.1` — đổi địa chỉ.
- `apimb start --reload` — uvicorn reload mode cho dev (tự động `--no-tray`).

## Setup chi tiết lần đầu

```powershell
python -m pip install -e ".[dev]"

cd apps/web
npm install
npm run build
cd ../..

apimb migrate
apimb plan seed
apimb user create --email admin@local --admin           # nhập password khi được hỏi
apimb fernet generate                                   # paste vào .env: APIBANK_FERNET_KEYS=primary:...
apimb bank-account create --bank-code MB --account-no 1234567890 \
    --holder "APIBANK SYSTEM" --username MB_USER --password MB_PASS
apimb system-bank set --account-id ba_xxx               # đánh dấu bank nhận topup ví

apimb doctor                                            # phải xanh hết các dòng
apimb start                                             # http://localhost:8000
```

Cần Python 3.12+ và Node.js 20+.

## Stack

- Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, Postgres 16/SQLite (local), Redis 7, APScheduler, httpx.
- Auth: cookie session server-side + bcrypt prehash SHA-256 + TOTP 2FA + CSRF double-submit.
- Frontend: Vite 5 + React 18 + TypeScript strict + Tailwind 3 + shadcn/ui primitives + TanStack Query + Zod + react-hook-form + recharts + framer-motion + sonner.
- Observability: structured JSON logs + Prometheus metrics (auth/billing/HTTP) + Sentry hook + Grafana dashboard.
- Deploy: Docker multi-stage + docker-compose + Caddy + GitHub Actions.

## Cấu trúc

```
apps/
  api/          # FastAPI app (lifespan + middleware + routes + SPA mount)
  cli/          # apimb / apibank CLI
  web/          # Vite SPA (landing + auth + dashboard + admin)
  worker/       # bank polling
  scheduler/    # cron jobs (reconcile, webhook, expire-subs)
packages/
  billing/      # wallet, topup, subscription, quota, plans seed
  notifications/# email + telegram + in-app + dispatcher
  security/     # auth, sessions, passwords, csrf, rate_limit, twofa, email_tokens
  schemas/      # pydantic auth + me + orders + ...
  db/           # SQLAlchemy models + repositories + session
  core/         # ingest + matcher + state machine
  banks/        # adapter + MB + node bridge
  obs/          # metrics + logging + sentry
infra/
  docker/       # multi-stage Dockerfile + compose + caddy + prometheus
  load/         # locust scenarios
docs/           # architecture, runbooks, performance, security
tests/          # unit + integration
```

## Test

```powershell
python -m pytest                            # 200+ test
python -m ruff check .
python -m mypy apps packages
cd apps/web && npm run typecheck && npm run test
```

## Vận hành

| Lệnh                       | Mô tả                                                       |
|----------------------------|-------------------------------------------------------------|
| `apimb start`              | API + worker + scheduler + dispatcher + SPA trên 1 process. |
| `apimb dev`                | uvicorn --reload + vite dev concurrency.                    |
| `apimb migrate`            | Apply migrations (target=head mặc định).                    |
| `apimb doctor`             | Kiểm tra môi trường & gợi ý fix.                            |
| `apimb user create`        | Tạo user, có flag `--admin`.                                |
| `apimb plan seed`          | Tạo 3 gói mặc định (trial/tháng/năm).                       |
| `apimb system-bank set`    | Đánh dấu bank account nhận topup ví.                        |
| `apimb fernet generate`    | Sinh khóa mã hoá credential bank.                           |

## Tài liệu chi tiết

- `docs/api.md` + `docs/openapi.json` — API reference.
- `docs/integration.md` — Hướng dẫn tích hợp API + webhook để thanh toán tự động.
- `docs/security/owasp.md` — OWASP checklist.
- `docs/performance.md` — Performance budget & locust.
- `docs/runbooks/` — Backup/restore, rotate fernet, GDPR delete.
- `docs/testing-live.md` — Hướng dẫn test trên môi trường thật.

## Cảnh báo

- Adapter MB dùng thư viện không chính thức (`mbbank-lib`). Tài khoản có thể bị khóa nếu MB phát hiện auto.
- Chỉ dùng read-only để lấy lịch sử giao dịch. Không tự động chuyển tiền.
- Không bao giờ chia sẻ `APIBANK_FERNET_KEYS`. Mất key đồng nghĩa mất khả năng giải mã credential bank.
- `apimb start` mặc định bật embedded workers; với production scale ngang hãy chạy worker tách process bằng `--no-embed` rồi gọi `python -m apps.worker.main` riêng.

## License

MIT (ghi rõ trong `LICENSE`).
