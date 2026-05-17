# Changelog

Tuân theo [keep-a-changelog](https://keepachangelog.com).

## [0.1.0] — 2026-05-17

### Security (audit 2026-05-17)

- **2FA hardening**: `challenge_token` single-use bắt buộc cho login step 2; lockout exponential (1m → 24h, không reset count); TOTP anti-replay 90s.
- **Tách secret**: thêm `APIBANK_SESSION_SECRET_KEY` (riêng `api_key_salt`); validator raise ở production khi secret còn default `CHANGE_ME` hoặc < 32 ký tự; bắt buộc `APIBANK_FERNET_KEYS`.
- **Cookie `Secure`** tự động ở production; có thể override `APIBANK_COOKIE_SECURE`.
- **IDOR fix** trên `/v1/orders/{id}`, `/v1/orders/:cancel`, `/v1/transactions`: chỉ user sở hữu bank account mới đọc/huỷ/list được. `enforce_subscription_and_quota` áp dụng cho mọi `/v1/*`.
- **Webhook signature đúng**: HMAC ký bằng secret gốc (decrypt Fernet) thay vì ciphertext; production bắt buộc Fernet keys, không silent fallback plain.
- **SSRF guard webhook**: chặn `127.0.0.0/8`, RFC1918, `169.254.0.0/16` (IMDS), loopback IPv6, scheme khác http(s); `follow_redirects=False`.
- **Rate-limit**: fallback in-memory khi Redis down (retry sau 60s); per-email bucket cho `/login`, `/forgot`, `/2fa/challenge`, `/register`, `/resend-verify` (10 hits/60s).
- **API key expiry**: `resolve_api_key` enforce `expires_at`; cập nhật `last_used_at/last_used_ip` mỗi lần auth.
- **Anti email-enumeration**: `/register` luôn trả 201, gửi email cảnh báo cho chủ tài khoản nếu trùng.
- **Path traversal SPA**: `is_relative_to(WEB_DIST.resolve())` trước khi serve static.

### Added

- **In-app notifications**: bảng `notifications` đã có; thêm route `/api/v1/me/notifications` (list, unread-count, mark-read, read-all) + `NotificationBell` ở dashboard layout (poll mỗi 30s).
- **Dispatcher producer wiring**:
  - `core/ingest.py` → `topup_credited` sau khi credit ví.
  - `me.py::purchase_subscription` → `subscription_purchased`.
  - `scheduler/main.py::subscription_expiring_soon_job` → notify trước hạn 3 ngày (idempotent).
  - `worker/main.py` → `bank_login_failed` (throttle 1h).
  - `webhook/dispatcher.py` → `webhook_failing` khi attempt rơi vào dead-letter.
- **Webhook test ping**: `POST /api/v1/me/webhooks/{id}/test` gửi inline 1 event `webhook.test`, trả `{delivered, status_code, signature, event_id}` cho UI hiển thị.
- **SMTP thật cho auth flow**: register-verify, resend-verify, forgot, password-changed-notice. `_send_email_stub` giờ là wrapper gọi `packages.notifications.email.send_email`. Cấu hình từ Admin Console.
- **`docs/openapi.json`**: tự sinh từ `app.openapi()` qua `python scripts/dump_openapi.py`. CI chạy script và fail nếu schema thay đổi mà không commit.

### Changed

- **Bank adapter**: chỉ MB và Vietinbank hoạt động. BIDV/ACB/VCB chuyển từ `NotImplementedError` thành `BankNotSupportedError` rõ ràng; FE disable trong dropdown; backend reject 422.
- **Webhook IP allowlist**: cột `ip_allowlist` giữ nullable cho legacy data nhưng UI và schema KHÔNG còn input/expose (semantics sai cho outbound).
- **Settings refactor**: `cookie_secure_effective` resolve theo `environment`/cờ override.

### Removed

- **Jinja admin UI** `/admin/*` (`apps/api/routes/admin_ui.py` + `apps/api/templates/admin/*`) — thay bằng SPA admin `/app/admin/*` (đã có sẵn). Loại `/admin/` khỏi CSRF exempt list.
- **`apps/api/routes/admin.py`** — endpoint legacy 1-route đã chuyển sang `admin_console`.
- **`packages/webhook/delivery.py`** — file mồ côi trùng chức năng `dispatcher.py`.
- **`/styleguide`** route công khai — wrap `import.meta.env.DEV` trong `App.tsx`.

### Fixed

- **`require_scope` bug**: dùng default value `authenticated_api_key` thay vì `Depends(...)` → check scope không chạy. Đã sửa, không route nào còn dùng pattern cũ.
- **Datetime tz-aware** so sánh khi DB là SQLite (giữ từ phiên trước).

### Migration

- `0005_2fa_replay_guard`: thêm cột `last_totp_code`, `last_totp_used_at` vào bảng `two_factors`.
- `APIBANK_SESSION_SECRET_KEY` mới — local/dev fallback `api_key_salt`; production phải set, runtime raise nếu thiếu.
- Mọi session admin (`apibank_admin` cookie) sẽ invalid sau khi đổi secret → user phải login lại.

### Known limits

- BIDV/ACB/VCB adapter chưa hoạt động; chỉ MB và Vietinbank được hỗ trợ.
- Playwright e2e suite vẫn placeholder; integration tests Python cover flow chính (~250+ test).
- Recovery codes 2FA chỉ hiển thị 1 lần khi enroll; chưa có UI regenerate (yêu cầu password) — runbook hiện hướng dẫn disable rồi enroll lại.
