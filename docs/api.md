# APIBank HTTP API

Phiên bản 0.1.0. Có 3 nhóm endpoint:

- **`/v1/*`** — Bearer API key (cho merchant tích hợp).
- **`/api/v1/auth/*`, `/api/v1/me/*`, `/api/v1/admin/*`** — cookie session (SPA dashboard, browser flow).
- **`/healthz`, `/readyz`, `/metrics`** — operational.

Schema chi tiết (mọi field, validator, response model) được export ở `docs/openapi.json` (sinh từ FastAPI bằng `python scripts/dump_openapi.py`). Phần dưới chỉ tóm tắt mức cao.

## Auth — flow

1. **Đăng ký**: `POST /api/v1/auth/register {email, password, full_name?}` → `201 {message}`. Server gửi email xác minh; phản hồi luôn 201, kể cả khi email đã đăng ký (anti-enumeration).
2. **Đăng nhập (1 step)**: `POST /api/v1/auth/login {email, password}` → `200 {user}` + cookie `apibank_sid` httpOnly + `apibank_csrf` cho double-submit.
3. **Đăng nhập (2 step, có 2FA)**:
   - Step 1: `POST /api/v1/auth/login {email, password}` → `200 {requires_2fa: true, challenge_token}`.
   - Step 2 (gọn): gọi lại `POST /login {email, password, code, challenge_token}`; hoặc chuyên dụng `POST /api/v1/auth/2fa/challenge {challenge_token, code}`.
   - `code` là TOTP 6 chữ số HOẶC recovery code 8 ký tự.
4. **Reset password**: `POST /forgot {email}` → server gửi token; `POST /reset {token, password}`. Cả hai luôn trả 200/`message: ok` để không leak.
5. **2FA setup**: `POST /2fa/enroll` (cookie session) → trả `secret + otpauth_uri`; xác nhận bằng `POST /2fa/verify {code}` → trả 10 recovery code (chỉ hiện 1 lần).

Header CSRF (`X-CSRF-Token`) bắt buộc cho mọi request mutation tới `/api/*`. Endpoint `/v1/*` (Bearer) bypass CSRF.

## Webhook signature

Mọi webhook outbound có 2 header:

- `Content-Type: application/json`
- `X-Signature: t=<unix_ts>,v1=<hmac_sha256_hex>`

Verify ở consumer:

```python
import hmac, hashlib

def verify(body: bytes, header: str, secret: str, *, tolerance=300) -> bool:
    parts = dict(p.split('=', 1) for p in header.split(',') if '=' in p)
    ts = int(parts['t']); sig = parts['v1']
    if abs(time.time() - ts) > tolerance:  # chống replay 5 phút
        return False
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, sig)
```

Server retry với delay `[0, 30, 120, 600, 3600, 21600, 86400]s`, max 7 lần, sau đó chuyển sang `dead` và phát noti `webhook_failing`.

## Multi-tenant safety

- Mọi route `/v1/*` (trừ admin scope) tự động filter theo `api_key.user_id`. User A không thể đọc/cancel order, transaction, webhook của user B → trả 404.
- `enforce_subscription_and_quota` chặn mọi `/v1/*` nếu subscription hết hạn (402) hoặc vượt quota plan (429).
- Webhook URL được kiểm chống SSRF: refuse `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16` (IMDS), loopback IPv6 — ở môi trường production. Local dev cho phép loopback nhưng vẫn cấm IMDS.

## Endpoint summary

Số lượng path tự sinh từ OpenAPI:

| Prefix | Mô tả | Auth |
|---|---|---|
| `/healthz`, `/readyz`, `/metrics` | Operational | none |
| `/api/v1/auth/*` (~25) | Register, login, 2FA, sessions, OAuth Google | cookie + CSRF |
| `/api/v1/me/*` (~24) | Bank accounts, webhooks (kèm `/test`), API keys, wallet, topup, plans, subscription, invoices, orders/tx, notifications | cookie + CSRF |
| `/api/v1/admin/*` (~25) | Users, plans, bank accounts, system bank, audit log, SMTP/Google/Telegram config | cookie + CSRF + role admin/owner + 2FA khuyến nghị |
| `/v1/orders` `POST/GET/cancel` | Tạo/đọc/huỷ order | Bearer + scope `orders:write` / `orders:read` |
| `/v1/transactions` | Liệt kê tx | Bearer + scope `transactions:read` |
| `/v1/bank-accounts` | List bank accounts của user (cho UI integration) | Bearer + scope `bank_accounts:read` |
| `/v1/webhooks` (admin scope) | Quản lý webhook hệ thống | Bearer + `admin:*` |
| `/api/v1/telegram/webhook` | Telegram bot inbound | secret token header |
| `/pay/{code}`, `/pay/{code}/status` | Payment landing + JSON polling | none / signed code |
| `/qr/{order_id}.png` | VietQR PNG (theo order **id**, không phải code) | none |
| `/api/v1/me/topup/{code}/events` | SSE realtime cho topup ví (dashboard only) | cookie + CSRF |

Để xem schema chi tiết:

```powershell
python scripts/dump_openapi.py   # ghi docs/openapi.json
# Hoặc serve qua Swagger UI khi `apimb start`:
# http://localhost:8000/docs
```

## Tóm tắt thay đổi 0.1.0

- Tách `session_secret_key` khỏi `api_key_salt`; production validate độ mạnh.
- 2FA dùng `challenge_token` single-use + lockout exponential + TOTP anti-replay.
- IDOR fix: `/v1/orders/{id}`, `:cancel`, `/v1/transactions` filter theo `user_id`.
- Webhook ký HMAC bằng secret gốc (decrypt từ Fernet), bắt buộc Fernet ở production, SSRF guard.
- Rate-limit fallback in-memory khi Redis down + per-email limit cho `/login`, `/forgot`, `/2fa/*`, `/register`.
- API key `expires_at` enforce ở `resolve_api_key`; cập nhật `last_used_at/ip`.
- Đăng ký không leak email tồn tại; gửi email cảnh báo cho user thật.
- SMTP thật cho register/forgot/resend-verify (cấu hình qua admin Console).
- In-app notification: `/api/v1/me/notifications` + bell UI; dispatcher wire vào ingest, subscription, scheduler, worker, webhook dead-letter.
- BIDV/ACB/VCB ẩn khỏi UI và backend reject (chỉ MB + Vietinbank hoạt động).
- Webhook test ping inline (`POST /me/webhooks/{id}/test`).
- Loại bỏ Jinja admin UI legacy `/admin/*` — chỉ giữ SPA admin tại `/app/admin`.
