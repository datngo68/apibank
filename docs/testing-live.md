# Hướng dẫn test thật

## Yêu cầu trước khi chạy

- Python 3.12, đã `python -m pip install -e ".[dev]"`.
- 1 tài khoản MB (đăng nhập được web banking).
- Số tài khoản MB nhận tiền.
- Webhook destination để verify: dùng `https://webhook.site` lấy 1 URL ngẫu nhiên (mở browser → copy URL).

## 1. Bootstrap môi trường local

```powershell
python scripts/bootstrap_local.py `
  --mb-username 0123456789 `
  --mb-password "MAT_KHAU_MB" `
  --mb-account-no 0011223344 `
  --mb-holder "NGUYEN VAN A" `
  --webhook-url "https://webhook.site/<uuid-cua-ban>"
```

Output sẽ in JSON gồm:
- `bank_account_id`: ID nội bộ của tài khoản MB.
- `api_key`: API key để gọi REST. **Lưu ngay**, không xem lại được.
- `webhook_secret`: secret HMAC ký webhook.

Script tự sinh `APIBANK_FERNET_KEYS` và `APIBANK_API_KEY_SALT` vào `.env` nếu chưa có.

## 2. Chạy API server

```powershell
python -m uvicorn apps.api.main:app --reload
```

API ở `http://127.0.0.1:8000`. Mở `http://127.0.0.1:8000/docs` để xem Swagger.

## 3. Test tạo đơn

```powershell
$ApiKey = "<paste api_key tu buoc 1>"
$BankAccountId = "<paste bank_account_id>"

curl.exe -X POST "http://127.0.0.1:8000/v1/orders" `
  -H "Authorization: Bearer $ApiKey" `
  -H "Idempotency-Key: test-001" `
  -H "Content-Type: application/json" `
  -d "{\"amount_vnd\":10000,\"bank_account_id\":\"$BankAccountId\",\"ttl_seconds\":900}"
```

Phản hồi 201 với `code` (ví dụ `DH4FK9A2`). Nội dung này là cái user phải gõ khi chuyển khoản.

## 4. Sinh QR cho đơn

Endpoint sẵn có:

```
GET /qr/{order_id}.png
```

Trả VietQR PNG generate local (không phụ thuộc dịch vụ ngoài). Lưu ý dùng
**order_id** (`ord_01HXXXX...`), không phải `code`. Hoặc gọi trực tiếp Python
nếu chỉ cần payload text:

```powershell
python -c "from packages.qr.vietqr import generate_vietqr_payload; print(generate_vietqr_payload(bank_bin='970422', account_no='0011223344', amount_vnd=10000, content='DH4FK9A2'))"
```

Bank BIN MB là `970422`. Quét chuỗi VietQR bằng app ngân hàng.

## 5. Chạy worker để poll MB thật

Mở terminal khác:

```powershell
python -m apps.worker.main
```

Worker sẽ:
- Login MB bằng `mbbank-lib` (5-10s lần đầu để tải WASM/ONNX).
- Poll mỗi `APIBANK_POLL_INTERVAL` giây — mặc định **60s** ở `.env.example` (dev,
  giảm xung đột với app mobile MB), **20s** ở `infra/docker/.env.production.example`.
- Ghi log JSON.

**Cảnh báo**: nếu login fail liên tiếp, dừng worker ngay. Có thể MB đã đổi WASM.

## 6. Chuyển khoản test

Từ tài khoản khác, chuyển vào số TK MB của bạn:
- **Số tiền**: đúng `amount_vnd` của đơn (ví dụ 10000 VND).
- **Nội dung**: chứa `code` đơn (ví dụ `DH4FK9A2` hoặc `Thanh toan DH4FK9A2`).

Sau 20-60s, worker sẽ:
1. Thấy giao dịch mới.
2. Match đơn pending.
3. Đẩy `webhook_attempt` vào outbox.

## 7. Chạy scheduler để dispatch webhook

Terminal thứ 3:

```powershell
python -m apps.scheduler.main
```

Scheduler bắn webhook mỗi **30s** (cron tick) **+ near-realtime qua Redis pub/sub
`webhook:kick`** (debounce 200ms) — nếu Redis sẵn, attempt vừa được tạo sẽ
được gửi gần như tức thì. Mở URL `webhook.site` trên trình duyệt, sẽ thấy POST đến với:
- Header `X-Signature: t=<unix>,v1=<hmac-sha256>`.
- Body JSON `{"id": "evt_...", "type": "payment.succeeded", "data": {...}}`.

## 8. Verify trạng thái đơn

```powershell
curl.exe -X GET "http://127.0.0.1:8000/v1/orders/<order_id>" -H "Authorization: Bearer $ApiKey"
```

Phải có `"status": "paid"` và `"paid_tx_id"` không null.

## Troubleshoot nhanh

| Triệu chứng | Xử lý |
|---|---|
| Worker login fail | Pin lại version `mbbank-lib`, hoặc chuyển sang Node bridge (đặt `APIBANK_MB_BRIDGE_URL`). |
| Tx không match | Kiểm tra DB: `SELECT state, content FROM transactions ORDER BY inserted_at DESC LIMIT 5;` Code có nằm trong content không? |
| Webhook không bắn | Bảng `webhook_attempts` có row pending? Scheduler đang chạy không? |
| Account bị MB khóa | Đăng nhập web banking thử. Nếu khóa, mở khóa trong app/chi nhánh, **dừng auto**. |

## Reset

```powershell
Remove-Item apibank.db
python scripts/bootstrap_local.py ...   # chạy lại
```
