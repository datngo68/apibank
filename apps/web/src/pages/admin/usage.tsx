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
import { adminEndpoints, type AdminUsageDailyPoint } from "@/lib/api";

export function AdminUsagePage() {
  const [days, setDays] = useState(30);

  const summary = useQuery({
    queryKey: ["admin", "usage", "summary", days],
    queryFn: async () => (await adminEndpoints.usageSummary(days)).data,
  });

  const series = useQuery({
    queryKey: ["admin", "usage", "timeseries", days],
    queryFn: async () =>
      (await adminEndpoints.usageTimeseries({ days })).data,
  });

  const cards = [
    {
      title: "Tổng request",
      value: summary.data ? summary.data.total_count.toLocaleString("vi-VN") : null,
      hint: `Trong ${days} ngày`,
    },
    {
      title: "Lỗi (≥400)",
      value: summary.data
        ? summary.data.total_errors.toLocaleString("vi-VN")
        : null,
      hint:
        summary.data && summary.data.total_count > 0
          ? `${(
              (summary.data.total_errors / summary.data.total_count) *
              100
            ).toFixed(2)}% tỉ lệ lỗi`
          : "—",
    },
    {
      title: "User active",
      value: summary.data ? String(summary.data.unique_users) : null,
      hint: `${summary.data?.unique_api_keys ?? 0} key đã gọi`,
    },
    {
      title: "Trung bình/ngày",
      value:
        summary.data && days > 0
          ? Math.round(summary.data.total_count / days).toLocaleString("vi-VN")
          : null,
      hint: "Request / ngày",
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Lượt request</h1>
          <p className="text-sm text-muted-foreground">
            Đếm theo ngày × user × API key × endpoint group. Cập nhật mỗi 60s.
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
                <div className="text-2xl font-semibold tabular-nums">{c.value}</div>
              )}
              <p className="mt-1 text-xs text-muted-foreground">{c.hint}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Request theo ngày</CardTitle>
          <CardDescription>Bar chart cuốn 90 ngày gần nhất.</CardDescription>
        </CardHeader>
        <CardContent>
          {series.isLoading ? (
            <Skeleton className="h-40 w-full" />
          ) : (series.data?.points.length ?? 0) === 0 ? (
            <p className="text-sm text-muted-foreground">Chưa có dữ liệu.</p>
          ) : (
            <UsageBarChart points={series.data?.points ?? []} />
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Top endpoint</CardTitle>
            <CardDescription>5 endpoint group nhiều request nhất.</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Endpoint</TableHead>
                  <TableHead className="text-right">Request</TableHead>
                  <TableHead className="text-right">Lỗi</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {summary.isLoading ? (
                  <TableRow>
                    <TableCell colSpan={3}>
                      <Skeleton className="h-6 w-full" />
                    </TableCell>
                  </TableRow>
                ) : (summary.data?.top_endpoints.length ?? 0) === 0 ? (
                  <TableEmpty colSpan={3}>Chưa có request.</TableEmpty>
                ) : (
                  summary.data?.top_endpoints.map((r) => (
                    <TableRow key={r.endpoint_group}>
                      <TableCell>
                        <code className="text-xs">{r.endpoint_group}</code>
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {r.count.toLocaleString("vi-VN")}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {r.error_count > 0 ? (
                          <Badge variant="warning">{r.error_count}</Badge>
                        ) : (
                          <span className="text-muted-foreground">0</span>
                        )}
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
            <CardTitle>Top user</CardTitle>
            <CardDescription>5 user gọi nhiều nhất.</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>User</TableHead>
                  <TableHead className="text-right">Request</TableHead>
                  <TableHead className="text-right">Lỗi</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {summary.isLoading ? (
                  <TableRow>
                    <TableCell colSpan={3}>
                      <Skeleton className="h-6 w-full" />
                    </TableCell>
                  </TableRow>
                ) : (summary.data?.top_users.length ?? 0) === 0 ? (
                  <TableEmpty colSpan={3}>Chưa có user nào.</TableEmpty>
                ) : (
                  summary.data?.top_users.map((r) => (
                    <TableRow key={r.user_id}>
                      <TableCell className="font-mono text-xs">
                        {r.user_email ?? r.user_id}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {r.count.toLocaleString("vi-VN")}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {r.error_count > 0 ? (
                          <Badge variant="warning">{r.error_count}</Badge>
                        ) : (
                          <span className="text-muted-foreground">0</span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

/** Lightweight inline SVG bar chart (không thêm dep). */
export function UsageBarChart({ points }: { points: AdminUsageDailyPoint[] }) {
  if (points.length === 0) return null;
  const max = Math.max(1, ...points.map((p) => p.count));
  const W = 800;
  const H = 160;
  const pad = 24;
  const barWidth = (W - pad * 2) / points.length;

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height={H}
        role="img"
        aria-label="Biểu đồ request theo ngày"
      >
        <line
          x1={pad}
          x2={W - pad}
          y1={H - pad}
          y2={H - pad}
          stroke="currentColor"
          strokeOpacity={0.2}
        />
        {points.map((p, i) => {
          const h = ((H - pad * 2) * p.count) / max;
          const x = pad + i * barWidth + barWidth * 0.15;
          const y = H - pad - h;
          const w = barWidth * 0.7;
          return (
            <g key={p.day}>
              <rect
                x={x}
                y={y}
                width={w}
                height={h}
                className="fill-primary"
              >
                <title>{`${p.day}: ${p.count.toLocaleString("vi-VN")} request, ${p.error_count} lỗi`}</title>
              </rect>
              {p.error_count > 0 ? (
                <rect
                  x={x}
                  y={y}
                  width={w}
                  height={Math.max(2, ((H - pad * 2) * p.error_count) / max)}
                  className="fill-destructive"
                  opacity={0.85}
                />
              ) : null}
            </g>
          );
        })}
      </svg>
      <div className="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1">
          <span className="inline-block size-2.5 rounded-sm bg-primary" />
          Request
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block size-2.5 rounded-sm bg-destructive" />
          Lỗi (≥400)
        </span>
      </div>
    </div>
  );
}
