import axios, { type AxiosInstance } from "axios";

const CSRF_COOKIE = "apibank_csrf";

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

export const api: AxiosInstance = axios.create({
  baseURL: "/",
  withCredentials: true,
  timeout: 20_000,
});

api.interceptors.request.use((config) => {
  const token = readCookie(CSRF_COOKIE);
  if (token && !["get", "head", "options"].includes((config.method ?? "get").toLowerCase())) {
    config.headers.set("X-CSRF-Token", token);
  }
  return config;
});

export interface ApiError {
  status: number;
  detail: string;
  raw: unknown;
}

/** Pydantic 422 error item ({type, loc, msg, input, ctx}) → human-readable. */
function formatValidationItem(item: unknown): string {
  if (typeof item === "string") return item;
  if (item && typeof item === "object") {
    const o = item as { msg?: unknown; loc?: unknown };
    const msg = typeof o.msg === "string" ? o.msg : "";
    const loc = Array.isArray(o.loc)
      ? o.loc
          .map(String)
          .filter((p) => p !== "body")
          .join(".")
      : "";
    if (msg && loc) return `${loc}: ${msg}`;
    if (msg) return msg;
    if (loc) return loc;
  }
  try {
    return JSON.stringify(item);
  } catch {
    return String(item);
  }
}

function normalizeDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map(formatValidationItem).join("; ");
  }
  if (detail && typeof detail === "object") {
    return formatValidationItem(detail);
  }
  return "";
}

export function toApiError(err: unknown): ApiError {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data as { detail?: unknown } | undefined;
    const detail =
      normalizeDetail(data?.detail) || err.message || "request failed";
    return { status: err.response?.status ?? 0, detail, raw: data };
  }
  return { status: 0, detail: String(err), raw: err };
}

// --------- types ---------------------------------------------------------

export interface UserPublic {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  status: string;
  locale: string;
  balance_vnd: string;
  email_verified_at: string | null;
  has_2fa: boolean;
  telegram_chat_id: string | null;
  last_login_at: string | null;
  created_at: string;
}

export interface AuthMeResponse {
  user: UserPublic;
  requires_2fa?: boolean;
}

export interface LoginResponse {
  user?: UserPublic;
  requires_2fa?: boolean;
  challenge_token?: string | null;
}

export interface PlanRead {
  id: string;
  code: string;
  name: string;
  description: string | null;
  price_vnd: string;
  duration_days: number;
  daily_quota: number;
  monthly_quota: number;
  features_json: { highlights?: string[]; popular?: boolean; trial?: boolean };
  sort_order: number;
}

export interface BankAccount {
  id: string;
  bank_code: string;
  account_no: string;
  account_holder: string;
  status: string;
  polling_enabled: boolean;
  polling_status: string;
  is_system_account: boolean;
  last_login_at: string | null;
  last_poll_at: string | null;
  verified_at: string | null;
  last_error: string | null;
  created_at: string;
}

export interface Webhook {
  id: string;
  name: string | null;
  url: string;
  active: boolean;
  events_json: { events?: string[] };
  headers_json: Record<string, string>;
  last_delivery_at: string | null;
  created_at: string;
}

export interface MeApiKey {
  id: string;
  name: string | null;
  scopes: string[];
  last_used_at: string | null;
  last_used_ip: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export interface MeApiKeyCreated extends MeApiKey {
  raw_key: string;
}

export interface WalletBalance {
  balance_vnd: string;
  pending_topups: number;
}

export interface WalletTransactionItem {
  id: string;
  type: string;
  amount_vnd: string;
  balance_after: string;
  ref_kind: string | null;
  ref_id: string | null;
  note: string | null;
  created_at: string;
}

export interface TopupResponse {
  order_id: string;
  code: string;
  amount_vnd: string;
  status: string;
  expired_at: string;
  pay_url: string;
  qr_url: string;
  bank_code: string;
  bank_name: string;
  account_no: string;
  account_holder: string;
  transfer_content: string;
}

export interface TopupCheckResponse {
  order_id: string;
  code: string;
  status: "pending" | "paid" | "expired" | "canceled";
  balance_vnd: string | null;
  waited_ms: number;
  message: string;
}

export interface TopupListItem {
  order_id: string;
  code: string;
  amount_vnd: string;
  status: string;
  created_at: string;
  expired_at: string;
  pay_url: string;
  qr_url: string;
  bank_code: string;
  bank_name: string;
  account_no: string;
  account_holder: string;
  transfer_content: string;
}

export interface SubscriptionRead {
  id: string;
  plan_id: string;
  plan_code: string | null;
  started_at: string;
  expires_at: string;
  status: string;
  auto_renew: boolean;
}

export interface InvoiceRead {
  id: string;
  plan_code: string | null;
  amount_vnd: string;
  currency: string;
  status: string;
  issued_at: string;
}

export interface OrderItem {
  id: string;
  code: string;
  amount_vnd: string;
  status: string;
  bank_account_id: string;
  description: string | null;
  customer_ref: string | null;
  expired_at: string;
  paid_at: string | null;
  created_at: string;
}

export interface TransactionItem {
  id: string;
  bank_account_id: string;
  bank_ref_no: string;
  amount_vnd: string;
  content: string;
  state: string;
  matched_order_id: string | null;
  posted_at: string;
}

// --------- endpoints ----------------------------------------------------

export const endpoints = {
  // auth
  register: (body: { email: string; password: string; full_name?: string }) =>
    api.post("/api/v1/auth/register", body),
  login: (body: { email: string; password: string; code?: string }) =>
    api.post<LoginResponse>("/api/v1/auth/login", body),
  logout: () => api.post("/api/v1/auth/logout"),
  me: () => api.get<AuthMeResponse>("/api/v1/auth/me"),
  verifyEmail: (token: string) => api.post("/api/v1/auth/verify-email", { token }),
  forgot: (email: string) => api.post("/api/v1/auth/forgot", { email }),
  reset: (token: string, password: string) => api.post("/api/v1/auth/reset", { token, password }),
  changePassword: (current_password: string, new_password: string) =>
    api.post("/api/v1/auth/change-password", { current_password, new_password }),
  enroll2fa: () => api.post("/api/v1/auth/2fa/enroll"),
  verify2fa: (code: string) => api.post("/api/v1/auth/2fa/verify", { code }),
  disable2fa: (password: string) => api.post("/api/v1/auth/2fa/disable", { password }),
  listSessions: () => api.get("/api/v1/auth/sessions"),
  revokeSession: (id: string) => api.delete(`/api/v1/auth/sessions/${id}`),
  logoutAll: () => api.post("/api/v1/auth/logout-all"),
  updateProfile: (body: { full_name?: string; locale?: string; telegram_chat_id?: string }) =>
    api.patch<UserPublic>("/api/v1/auth/profile", body),
  linkUserTelegram: () =>
    api.post<{ deep_link_url: string; token: string; expires_in: number }>(
      "/api/v1/auth/profile/telegram/link-chat",
    ),
  unlinkUserTelegram: () => api.delete("/api/v1/auth/profile/telegram"),

  // public
  plans: () => api.get<PlanRead[]>("/api/v1/plans"),

  // bank accounts
  bankAccounts: () => api.get<BankAccount[]>("/api/v1/me/bank-accounts"),
  createBank: (body: {
    bank_code: string;
    account_no: string;
    account_holder: string;
    username: string;
    password: string;
  }) => api.post<BankAccount>("/api/v1/me/bank-accounts", body),
  rotateBank: (id: string, body: { username: string; password: string }) =>
    api.post<BankAccount>(`/api/v1/me/bank-accounts/${id}/rotate`, body),
  verifyBank: (id: string) =>
    api.post<BankAccount>(`/api/v1/me/bank-accounts/${id}/verify`),
  setBankPolling: (id: string, polling_enabled: boolean) =>
    api.patch<BankAccount>(`/api/v1/me/bank-accounts/${id}`, { polling_enabled }),
  deleteBank: (id: string) => api.delete(`/api/v1/me/bank-accounts/${id}`),

  // webhooks
  webhooks: () => api.get<Webhook[]>("/api/v1/me/webhooks"),
  createWebhook: (body: {
    name?: string;
    url: string;
    secret: string;
    events?: string[];
  }) => api.post<Webhook>("/api/v1/me/webhooks", body),
  updateWebhook: (
    id: string,
    body: { active?: boolean; events?: string[]; name?: string },
  ) => api.patch<Webhook>(`/api/v1/me/webhooks/${id}`, body),
  deleteWebhook: (id: string) => api.delete(`/api/v1/me/webhooks/${id}`),
  webhookAttempts: (id: string) => api.get(`/api/v1/me/webhooks/${id}/attempts`),
  webhookTest: (id: string) =>
    api.post<{
      delivered: boolean;
      status_code: number | null;
      error: string | null;
      signature: string;
      event_id: string;
    }>(`/api/v1/me/webhooks/${id}/test`),

  // api keys
  apiKeys: () => api.get<MeApiKey[]>("/api/v1/me/api-keys"),
  createApiKey: (body: { name: string; scopes?: string[]; expires_at?: string | null }) =>
    api.post<MeApiKeyCreated>("/api/v1/me/api-keys", body),
  revokeApiKey: (id: string) => api.post(`/api/v1/me/api-keys/${id}/revoke`),

  // wallet / topup
  wallet: () => api.get<WalletBalance>("/api/v1/me/wallet"),
  walletTransactions: () => api.get<WalletTransactionItem[]>("/api/v1/me/wallet/transactions"),
  topup: (amount_vnd: number) => api.post<TopupResponse>("/api/v1/me/topup", { amount_vnd }),
  topupStatus: (code: string) => api.get(`/pay/${code}/status`),
  pendingTopups: () => api.get<TopupListItem[]>("/api/v1/me/topups"),
  cancelTopup: (orderId: string) =>
    api.post<TopupListItem>(`/api/v1/me/topups/${orderId}:cancel`),
  checkTopup: (orderId: string) =>
    api.post<TopupCheckResponse>(`/api/v1/me/topups/${orderId}:check`, undefined, {
      // BE đợi tối đa 12s sau khi kick worker; cho client thêm buffer.
      timeout: 30_000,
    }),

  // subscription / invoices
  subscription: () => api.get<SubscriptionRead | null>("/api/v1/me/subscription"),
  purchaseSubscription: (plan_code: string) =>
    api.post<SubscriptionRead>("/api/v1/me/subscription/purchase", { plan_code }),
  invoices: () => api.get<InvoiceRead[]>("/api/v1/me/invoices"),

  // orders / transactions
  orders: (params?: { status?: string; bank_account_id?: string }) =>
    api.get<OrderItem[]>("/api/v1/me/orders", { params }),
  transactions: (params?: { state?: string; bank_account_id?: string }) =>
    api.get<TransactionItem[]>("/api/v1/me/transactions", { params }),

  // google oauth status (public)
  googleStatus: () => api.get<{ enabled: boolean }>("/api/v1/auth/google/status"),

  // notifications (in-app inbox)
  notifications: (params?: { limit?: number; unread_only?: boolean }) =>
    api.get<NotificationItem[]>("/api/v1/me/notifications", { params }),
  notificationsUnreadCount: () =>
    api.get<{ unread: number }>("/api/v1/me/notifications/unread-count"),
  markNotificationRead: (id: string) =>
    api.patch<NotificationItem>(`/api/v1/me/notifications/${id}`),
  markAllNotificationsRead: () =>
    api.post("/api/v1/me/notifications/read-all"),

  // notification preferences (matrix kind x channel)
  notificationPreferences: () =>
    api.get<NotificationPreferenceList>("/api/v1/me/notification-preferences"),
  updateNotificationPreferences: (items: NotificationPreferenceItem[]) =>
    api.put<NotificationPreferenceList>("/api/v1/me/notification-preferences", { items }),
};

export interface NotificationItem {
  id: string;
  kind: string;
  title: string;
  body: string | null;
  payload_json: Record<string, unknown>;
  read_at: string | null;
  created_at: string;
}

export interface NotificationPreferenceItem {
  kind: string;
  channel: "in_app" | "email" | "telegram";
  enabled: boolean;
}

export interface NotificationPreferenceList {
  items: NotificationPreferenceItem[];
}

// --------- ADMIN console ------------------------------------------------

export interface AdminUserListItem {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  status: string;
  balance_vnd: string;
  last_login_at: string | null;
  created_at: string;
}

export interface AdminUserListResponse {
  items: AdminUserListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminUserDetail extends AdminUserListItem {
  locale: string;
  has_2fa: boolean;
  email_verified_at: string | null;
  telegram_chat_id: string | null;
  bank_accounts_count: number;
  sessions_count: number;
  subscription: {
    id: string;
    plan_code: string | null;
    started_at: string;
    expires_at: string;
    status: string;
  } | null;
  recent_wallet_tx: Array<{
    id: string;
    type: string;
    amount_vnd: string;
    balance_after: string;
    note: string | null;
    created_at: string;
  }>;
}

export interface AdminPlan {
  id: string;
  code: string;
  name: string;
  description: string | null;
  price_vnd: string;
  duration_days: number;
  daily_quota: number;
  monthly_quota: number;
  features_json: { highlights?: string[]; popular?: boolean; trial?: boolean };
  sort_order: number;
  active: boolean;
  created_at: string;
}

export interface AdminPlanCreateInput {
  code: string;
  name: string;
  description?: string | null;
  price_vnd: number;
  duration_days: number;
  daily_quota?: number;
  monthly_quota?: number;
  features_json?: Record<string, unknown>;
  sort_order?: number;
  active?: boolean;
}

export interface AdminBankAccount {
  id: string;
  user_id: string | null;
  user_email: string | null;
  bank_code: string;
  account_no: string;
  account_holder: string;
  status: string;
  polling_enabled: boolean;
  polling_status: string;
  is_system_account: boolean;
  last_poll_at: string | null;
  last_error: string | null;
  created_at: string;
}

export interface AdminStats {
  users_total: number;
  users_active: number;
  orders_pending: number;
  orders_paid_24h: number;
  tx_24h: number;
  wallet_total_vnd: string;
  subscriptions_active: number;
  bank_accounts: number;
}

export interface AdminAuditItem {
  id: string;
  actor: string;
  action: string;
  target_type: string;
  target_id: string;
  ip: string | null;
  created_at: string;
  after_json: Record<string, unknown> | null;
  before_json: Record<string, unknown> | null;
}

export interface AdminAuditResponse {
  items: AdminAuditItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminWalletOpResponse {
  tx_id: string;
  balance_after: string;
  amount_vnd: string;
}

export interface SmtpConfigRead {
  host: string;
  port: number;
  user: string;
  from_addr: string;
  use_tls: boolean;
  enabled: boolean;
  password_set: boolean;
}

export interface SmtpConfigUpdate {
  host: string;
  port: number;
  user: string;
  password?: string | null;
  from_addr: string;
  use_tls: boolean;
  enabled: boolean;
}

export interface GoogleConfigRead {
  client_id: string;
  redirect_uri: string;
  enabled: boolean;
  client_secret_set: boolean;
}

export interface GoogleConfigUpdate {
  client_id: string;
  client_secret?: string | null;
  redirect_uri: string;
  enabled: boolean;
}

export interface TelegramConfigRead {
  enabled: boolean;
  webhook_url: string;
  admin_chat_id: string;
  bot_username: string;
  bot_token_set: boolean;
}

export interface TelegramConfigUpdate {
  bot_token?: string | null;
  enabled: boolean;
}

export const adminEndpoints = {
  // users
  listUsers: (params?: {
    q?: string;
    role?: string;
    status?: string;
    limit?: number;
    offset?: number;
  }) => api.get<AdminUserListResponse>("/api/v1/admin/users", { params }),
  getUser: (id: string) => api.get<AdminUserDetail>(`/api/v1/admin/users/${id}`),
  updateUser: (
    id: string,
    body: { role?: string; status?: string; full_name?: string },
  ) => api.patch<AdminUserListItem>(`/api/v1/admin/users/${id}`, body),
  walletCredit: (id: string, body: { amount_vnd: number; note?: string }) =>
    api.post<AdminWalletOpResponse>(
      `/api/v1/admin/users/${id}/wallet/credit`,
      body,
    ),
  walletRefund: (
    id: string,
    body: { amount_vnd: number; note?: string; ref_id?: string },
  ) =>
    api.post<AdminWalletOpResponse>(
      `/api/v1/admin/users/${id}/wallet/refund`,
      body,
    ),
  walletAdjust: (id: string, body: { amount_vnd: number; note?: string }) =>
    api.post<AdminWalletOpResponse>(
      `/api/v1/admin/users/${id}/wallet/adjust`,
      body,
    ),
  resetPassword: (id: string) =>
    api.post(`/api/v1/admin/users/${id}/reset-password`),
  disable2fa: (id: string) =>
    api.post(`/api/v1/admin/users/${id}/disable-2fa`),

  // plans
  listPlans: () => api.get<AdminPlan[]>("/api/v1/admin/plans"),
  createPlan: (body: AdminPlanCreateInput) =>
    api.post<AdminPlan>("/api/v1/admin/plans", body),
  updatePlan: (id: string, body: Partial<AdminPlanCreateInput>) =>
    api.patch<AdminPlan>(`/api/v1/admin/plans/${id}`, body),
  deletePlan: (id: string) => api.delete(`/api/v1/admin/plans/${id}`),

  // bank accounts + system bank
  listBankAccounts: () =>
    api.get<AdminBankAccount[]>("/api/v1/admin/bank-accounts"),
  getSystemBank: () =>
    api.get<AdminBankAccount | null>("/api/v1/admin/system-bank"),
  setSystemBank: (bank_account_id: string) =>
    api.post("/api/v1/admin/system-bank", { bank_account_id }),
  unsetSystemBank: () => api.delete("/api/v1/admin/system-bank"),

  // stats + audit
  getStats: () => api.get<AdminStats>("/api/v1/admin/stats"),
  listAudit: (params?: {
    action?: string;
    actor?: string;
    limit?: number;
    offset?: number;
  }) => api.get<AdminAuditResponse>("/api/v1/admin/audit-log", { params }),

  // config: SMTP
  getSmtp: () => api.get<SmtpConfigRead>("/api/v1/admin/config/smtp"),
  saveSmtp: (body: SmtpConfigUpdate) =>
    api.put<SmtpConfigRead>("/api/v1/admin/config/smtp", body),
  testSmtp: (to_email: string) =>
    api.post<{ ok: boolean; error: string | null }>(
      "/api/v1/admin/config/smtp/test",
      { to_email },
    ),

  // config: Google
  getGoogle: () => api.get<GoogleConfigRead>("/api/v1/admin/config/google"),
  saveGoogle: (body: GoogleConfigUpdate) =>
    api.put<GoogleConfigRead>("/api/v1/admin/config/google", body),

  // config: Telegram
  getTelegram: () =>
    api.get<TelegramConfigRead>("/api/v1/admin/config/telegram"),
  saveTelegram: (body: TelegramConfigUpdate) =>
    api.put<TelegramConfigRead>("/api/v1/admin/config/telegram", body),
  registerTelegramWebhook: (base_url: string) =>
    api.post<{ ok: boolean; description: string | null; webhook_url: string | null }>(
      "/api/v1/admin/config/telegram/register-webhook",
      { base_url },
    ),
  deleteTelegramWebhook: () =>
    api.delete("/api/v1/admin/config/telegram/webhook"),
  linkTelegramChat: () =>
    api.post<{ deep_link_url: string; token: string; expires_in: number }>(
      "/api/v1/admin/config/telegram/link-chat",
    ),
  unlinkTelegramChat: () =>
    api.delete("/api/v1/admin/config/telegram/admin-chat"),
};
