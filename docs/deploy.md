# Deploy APIBank trên VPS Linux

Hướng dẫn này deploy APIBank lên 1 VPS Linux (Ubuntu 22.04+ / Debian 12+) với
domain quản lý qua Cloudflare. Stack chạy hoàn toàn trong Docker:
api + worker + scheduler + Postgres 16 + Redis 7 + Caddy 2 (Let's Encrypt).

## Yêu cầu

- VPS Ubuntu 22.04+ hoặc Debian 12+, RAM ≥ 1GB, ổ cứng ≥ 10GB.
- User SSH có quyền sudo (không deploy bằng root trực tiếp).
- Domain trỏ A/AAAA về IP VPS, đang quản lý DNS trên Cloudflare.
- Có thể bật Cloudflare proxy (orange cloud) — Caddy vẫn cấp được cert.

## Bước 1 — Cloudflare API token

1. Mở https://dash.cloudflare.com/profile/api-tokens → **Create Token**.
2. Chọn template **Edit zone DNS**.
3. Zone Resources → **Include — Specific zone — chọn domain** của bạn.
4. Click Continue → Create Token. **Copy token ngay** (chỉ hiện 1 lần).

Token này chỉ cần để Caddy tạo TXT record `_acme-challenge` tạm thời.

## Bước 2 — DNS

Tạo record A (hoặc AAAA cho IPv6) cho domain APIBank, ví dụ:

```
Type   Name        Content              Proxy status
A      apibank     1.2.3.4              Proxied (orange cloud)  ← OK với DNS-01
```

Đợi khoảng 30-60 giây cho propagate.

## Bước 3 — Cài và bootstrap

Trên VPS, chạy 1 lệnh:

```bash
curl -fsSL https://raw.githubusercontent.com/datngo68/apibank/main/scripts/install.sh | bash
```

Script sẽ:

1. Cài Docker + compose plugin (nếu chưa có).
2. Clone repo về `/opt/apibank`.
3. Tạo `.env` từ template.
4. Sinh ngẫu nhiên: `APIBANK_FERNET_KEYS`, `APIBANK_API_KEY_SALT`,
   `APIBANK_SESSION_SECRET_KEY`, `POSTGRES_PASSWORD`.
5. **Dừng lại yêu cầu bạn điền** `APIBANK_DOMAIN`, `APIBANK_ACME_EMAIL`,
   `CLOUDFLARE_API_TOKEN` vào `/opt/apibank/.env`.

Sau khi điền xong, chạy lại bootstrap để tiếp tục:

```bash
cd /opt/apibank
nano .env                         # điền domain, email, Cloudflare token
bash infra/docker/bootstrap.sh
```

Bootstrap sẽ:

- Build image `apibank:latest` + `apibank-caddy:latest`.
- Start Postgres + Redis.
- Chạy `alembic upgrade head` (service `migrate`).
- Seed gói cước mặc định.
- Hỏi email + password để tạo admin user.

## Bước 4 — Khởi động stack

```bash
docker compose -f infra/docker/docker-compose.yml up -d
docker compose -f infra/docker/docker-compose.yml ps
```

Sau ~30 giây Caddy sẽ cấp xong Let's Encrypt cert (xem log
`docker compose ... logs -f caddy`). Truy cập `https://your-domain` để vào
landing page. Login bằng email admin đã tạo ở bước 3.

## Bước 5 — Cấu hình bank account

1. Vào dashboard → **Bank accounts** → Thêm tài khoản MB (username + password).
2. Verify đăng nhập OK (worker poll thử + lưu cookie).
3. **System bank** → đánh dấu tài khoản này nhận topup ví.
4. Test bằng cách tạo 1 topup từ trang **Wallet** rồi chuyển tiền thật.

## Vận hành

### Xem log

```bash
cd /opt/apibank
docker compose -f infra/docker/docker-compose.yml logs -f api
docker compose -f infra/docker/docker-compose.yml logs -f worker
docker compose -f infra/docker/docker-compose.yml logs -f scheduler
docker compose -f infra/docker/docker-compose.yml logs -f caddy
```

### Cập nhật phiên bản mới

```bash
cd /opt/apibank
git pull
docker compose -f infra/docker/docker-compose.yml build api caddy
docker compose -f infra/docker/docker-compose.yml run --rm migrate
docker compose -f infra/docker/docker-compose.yml up -d
```

### Backup database

```bash
# Snapshot tức thì
docker compose -f infra/docker/docker-compose.yml exec -T postgres \
    pg_dump -U apibank apibank | gzip > "backup-$(date +%Y%m%d-%H%M).sql.gz"
```

Hoặc dùng [infra/scripts/backup.sh](../infra/scripts/backup.sh) đã có sẵn.

### Restore

```bash
gunzip < backup-2026-05-17-1200.sql.gz | docker compose -f infra/docker/docker-compose.yml \
    exec -T postgres psql -U apibank -d apibank
```

### Bật stack observability (Prometheus + Grafana + Loki)

```bash
docker compose -f infra/docker/docker-compose.yml --profile observability up -d
```

Grafana mặc định ở `http://<vps-ip>:3000` — nên đặt sau VPN hoặc khoá firewall
nếu không cần truy cập public.

### Bật node-bridge fallback (khi mbbank-lib python không work)

```bash
docker compose -f infra/docker/docker-compose.yml --profile fallback up -d mb-bridge
```

Sau đó set `APIBANK_MB_BRIDGE_URL=http://mb-bridge:3000` trong `.env`.

## Troubleshooting

### Caddy không cấp được cert

Xem log `docker compose ... logs caddy`. Lỗi phổ biến:

- **`unauthorized`**: Cloudflare API token thiếu quyền hoặc sai zone.
  Tạo lại token với template "Edit zone DNS" + đúng zone.
- **`no such host`**: domain chưa propagate. Chờ thêm vài phút hoặc kiểm tra
  `dig +short your-domain` từ ngoài VPS.
- **`rate limited`**: Let's Encrypt giới hạn 5 cert/tuần/domain. Đợi 7 ngày
  hoặc dùng staging endpoint:
  ```
  # Tạm thời thêm vào Caddyfile dưới `tls`:
  ca https://acme-staging-v02.api.letsencrypt.org/directory
  ```

### Migration fail

```bash
docker compose -f infra/docker/docker-compose.yml run --rm migrate
```

Xem error chi tiết. Nếu DB schema lệch, có thể reset (mất data):

```bash
docker compose -f infra/docker/docker-compose.yml down
docker volume rm docker_pgdata
docker compose -f infra/docker/docker-compose.yml up -d postgres
docker compose -f infra/docker/docker-compose.yml run --rm migrate
```

### Worker không poll được MB

```bash
docker compose -f infra/docker/docker-compose.yml logs worker | grep -E "bank_login|poll_failed"
```

Nếu thấy `bank_login_failed_retrying` → username/password sai hoặc MB yêu cầu OTP.
Vào dashboard → Bank accounts → cập nhật credential. Xem [docs/runbooks/incident-poller-stuck.md](runbooks/incident-poller-stuck.md).

### Quên password admin

```bash
docker compose -f infra/docker/docker-compose.yml run --rm \
    --entrypoint apimb api user reset-password admin@example.com
```

## Bảo mật khuyến nghị

- Đóng port 5432 (Postgres) và 6379 (Redis) khỏi public — đã đóng sẵn trong
  compose (chỉ expose internal network).
- Giới hạn SSH bằng key + fail2ban.
- Backup `.env` (chứa Fernet key) ra ngoài VPS — mất key đồng nghĩa mất
  credential bank đã encrypt.
- Rotate Fernet key mỗi 90 ngày: xem [docs/runbooks/rotate-fernet-key.md](runbooks/rotate-fernet-key.md).
- Bật Cloudflare WAF rule cho `/api/v1/auth/login` chống brute-force chéo
  (rate limit của app đã có ở tầng app).
