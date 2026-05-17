# ADR 0001: BankAdapter abstraction

## Quyết định

Dùng `BankAdapter` Protocol để tách core thanh toán khỏi từng ngân hàng.

## Lý do

- MB có OSS lib tốt nhất hiện tại.
- BIDV/ACB/VCB chưa ổn định, cần stub trước để không khóa kiến trúc.
- Có thể fallback sang Node bridge hoặc Casso/SePay mà không đổi matcher/webhook.
