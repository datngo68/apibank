import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableEmpty,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { adminEndpoints, type AdminRevenuePoint } from "@/lib/api";
import { formatVnd, formatDateTime } from "@/lib/utils";

export function AdminRevenuePage() {
  const [days, setDays] = useState(30);

  const summary = useQuery({
    queryKey: ["admin", "revenue", "summary"],
    queryFn: async () => (await adminEndpoints.revenueSummary()).data,
  });
  const series = useQuery({
    queryKey: ["admin", "revenue", "timeseries", days],
    queryFn: async () => (await adminEndpoints.revenueTimeseries(days)).data,
  });
  const byPlan = useQuery({
    queryKey: ["admin", "revenue", "by-plan", days],
    queryFn: async () => (await adminEndpoints.revenueByPlan(days)).data,
  });
  const byCoupon = useQuery({
    queryKey: ["admin", "revenue", "by-coupon", days],
    queryFn: async () => (await adminEndpoints.revenueByCoupon(days)).data,
  });
  const invoices = useQuery({
    queryKey: ["admin", "revenue", "invoices"],
    queryFn: async () =>
      (
        await adminEndpoints.listInvoices({ status: "paid", limit: 50 })
      ).data,
  });

  const cards = [
    {
      title: "Hôm nay",
      value: summary.data ? formatVnd(summary.data.today_vnd) : null,
      hint: "Doanh thu subscription",
    },
    {
      title: "Tháng này",
      value: summary.data ? formatVnd(summary.data.this_month_vnd) : null,
      hint: "Tính từ ngày 1",
    },
    {
      title: "30 ngày",
      value: summary.data ? formatVnd(summary.data.last_30d_vnd) : null,
      hint: summary.data
        ? `${summary.data.total_invoices_paid.toLocaleString("vi-VN")} hoá đơn paid`
        : "—",
    },
    {
      title: "MRR",
      value: summary.data ? formatVnd(summary.data.mrr_vnd) : null,
      hint: "Quy đổi 30 ngày từ subscription active",
    },
  ];

  const secondaryCards = [
    {
      title: "Topup 30d",
      value: summary.data ? formatVnd(summary.data.topup_vnd_30d) : null,
    },
    {
      title: "Refund 30d",
      value: summary.data ? formatVnd(summary.data.refund_vnd_30d) : null,
    },
    {
      title: "Discount 30d",
      value: summary.data ? formatVnd(summary.data.discount_vnd_30d) : null,
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Doanh thu</h1>
          <p className="text-sm text-muted-foreground">
            Tính từ Invoice (subscription) và WalletTransaction (topup/refund).
          </p>
        </div>
        <select
          className="flex h-9 rounded-md border border-input bg-background px-3 text-sm"
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
        >
          <option value={7}>7 ngày</option>
          <option value={30}>30 ngày</option>
          <option value={90}>90 ngày</option>
        </select>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {cards.map((c) => (
          <Card key={c.title}>
            <CardHeader className="pb-2">
              <CardDescription className="uppercase tracking-wider">
                {c.title}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {c.value === null ? (
                <Skeleton className="h-7 w-32" />
              ) : (
                <div className="text-2xl font-semibold tabular-nums">
                  {c.value}
                </div>
              )}
              <p className="mt-1 text-xs text-muted-foreground">{c.hint}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {secondaryCards.map((c) => (
          <Card key={c.title}>
            <CardHeader className="pb-2">
              <CardDescription className="uppercase tracking-wider">
                {c.title}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {c.value === null ? (
                <Skeleton className="h-7 w-32" />
              ) : (
                <div className="text-xl font-semibold tabular-nums">{c.value}</div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Doanh thu theo ngày</CardTitle>
          <CardDescription>
            Subscription + topup − refund = net theo từng ngày.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {series.isLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : (series.data?.points.length ?? 0) === 0 ? (
            <p className="text-sm text-muted-foreground">Chưa có dữ liệu.</p>
          ) : (
            <RevenueLineChart points={series.data?.points ?? []} />
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Theo plan</CardTitle>
            <CardDescription>{days} ngày gần nhất.</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Plan</TableHead>
                  <TableHead className="text-right">Hoá đơn</TableHead>
                  <TableHead className="text-right">Net</TableHead>
                  <TableHead className="text-right">Discount</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {byPlan.isLoading ? (
                  <TableRow>
                    <TableCell colSpan={4}>
                      <Skeleton className="h-6 w-full" />
                    </TableCell>
                  </TableRow>
                ) : (byPlan.data?.length ?? 0) === 0 ? (
                  <TableEmpty colSpan={4}>Chưa có doanh thu.</TableEmpty>
                ) : (
                  byPlan.data?.map((r) => (
                    <TableRow key={r.plan_code ?? "(none)"}>
                      <TableCell className="font-medium">
                        {r.plan_code ?? "(không gắn plan)"}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {r.invoices.toLocaleString("vi-VN")}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {formatVnd(r.net_vnd)}
                      </TableCell>
                      <TableCell className="text-right font-mono text-muted-foreground">
                        {formatVnd(r.discount_vnd)}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Theo coupon</CardTitle>
            <CardDescription>Coupon đang hot.</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Coupon</TableHead>
                  <TableHead className="text-right">Lượt dùng</TableHead>
                  <TableHead className="text-right">Discount</TableHead>
                  <TableHead className="text-right">Net</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {byCoupon.isLoading ? (
                  <TableRow>
                    <TableCell colSpan={4}>
                      <Skeleton className="h-6 w-full" />
                    </TableCell>
                  </TableRow>
                ) : (byCoupon.data?.length ?? 0) === 0 ? (
                  <TableEmpty colSpan={4}>Chưa có coupon nào áp dụng.</TableEmpty>
                ) : (
                  byCoupon.data?.map((r) => (
                    <TableRow key={r.coupon_code ?? "(none)"}>
                      <TableCell>
                        <Badge variant="muted">{r.coupon_code ?? "—"}</Badge>
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {r.redemptions.toLocaleString("vi-VN")}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        −{formatVnd(r.discount_vnd)}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {formatVnd(r.net_vnd)}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Hoá đơn gần nhất</CardTitle>
          <CardDescription>50 hoá đơn paid mới nhất.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>User</TableHead>
                <TableHead>Plan</TableHead>
                <TableHead>Coupon</TableHead>
                <TableHead className="text-right">Số tiền</TableHead>
                <TableHead className="text-right">Discount</TableHead>
                <TableHead>Thời gian</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {invoices.isLoading ? (
                <TableRow>
                  <TableCell colSpan={6}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              ) : (invoices.data?.items.length ?? 0) === 0 ? (
                <TableEmpty colSpan={6}>Chưa có hoá đơn.</TableEmpty>
              ) : (
                invoices.data?.items.map((inv) => (
                  <TableRow key={inv.id}>
                    <TableCell className="font-mono text-xs">
                      {inv.user_email ?? inv.user_id}
                    </TableCell>
                    <TableCell>{inv.plan_code ?? "—"}</TableCell>
                    <TableCell>
                      {inv.coupon_code ? (
                        <Badge variant="muted">{inv.coupon_code}</Badge>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      {formatVnd(inv.amount_vnd)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-muted-foreground">
                      {Number(inv.discount_vnd) > 0
                        ? `−${formatVnd(inv.discount_vnd)}`
                        : "—"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDateTime(inv.issued_at)}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function RevenueLineChart({ points }: { points: AdminRevenuePoint[] }) {
  if (points.length === 0) return null;
  const W = 800;
  const H = 200;
  const pad = 28;
  const xs = (i: number) =>
    pad + (i / Math.max(1, points.length - 1)) * (W - pad * 2);
  const max = Math.max(
    1,
    ...points.map((p) => Number(p.net_vnd) || 0),
    ...points.map((p) => Number(p.subscription_vnd) || 0),
    ...points.map((p) => Number(p.topup_vnd) || 0),
  );
  const ys = (v: number) => H - pad - ((H - pad * 2) * Math.max(0, v)) / max;

  const line = (key: keyof AdminRevenuePoint) =>
    points
      .map((p, i) => `${i === 0 ? "M" : "L"}${xs(i)},${ys(Number(p[key]) || 0)}`)
      .join(" ");

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height={H}
        role="img"
        aria-label="Biểu đồ doanh thu"
      >
        <line
          x1={pad}
          x2={W - pad}
          y1={H - pad}
          y2={H - pad}
          stroke="currentColor"
          strokeOpacity={0.2}
        />
        <path
          d={line("subscription_vnd")}
          fill="none"
          className="stroke-primary"
          strokeWidth={2}
        />
        <path
          d={line("topup_vnd")}
          fill="none"
          className="stroke-success"
          strokeWidth={2}
        />
        <path
          d={line("net_vnd")}
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeDasharray="4 4"
          opacity={0.6}
        />
        {points.map((p, i) => (
          <g key={p.day}>
            <circle
              cx={xs(i)}
              cy={ys(Number(p.net_vnd) || 0)}
              r={2}
              className="fill-foreground"
            >
              <title>{`${p.day}: subs ${formatVnd(p.subscription_vnd)} + topup ${formatVnd(p.topup_vnd)} − refund ${formatVnd(p.refund_vnd)} = ${formatVnd(p.net_vnd)}`}</title>
            </circle>
          </g>
        ))}
      </svg>
      <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-0.5 w-4 bg-primary" /> Subscription
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-0.5 w-4 bg-success" /> Topup
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-0.5 w-4 border-t border-dashed border-foreground" />
          Net
        </span>
      </div>
    </div>
  );
}
