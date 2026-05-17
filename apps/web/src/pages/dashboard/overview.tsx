import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { OrderStatusPill, TxStatePill } from "@/components/ui/status-pill";
import {
  Table,
  TableBody,
  TableCell,
  TableEmpty,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { CheckCircle2, Circle } from "lucide-react";
import { endpoints } from "@/lib/api";
import { formatVnd, formatDateTime, relativeTime } from "@/lib/utils";
import { useAuth } from "@/lib/auth";

export function OverviewPage() {
  const { data: auth } = useAuth();
  const banks = useQuery({ queryKey: ["banks"], queryFn: async () => (await endpoints.bankAccounts()).data });
  const wallet = useQuery({ queryKey: ["wallet"], queryFn: async () => (await endpoints.wallet()).data });
  const sub = useQuery({ queryKey: ["sub"], queryFn: async () => (await endpoints.subscription()).data });
  const apiKeys = useQuery({ queryKey: ["api-keys"], queryFn: async () => (await endpoints.apiKeys()).data });
  const orders = useQuery({ queryKey: ["orders-recent"], queryFn: async () => (await endpoints.orders()).data });
  const txs = useQuery({ queryKey: ["txs-recent"], queryFn: async () => (await endpoints.transactions()).data });

  const checklist = [
    { ok: (banks.data?.length ?? 0) > 0, label: "Thêm tài khoản ngân hàng", to: "/app/bank-accounts" },
    { ok: (wallet.data ? Number(wallet.data.balance_vnd) > 0 : false), label: "Nạp tiền vào ví", to: "/app/wallet" },
    { ok: !!sub.data, label: "Mua hoặc kích hoạt gói cước", to: "/app/billing" },
    { ok: (apiKeys.data?.length ?? 0) > 0, label: "Tạo API key đầu tiên", to: "/app/api-keys" },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Xin chào{auth?.user?.full_name ? `, ${auth.user.full_name}` : ""}
        </h1>
        <p className="text-sm text-muted-foreground">
          Tóm tắt hoạt động tài khoản APIBank của bạn.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Stat
          title="Số dư ví"
          value={wallet.isLoading ? null : formatVnd(wallet.data?.balance_vnd ?? 0)}
          hint={wallet.data ? `${wallet.data.pending_topups} đơn nạp đang chờ` : ""}
        />
        <Stat
          title="Gói hiện tại"
          value={sub.isLoading ? null : sub.data ? sub.data.plan_code ?? "—" : "Chưa có"}
          hint={
            sub.data?.expires_at ? `Hết hạn ${formatDateTime(sub.data.expires_at)}` : "Mua gói để dùng API"
          }
        />
        <Stat
          title="Tài khoản ngân hàng"
          value={banks.isLoading ? null : (banks.data?.length ?? 0).toString()}
          hint="Đang theo dõi"
        />
        <Stat
          title="API keys"
          value={apiKeys.isLoading ? null : (apiKeys.data?.length ?? 0).toString()}
          hint="Đã phát hành"
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Bắt đầu</CardTitle>
          <CardDescription>Hoàn thành 4 bước để hệ thống nhận tiền tự động.</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="grid gap-3 md:grid-cols-2">
            {checklist.map((item) => (
              <li
                key={item.label}
                className="flex items-center justify-between rounded-md border bg-background px-3 py-2"
              >
                <span className="flex items-center gap-2 text-sm">
                  {item.ok ? (
                    <CheckCircle2 className="size-4 text-success" aria-hidden />
                  ) : (
                    <Circle className="size-4 text-muted-foreground" aria-hidden />
                  )}
                  {item.label}
                </span>
                <Button asChild size="sm" variant={item.ok ? "ghost" : "outline"}>
                  <Link to={item.to}>{item.ok ? "Xem" : "Thực hiện"}</Link>
                </Button>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <div>
              <CardTitle>Đơn hàng gần đây</CardTitle>
              <CardDescription>10 đơn hàng tạo gần nhất.</CardDescription>
            </div>
            <Button asChild size="sm" variant="ghost">
              <Link to="/app/orders">Xem tất cả</Link>
            </Button>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Mã</TableHead>
                  <TableHead>Số tiền</TableHead>
                  <TableHead>Trạng thái</TableHead>
                  <TableHead>Tạo</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {orders.isLoading ? (
                  <TableRow>
                    <TableCell colSpan={4}>
                      <Skeleton className="h-6 w-full" />
                    </TableCell>
                  </TableRow>
                ) : (orders.data?.length ?? 0) === 0 ? (
                  <TableEmpty colSpan={4}>Chưa có đơn nào.</TableEmpty>
                ) : (
                  orders.data?.slice(0, 5).map((o) => (
                    <TableRow key={o.id}>
                      <TableCell className="font-mono text-xs">{o.code}</TableCell>
                      <TableCell>{formatVnd(o.amount_vnd)}</TableCell>
                      <TableCell>
                        <OrderStatusPill status={o.status} />
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {relativeTime(o.created_at)}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <div>
              <CardTitle>Giao dịch ngân hàng gần đây</CardTitle>
              <CardDescription>Cập nhật từ poller.</CardDescription>
            </div>
            <Button asChild size="sm" variant="ghost">
              <Link to="/app/transactions">Xem tất cả</Link>
            </Button>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Ref</TableHead>
                  <TableHead>Số tiền</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead>Thời gian</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {txs.isLoading ? (
                  <TableRow>
                    <TableCell colSpan={4}>
                      <Skeleton className="h-6 w-full" />
                    </TableCell>
                  </TableRow>
                ) : (txs.data?.length ?? 0) === 0 ? (
                  <TableEmpty colSpan={4}>Chưa có giao dịch.</TableEmpty>
                ) : (
                  txs.data?.slice(0, 5).map((tx) => (
                    <TableRow key={tx.id}>
                      <TableCell className="font-mono text-xs">{tx.bank_ref_no}</TableCell>
                      <TableCell>{formatVnd(tx.amount_vnd)}</TableCell>
                      <TableCell>
                        <TxStatePill state={tx.state} />
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {relativeTime(tx.posted_at)}
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

function Stat({
  title,
  value,
  hint,
}: {
  title: string;
  value: string | null;
  hint?: string;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription className="uppercase tracking-wider">{title}</CardDescription>
      </CardHeader>
      <CardContent>
        {value === null ? <Skeleton className="h-7 w-32" /> : <div className="text-2xl font-semibold tabular-nums">{value}</div>}
        {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
        {!value ? null : <Badge variant="muted" className="mt-2 hidden">{value}</Badge>}
      </CardContent>
    </Card>
  );
}
