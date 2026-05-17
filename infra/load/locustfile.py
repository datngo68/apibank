"""Locust scenarios mô phỏng tải thực tế.

Chạy:
    locust -f infra/load/locustfile.py --host http://localhost:8000

User class:
- AnonymousUser: GET /healthz, /api/v1/plans (mô phỏng landing traffic).
- AuthenticatedUser: register → login → list bank/wallet (mô phỏng dashboard).
- ApiClient: gọi /v1/orders với Bearer key (mô phỏng integration shop).
- TopupUser: register → tạo topup → connect SSE → đo thời gian event "paid"
  (sau khi seed transaction match qua background).
- WebhookDrainUser: gọi `/api/v1/me/webhooks/...` để seed attempts rồi đo
  drain time. Mục đích phục vụ scenario drain riêng — không weight default.
"""

from __future__ import annotations

import os
import secrets
import time
import uuid

from locust import HttpUser, between, events, task


class AnonymousUser(HttpUser):
    weight = 3
    wait_time = between(1, 3)

    @task(10)
    def health(self) -> None:
        self.client.get("/healthz")

    @task(5)
    def list_plans(self) -> None:
        self.client.get("/api/v1/plans")

    @task(2)
    def landing(self) -> None:
        self.client.get("/")


class AuthenticatedUser(HttpUser):
    weight = 2
    wait_time = between(2, 5)

    def on_start(self) -> None:
        self.email = f"load-{secrets.token_hex(6)}@example.com"
        # warm CSRF cookie
        self.client.get("/healthz")
        csrf = self.client.cookies.get("apibank_csrf", "")
        self.headers = {"X-CSRF-Token": csrf}
        self.client.post(
            "/api/v1/auth/register",
            json={"email": self.email, "password": "Strong-Pass-1"},
            headers=self.headers,
        )
        self.client.post(
            "/api/v1/auth/login",
            json={"email": self.email, "password": "Strong-Pass-1"},
            headers=self.headers,
        )

    @task
    def me(self) -> None:
        self.client.get("/api/v1/auth/me")

    @task
    def wallet(self) -> None:
        self.client.get("/api/v1/me/wallet")


class ApiClient(HttpUser):
    """Cần API key trong env LOCUST_API_KEY và bank_account_id."""

    weight = 1
    wait_time = between(0.5, 1.5)

    def on_start(self) -> None:
        self.api_key = os.environ.get("LOCUST_API_KEY", "")
        self.bank_id = os.environ.get("LOCUST_BANK_ID", "")
        if not self.api_key:
            self.environment.runner.quit()

    @task
    def create_order(self) -> None:
        self.client.post(
            "/v1/orders",
            json={"amount_vnd": 50_000, "bank_account_id": self.bank_id},
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Idempotency-Key": str(uuid.uuid4()),
            },
        )


class TopupUser(HttpUser):
    """Mô phỏng user nạp ví: register → POST /me/topup → connect SSE.

    Yêu cầu hệ thống đã được setup ``apimb system-bank set`` để route
    ``/me/topup`` không trả 503.

    Đo gì: thời gian từ POST topup tới khi nhận event ``paid`` qua SSE.
    Vì test thật cần human trasnfer tiền, scenario này chỉ chạy được
    nếu env ``LOCUST_TOPUP_ENABLED=1`` và admin đã có sẵn cách auto-credit
    (vd CLI ``apimb topup credit-test``).
    """

    weight = 0  # Opt-in: chạy với --tag topup
    wait_time = between(2, 5)

    def on_start(self) -> None:
        if os.environ.get("LOCUST_TOPUP_ENABLED") != "1":
            self.environment.runner.quit()
            return
        self.email = f"topup-load-{secrets.token_hex(6)}@example.com"
        self.client.get("/healthz")
        csrf = self.client.cookies.get("apibank_csrf", "")
        self.headers = {"X-CSRF-Token": csrf}
        self.client.post(
            "/api/v1/auth/register",
            json={"email": self.email, "password": "Strong-Pass-1"},
            headers=self.headers,
        )
        self.client.post(
            "/api/v1/auth/login",
            json={"email": self.email, "password": "Strong-Pass-1"},
            headers=self.headers,
        )

    @task
    def topup_and_wait(self) -> None:
        start = time.monotonic()
        res = self.client.post(
            "/api/v1/me/topup",
            json={"amount_vnd": 50_000},
            headers=self.headers,
            name="POST /me/topup",
        )
        if res.status_code != 201:
            return
        code = res.json().get("code")
        if not code:
            return
        # Connect SSE và đợi event "paid". Block tối đa 30s.
        with self.client.stream(
            "GET",
            f"/api/v1/me/topup/{code}/events",
            timeout=30,
            name="SSE /me/topup/.../events",
        ) as stream:
            for line in stream.iter_lines():
                if not line:
                    continue
                if line.startswith("event: paid"):
                    elapsed_ms = (time.monotonic() - start) * 1000
                    events.request.fire(
                        request_type="SSE",
                        name="topup.paid_latency",
                        response_time=elapsed_ms,
                        response_length=0,
                        exception=None,
                    )
                    return
                if line.startswith("event: timeout") or line.startswith(
                    "event: expired"
                ):
                    return


class WebhookDrainUser(HttpUser):
    """Sub-scenario: đo replay throughput.

    Cần env ``LOCUST_API_KEY`` (admin scope). Spam attempt:replay → đo
    delivered/s qua metric ``apibank_webhook_attempts_total{status="delivered"}``.
    """

    weight = 0  # Opt-in
    wait_time = between(0.1, 0.3)

    def on_start(self) -> None:
        self.api_key = os.environ.get("LOCUST_API_KEY", "")
        self.attempt_id = os.environ.get("LOCUST_ATTEMPT_ID", "")
        if not self.api_key or not self.attempt_id:
            self.environment.runner.quit()

    @task
    def replay_attempt(self) -> None:
        self.client.post(
            f"/v1/webhooks/attempts/{self.attempt_id}:replay",
            headers={"Authorization": f"Bearer {self.api_key}"},
            name="POST webhook attempt:replay",
        )
