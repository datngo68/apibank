# ADR 0003: Fernet credential encryption + rotation

## Quyết định

Credential ngân hàng và webhook secret được mã hóa Fernet (AES128-CBC + HMAC) bằng key trong env `APIBANK_FERNET_KEYS`. Hỗ trợ multi-key (`primary:...,old:...`) để rotate online.

## Lý do

- Đảm bảo plaintext không xuất hiện trong DB hoặc backup.
- Multi-key cho phép decrypt với key cũ trong giai đoạn re-encrypt.
- Lib chuẩn `cryptography` đã được audit.
