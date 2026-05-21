# OWASP Top 10 — APIBank checklist

Bản đối chiếu tại 0.1.0 (sau security hardening 2026-05-17). Mỗi mục có người triển khai và bằng chứng (path + line).

| #  | Risk                          | Tình trạng | Đối ứng                                                                                  |
|----|-------------------------------|-----------|-------------------------------------------------------------------------------------------|
| A01| Broken Access Control         | ✅ Pass   | `/v1/*` filter theo `api_key.user_id` (`packages/security/dependencies.py::assert_bank_account_owned`); `/api/v1/me/*` filter `user_id`; `tests/integration/test_idor.py` cover. |
| A02| Cryptographic Failures        | ✅ Pass   | Bcrypt rounds=12 + SHA-256 prehash; Fernet rotation cho credential bank và webhook secret (`packages/webhook/__init__.py::encrypt_webhook_secret`). Production raise nếu `FERNET_KEYS` rỗng hoặc secret default. |
| A03| Injection                     | ✅ Pass   | SQLAlchemy ORM (parameterized); webhook URL `pydantic.HttpUrl` + scheme allowlist `http(s)`; SPA fallback `is_relative_to(WEB_DIST)` chống path traversal. |
| A04| Insecure Design               | ✅ Pass   | Wallet double-entry + idempotency UNIQUE; lockout exponential (1m → 24h) trong `auth.py::_next_lockout_duration`; 2FA challenge_token single-use + TOTP anti-replay (cửa sổ 90s). |
| A05| Security Misconfiguration     | ✅ Pass   | Security headers middleware (HSTS prod, CSP, Frame-DENY, Permissions-Policy); cookie `Secure` tự động ở production; `Settings` validator raise khi salt/session_secret/Fernet còn default trong production. |
| A06| Vulnerable Components         | ✅ Pass   | `pip-audit` + `npm audit --omit=dev` chạy nightly trong `.github/workflows/nightly.yml` và **fail build** nếu có CVE high+ (đã bỏ `\|\| true`). |
| A07| Identification & Auth Failures| ✅ Pass   | 2FA TOTP + recovery codes + challenge_token; session table revoke per-device + logout-all; rate-limit theo email cho `/login`, `/forgot`, `/2fa/*`, `/register` (10 hits/60s/email). |
| A08| Software & Data Integrity     | ✅ Pass   | Webhook ký HMAC SHA-256 bằng secret gốc (đã sửa: trước đây ký bằng Fernet ciphertext); CSRF double-submit; `follow_redirects=False` khi gửi webhook. |
| A09| Logging & Monitoring          | ✅ Pass   | JSON log + request_id, Prometheus metrics, alert rules, Sentry hook. Audit log multi-tenant với actor='system' phân biệt. |
| A10| SSRF                          | ✅ Pass   | `packages/webhook/is_safe_webhook_url` chặn private/loopback/link-local/multicast (production); chặn IMDS `169.254.169.254` cả ở dev. Test: `tests/unit/test_webhook_safety.py`, `test_webhook_dispatcher_decrypt.py`. |

## Việc cần làm trước khi public

- [x] Bật `pip-audit` trong CI nightly và fail build với high+ CVE.
- [x] Bật `npm audit --omit=dev` và fail với high+ severity.
- [ ] Cấu hình Caddy/cloud egress để block `metadata.google.internal`, `169.254.169.254` (defense in depth ngoài ứng dụng).
- [ ] Chạy ZAP baseline scan vào URL staging trước mỗi release (script trong `infra/scripts/`, optional CI job).
- [ ] Rà soát audit log mỗi tháng để phát hiện hành vi bất thường.

## Phát hiện và đóng (audit 2026-05-17)

| Severity | Mô tả | File:line | Trạng thái |
|---|---|---|---|
| CRITICAL | 2FA `challenge_token` không verify, cho phép brute-force TOTP song song với password | `apps/api/routes/auth.py:255-273` | Đã fix — endpoint `/2fa/challenge` verify token; `/login` step 2 yêu cầu `challenge_token`. |
| CRITICAL | Webhook HMAC ký bằng `secret_enc` (ciphertext Fernet) thay vì secret gốc | `packages/webhook/dispatcher.py:54` | Đã fix — `decrypt_webhook_secret` trước khi ký. |
| CRITICAL | `SessionMiddleware` dùng chung secret với `api_key_salt` | `apps/api/main.py:69-74` | Đã fix — thêm `session_secret_key` riêng + production validator. |
| HIGH | Cookie `secure=False` cứng | `apps/api/routes/auth.py:84-93` | Đã fix — `cookie_secure_effective`. |
| HIGH | Lockout reset count khi đạt threshold (cho phép brute trở lại) | `apps/api/routes/auth.py:200-205` | Đã fix — không reset count, exponential backoff. |
| HIGH | Email enumeration ở `/register` (409 leak) | `apps/api/routes/auth.py:136-141` | Đã fix — luôn 201, gửi email cảnh báo cho user thật. |
| HIGH | IDOR `/v1/orders/{id}`, `/v1/transactions` không filter theo user_id | `apps/api/routes/{orders,transactions}.py` | Đã fix — `assert_bank_account_owned`, repository filter. |
| HIGH | Subscription gate chỉ áp `POST /v1/orders` | `apps/api/routes/orders.py` | Đã fix — áp lên mọi route `/v1/*`. |
| HIGH | `require_scope` bug: dùng default value thay vì Depends | `apps/api/routes/{orders,webhooks}.py` (helper `_require_scope`) | Đã fix. |
| HIGH | Admin Jinja UI `/admin/*` không CSRF, login bằng API key, raw key qua URL | `apps/api/routes/admin_ui.py` | Đã xoá toàn bộ; SPA admin (`/app/admin/*`) là đường duy nhất. |
| HIGH | Webhook SSRF: gọi private IP/IMDS | `packages/webhook/dispatcher.py` | Đã fix — `is_safe_webhook_url` + `follow_redirects=False`. |
| HIGH | Rate-limit Redis down → no-limit forever | `apps/api/middleware/rate_limit.py:27-44` | Đã fix — fallback in-memory + retry sau 60s. |
| HIGH | `ApiKey.expires_at` không enforce ở resolver | `packages/security/api_keys.py::resolve_api_key` | Đã fix — kiểm `expires_at < now` ở `authenticated_api_key`. |
| MEDIUM | SPA path traversal | `apps/api/spa.py:95-112` | Đã fix — `is_relative_to(WEB_DIST.resolve())`. |
| MEDIUM | TOTP code có thể dùng lại trong cửa sổ 90s | `packages/security/twofa.py` | Đã fix — `last_totp_code/last_totp_used_at` trong `TwoFactor`. |
| MEDIUM | Webhook IP allowlist semantics sai (outbound) | `packages/db/models.py::Webhook` | Đã ngừng dùng — UI và schema bỏ field; cột giữ nullable cho legacy. |

Xem changelog `docs/changelog.md` để biết PR/scripts cụ thể.
