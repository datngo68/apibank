import { Helmet } from "react-helmet-async";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  ShieldCheck,
  Zap,
  BellRing,
  Wallet,
  CheckCircle2,
  ArrowRight,
  Webhook,
  KeyRound,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { endpoints, type PlanRead } from "@/lib/api";
import { formatVnd, cn } from "@/lib/utils";

function Hero() {
  return (
    <section className="relative overflow-hidden">
      <div className="absolute inset-0 -z-10 gradient-mesh" />
      <div
        className="absolute inset-0 -z-10 opacity-[0.04] dark:opacity-[0.06]"
        style={{
          backgroundImage:
            "linear-gradient(to right, currentColor 1px, transparent 1px), linear-gradient(to bottom, currentColor 1px, transparent 1px)",
          backgroundSize: "32px 32px",
        }}
        aria-hidden
      />
      <div className="container py-20 md:py-28">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="mx-auto max-w-3xl text-center"
        >
          <Badge variant="primary" className="mb-4">
            APIBank · Cổng nhận tiền tự động
          </Badge>
          <h1 className="text-balance text-4xl font-semibold tracking-tight md:text-6xl">
            Nhận biến động số dư & xác thực giao dịch{" "}
            <span className="text-primary">trong 5 giây</span>
          </h1>
          <p className="mt-5 text-lg text-muted-foreground">
            Tự host, kết nối nhiều ngân hàng Việt Nam, gửi webhook chuẩn HMAC, không giới hạn số
            lần kiểm tra. Phù hợp shop online, hệ thống nạp đại lý, đối soát kế toán.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <Button asChild size="lg">
              <Link to="/register">
                Đăng ký miễn phí <ArrowRight className="size-4" aria-hidden />
              </Link>
            </Button>
            <Button asChild size="lg" variant="outline">
              <Link to="/pricing">Xem bảng giá</Link>
            </Button>
          </div>
          <p className="mt-4 text-xs text-muted-foreground">
            Không cần thẻ thanh toán · Hủy bất cứ lúc nào · 1.000đ/ngày trải nghiệm
          </p>
        </motion.div>
      </div>
    </section>
  );
}

const FEATURES = [
  {
    icon: Zap,
    title: "Realtime tốc độ 5 giây",
    body: "Polling tối ưu + cache theo bank, đảm bảo webhook về shop của bạn ngay khi tiền vào tài khoản.",
  },
  {
    icon: ShieldCheck,
    title: "An toàn dữ liệu tuyệt đối",
    body: "Credential ngân hàng được mã hóa Fernet, hash mật khẩu bcrypt, audit log mọi hành động.",
  },
  {
    icon: BellRing,
    title: "Thông báo Telegram & Email",
    body: "Nhận cảnh báo khi giao dịch về, khi gói sắp hết hạn, hoặc khi đăng nhập ngân hàng lỗi.",
  },
  {
    icon: Wallet,
    title: "Ví số dư minh bạch",
    body: "Mua gói, gia hạn bằng ví. Lịch sử tiêu dùng đầy đủ, hóa đơn xuất tự động.",
  },
  {
    icon: Webhook,
    title: "Webhook chuẩn HMAC SHA256",
    body: "IP allowlist, retry 7 lần backoff, replay từ dashboard, mock test ping ngay tại UI.",
  },
  {
    icon: KeyRound,
    title: "Quản lý API key theo scope",
    body: "Tạo nhiều key với scope riêng, theo dõi last-used, thu hồi tức thì khi cần.",
  },
];

function Features() {
  return (
    <section id="features" className="border-t bg-muted/20">
      <div className="container py-16">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-semibold tracking-tight">
            Mọi thứ bạn cần để nhận tiền tự động
          </h2>
          <p className="mt-3 text-muted-foreground">
            APIBank gói gọn cổng thanh toán, đối soát giao dịch, webhook và quản lý gói cước trong
            một nền tảng tự host.
          </p>
        </div>
        <div className="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(({ icon: Icon, title, body }) => (
            <Card key={title} className="border-muted/60">
              <CardHeader>
                <div className="mb-3 inline-flex size-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Icon className="size-5" aria-hidden />
                </div>
                <CardTitle className="text-lg">{title}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">{body}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}

function HowItWorks() {
  const steps = [
    {
      title: "1. Thêm tài khoản ngân hàng",
      body: "Nhập thông tin tài khoản & mật khẩu app banking. Credential được mã hóa Fernet trước khi lưu.",
    },
    {
      title: "2. Tạo API key & Webhook",
      body: "Sinh API key có scope phù hợp, đăng ký URL webhook nhận sự kiện thanh toán.",
    },
    {
      title: "3. Tích hợp & nhận tiền",
      body: "Dùng SDK / curl tạo order, hệ thống tự match giao dịch và gửi webhook về shop.",
    },
  ];
  return (
    <section className="border-t">
      <div className="container py-16">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-semibold tracking-tight">Tích hợp trong 5 phút</h2>
          <p className="mt-3 text-muted-foreground">
            Tài liệu API chuẩn OpenAPI, có sẵn ví dụ Node, Python, PHP, cURL.
          </p>
        </div>
        <ol className="mx-auto mt-10 grid max-w-4xl gap-4 md:grid-cols-3">
          {steps.map((s) => (
            <li key={s.title} className="rounded-xl border bg-card p-6">
              <h3 className="font-semibold">{s.title}</h3>
              <p className="mt-2 text-sm text-muted-foreground">{s.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function PriceCard({ plan, popular }: { plan: PlanRead; popular: boolean }) {
  const pricePerDay = plan.duration_days
    ? Math.round(Number(plan.price_vnd) / plan.duration_days)
    : Number(plan.price_vnd);
  return (
    <Card
      className={cn(
        "relative flex flex-col",
        popular && "border-primary shadow-lg shadow-primary/10",
      )}
    >
      {popular ? (
        <Badge variant="primary" className="absolute right-4 top-4">
          Khuyên dùng
        </Badge>
      ) : null}
      <CardHeader>
        <CardTitle>{plan.name}</CardTitle>
        <CardDescription>{plan.description}</CardDescription>
      </CardHeader>
      <CardContent className="flex-1">
        <div className="flex items-baseline gap-1">
          <span className="text-3xl font-semibold tracking-tight">{formatVnd(plan.price_vnd)}</span>
          <span className="text-sm text-muted-foreground">/ {plan.duration_days} ngày</span>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          ~ {formatVnd(pricePerDay)} mỗi ngày
        </p>
        <ul className="mt-5 space-y-2 text-sm">
          {(plan.features_json.highlights ?? []).map((highlight) => (
            <li key={highlight} className="flex items-start gap-2">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
              <span>{highlight}</span>
            </li>
          ))}
        </ul>
      </CardContent>
      <div className="p-6 pt-0">
        <Button asChild className="w-full" variant={popular ? "primary" : "outline"}>
          <Link to="/register">Bắt đầu</Link>
        </Button>
      </div>
    </Card>
  );
}

function Pricing() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["plans"],
    queryFn: async () => (await endpoints.plans()).data,
  });
  return (
    <section id="pricing" className="border-t bg-muted/20">
      <div className="container py-16">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-semibold tracking-tight">Gói cước minh bạch</h2>
          <p className="mt-3 text-muted-foreground">
            Hoàn tiền 100% nếu không vừa ý hoặc phát sinh lỗi trong quá trình sử dụng.
          </p>
        </div>
        <div className="mt-10 grid gap-4 md:grid-cols-3">
          {isLoading ? (
            Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-80" />)
          ) : isError || !data ? (
            <p className="col-span-3 text-center text-sm text-muted-foreground">
              Không tải được bảng giá. Vui lòng thử lại.
            </p>
          ) : (
            data.map((plan) => (
              <PriceCard
                key={plan.id}
                plan={plan}
                popular={Boolean(plan.features_json.popular)}
              />
            ))
          )}
        </div>
      </div>
    </section>
  );
}

const FAQS = [
  {
    q: "APIBank có an toàn cho tài khoản ngân hàng của tôi không?",
    a: "Có. Credential được mã hóa Fernet trước khi lưu, mọi truy cập đều ghi audit log. Bạn có thể xoay credential bất cứ lúc nào hoặc xoá tài khoản khỏi hệ thống.",
  },
  {
    q: "Tích hợp APIBank cần bao lâu?",
    a: "Trung bình 5 phút: tạo API key → đăng ký webhook URL → gửi POST /v1/orders. Đội ngũ hỗ trợ tích hợp miễn phí 24/7 qua Telegram.",
  },
  {
    q: "Hệ thống có hỗ trợ những ngân hàng nào?",
    a: "Hiện hỗ trợ MB, BIDV, ACB, VCB. Có thể thêm adapter bank mới theo yêu cầu.",
  },
  {
    q: "Tôi có thể tự host APIBank không?",
    a: "Có, đây là sản phẩm self-host. Một lệnh `apimb start` chạy đủ API + worker + scheduler + dashboard.",
  },
];

function Faq() {
  return (
    <section className="border-t">
      <div className="container py-16">
        <div className="mx-auto max-w-3xl">
          <h2 className="text-center text-3xl font-semibold tracking-tight">
            Câu hỏi thường gặp
          </h2>
          <div className="mt-8 divide-y rounded-xl border bg-card">
            {FAQS.map((item) => (
              <details key={item.q} className="group p-5">
                <summary className="flex cursor-pointer items-center justify-between text-base font-medium">
                  {item.q}
                  <span
                    className="ml-3 text-xs text-muted-foreground transition-transform group-open:rotate-180"
                    aria-hidden
                  >
                    ▼
                  </span>
                </summary>
                <p className="mt-3 text-sm text-muted-foreground">{item.a}</p>
              </details>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function CallToAction() {
  return (
    <section className="border-t bg-primary/5">
      <div className="container py-16 text-center">
        <h2 className="text-3xl font-semibold tracking-tight">Sẵn sàng chạy hệ thống của bạn?</h2>
        <p className="mt-3 text-muted-foreground">
          Đăng ký dưới 30 giây, dùng thử gói 1.000đ/ngày trước khi chuyển sang gói tháng/năm.
        </p>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
          <Button asChild size="lg">
            <Link to="/register">
              Tạo tài khoản <ArrowRight className="size-4" aria-hidden />
            </Link>
          </Button>
          <Button asChild size="lg" variant="ghost">
            <Link to="/styleguide">Xem design system</Link>
          </Button>
        </div>
      </div>
    </section>
  );
}

export function LandingPage() {
  return (
    <>
      <Helmet>
        <title>APIBank · Cổng thanh toán & xác thực giao dịch tự động</title>
        <meta
          name="description"
          content="APIBank là nền tảng nhận biến động số dư realtime cho nhiều ngân hàng Việt Nam, có webhook chuẩn HMAC, ví số dư, tự host bằng một lệnh CLI."
        />
        <meta property="og:title" content="APIBank — Cổng thanh toán tự host" />
        <meta property="og:type" content="website" />
        <meta property="og:locale" content="vi_VN" />
      </Helmet>
      <Hero />
      <Features />
      <HowItWorks />
      <Pricing />
      <Faq />
      <CallToAction />
    </>
  );
}
