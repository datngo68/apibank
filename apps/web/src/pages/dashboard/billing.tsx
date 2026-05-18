import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CheckCircle2, TicketPercent, X } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
import { endpoints, toApiError, type CouponPreviewResponse } from "@/lib/api";
import { cn, formatVnd, formatDateTime } from "@/lib/utils";
import { AUTH_QUERY_KEY } from "@/lib/auth";

export function BillingPage() {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const [couponInput, setCouponInput] = useState("");
  const [appliedCoupon, setAppliedCoupon] = useState<CouponPreviewResponse | null>(
    null,
  );
  const [couponPlanCode, setCouponPlanCode] = useState<string | null>(null);

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
    mutationFn: async (planCode: string) => {
      const code =
        appliedCoupon && appliedCoupon.plan_code === planCode
          ? appliedCoupon.code
          : null;
      return (await endpoints.purchaseSubscription(planCode, code)).data;
    },
    onSuccess: () => {
      toast.success("Đã kích hoạt gói");
      qc.invalidateQueries({ queryKey: ["sub"] });
      qc.invalidateQueries({ queryKey: ["invoices"] });
      qc.invalidateQueries({ queryKey: ["wallet"] });
      qc.invalidateQueries({ queryKey: AUTH_QUERY_KEY });
      setAppliedCoupon(null);
      setCouponInput("");
      setCouponPlanCode(null);
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  const previewMutation = useMutation({
    mutationFn: async (vars: { code: string; plan_code: string }) =>
      (await endpoints.previewCoupon(vars.code, vars.plan_code)).data,
    onSuccess: (data) => {
      setAppliedCoupon(data);
      setCouponPlanCode(data.plan_code);
      toast.success(
        `Áp mã thành công cho gói ${data.plan_code}: -${formatVnd(data.discount_vnd)}`,
      );
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

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <TicketPercent className="size-4" /> Mã giảm giá
          </CardTitle>
          <CardDescription>
            Nhập mã rồi chọn gói muốn áp dụng. Mã sẽ được áp khi bấm "Mua bằng ví".
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Input
              className="max-w-xs"
              placeholder="Nhập mã, ví dụ WELCOME10"
              value={couponInput}
              onChange={(e) => setCouponInput(e.target.value.toUpperCase())}
              disabled={appliedCoupon !== null}
            />
            {appliedCoupon ? (
              <Button
                variant="ghost"
                onClick={() => {
                  setAppliedCoupon(null);
                  setCouponPlanCode(null);
                  setCouponInput("");
                }}
              >
                <X className="mr-1 size-4" /> Bỏ mã
              </Button>
            ) : (
              <PreviewButtons
                plans={plans.data ?? []}
                disabled={!couponInput.trim() || previewMutation.isPending}
                pendingFor={
                  previewMutation.isPending ? previewMutation.variables?.plan_code : undefined
                }
                onPreview={(planCode) =>
                  previewMutation.mutate({
                    code: couponInput.trim(),
                    plan_code: planCode,
                  })
                }
              />
            )}
          </div>
          {appliedCoupon ? (
            <div className="rounded-md border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-sm">
              Mã <strong>{appliedCoupon.code}</strong> áp dụng cho gói{" "}
              <strong>{appliedCoupon.plan_code}</strong> — giảm{" "}
              <strong>{formatVnd(appliedCoupon.discount_vnd)}</strong>, còn{" "}
              <strong>{formatVnd(appliedCoupon.final_amount_vnd)}</strong>.
            </div>
          ) : null}
        </CardContent>
      </Card>

      <div className="grid items-stretch gap-4 md:grid-cols-3">
        {plans.isLoading || !plans.data
          ? Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-72" />)
          : plans.data.map((plan) => {
              const couponMatches =
                appliedCoupon !== null && couponPlanCode === plan.code;
              const finalPrice = couponMatches
                ? Number(appliedCoupon!.final_amount_vnd)
                : Number(plan.price_vnd);
              return (
                <Card
                  key={plan.id}
                  className={cn(
                    "flex flex-col",
                    plan.features_json.popular && "border-primary",
                    couponMatches && "ring-2 ring-emerald-500/40",
                  )}
                >
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <CardTitle>{plan.name}</CardTitle>
                      {plan.features_json.popular ? (
                        <Badge variant="primary">Khuyên dùng</Badge>
                      ) : null}
                    </div>
                    <CardDescription>{plan.description}</CardDescription>
                  </CardHeader>
                  <CardContent className="flex flex-1 flex-col">
                    <div className="space-y-1">
                      {couponMatches ? (
                        <p className="text-sm text-muted-foreground line-through">
                          {formatVnd(plan.price_vnd)}
                        </p>
                      ) : null}
                      <p className="text-2xl font-semibold tabular-nums">
                        {formatVnd(finalPrice)}
                        <span className="ml-1 text-xs text-muted-foreground">
                          / {plan.duration_days}d
                        </span>
                      </p>
                      {couponMatches ? (
                        <p className="text-xs text-emerald-600 dark:text-emerald-400">
                          Đã áp mã {appliedCoupon!.code} (-
                          {formatVnd(appliedCoupon!.discount_vnd)})
                        </p>
                      ) : null}
                    </div>
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
                          description: `Số tiền ${formatVnd(finalPrice)} sẽ được trừ vào ví. Phần dư của gói hiện tại (nếu có) sẽ được hoàn lại theo tỉ lệ.`,
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
              );
            })}
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
                <TableHead>Mã giảm</TableHead>
                <TableHead>Trạng thái</TableHead>
                <TableHead>Phát hành</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {invoices.isLoading ? (
                <TableRow>
                  <TableCell colSpan={5}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              ) : (invoices.data?.length ?? 0) === 0 ? (
                <TableEmpty colSpan={5}>Chưa có hóa đơn.</TableEmpty>
              ) : (
                invoices.data?.map((inv) => (
                  <TableRow key={inv.id}>
                    <TableCell>{inv.plan_code ?? "—"}</TableCell>
                    <TableCell>
                      <div className="flex flex-col">
                        <span>{formatVnd(inv.amount_vnd)}</span>
                        {inv.original_amount_vnd ? (
                          <span className="text-xs text-muted-foreground line-through">
                            {formatVnd(inv.original_amount_vnd)}
                          </span>
                        ) : null}
                      </div>
                    </TableCell>
                    <TableCell className="text-xs">
                      {inv.coupon_code ? (
                        <Badge variant="muted">
                          {inv.coupon_code} (-{formatVnd(inv.discount_vnd ?? 0)})
                        </Badge>
                      ) : (
                        "—"
                      )}
                    </TableCell>
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

function PreviewButtons({
  plans,
  disabled,
  pendingFor,
  onPreview,
}: {
  plans: { code: string; name: string }[];
  disabled: boolean;
  pendingFor: string | undefined;
  onPreview: (planCode: string) => void;
}) {
  if (plans.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-xs text-muted-foreground">Áp cho:</span>
      {plans.map((p) => (
        <Button
          key={p.code}
          size="sm"
          variant="outline"
          loading={pendingFor === p.code}
          disabled={disabled}
          onClick={() => onPreview(p.code)}
        >
          {p.code}
        </Button>
      ))}
    </div>
  );
}
