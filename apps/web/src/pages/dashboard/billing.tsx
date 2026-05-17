import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CheckCircle2 } from "lucide-react";
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
import {
  Table,
  TableBody,
  TableCell,
  TableEmpty,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { endpoints, toApiError } from "@/lib/api";
import { cn, formatVnd, formatDateTime } from "@/lib/utils";
import { AUTH_QUERY_KEY } from "@/lib/auth";

export function BillingPage() {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const sub = useQuery({
    queryKey: ["sub"],
    queryFn: async () => (await endpoints.subscription()).data,
  });
  const plans = useQuery({
    queryKey: ["plans"],
    queryFn: async () => (await endpoints.plans()).data,
  });
  const invoices = useQuery({
    queryKey: ["invoices"],
    queryFn: async () => (await endpoints.invoices()).data,
  });
  const purchase = useMutation({
    mutationFn: async (planCode: string) => (await endpoints.purchaseSubscription(planCode)).data,
    onSuccess: () => {
      toast.success("Đã kích hoạt gói");
      qc.invalidateQueries({ queryKey: ["sub"] });
      qc.invalidateQueries({ queryKey: ["invoices"] });
      qc.invalidateQueries({ queryKey: ["wallet"] });
      qc.invalidateQueries({ queryKey: AUTH_QUERY_KEY });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Gói cước</h1>
        <p className="text-sm text-muted-foreground">
          Mua/đổi gói, xem hóa đơn. Phần dư của gói hiện tại sẽ được hoàn lại theo tỉ lệ khi đổi
          sang gói khác.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Gói hiện tại</CardTitle>
          <CardDescription>Áp dụng quota theo gói cho mọi API key.</CardDescription>
        </CardHeader>
        <CardContent>
          {sub.isLoading ? (
            <Skeleton className="h-12 w-72" />
          ) : sub.data ? (
            <div className="flex flex-wrap items-center gap-3">
              <Badge variant="success">{sub.data.plan_code ?? "active"}</Badge>
              <span className="text-sm">
                Hết hạn lúc <strong>{formatDateTime(sub.data.expires_at)}</strong>
              </span>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Bạn chưa kích hoạt gói nào.</p>
          )}
        </CardContent>
      </Card>

      <div className="grid items-stretch gap-4 md:grid-cols-3">
        {plans.isLoading || !plans.data
          ? Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-72" />)
          : plans.data.map((plan) => (
              <Card
                key={plan.id}
                className={cn("flex flex-col", plan.features_json.popular && "border-primary")}
              >
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle>{plan.name}</CardTitle>
                    {plan.features_json.popular ? <Badge variant="primary">Khuyên dùng</Badge> : null}
                  </div>
                  <CardDescription>{plan.description}</CardDescription>
                </CardHeader>
                <CardContent className="flex flex-1 flex-col">
                  <p className="text-2xl font-semibold tabular-nums">
                    {formatVnd(plan.price_vnd)}
                    <span className="ml-1 text-xs text-muted-foreground">
                      / {plan.duration_days}d
                    </span>
                  </p>
                  <ul className="mt-3 flex-1 space-y-1.5 text-sm">
                    {(plan.features_json.highlights ?? []).map((h) => (
                      <li key={h} className="flex items-start gap-2">
                        <CheckCircle2 className="mt-0.5 size-4 text-primary" aria-hidden /> {h}
                      </li>
                    ))}
                  </ul>
                  <Button
                    className="mt-4 w-full"
                    loading={purchase.isPending && purchase.variables === plan.code}
                    onClick={async () => {
                      const ok = await confirm({
                        title: `Mua gói ${plan.name}`,
                        description: `Số tiền ${formatVnd(plan.price_vnd)} sẽ được trừ vào ví. Phần dư của gói hiện tại (nếu có) sẽ được hoàn lại theo tỉ lệ.`,
                        confirmText: "Xác nhận mua",
                        variant: "primary",
                      });
                      if (ok) purchase.mutate(plan.code);
                    }}
                  >
                    Mua bằng ví
                  </Button>
                </CardContent>
              </Card>
            ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Lịch sử hóa đơn</CardTitle>
          <CardDescription>Mỗi lần mua/gia hạn tạo 1 invoice.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Plan</TableHead>
                <TableHead>Số tiền</TableHead>
                <TableHead>Trạng thái</TableHead>
                <TableHead>Phát hành</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {invoices.isLoading ? (
                <TableRow>
                  <TableCell colSpan={4}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              ) : (invoices.data?.length ?? 0) === 0 ? (
                <TableEmpty colSpan={4}>Chưa có hóa đơn.</TableEmpty>
              ) : (
                invoices.data?.map((inv) => (
                  <TableRow key={inv.id}>
                    <TableCell>{inv.plan_code ?? "—"}</TableCell>
                    <TableCell>{formatVnd(inv.amount_vnd)}</TableCell>
                    <TableCell>
                      <Badge variant={inv.status === "paid" ? "success" : "muted"}>
                        {inv.status}
                      </Badge>
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
