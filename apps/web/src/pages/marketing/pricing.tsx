import { Helmet } from "react-helmet-async";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Card, CardHeader, CardContent, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { CheckCircle2 } from "lucide-react";
import { endpoints } from "@/lib/api";
import { formatVnd } from "@/lib/utils";

export function PricingPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["plans"],
    queryFn: async () => (await endpoints.plans()).data,
  });
  return (
    <>
      <Helmet>
        <title>Bảng giá · APIBank</title>
      </Helmet>
      <section className="container py-14">
        <div className="mx-auto max-w-2xl text-center">
          <Badge variant="primary">Pricing</Badge>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight">
            Trả theo nhu cầu, không ràng buộc
          </h1>
          <p className="mt-3 text-muted-foreground">
            Mỗi gói đều bao gồm webhook, ví số dư, hỗ trợ Telegram. Có thể đổi gói bất cứ lúc nào,
            phần dư được hoàn lại ví theo tỉ lệ.
          </p>
        </div>
        <div className="mt-10 grid gap-4 md:grid-cols-3">
          {isLoading || !data
            ? Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-72" />)
            : data.map((plan) => (
                <Card key={plan.id} className={plan.features_json.popular ? "border-primary" : ""}>
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <CardTitle>{plan.name}</CardTitle>
                      {plan.features_json.popular ? (
                        <Badge variant="primary">Khuyên dùng</Badge>
                      ) : null}
                    </div>
                    <CardDescription>{plan.description}</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <p className="text-3xl font-semibold tracking-tight">
                      {formatVnd(plan.price_vnd)}
                      <span className="ml-1 text-sm text-muted-foreground">/ {plan.duration_days}d</span>
                    </p>
                    <ul className="mt-4 space-y-2 text-sm">
                      {(plan.features_json.highlights ?? []).map((h) => (
                        <li key={h} className="flex items-start gap-2">
                          <CheckCircle2 className="mt-0.5 size-4 text-primary" aria-hidden />
                          <span>{h}</span>
                        </li>
                      ))}
                    </ul>
                    <Button asChild className="mt-6 w-full">
                      <Link to="/register">Bắt đầu với {plan.name}</Link>
                    </Button>
                  </CardContent>
                </Card>
              ))}
        </div>
      </section>
    </>
  );
}
