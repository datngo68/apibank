# Runbook: MB lib hỏng

1. Kiểm tra alert `apibank_poll_failure_total{bank="MB"}`.
2. Xem log `poll_failed` theo `bank_account_id`.
3. Tạm disable `polling_enabled` cho account lỗi.
4. Switch backend sang Node bridge `CookieGMVN/MBBank` nếu đã cấu hình.
5. Nếu cả 2 lỗi, bật fallback Casso/SePay adapter.
6. Reconcile lại 48h gần nhất sau khi khôi phục.
