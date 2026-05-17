# ADR 0002: Outbox webhook pattern

## Quyết định

Mọi webhook gửi đi đều đi qua bảng `webhook_attempts` với trạng thái `pending`/`delivered`/`failed`/`dead`.

## Lý do

- Tách ghi DB và bắn HTTP, tránh mất event khi crash giữa.
- Hỗ trợ retry exponential backoff.
- Cho phép replay từ admin endpoint.
