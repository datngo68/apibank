# Playwright e2e — placeholder

Phase 3.17 đã được khởi tạo nhưng chưa cài đặt Playwright vào CI vì:

1. Backend đã có **200+ integration tests** chạy qua FastAPI thật, cover toàn bộ luồng
   register → login → bank → topup → ingest → wallet → subscription.
2. SPA build đã được kiểm bằng `tests/integration/test_spa_mount.py` (6 cases).
3. Toàn bộ component dùng chung được render thử trong `/styleguide`.

Để bổ sung Playwright sau:

```powershell
cd apps/web
npm i -D @playwright/test @axe-core/playwright
npx playwright install chromium
mkdir e2e
```

Tham khảo `e2e/README.md` này để mở rộng. Các spec cần viết:

- `auth.spec.ts`: register → verify → login → logout.
- `bank.spec.ts`: thêm bank → list → rotate → delete.
- `topup.spec.ts`: tạo topup → giả lập paid → balance tăng.
- `subscription.spec.ts`: mua plan → invoice xuất hiện.
- `a11y.spec.ts`: chạy axe trên 10 page chính, gate `serious`/`critical`.

CI: thêm job `e2e` trong `.github/workflows/e2e.yml` chạy `docker compose up -d`
rồi `npx playwright test --reporter=list`.
