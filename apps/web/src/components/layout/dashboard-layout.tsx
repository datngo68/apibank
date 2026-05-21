import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Helmet } from "react-helmet-async";
import {
  LayoutDashboard,
  Banknote,
  Webhook,
  KeyRound,
  ShoppingBag,
  ArrowLeftRight,
  Wallet,
  CreditCard,
  Settings,
  ShieldCheck,
  Users,
  ServerCog,
  ScrollText,
  BookOpen,
  LogOut,
  ChevronRight,
  TicketPercent,
  Activity,
  TrendingUp,
} from "lucide-react";
import { useEffect } from "react";
import { Logo } from "@/components/logo";
import { NotificationBell } from "@/components/notification-bell";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth, useLogout } from "@/lib/auth";
import { cn, formatVnd } from "@/lib/utils";

interface NavItem {
  to: string;
  label: string;
  icon: typeof LayoutDashboard;
  end?: boolean;
}

const NAV: NavItem[] = [
  { to: "/app", label: "Tổng quan", icon: LayoutDashboard, end: true },
  { to: "/app/bank-accounts", label: "Tài khoản ngân hàng", icon: Banknote },
  { to: "/app/webhooks", label: "Webhooks", icon: Webhook },
  { to: "/app/api-keys", label: "API keys", icon: KeyRound },
  { to: "/app/orders", label: "Đơn hàng", icon: ShoppingBag },
  { to: "/app/transactions", label: "Giao dịch", icon: ArrowLeftRight },
  { to: "/app/wallet", label: "Ví số dư", icon: Wallet },
  { to: "/app/billing", label: "Gói cước", icon: CreditCard },
  { to: "/app/docs", label: "Hướng dẫn tích hợp", icon: BookOpen },
  { to: "/app/settings", label: "Cài đặt", icon: Settings },
];

const ADMIN_NAV: NavItem[] = [
  { to: "/app/admin", label: "Admin dashboard", icon: ShieldCheck, end: true },
  { to: "/app/admin/users", label: "Người dùng", icon: Users },
  { to: "/app/admin/api-keys", label: "API keys", icon: KeyRound },
  { to: "/app/admin/usage", label: "Lượt request", icon: Activity },
  { to: "/app/admin/revenue", label: "Doanh thu", icon: TrendingUp },
  { to: "/app/admin/plans", label: "Plans", icon: CreditCard },
  { to: "/app/admin/coupons", label: "Mã giảm giá", icon: TicketPercent },
  { to: "/app/admin/bank-accounts", label: "Ngân hàng hệ thống", icon: Banknote },
  { to: "/app/admin/config", label: "Cấu hình", icon: ServerCog },
  { to: "/app/admin/audit-log", label: "Audit log", icon: ScrollText },
];

export function DashboardLayout() {
  const { data, isLoading } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const logout = useLogout();

  useEffect(() => {
    if (!isLoading && !data?.user) {
      navigate("/login", { replace: true, state: { from: location.pathname } });
    }
  }, [isLoading, data, navigate, location.pathname]);

  if (isLoading || !data?.user) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">
        Đang tải dashboard…
      </div>
    );
  }

  const isAdmin = ["admin", "owner"].includes(data.user.role);

  return (
    <div className="flex min-h-screen bg-muted/20">
      <Helmet>
        <html lang="vi" />
        <title>Dashboard · APIBank</title>
      </Helmet>
      <aside className="hidden w-64 border-r bg-background md:flex md:flex-col">
        <div className="flex h-14 items-center px-4">
          <Link to="/app" className="focus-ring rounded-md" aria-label="APIBank">
            <Logo />
          </Link>
        </div>
        <nav className="flex-1 space-y-1 px-3 py-2 text-sm" aria-label="Dashboard">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2 rounded-md px-3 py-2 transition-colors",
                  isActive
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                )
              }
            >
              <Icon className="size-4" aria-hidden /> {label}
            </NavLink>
          ))}
          {isAdmin ? (
            <>
              <p className="mt-4 px-3 text-xs uppercase tracking-wider text-muted-foreground">
                Admin
              </p>
              {ADMIN_NAV.map(({ to, label, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-2 rounded-md px-3 py-2 transition-colors",
                      isActive
                        ? "bg-primary/10 text-primary"
                        : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                    )
                  }
                >
                  <Icon className="size-4" aria-hidden /> {label}
                </NavLink>
              ))}
            </>
          ) : null}
        </nav>
        <div className="border-t p-3 text-xs text-muted-foreground">
          <div className="mb-1">Số dư ví</div>
          <div className="font-mono text-sm text-foreground">
            {formatVnd(Number(data.user.balance_vnd))}
          </div>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-14 items-center justify-between border-b bg-background/85 px-4 backdrop-blur">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Link to="/app">Dashboard</Link>
            <ChevronRight className="size-3.5" aria-hidden />
            <span className="font-medium text-foreground">{currentLabel(location.pathname)}</span>
          </div>
          <div className="flex items-center gap-2">
            <NotificationBell />
            <ThemeToggle />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" className="gap-2">
                  <span className="inline-flex size-7 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                    {(data.user.full_name ?? data.user.email).slice(0, 1).toUpperCase()}
                  </span>
                  <span className="hidden text-sm sm:inline">{data.user.email}</span>
                  {isAdmin ? (
                    <Badge variant="primary" className="ml-1">
                      {data.user.role}
                    </Badge>
                  ) : null}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="min-w-[12rem]">
                <DropdownMenuLabel>Tài khoản</DropdownMenuLabel>
                <DropdownMenuItem asChild>
                  <Link to="/app/settings">Cài đặt</Link>
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => logout.mutate()}>
                  <LogOut className="size-4" aria-hidden /> Đăng xuất
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>
        <main className="flex-1 px-4 py-6 md:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function currentLabel(pathname: string): string {
  const match = [...NAV, ...ADMIN_NAV]
    .filter((it) => pathname === it.to || pathname.startsWith(it.to + "/"))
    .sort((a, b) => b.to.length - a.to.length)[0];
  return match?.label ?? "Dashboard";
}
