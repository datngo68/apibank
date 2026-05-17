# Hướng dẫn tích hợp APIBank — Thanh toán tự động qua API & Webhook

Tài liệu này dành cho **merchant / developer** muốn tích hợp APIBank vào website,
app, bot Telegram, hệ thống bán hàng, SaaS… để **nhận tiền chuyển khoản tự động**
và được hệ thống bắn webhook về ngay khi tiền vào.

> Base URL mặc định: `http://localhost:8000` (self-host). Khi deploy sau Caddy /
> Cloudflare, thay bằng domain thật, ví dụ `https://pay.example.com`.

---

## 1. Mô hình tổng quan

```
┌────────┐  1. POST /v1/orders   ┌──────────┐  2. Tiền vào tài khoản MB/VTB  ┌──────────┐
│ Hệ      │ ─────────────────►  │ APIBank  │ ◄──────────────────────────── │ Ngân hàng │
│ thống   │  ◄── 201 {code, qr} │ (FastAPI │  3. Worker poll lịch sử tx     │ (MB/VTB) │
│ bạn     │                     │ + worker)│  4. Matcher khớp content       └──────────┘
│         │  ◄── webhook        │          │
└────────┘  payment.succeeded   └──────────┘
```

Flow tóm gọn:

1. Bạn gọi `POST /v1/orders` với số tiền + mô tả → APIBank trả về `code` (mã CK
   duy nhất) và link `/pay/{code}` hiển thị QR + thông tin tài khoản.
2. Khách hàng quét QR / chuyển khoản với nội dung `code` đó.
3. Worker APIBank poll tài khoản ngân hàng định kỳ (~10s), khớp tx theo amount +
   content → đánh dấu order `paid`.
4. Hệ thống bắn `webhook payment.succeeded` về URL bạn đăng ký, có **chữ ký
   HMAC-SHA256** để bạn verify chống giả mạo.
5. Bạn trả `2xx` → APIBank coi là delivered. Trả `4xx/5xx` → retry theo lịch
   `0s, 30s, 2m, 10m, 1h, 6h, 24h` (tối đa 7 lần) rồi mới chuyển `dead`.

---

## 2. Chuẩn bị

### 2.1. Đăng ký tài khoản và lấy API key

1. Mở dashboard `http://localhost:8000/app`, đăng ký + xác thực email.
2. Vào **Settings → API Keys → New key**, đặt tên (ví dụ `prod-shop`),
   chọn scope cần thiết:
   - `orders:write` — tạo / huỷ order.
   - `orders:read` — đọc order.
   - `transactions:read` — đọc lịch sử giao dịch.
   - `admin:*` — chỉ cấp khi cần quản lý webhook hệ thống cấp cao.
3. **Copy ngay** key dạng `sk_live_xxx...` — server không lưu plaintext, chỉ
   hash. Mất là phải tạo lại.

### 2.2. Cấu hình bank account nhận tiền

Trên dashboard hoặc CLI:

```powershell
apimb bank-account create --bank-code MB --account-no 1234567890 \
    --holder "CONG TY ABC" --username MB_USER --password MB_PASS
```

Lấy `bank_account_id` (ví dụ `ba_01HXXXX...`) — bạn sẽ truyền vào mỗi order.

### 2.3. Đăng ký webhook endpoint

Trên dashboard **Settings → Webhooks → New endpoint**:

| Field        | Giá trị                                             |
|--------------|-----------------------------------------------------|
| URL          | `https://yourshop.com/payments/apibank/webhook`     |
| Secret       | Chuỗi ngẫu nhiên ≥ 16 ký tự (lưu cùng phía bạn)     |
| Events       | `payment.succeeded` (mặc định)                      |
| Active       | true                                                |

> APIBank chặn URL trỏ vào `127.0.0.0/8`, `10.0.0.0/8`, `172.16/12`,
> `192.168/16`, `169.254/16` (anti-SSRF) ở môi trường production.

Hoặc qua API (nếu key có scope `admin:*`):

```http
POST /v1/webhooks
Authorization: Bearer sk_live_xxx
Content-Type: application/json

{
  "url": "https://yourshop.com/payments/apibank/webhook",
  "secret": "a-long-random-string-32-chars",
  "active": true,
  "headers": {"X-Source": "apibank"}
}
```

---

## 3. Tạo order — `POST /v1/orders`

### Request

```http
POST /v1/orders
Authorization: Bearer sk_live_xxx
Content-Type: application/json
Idempotency-Key: order-2026-05-17-0001

{
  "amount_vnd": 50000,
  "bank_account_id": "ba_01HXXXX...",
  "description": "Thanh toán đơn #1234",
  "customer_ref": "user_42",
  "metadata": {"order_internal_id": "1234", "channel": "web"},
  "ttl_seconds": 900
}
```

| Field             | Bắt buộc | Mô tả                                                     |
|-------------------|----------|-----------------------------------------------------------|
| `amount_vnd`      | yes      | Số tiền VND, > 0. Match exact amount.                     |
| `bank_account_id` | yes      | Tài khoản ngân hàng nhận tiền (phải thuộc user của key).  |
| `description`     | no       | Hiển thị ở landing `/pay/{code}`.                         |
| `customer_ref`    | no       | Tham chiếu của bạn (user_id, email, phone…).              |
| `metadata`        | no       | Dict tự do, sẽ trả lại trong webhook + `GET /v1/orders`.  |
| `ttl_seconds`     | no       | TTL order, default 900s (15 phút), max 86400 (24h).       |

> `Idempotency-Key` là **bắt buộc** — header này dài tối đa 100 ký tự, unique
> per-API-key. Gửi lại cùng key + cùng body → trả lại order cũ (idempotent).
> Cùng key + body khác → 409 Conflict.

### Response — 201 Created

```json
{
  "id": "ord_01HXXXX...",
  "code": "APIB7K3M2A",
  "amount_vnd": 50000,
  "status": "pending",
  "bank_account_id": "ba_01HXXXX...",
  "expired_at": "2026-05-17T01:15:00+00:00",
  "paid_tx_id": null,
  "paid_at": null,
  "customer_ref": "user_42",
  "metadata_json": {"order_internal_id": "1234", "channel": "web"},
  "created_at": "2026-05-17T01:00:00+00:00",
  "updated_at": "2026-05-17T01:00:00+00:00"
}
```

Hiển thị thanh toán cho khách:

- **Landing có sẵn QR**: redirect khách đến `https://pay.example.com/pay/APIB7K3M2A`.
- **QR raw VietQR**: nhúng `<img src="https://pay.example.com/qr/APIB7K3M2A.png">`.
- **Polling status (fallback)**: `GET /pay/APIB7K3M2A/status` →
  `{ "status": "pending" | "paid" | "expired" | "cancelled" }`.
- **Realtime SSE**: `GET /pay/APIB7K3M2A/events` (server-sent events).

### Hủy order

```http
POST /v1/orders/{order_id}:cancel
Authorization: Bearer sk_live_xxx
```

Trả 200 + order với `status: cancelled`. Đã `paid` thì không hủy được.

---

## 4. Nhận webhook — `payment.succeeded`

Khi worker khớp tx với order, APIBank `POST` tới URL bạn đăng ký:

### Headers

```
Content-Type: application/json
X-Signature: t=1747443600,v1=4f8b7c3a9e2d1b6a0c5f8e7d4a3b2c1d0e9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b
```

### Body

```json
{
  "id": "evt_01HXXXX...",
  "type": "payment.succeeded",
  "created_at": "2026-05-17T01:05:23+00:00",
  "data": {
    "order_id": "ord_01HXXXX...",
    "transaction_id": "tx_01HXXXX...",
    "code": "APIB7K3M2A",
    "amount_vnd": 50000,
    "bank_ref_no": "FT26137123456",
    "posted_at": "2026-05-17T01:05:20+00:00",
    "customer_ref": "user_42",
    "metadata": {"order_internal_id": "1234", "channel": "web"}
  }
}
```

### Verify chữ ký — bắt buộc

`X-Signature` có dạng `t=<unix_ts>,v1=<hex>`. Công thức:

```
v1 = HMAC_SHA256(secret, f"{t}." + raw_body_bytes).hex()
```

**Phải dùng raw body** (chưa parse JSON, chưa minify lại), nếu không HMAC sai.

#### Node.js (Express)

```js
import crypto from "node:crypto";
import express from "express";

const app = express();

// Quan trọng: raw body cho route webhook
app.post(
  "/payments/apibank/webhook",
  express.raw({ type: "application/json" }),
  (req, res) => {
    const sigHeader = req.header("X-Signature") || "";
    const parts = Object.fromEntries(
      sigHeader.split(",").map((kv) => kv.split("=", 2))
    );
    const t = Number(parts.t);
    const v1 = parts.v1;
    if (!t || !v1) return res.status(400).send("bad signature");
    if (Math.abs(Date.now() / 1000 - t) > 300) {
      return res.status(400).send("expired"); // chống replay 5 phút
    }
    const expected = crypto
      .createHmac("sha256", process.env.APIBANK_WEBHOOK_SECRET)
      .update(`${t}.`)
      .update(req.body)
      .digest("hex");
    if (
      !crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(v1))
    ) {
      return res.status(401).send("invalid signature");
    }
    const evt = JSON.parse(req.body.toString("utf8"));
    // TODO: idempotent xử lý theo evt.id (tránh xử lý 2 lần khi retry)
    handlePaymentSucceeded(evt.data).catch(console.error);
    res.status(200).send("ok");
  }
);
```

#### Python (FastAPI)

```python
import hmac, hashlib, os, time
from fastapi import APIRouter, Request, HTTPException

router = APIRouter()
SECRET = os.environ["APIBANK_WEBHOOK_SECRET"].encode()

@router.post("/payments/apibank/webhook")
async def webhook(request: Request):
    body = await request.body()  # raw bytes!
    header = request.headers.get("x-signature", "")
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    try:
        t = int(parts["t"]); v1 = parts["v1"]
    except (KeyError, ValueError):
        raise HTTPException(400, "bad signature")
    if abs(time.time() - t) > 300:
        raise HTTPException(400, "expired")
    expected = hmac.new(SECRET, f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, v1):
        raise HTTPException(401, "invalid signature")
    evt = await request.json()
    # idempotent theo evt["id"]
    await handle_payment(evt["data"])
    return {"ok": True}
```

#### PHP

```php
<?php
$secret = getenv('APIBANK_WEBHOOK_SECRET');
$raw    = file_get_contents('php://input');
$header = $_SERVER['HTTP_X_SIGNATURE'] ?? '';
$parts  = [];
foreach (explode(',', $header) as $kv) {
    [$k, $v] = array_pad(explode('=', $kv, 2), 2, null);
    $parts[$k] = $v;
}
if (empty($parts['t']) || empty($parts['v1'])) { http_response_code(400); exit; }
if (abs(time() - (int)$parts['t']) > 300)     { http_response_code(400); exit; }
$expected = hash_hmac('sha256', $parts['t'] . '.' . $raw, $secret);
if (!hash_equals($expected, $parts['v1']))    { http_response_code(401); exit; }

$evt = json_decode($raw, true);
// idempotent theo $evt['id']
handlePayment($evt['data']);
http_response_code(200);
echo 'ok';
```

### Quy tắc xử lý phía consumer

- **Idempotent**: lưu `evt.id` đã xử lý vào DB (unique). Webhook có thể về 2
  lần khi bạn timeout — đừng cộng tiền hai lần.
- **Trả `2xx` nhanh** (< 5s lý tưởng). Việc nặng push qua queue (BullMQ, Celery,
  Sidekiq…).
- **Không tin `data.amount_vnd` mù quáng**: cross-check với order nội bộ của
  bạn theo `metadata.order_internal_id` hoặc `customer_ref`.
- **Tolerance 5 phút** cho `t` đủ chống replay nhưng đừng giảm xuống 0 — đồng
  hồ lệch là bình thường.

### Retry & dead-letter

| Lần | Delay sau attempt trước |
|-----|-------------------------|
| 1   | 0s (ngay khi tx khớp)   |
| 2   | 30s                     |
| 3   | 2 phút                  |
| 4   | 10 phút                 |
| 5   | 1 giờ                   |
| 6   | 6 giờ                   |
| 7   | 24 giờ                  |

Sau 7 lần fail → `status = dead`, dashboard hiện cảnh báo + gửi notification
`webhook_failing`. Replay thủ công: `POST /v1/webhooks/attempts/{attempt_id}:replay`
(scope `admin:*`) hoặc bấm **Replay** trên dashboard.

---

## 5. Reconciliation — đối soát ngược

Trong trường hợp webhook chết hẳn / mất, dùng API đọc trực tiếp:

```http
GET /v1/orders/{order_id}
GET /v1/transactions?from=2026-05-17T00:00:00Z&to=2026-05-17T23:59:59Z&account=ba_01HXXXX
Authorization: Bearer sk_live_xxx
```

Khuyến nghị mỗi đêm chạy 1 cron đối soát:

1. Lấy mọi order `pending` quá 1 giờ trên hệ thống bạn.
2. Gọi `GET /v1/orders/{id}` — nếu APIBank đã `paid` mà bạn vẫn `pending` →
   replay nội bộ (thường do webhook fail và bạn không catch kịp).

---

## 6. Test webhook ngay (không cần chuyển tiền thật)

- **Dashboard**: vào webhook detail → bấm **Send test ping** → APIBank gửi 1
  event `webhook.test` inline, hiện ngay status code và body trả về.
- **API**: `POST /api/v1/me/webhooks/{webhook_id}/test` (cookie session).
- **Local test**: chạy ngrok / cloudflared expose `localhost:3000`, đăng ký URL
  ngrok làm webhook URL, rồi tạo 1 order test.

Có thể chạy 1 listener nhanh để xem payload:

```bash
# Node — bun/npx
npx -y http-echo-server 3000
# Python
python -m http.server 3000  # chỉ hiện request line, dùng tcpdump/ngrok inspect
```

---

## 7. Tích hợp các kênh khác

### 7.1. Bot Telegram bán hàng

1. Tạo order khi user bấm **/buy** → gửi inline button mở `https://pay.example.com/pay/{code}`.
2. Webhook `payment.succeeded` → bot gửi message `"Đơn #1234 đã thanh toán ✅"`.

### 7.2. SaaS / membership

- Dùng `metadata.user_id` + `metadata.plan_id` khi tạo order.
- Webhook đến → upgrade subscription user trong DB của bạn.
- Subscription hết hạn → tạo order renewal mới rồi gửi mail kèm link `/pay/{code}`.

### 7.3. Shopee/Lazada/POS thủ công

- Mỗi đơn POS → tạo 1 order, in QR đính kèm hoá đơn.
- Webhook về → đổi trạng thái POS sang **đã thanh toán**.

### 7.4. WordPress / WooCommerce

Viết plugin gọi `POST /v1/orders` ở hook `woocommerce_checkout_order_processed`,
hiển thị QR ở `thankyou` page, listen webhook ở custom REST route, set order
`completed` khi nhận `payment.succeeded`.

---

## 8. Bảo mật

| Mục              | Khuyến nghị                                                              |
|------------------|--------------------------------------------------------------------------|
| API key          | Lưu ở secret manager (Vault / AWS SM / .env không commit). Rotate 90 ngày. |
| Webhook secret   | ≥ 32 ký tự ngẫu nhiên (`openssl rand -hex 32`). Mỗi endpoint 1 secret riêng. |
| HTTPS            | Webhook URL **bắt buộc HTTPS** ở production. APIBank không follow redirect. |
| Verify timestamp | Tolerance ≤ 300s, từ chối `t` cũ → chống replay.                          |
| Compare HMAC     | Luôn dùng `timingSafeEqual` / `hmac.compare_digest` chứ không `==`.       |
| IP allowlist     | Nếu có WAF, allow IP server APIBank. Hoặc đặt webhook sau Cloudflare Tunnel. |
| Logging          | Đừng log full body kèm header `X-Signature` ra log public — payload có metadata.|

---

## 9. Mã lỗi & xử lý

| HTTP | Khi nào                              | Cách xử lý                                       |
|------|--------------------------------------|--------------------------------------------------|
| 401  | Bearer sai/thiếu                     | Kiểm tra header `Authorization: Bearer ...`     |
| 402  | Subscription hết hạn                 | Renew gói trên dashboard                         |
| 403  | Thiếu scope                          | Thêm scope cho API key, không bypass.            |
| 404  | Order/webhook không thuộc user       | IDOR safe — đừng probe id user khác.             |
| 409  | `Idempotency-Key` đã dùng + body khác| Đổi key hoặc gửi đúng body cũ.                   |
| 422  | URL webhook không hợp lệ / SSRF      | Đổi sang URL public HTTPS hợp lệ.                |
| 429  | Vượt quota plan                      | Nâng plan hoặc đợi quota reset.                  |
| 503  | Fernet key chưa cấu hình             | Set `APIBANK_FERNET_KEYS` ở .env, restart.       |

---

## 10. Checklist go-live

- [ ] Domain HTTPS hợp lệ cho cả APIBank và webhook endpoint.
- [ ] `APIBANK_FERNET_KEYS` đã set, đã backup ở 2 nơi (mất key = mất bank cred).
- [ ] Bank account đã `apimb doctor` xanh, login MB/VTB ok.
- [ ] API key tạo riêng cho production, scope tối thiểu.
- [ ] Webhook endpoint đã verify chữ ký, đã idempotent theo `evt.id`.
- [ ] Đã thử `payment test ping` thành công 200.
- [ ] Đã chạy 1 lần real-money test (5.000–10.000 VND) end-to-end.
- [ ] Cron đối soát hàng đêm (`GET /v1/orders/{id}` cho order pending > 1h).
- [ ] Alert khi webhook attempts `dead` > 0 (Sentry / Telegram bot).
- [ ] Rotate plan: API key 90 ngày, webhook secret 180 ngày.

---

## 11. Tham khảo nhanh

- Swagger UI: `http://localhost:8000/docs` (chỉ bật khi `DEBUG=true`).
- OpenAPI JSON: `docs/openapi.json` — sinh bằng `python scripts/dump_openapi.py`.
- API reference: [`docs/api.md`](./api.md).
- Architecture: [`docs/architecture.md`](./architecture.md).
- Runbook webhook chết: [`docs/runbooks/webhook-dead-letter-flood.md`](./runbooks/webhook-dead-letter-flood.md).

Bug / câu hỏi tích hợp: mở issue ở repo hoặc liên hệ admin instance bạn đang dùng.
