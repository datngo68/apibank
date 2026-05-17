import { Outlet, Link } from "react-router-dom";
import { Helmet } from "react-helmet-async";
import { Logo } from "@/components/logo";
import { ThemeToggle } from "@/components/theme-toggle";

export function AuthLayout() {
  return (
    <div className="flex min-h-screen flex-col bg-muted/20">
      <Helmet>
        <html lang="vi" />
      </Helmet>
      <header className="container flex h-14 items-center justify-between">
        <Link to="/" className="focus-ring rounded-md" aria-label="APIBank">
          <Logo />
        </Link>
        <ThemeToggle />
      </header>
      <main id="main" className="container flex flex-1 items-center justify-center px-4 py-8">
        <div className="w-full max-w-md">
          <Outlet />
        </div>
      </main>
      <footer className="border-t py-4 text-center text-xs text-muted-foreground">
        © {new Date().getFullYear()} APIBank · Tự host · An toàn · Minh bạch
      </footer>
    </div>
  );
}
