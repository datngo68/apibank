import { Routes, Route } from "react-router-dom";
import { MarketingLayout } from "@/components/layout/marketing-layout";
import { AuthLayout } from "@/components/layout/auth-layout";
import { DashboardLayout } from "@/components/layout/dashboard-layout";
import { LandingPage } from "@/pages/marketing/landing";
import { PricingPage } from "@/pages/marketing/pricing";
import { TermsPage, PrivacyPage } from "@/pages/marketing/legal";
import { StyleGuidePage } from "@/pages/style-guide";
import { LoginPage } from "@/pages/auth/login";
import { RegisterPage } from "@/pages/auth/register";
import { ForgotPasswordPage, ResetPasswordPage, VerifyEmailPage } from "@/pages/auth/password";
import { OverviewPage } from "@/pages/dashboard/overview";
import { BankAccountsPage } from "@/pages/dashboard/bank-accounts";
import { WebhooksPage } from "@/pages/dashboard/webhooks";
import { ApiKeysPage } from "@/pages/dashboard/api-keys";
import { OrdersPage, TransactionsPage } from "@/pages/dashboard/orders-tx";
import { WalletPage } from "@/pages/dashboard/wallet";
import { BillingPage } from "@/pages/dashboard/billing";
import { SettingsPage } from "@/pages/dashboard/settings";
import { DocsPage } from "@/pages/dashboard/docs";
import { NotificationsPage } from "@/pages/dashboard/notifications";
import {
  AdminDashboardPage,
  AdminUsersPage,
  AdminPlansPage,
  AdminCouponsPage,
  AdminBankAccountsPage,
  AdminConfigPage,
  AdminAuditLogPage,
} from "@/pages/admin";

function NotFound() {
  return (
    <div className="container py-24 text-center">
      <h1 className="text-3xl font-semibold tracking-tight">Không tìm thấy trang</h1>
      <p className="mt-2 text-muted-foreground">
        Liên kết có thể đã thay đổi hoặc bạn chưa đăng nhập.
      </p>
    </div>
  );
}

export function App() {
  return (
    <Routes>
      <Route element={<MarketingLayout />}>
        <Route path="/" element={<LandingPage />} />
        <Route path="/pricing" element={<PricingPage />} />
        <Route path="/legal/terms" element={<TermsPage />} />
        <Route path="/legal/privacy" element={<PrivacyPage />} />
        {import.meta.env.DEV ? (
          <Route path="/styleguide" element={<StyleGuidePage />} />
        ) : null}
      </Route>

      <Route element={<AuthLayout />}>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/forgot" element={<ForgotPasswordPage />} />
        <Route path="/reset" element={<ResetPasswordPage />} />
        <Route path="/verify-email" element={<VerifyEmailPage />} />
      </Route>

      <Route path="/app" element={<DashboardLayout />}>
        <Route index element={<OverviewPage />} />
        <Route path="bank-accounts" element={<BankAccountsPage />} />
        <Route path="webhooks" element={<WebhooksPage />} />
        <Route path="api-keys" element={<ApiKeysPage />} />
        <Route path="orders" element={<OrdersPage />} />
        <Route path="transactions" element={<TransactionsPage />} />
        <Route path="wallet" element={<WalletPage />} />
        <Route path="billing" element={<BillingPage />} />
        <Route path="notifications" element={<NotificationsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="docs" element={<DocsPage />} />
        <Route path="admin" element={<AdminDashboardPage />} />
        <Route path="admin/users" element={<AdminUsersPage />} />
        <Route path="admin/plans" element={<AdminPlansPage />} />
        <Route path="admin/coupons" element={<AdminCouponsPage />} />
        <Route path="admin/bank-accounts" element={<AdminBankAccountsPage />} />
        <Route path="admin/config" element={<AdminConfigPage />} />
        <Route path="admin/audit-log" element={<AdminAuditLogPage />} />
      </Route>

      <Route element={<MarketingLayout />}>
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
