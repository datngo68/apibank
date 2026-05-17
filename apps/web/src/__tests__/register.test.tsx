import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { HelmetProvider } from "react-helmet-async";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    endpoints: {
      ...actual.endpoints,
      register: vi.fn(async () => ({ data: { message: "ok" } })),
    },
  };
});

import { RegisterPage } from "@/pages/auth/register";

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <HelmetProvider>
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <RegisterPage />
          <Toaster />
        </MemoryRouter>
      </QueryClientProvider>
    </HelmetProvider>,
  );
}

describe("RegisterPage", () => {
  it("hiển thị field nhập lại mật khẩu", () => {
    renderPage();
    expect(screen.getByLabelText("Nhập lại mật khẩu")).toBeInTheDocument();
  });

  it("không có alert bảo mật bcrypt/SHA", () => {
    renderPage();
    expect(screen.queryByText(/bcrypt/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/SHA-256/i)).not.toBeInTheDocument();
  });

  it("báo lỗi khi mật khẩu xác nhận không khớp", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText("Email"), "user@a.com");
    await user.type(screen.getByLabelText("Mật khẩu"), "Strong-Pass-1");
    await user.type(screen.getByLabelText("Nhập lại mật khẩu"), "Different-Pass-2");
    await user.click(screen.getByRole("button", { name: "Tạo tài khoản" }));
    await waitFor(() =>
      expect(screen.getByText("Mật khẩu xác nhận không khớp")).toBeInTheDocument(),
    );
  });
});
