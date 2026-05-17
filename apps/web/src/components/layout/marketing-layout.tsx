import { Outlet, Link, NavLink } from "react-router-dom";
import { Helmet } from "react-helmet-async";
import { Logo } from "@/components/logo";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";

function Header() {
  const { data } = useAuth();
  return (
    <header className="sticky top-0 z-30 border-b bg-background/85 backdrop-blur">
      <div className="container flex h-14 items-center justify-between">
        <Link to="/" className="focus-ring rounded-md" aria-label="APIBank">
          <Logo />
        </Link>
        <nav className="hidden items-center gap-6 text-sm md:flex" aria-label="Điều hướng chính">
          <NavLink to="/" end className={({ isActive }) => (isActive ? "text-foreground" : "text-muted-foreground hover:text-foreground")}>Trang chủ</NavLink>
          <NavLink to="/pricing" className={({ isActive }) => (isActive ? "text-foreground" : "text-muted-foreground hover:text-foreground")}>Bảng giá</NavLink>
          <a href="/api/docs" className="text-muted-foreground hover:text-foreground">Tài liệu API</a>
          <NavLink to="/styleguide" className={({ isActive }) => (isActive ? "text-foreground" : "text-muted-foreground hover:text-foreground")}>Style guide</NavLink>
        </nav>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          {data?.user ? (
            <Button asChild size="sm">
              <Link to="/app">Vào dashboard</Link>
            </Button>
          ) : (
            <>
              <Button asChild size="sm" variant="ghost">
                <Link to="/login">Đăng nhập</Link>
              </Button>
              <Button asChild size="sm">
                <Link to="/register">Đăng ký</Link>
              </Button>
            </>
          )}
        </div>
      </div>
    </header>
  );
}

function Footer() {
  return (
    <footer className="border-t bg-muted/10">
      <div className="container grid gap-8 py-10 md:grid-cols-4">
        <div className="space-y-2">
          <Logo />
          <p className="text-sm text-muted-foreground">
            Cổng nhận tiền tự host, an toàn, minh bạch. Sử dụng tại Việt Nam.
          </p>
        </div>
        <div>
          <h4 className="text-sm font-semibold">Sản phẩm</h4>
          <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
            <li><Link to="/pricing" className="hover:text-foreground">Bảng giá</Link></li>
            <li><a href="/api/docs" className="hover:text-foreground">Tài liệu API</a></li>
            <li><Link to="/styleguide" className="hover:text-foreground">Style guide</Link></li>
          </ul>
        </div>
        <div>
          <h4 className="text-sm font-semibold">Tài nguyên</h4>
          <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
            <li><Link to="/legal/terms" className="hover:text-foreground">Điều khoản</Link></li>
            <li><Link to="/legal/privacy" className="hover:text-foreground">Chính sách bảo mật</Link></li>
          </ul>
        </div>
        <div>
          <h4 className="text-sm font-semibold">Liên hệ</h4>
          <p className="mt-2 text-sm text-muted-foreground">
            Tự host? Tài liệu CLI và Docker compose có sẵn trong repo. Hỗ trợ qua Telegram &
            email.
          </p>
        </div>
      </div>
      <div className="border-t py-4 text-center text-xs text-muted-foreground">
        © {new Date().getFullYear()} APIBank · Self-host · Open source friendly
      </div>
    </footer>
  );
}

export function MarketingLayout() {
  return (
    <div className="flex min-h-screen flex-col">
      <Helmet>
        <html lang="vi" />
      </Helmet>
      <Header />
      <main id="main" className="flex-1">
        <Outlet />
      </main>
      <Footer />
    </div>
  );
}
