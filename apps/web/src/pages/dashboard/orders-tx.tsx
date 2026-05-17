import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { OrderStatusPill, TxStatePill } from "@/components/ui/status-pill";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableEmpty,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { endpoints } from "@/lib/api";
import { formatVnd, formatDateTime } from "@/lib/utils";

export function OrdersPage() {
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const orders = useQuery({
    queryKey: ["orders", statusFilter],
    queryFn: async () =>
      (await endpoints.orders(statusFilter ? { status: statusFilter } : undefined)).data,
  });
  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Đơn hàng</h1>
          <p className="text-sm text-muted-foreground">
            Tất cả đơn được tạo trên các tài khoản ngân hàng của bạn.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {(["pending", "paid", "expired", "canceled"] as const).map((s) => (
            <Button
              key={s}
              size="sm"
              variant={statusFilter === s ? "primary" : "outline"}
              onClick={() => setStatusFilter(statusFilter === s ? undefined : s)}
            >
              {s}
            </Button>
          ))}
        </div>
      </div>
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Mã</TableHead>
                <TableHead>Số tiền</TableHead>
                <TableHead>Trạng thái</TableHead>
                <TableHead>Ref</TableHead>
                <TableHead>Tạo</TableHead>
                <TableHead>Hết hạn</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {orders.isLoading ? (
                <TableRow>
                  <TableCell colSpan={6}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              ) : (orders.data?.length ?? 0) === 0 ? (
                <TableEmpty colSpan={6}>Chưa có đơn nào.</TableEmpty>
              ) : (
                orders.data?.map((o) => (
                  <TableRow key={o.id}>
                    <TableCell className="font-mono text-xs">{o.code}</TableCell>
                    <TableCell>{formatVnd(o.amount_vnd)}</TableCell>
                    <TableCell>
                      <OrderStatusPill status={o.status} />
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {o.customer_ref ?? "—"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDateTime(o.created_at)}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDateTime(o.expired_at)}
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

export function TransactionsPage() {
  const [stateFilter, setStateFilter] = useState<string | undefined>();
  const txs = useQuery({
    queryKey: ["txs", stateFilter],
    queryFn: async () =>
      (await endpoints.transactions(stateFilter ? { state: stateFilter } : undefined)).data,
  });
  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Giao dịch ngân hàng</h1>
          <p className="text-sm text-muted-foreground">
            Toàn bộ biến động số dư mà worker quan sát được.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {(["new", "matched", "review", "ignored"] as const).map((s) => (
            <Button
              key={s}
              size="sm"
              variant={stateFilter === s ? "primary" : "outline"}
              onClick={() => setStateFilter(stateFilter === s ? undefined : s)}
            >
              {s}
            </Button>
          ))}
        </div>
      </div>
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Bank Ref</TableHead>
                <TableHead>Số tiền</TableHead>
                <TableHead>Nội dung</TableHead>
                <TableHead>State</TableHead>
                <TableHead>Đơn match</TableHead>
                <TableHead>Posted</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {txs.isLoading ? (
                <TableRow>
                  <TableCell colSpan={6}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              ) : (txs.data?.length ?? 0) === 0 ? (
                <TableEmpty colSpan={6}>Chưa có giao dịch nào.</TableEmpty>
              ) : (
                txs.data?.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell className="font-mono text-xs">{t.bank_ref_no}</TableCell>
                    <TableCell>{formatVnd(t.amount_vnd)}</TableCell>
                    <TableCell className="max-w-[28ch] truncate text-xs">
                      {t.content}
                    </TableCell>
                    <TableCell>
                      <TxStatePill state={t.state} />
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {t.matched_order_id ? <Badge variant="success">{t.matched_order_id}</Badge> : "—"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDateTime(t.posted_at)}
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

// Suppress unused vars to satisfy strict mode
void useQueryClient;
void Card;
void CardContent;
void CardDescription;
void CardHeader;
void CardTitle;
void Input;
void Label;
