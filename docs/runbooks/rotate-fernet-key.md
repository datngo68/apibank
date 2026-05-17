# Runbook: rotate Fernet key

1. Thêm key mới vào đầu `APIBANK_FERNET_KEYS`.
2. Deploy app.
3. Chạy job re-encrypt credential/webhook secret.
4. Giữ key cũ ít nhất 7 ngày.
5. Xóa key cũ sau khi verify decrypt toàn bộ secret.
