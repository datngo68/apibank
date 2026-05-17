from prometheus_client import Counter, Gauge, Histogram

# --- Bank polling --------------------------------------------------------
poll_success_total = Counter("apibank_poll_success_total", "Successful bank polls", ["bank"])
poll_failure_total = Counter("apibank_poll_failure_total", "Failed bank polls", ["bank"])
poll_duration_seconds = Histogram("apibank_poll_duration_seconds", "Bank poll duration seconds")
bank_login_failure_total = Counter(
    "apibank_bank_login_failure_total", "Bank login failures", ["bank"]
)

# --- Orders / matching ---------------------------------------------------
orders_total = Counter("apibank_orders_total", "Orders by status", ["status"])
match_total = Counter("apibank_match_total", "Match results", ["result"])

# --- Webhook delivery ----------------------------------------------------
webhook_attempts_total = Counter("apibank_webhook_attempts_total", "Webhook attempts", ["status"])
webhook_delivery_seconds = Histogram(
    "apibank_webhook_delivery_seconds", "Webhook delivery seconds"
)
webhook_failure_total = Counter(
    "apibank_webhook_failure_total", "Webhook failures", ["http_status"]
)
webhook_dispatch_concurrency = Gauge(
    "apibank_webhook_dispatch_concurrency",
    "In-flight webhook dispatch tasks",
)
webhook_kick_total = Counter(
    "apibank_webhook_kick_total", "Webhook dispatcher kick events", ["source"]
)

# --- Ingest critical path ------------------------------------------------
ingest_critical_path_seconds = Histogram(
    "apibank_ingest_critical_path_seconds",
    "Time spent in ingest_transaction (insert tx -> commit)",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)

# --- Notification outbox -------------------------------------------------
notification_dispatch_total = Counter(
    "apibank_notification_dispatch_total",
    "Notifications dispatched from outbox",
    ["channel", "result"],
)

# --- Auth ----------------------------------------------------------------
auth_login_total = Counter(
    "apibank_auth_login_total", "Login attempts", ["result"]
)
auth_register_total = Counter("apibank_auth_register_total", "User registrations")

# --- Billing -------------------------------------------------------------
topup_credited_total = Counter(
    "apibank_topup_credited_total", "Successful topup credits", []
)
subscription_purchased_total = Counter(
    "apibank_subscription_purchased_total", "Subscription purchases", ["plan"]
)
quota_exceeded_total = Counter(
    "apibank_quota_exceeded_total", "API key quota exceeded events", []
)

# --- HTTP latency --------------------------------------------------------
http_request_duration_seconds = Histogram(
    "apibank_http_request_duration_seconds",
    "HTTP request duration",
    labelnames=["method", "route", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

# --- Gauges ---------------------------------------------------------------
active_subscriptions_gauge = Gauge(
    "apibank_active_subscriptions", "Number of active subscriptions"
)
wallet_total_balance_vnd = Gauge(
    "apibank_wallet_total_balance_vnd", "Sum of all user wallet balances in VND"
)
