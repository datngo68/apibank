# Launch checklist — APIBank 0.1.0

Mọi mục dưới đây phải được kiểm và tick xanh trước khi public.
Mỗi check ghi rõ owner, evidence (script/log/screenshot) và ngày drill cuối.

## 1. Backup & restore drill ✅

- [ ] `pg_dump` hằng đêm vào S3.
- [ ] Drill quý: `dropdb` → `restore` → `apimb migrate` → `apimb doctor` xanh.
- [ ] RTO đo được ≤ 30 phút, RPO ≤ 1 giờ.

Tham chiếu: `docs/runbooks/backup-restore.md`.

## 2. Migration rollback drill ✅

- [ ] `apimb migrate downgrade --target 0001_initial` không lỗi.
- [ ] Sau rollback, app cũ (legacy single-tenant) vẫn boot được.

Lệnh:

```bash
apimb migrate --target 0002_poll_cursors --downgrade
apimb migrate --target head
```

## 3. Fernet key rotation drill ✅

- [ ] Sinh key mới, thêm vào trước key cũ trong `APIBANK_FERNET_KEYS`.
- [ ] Restart, đăng nhập bank vẫn ok.
- [ ] Re-encrypt batch (script polish round) chạy không lỗi.
- [ ] Loại key cũ sau 30 ngày, restart, doctor xanh.

## 4. Rate limit & brute-force gate ✅

- [ ] `pytest tests/integration/test_auth_routes.py::test_lockout_after_5_failed_logins` pass.
- [ ] k6/curl smoke 6 lần sai → bị 423.

## 5. GDPR data export & delete

- [ ] CLI `apimb user export --email`, `apimb user delete --email`. (Hiện tại: scaffold trong `docs/runbooks/backup-restore.md`).
- [ ] Endpoint `POST /api/v1/me/data-export` (sẽ thêm).
- [ ] Endpoint `DELETE /api/v1/me/account` (sẽ thêm) — anonymize, ledger giữ 7 năm.

## 6. ToS / Privacy

- [ ] `/legal/terms` & `/legal/privacy` đã review pháp lý.
- [ ] Email no-reply@ và domain SPF/DKIM/DMARC pass.

## 7. Monitoring alerts dry-run ✅

- [ ] Grafana dashboard nhận metric trong < 30s sau khi container up.
- [ ] Alert rule `WebhookFailureSpike` trigger khi mock webhook fail 30%.
- [ ] Telegram bot nhận message thử nghiệm `apimb` notification.

## 8. Security scan ✅

- [ ] `pip-audit` xanh hoặc xử lý hết high CVE.
- [ ] `npm audit --omit=dev` xanh.
- [ ] `gitleaks` không có match.
- [ ] ZAP baseline scan (staging) không có alert level 3+.

## 9. Email deliverability

- [ ] SPF: `v=spf1 include:_spf.google.com ~all`.
- [ ] DKIM ký bằng selector apibank.
- [ ] DMARC `p=quarantine; rua=mailto:dmarc@apibank.local`.
- [ ] Test gửi email register thực tế qua Mailtrap → Inbox Gmail/Yahoo OK.

## 10. Smoke prod < 90s

```text
register → verify-email → login → add bank → topup 10k → ingest paid → buy trial → tạo order → webhook delivered.
```

Mỗi bước log timestamp, tổng < 90s end-to-end.

## 11. Pre-flight CI xanh ✅

- [ ] `python -m ruff check .`
- [ ] `python -m mypy apps packages`
- [ ] `python -m pytest -q` (200+ tests)
- [ ] `cd apps/web && npm run lint && npm run test && npm run build`
- [ ] CI workflows `ci`, `nightly`, `release` đều có run gần nhất xanh.

## 12. Disaster recovery doc

- [ ] `docs/runbooks/incident-poller-stuck.md`.
- [ ] `docs/runbooks/incident-webhook-storm.md`.
- [ ] `docs/runbooks/rotate-fernet.md`.
- [ ] On-call rotation set up (Slack/PagerDuty).
