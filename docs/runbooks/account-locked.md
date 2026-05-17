# Runbook: tài khoản ngân hàng bị khóa

1. Dừng poll account bị khóa.
2. Đổi `status=locked`.
3. Route đơn mới sang tài khoản thu hộ dự phòng.
4. Thông báo vận hành kiểm tra app ngân hàng.
5. Reconcile các đơn pending trước khi khóa.
