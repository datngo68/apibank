# Pending-Order Bank Polling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho phép từng tài khoản ngân hàng chỉ gọi API lịch sử giao dịch khi có đơn pending chưa hết hạn, mặc định bật cho MB.

**Architecture:** Lưu cờ `poll_only_when_pending` trên `BankAccount`; worker dùng một truy vấn `EXISTS` trước khi gọi adapter. API PATCH hiện tại cập nhật cả trạng thái polling và cờ mới, còn UI hiển thị switch trên từng thẻ tài khoản. Mọi luồng tạo đơn đánh thức worker sau commit bằng `poll_kick`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, Alembic, pytest, React, TypeScript, TanStack Query, Vitest.

## Global Constraints

- Tùy chọn áp dụng theo từng `BankAccount`.
- Mọi `Order` pending chưa hết hạn gắn với tài khoản đều kích hoạt polling.
- MB mới và MB hiện có mặc định bật; ngân hàng khác mặc định tắt.
- Khi không có đơn, worker không gọi adapter và không login MB.
- Không thay đổi matcher, thời hạn đơn hoặc tích hợp nhà cung cấp khác.
- Tuân thủ TDD: test phải thất bại đúng nguyên nhân trước khi sửa production code.

---

### Task 1: Persist polling policy and expose it through the account API

**Files:**
- Create: `alembic/versions/0019_bank_poll_pending.py`
- Modify: `packages/db/models.py`
- Modify: `packages/schemas/me.py`
- Modify: `apps/api/routes/me.py`
- Test: `tests/integration/test_me_routes.py`

**Interfaces:**
- Produces: `BankAccount.poll_only_when_pending: bool`
- Produces: `BankAccountUpdate.polling_enabled: bool | None` and `poll_only_when_pending: bool | None`
- Produces: `BankAccountRead.poll_only_when_pending: bool`

- [ ] **Step 1: Write failing API tests**

Add tests that create an MB account and assert `poll_only_when_pending is True`, then PATCH only that field and assert `polling_enabled` is unchanged. Add an ownership test using another user’s account and expect `404`.

```python
assert created.json()["poll_only_when_pending"] is True
response = await client.patch(
    f"/api/v1/me/bank-accounts/{bank_id}",
    json={"poll_only_when_pending": False},
)
assert response.status_code == 200
assert response.json()["poll_only_when_pending"] is False
assert response.json()["polling_enabled"] is True
```

- [ ] **Step 2: Run tests and verify RED**

Run: `APIBANK_ENVIRONMENT=test pytest tests/integration/test_me_routes.py -q --no-cov`

Expected: response/schema lacks `poll_only_when_pending` or PATCH validation rejects the payload.

- [ ] **Step 3: Add model, migration, schemas, and PATCH behavior**

Add the model field:

```python
poll_only_when_pending: Mapped[bool] = mapped_column(Boolean, default=False)
```

Create migration `0019_bank_poll_pending` after `0018_bank_session`:

```python
op.add_column(
    "bank_accounts",
    sa.Column("poll_only_when_pending", sa.Boolean(), nullable=False, server_default=sa.false()),
)
op.execute(
    sa.text("UPDATE bank_accounts SET poll_only_when_pending = true WHERE bank_code = 'MB'")
)
```

Downgrade drops the column. Extend schemas:

```python
class BankAccountUpdate(BaseModel):
    polling_enabled: bool | None = None
    poll_only_when_pending: bool | None = None

class BankAccountRead(BaseModel):
    poll_only_when_pending: bool
```

In account creation set `poll_only_when_pending=bank_code == "MB"`. In PATCH, reject an empty payload with HTTP 422, independently update supplied fields, audit the before/after values, commit, publish the existing account-rescan event, and call `poll_kick.kick(account.id)` so a policy change is observed immediately.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `APIBANK_ENVIRONMENT=test pytest tests/integration/test_me_routes.py -q --no-cov`

Expected: all tests in the file pass.

- [ ] **Step 5: Verify migration chain and commit**

Run: `alembic heads && alembic history -r "0018_bank_session:head"`

Expected: exactly one head, `0019_bank_poll_pending`.

```bash
git add alembic/versions/0019_bank_poll_pending.py packages/db/models.py packages/schemas/me.py apps/api/routes/me.py tests/integration/test_me_routes.py
git commit -m "feat: configure pending-order bank polling"
```

---

### Task 2: Gate bank calls on active pending orders

**Files:**
- Modify: `apps/worker/main.py`
- Create: `tests/unit/test_worker_poll_policy.py`

**Interfaces:**
- Produces: `async def _has_active_pending_order(bank_account_id: str, now: datetime) -> bool`
- Produces: `async def _should_poll(account: BankAccount, now: datetime) -> bool`
- Consumes: `BankAccount.poll_only_when_pending`

- [ ] **Step 1: Write failing policy tests**

Use an isolated SQLite test database/sessionmaker or monkeypatch the worker sessionmaker. Cover these cases separately:

```python
assert await _should_poll(account_with_policy_disabled, now) is True
assert await _should_poll(account_with_no_orders, now) is False
assert await _should_poll(account_with_active_pending_order, now) is True
assert await _should_poll(account_with_expired_pending_order, now) is False
assert await _should_poll(account_with_other_account_order, now) is False
```

Also test that the no-order branch never invokes `adapter.list_transactions` by extracting one poll-cycle helper if needed; keep the helper limited to deciding/skipping the existing poll body.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest tests/unit/test_worker_poll_policy.py -q --no-cov`

Expected: imports fail because `_should_poll` and `_has_active_pending_order` do not exist.

- [ ] **Step 3: Implement the database existence check**

Use SQLAlchemy `exists`:

```python
stmt = select(
    exists().where(
        Order.bank_account_id == bank_account_id,
        Order.status == "pending",
        Order.expired_at > now,
    )
)
```

`_should_poll` returns `True` immediately when policy is disabled; otherwise delegates to `_has_active_pending_order`.

At the beginning of each worker poll cycle, before `adapter.list_transactions`, call `_should_poll`. If false:

- Set `polling_status="waiting_order"`, `last_error=None` only when entering/remaining wait.
- Do not call `adapter.login`, `adapter.list_transactions`, or update `last_poll_at`.
- Reuse the existing wait-on-kick-or-timeout block.

Move initial eager login behind the policy: accounts configured for pending-only with no active order must start without calling MB. When an active order appears, restore the saved session and let the first bank operation authenticate only if necessary.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `pytest tests/unit/test_worker_poll_policy.py tests/unit/test_bank_adapter_contract.py -q --no-cov`

Expected: all tests pass and the skip-path adapter call count remains zero.

- [ ] **Step 5: Run worker static checks and commit**

Run:

```bash
ruff check apps/worker/main.py tests/unit/test_worker_poll_policy.py
mypy apps/worker/main.py
```

Expected: no issues.

```bash
git add apps/worker/main.py tests/unit/test_worker_poll_policy.py
git commit -m "feat: poll banks only for pending orders"
```

---

### Task 3: Wake the worker after every order creation

**Files:**
- Modify: `packages/db/repositories.py`
- Test: `tests/integration/test_orders_api.py`

**Interfaces:**
- Consumes: `poll_kick.kick(bank_account_id: str) -> bool`
- Guarantees: wake happens only after successful order commit.

- [ ] **Step 1: Write a failing order wake-up test**

Monkeypatch `packages.banks.poll_kick.kick`, create an order through the API, and assert exactly one call with the created order’s `bank_account_id` after a successful response.

```python
assert kicked == [bank_account.id]
```

Add a validation-failure case and assert `kicked == []`.

- [ ] **Step 2: Run test and verify RED**

Run: `APIBANK_ENVIRONMENT=test pytest tests/integration/test_orders_api.py -q --no-cov`

Expected: successful creation does not call `poll_kick.kick`.

- [ ] **Step 3: Add post-commit wake-up**

After `commit()` and `refresh(order)` in `OrderRepository.create_order`, call:

```python
from packages.banks import poll_kick
await poll_kick.kick(order.bank_account_id)
```

Do not kick before commit. Preserve the existing top-up/check kick behavior.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `APIBANK_ENVIRONMENT=test pytest tests/integration/test_orders_api.py -q --no-cov`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add packages/db/repositories.py tests/integration/test_orders_api.py
git commit -m "feat: wake bank worker for new orders"
```

---

### Task 4: Add the per-account UI switch

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/pages/dashboard/bank-accounts.tsx`
- Create: `apps/web/src/__tests__/bank-accounts.test.tsx`

**Interfaces:**
- Consumes/produces: `BankAccount.poll_only_when_pending: boolean`
- Produces: `endpoints.updateBank(id, body)` with partial body `{ polling_enabled?: boolean; poll_only_when_pending?: boolean }`

- [ ] **Step 1: Write failing component tests**

Mock `endpoints.bankAccounts` with one MB account and render `BankAccountsPage`. Assert the labeled switch reflects the API value. Toggle it and assert PATCH payload:

```typescript
expect(updateBank).toHaveBeenCalledWith("ba_1", {
  poll_only_when_pending: false,
});
```

Test mutation failure: toast error is shown and query invalidation/refetch restores server state.

- [ ] **Step 2: Run tests and verify RED**

Run: `cd apps/web && npm test -- --run src/__tests__/bank-accounts.test.tsx`

Expected: missing field/endpoint/switch assertions fail.

- [ ] **Step 3: Extend API types and endpoint**

Add:

```typescript
poll_only_when_pending: boolean;
```

Replace the single-purpose endpoint with:

```typescript
updateBank: (
  id: string,
  body: { polling_enabled?: boolean; poll_only_when_pending?: boolean },
) => api.patch<BankAccount>(`/api/v1/me/bank-accounts/${id}`, body),
```

Update the existing pause mutation to use `updateBank`.

- [ ] **Step 4: Render and wire the switch**

Import the existing `Switch`. Add a labeled row to each `BankCard`:

```tsx
<Switch
  checked={bank.poll_only_when_pending}
  disabled={updatePolicy.isPending}
  onCheckedChange={(checked) =>
    updatePolicy.mutate({ poll_only_when_pending: checked })
  }
  aria-label="Chỉ kiểm tra giao dịch khi có đơn chờ thanh toán"
/>
```

Include the approved explanatory copy and invalidate `['banks']` on both success and error so UI returns to authoritative server state.

- [ ] **Step 5: Run frontend verification and commit**

Run:

```bash
cd apps/web
npm test -- --run src/__tests__/bank-accounts.test.tsx
npm run build
```

Expected: tests and TypeScript/Vite build pass.

```bash
git add apps/web/src/lib/api.ts apps/web/src/pages/dashboard/bank-accounts.tsx apps/web/src/__tests__/bank-accounts.test.tsx
git commit -m "feat: add pending-order polling switch"
```

---

### Task 5: Full verification, push, and deploy

**Files:**
- Verify all files changed in Tasks 1–4.

- [ ] **Step 1: Run backend verification**

```bash
pytest tests/unit/test_worker_poll_policy.py tests/unit/test_bank_adapter_contract.py tests/integration/test_me_routes.py tests/integration/test_orders_api.py -q --no-cov
ruff check apps/worker/main.py apps/api/routes/me.py packages/db/models.py packages/db/repositories.py packages/schemas/me.py tests/unit/test_worker_poll_policy.py
mypy apps/worker/main.py apps/api/routes/me.py packages/db/repositories.py packages/schemas/me.py
alembic heads
git diff --check
```

Expected: all commands exit 0 and Alembic reports only `0019_bank_poll_pending (head)`.

- [ ] **Step 2: Run frontend verification**

```bash
cd apps/web
npm test -- --run
npm run build
```

Expected: all tests pass and production build succeeds.

- [ ] **Step 3: Review and push**

```bash
git status --short
git log -5 --oneline
git push origin main
```

Expected: clean worktree and `main` pushed successfully.

- [ ] **Step 4: Deploy to VPS**

Sync the committed tree without overwriting `/opt/apibank/.env`, then run:

```bash
cd /opt/apibank/infra/docker
docker compose --env-file /opt/apibank/.env \
  -f docker-compose.yml -f docker-compose.build.yml \
  up -d --build migrate api worker scheduler
```

Expected: migration exits 0 and API becomes healthy.

- [ ] **Step 5: Verify production behavior**

Verify:

```bash
docker exec docker-api-1 python -m alembic current
docker exec docker-api-1 python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/healthz').read())"
docker logs --since 10m docker-worker-1
```

Query database through application session and confirm the active MB account has `poll_only_when_pending = true`. When no active pending order exists, wait longer than one `poll_interval` and confirm `last_poll_at` does not advance and worker reports `waiting_order`. Create a controlled pending order, confirm worker wakes and `last_poll_at` advances once polling starts, then cancel/expire the order and confirm polling stops again.
