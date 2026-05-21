# Migration zero-downtime strategy

Mục tiêu: rolling deploy không drop request, không cần stop/start dịch vụ
giữa hai version DB schema.

## Nguyên tắc

- Schema thay đổi phải tương thích với CẢ phiên bản code đang chạy lẫn phiên
  bản sắp lên. Tức migration A phải hoạt động với code N-1 và N; sau khi
  cluster đã chạy xong code N, migration B (cleanup) mới được apply.
- Tách mỗi thay đổi rủi ro thành 2-3 release nhỏ: expand → migrate → contract.

## Các pattern cụ thể

### Add column

1. Migration: `op.add_column(..., nullable=True)` hoặc `nullable=False, server_default=...`.
2. Code mới đọc/ghi cột mới. Code cũ vẫn chạy được vì cột là optional/có default.
3. (Tuỳ) migration sau drop default nếu không muốn server_default vĩnh viễn.

### Drop column

1. Release N: code dừng đọc/ghi cột (nhưng cột vẫn tồn tại).
2. Deploy xong → migration drop column ở release N+1.
3. KHÔNG drop trong cùng release với code thay đổi.

### Rename column (hoặc đổi type)

1. Add cột mới `*_new`, code dual-write (đọc cột cũ, ghi cả hai).
2. Backfill cột mới từ cột cũ qua script async.
3. Code đổi sang đọc cột mới, ghi cả hai.
4. Code chỉ đọc/ghi cột mới (dừng dual-write).
5. Drop cột cũ.

### Add NOT NULL

1. Add column nullable + default.
2. Backfill.
3. Migration `ALTER COLUMN ... SET NOT NULL` riêng (trên Postgres ≥ 12 nó scan bảng + acquire AccessExclusive).

### Add index lớn

- Postgres: `CREATE INDEX CONCURRENTLY` (không khoá writes). Alembic không
  hỗ trợ default; cần `op.execute("CREATE INDEX CONCURRENTLY ...")` ngoài transaction
  với `is_transactional_ddl = False` hoặc batch `--sql`.

## Tránh

- `DROP TABLE`/`DROP COLUMN` cùng release với code change.
- `ALTER COLUMN TYPE` không qua expand-contract (block toàn bảng).
- `RENAME COLUMN` mà không expand-contract.
- Schema migration kéo dài > 30s mà không CONCURRENTLY (timeout client).

## Checklist trước merge migration

- [ ] Cột mới có nullable hoặc server_default?
- [ ] Backfill script tách riêng, idempotent?
- [ ] Code N và N+1 cùng đọc được schema mới + cũ?
- [ ] Có rollback path (migration `downgrade()` chạy được)?
- [ ] Index lớn dùng CONCURRENTLY?
- [ ] Mọi statement < 30s (statement_timeout) hoặc đã document cần stop traffic?

## Ghi chú riêng repo APIBank

- `apps/scheduler/main.py` và `apps/worker/main.py` cùng dùng `head` schema.
  Khi rolling deploy, nên đẩy migration TRƯỚC khi rollout code mới (nếu
  expand) và SAU khi rollout xong (nếu contract).
- Encrypt-at-rest PII (`APIBANK_ENCRYPT_PII=true`) đã thiết kế để đọc cả
  giá trị cũ (plain) lẫn mới (`enc:v1:...`) — bật/tắt runtime an toàn.
