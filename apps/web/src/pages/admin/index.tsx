import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableEmpty,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { adminEndpoints } from "@/lib/api";
import { formatVnd, formatDateTime, relativeTime } from "@/lib/utils";

export function AdminDashboardPage() {
  const stats = useQuery({
    queryKey: ["admin", "stats"],
    queryFn: async () => (await adminEndpoints.getStats()).data,
    refetchInterval: 30_000,
  });
  const audit = useQuery({
    queryKey: ["admin", "audit", "recent"],
    queryFn: async () =>
      (await adminEndpoints.listAudit({ limit: 10 })).data.items,
  });

  const cards = [
    {
      title: "Người dùng",
      value: stats.data ? `${stats.data.users_active}/${stats.data.users_total}` : null,
      hint: "active / tổng",
    },
    {
      title: "Đơn pending",
      value: stats.data ? String(stats.data.orders_pending) : null,
      hint: `${stats.data?.orders_paid_24h ?? 0} đơn paid trong 24h`,
    },
    {
      title: "Số dư hệ thống",
      value: stats.data ? formatVnd(stats.data.wallet_total_vnd) : null,
      hint: "tổng balance ví",
    },
    {
      title: "Subscription active",
      value: stats.data ? String(stats.data.subscriptions_active) : null,
      hint: `${stats.data?.bank_accounts ?? 0} bank account active`,
    },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Admin dashboard</h1>
        <p className="text-sm text-muted-foreground">
          Tổng quan hệ thống. Vào các trang con để vận hành.
        </p>
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
        <CardHeader className="flex-row items-center justify-between">
          <div>
            <CardTitle>Audit log gần đây</CardTitle>
            <CardDescription>10 thao tác mới nhất.</CardDescription>
          </div>
          <Link to="/app/admin/audit-log" className="text-sm text-primary hover:underline">
            Xem tất cả
          </Link>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Thời gian</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Actor</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>IP</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {audit.isLoading ? (
                <TableRow>
                  <TableCell colSpan={5}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              ) : (audit.data?.length ?? 0) === 0 ? (
                <TableEmpty colSpan={5}>Chưa có log nào.</TableEmpty>
              ) : (
                audit.data?.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell className="text-xs text-muted-foreground">
                      <span title={formatDateTime(a.created_at)}>
                        {relativeTime(a.created_at)}
                      </span>
                    </TableCell>
                    <TableCell>
                      <Badge variant="muted">{a.action}</Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs">{a.actor}</TableCell>
                    <TableCell className="text-xs">
                      {a.target_type}/{a.target_id.slice(0, 12)}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {a.ip ?? "—"}
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

export { AdminUsersPage } from "./users";
export { AdminPlansPage } from "./plans";
export { AdminBankAccountsPage } from "./bank-accounts";
export { AdminConfigPage } from "./config";
export { AdminAuditLogPage } from "./audit-log";
