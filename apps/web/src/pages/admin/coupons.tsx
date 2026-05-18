import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import {
  adminEndpoints,
  toApiError,
  type AdminCoupon,
  type AdminCouponCreateInput,
  type AdminCouponUpdateInput,
  type AdminPlan,
} from "@/lib/api";
import { formatVnd, formatDateTime, relativeTime } from "@/lib/utils";

export function AdminCouponsPage() {
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<AdminCoupon | null>(null);
  const [redemptionsFor, setRedemptionsFor] = useState<AdminCoupon | null>(null);

  const list = useQuery({
    queryKey: ["admin", "coupons"],
    queryFn: async () => (await adminEndpoints.listCoupons()).data,
  });
  const plans = useQuery({
    queryKey: ["admin", "plans"],
    queryFn: async () => (await adminEndpoints.listPlans()).data,
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Mã giảm giá</h1>
          <p className="text-sm text-muted-foreground">
            Tạo mã giảm giá áp dụng khi user mua/đổi gói. Mã đã có người dùng nên
            tắt thay vì xóa để giữ audit.
          </p>
        </div>
        <Button onClick={() => setCreating(true)}>+ Tạo mã</Button>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Code</TableHead>
                <TableHead>Loại</TableHead>
                <TableHead className="text-right">Giá trị</TableHead>
                <TableHead className="text-right">Đã dùng</TableHead>
                <TableHead>Hiệu lực</TableHead>
                <TableHead>Plan áp dụng</TableHead>
                <TableHead>Active</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.isLoading ? (
                <TableRow>
                  <TableCell colSpan={8}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              ) : (list.data?.length ?? 0) === 0 ? (
                <TableEmpty colSpan={8}>Chưa có mã giảm giá nào.</TableEmpty>
              ) : (
                list.data?.map((c) => (
                  <TableRow key={c.id}>
                    <TableCell className="font-mono text-xs">{c.code}</TableCell>
                    <TableCell>
                      <Badge variant="muted">{c.discount_type}</Badge>
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      {formatDiscount(c)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {c.redeemed_count}
                      {c.max_redemptions != null ? `/${c.max_redemptions}` : ""}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatRange(c.valid_from, c.valid_until)}
                    </TableCell>
                    <TableCell className="text-xs">
                      {c.plan_codes_json.length === 0
                        ? "Tất cả"
                        : c.plan_codes_json.join(", ")}
                    </TableCell>
                    <TableCell>
                      <Badge variant={c.active ? "success" : "muted"}>
                        {c.active ? "active" : "off"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setRedemptionsFor(c)}
                      >
                        Lượt dùng
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setEditing(c)}>
                        Sửa
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {creating ? (
        <CouponFormDialog
          mode="create"
          plans={plans.data ?? []}
          onClose={() => setCreating(false)}
        />
      ) : null}
      {editing ? (
        <CouponFormDialog
          mode="edit"
          coupon={editing}
          plans={plans.data ?? []}
          onClose={() => setEditing(null)}
        />
      ) : null}
      {redemptionsFor ? (
        <RedemptionsDialog
          coupon={redemptionsFor}
          onClose={() => setRedemptionsFor(null)}
        />
      ) : null}
    </div>
  );
}

function formatDiscount(c: AdminCoupon): string {
  if (c.discount_type === "percent") {
    const cap = c.max_discount_vnd
      ? ` (tối đa ${formatVnd(c.max_discount_vnd)})`
      : "";
    return `-${c.percent_off ?? 0}%${cap}`;
  }
  return `-${formatVnd(c.amount_off_vnd ?? 0)}`;
}

function formatRange(from: string | null, until: string | null): string {
  if (!from && !until) return "Vô thời hạn";
  const f = from ? formatDateTime(from) : "—";
  const u = until ? formatDateTime(until) : "—";
  return `${f} → ${u}`;
}

interface FormState {
  code: string;
  description: string;
  discount_type: "percent" | "fixed";
  percent_off: number | "";
  amount_off_vnd: number | "";
  max_discount_vnd: number | "";
  min_amount_vnd: number | "";
  max_redemptions: number | "";
  max_per_user: number;
  valid_from: string;
  valid_until: string;
  plan_codes: string[];
  active: boolean;
}

function CouponFormDialog({
  mode,
  coupon,
  plans,
  onClose,
}: {
  mode: "create" | "edit";
  coupon?: AdminCoupon;
  plans: AdminPlan[];
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const [form, setForm] = useState<FormState>({
    code: coupon?.code ?? "",
    description: coupon?.description ?? "",
    discount_type: coupon?.discount_type ?? "percent",
    percent_off: coupon?.percent_off ?? 10,
    amount_off_vnd: coupon?.amount_off_vnd ? Number(coupon.amount_off_vnd) : "",
    max_discount_vnd: coupon?.max_discount_vnd
      ? Number(coupon.max_discount_vnd)
      : "",
    min_amount_vnd: coupon?.min_amount_vnd ? Number(coupon.min_amount_vnd) : "",
    max_redemptions: coupon?.max_redemptions ?? "",
    max_per_user: coupon?.max_per_user ?? 1,
    valid_from: toLocalInput(coupon?.valid_from),
    valid_until: toLocalInput(coupon?.valid_until),
    plan_codes: coupon?.plan_codes_json ?? [],
    active: coupon?.active ?? true,
  });

  const save = useMutation({
    mutationFn: async () => {
      if (mode === "create") {
        const body: AdminCouponCreateInput = {
          code: form.code.trim(),
          description: form.description || null,
          discount_type: form.discount_type,
          percent_off:
            form.discount_type === "percent"
              ? Number(form.percent_off || 0)
              : null,
          amount_off_vnd:
            form.discount_type === "fixed"
              ? Number(form.amount_off_vnd || 0)
              : null,
          max_discount_vnd:
            form.discount_type === "percent" && form.max_discount_vnd !== ""
              ? Number(form.max_discount_vnd)
              : null,
          min_amount_vnd:
            form.min_amount_vnd === "" ? null : Number(form.min_amount_vnd),
          max_redemptions:
            form.max_redemptions === "" ? null : Number(form.max_redemptions),
          max_per_user: form.max_per_user,
          valid_from: form.valid_from
            ? new Date(form.valid_from).toISOString()
            : null,
          valid_until: form.valid_until
            ? new Date(form.valid_until).toISOString()
            : null,
          plan_codes: form.plan_codes,
          active: form.active,
        };
        return (await adminEndpoints.createCoupon(body)).data;
      }
      const body: AdminCouponUpdateInput = {
        description: form.description || null,
        max_redemptions:
          form.max_redemptions === "" ? null : Number(form.max_redemptions),
        max_per_user: form.max_per_user,
        valid_from: form.valid_from
          ? new Date(form.valid_from).toISOString()
          : null,
        valid_until: form.valid_until
          ? new Date(form.valid_until).toISOString()
          : null,
        plan_codes: form.plan_codes,
        active: form.active,
      };
      return (await adminEndpoints.updateCoupon(coupon!.id, body)).data;
    },
    onSuccess: () => {
      toast.success(mode === "create" ? "Đã tạo mã" : "Đã cập nhật mã");
      qc.invalidateQueries({ queryKey: ["admin", "coupons"] });
      onClose();
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  const remove = useMutation({
    mutationFn: async () => (await adminEndpoints.deleteCoupon(coupon!.id)).data,
    onSuccess: () => {
      toast.success("Đã xoá mã");
      qc.invalidateQueries({ queryKey: ["admin", "coupons"] });
      onClose();
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  const isPercent = form.discount_type === "percent";
  const editOnlyHint = mode === "edit"
    ? "Loại/giá trị giảm và mã không đổi sau khi tạo. Có thể tắt để ngừng phát hành."
    : "Loại giảm giá và mã không thể đổi sau khi tạo.";

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {mode === "create" ? "Tạo mã giảm giá" : `Sửa mã ${coupon?.code}`}
          </DialogTitle>
          <DialogDescription>{editOnlyHint}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Mã (A-Z, 0-9, _ -)" colSpan={2}>
            <Input
              value={form.code}
              disabled={mode === "edit"}
              onChange={(e) =>
                setForm((f) => ({ ...f, code: e.target.value.toUpperCase() }))
              }
              placeholder="WELCOME10"
            />
          </Field>
          <Field label="Loại giảm">
            <select
              className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm disabled:opacity-50"
              value={form.discount_type}
              disabled={mode === "edit"}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  discount_type: e.target.value as "percent" | "fixed",
                }))
              }
            >
              <option value="percent">Phần trăm (%)</option>
              <option value="fixed">Số tiền cố định (VND)</option>
            </select>
          </Field>
          {isPercent ? (
            <>
              <Field label="Giảm (%)">
                <Input
                  type="number"
                  min={1}
                  max={100}
                  value={form.percent_off}
                  disabled={mode === "edit"}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      percent_off: numericOrEmpty(e.target.value),
                    }))
                  }
                />
              </Field>
              <Field label="Trần discount (VND, để trống = không trần)">
                <Input
                  type="number"
                  min={0}
                  value={form.max_discount_vnd}
                  disabled={mode === "edit"}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      max_discount_vnd: numericOrEmpty(e.target.value),
                    }))
                  }
                />
              </Field>
            </>
          ) : (
            <Field label="Giảm cố định (VND)">
              <Input
                type="number"
                min={1}
                value={form.amount_off_vnd}
                disabled={mode === "edit"}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    amount_off_vnd: numericOrEmpty(e.target.value),
                  }))
                }
              />
            </Field>
          )}
          <Field label="Đơn tối thiểu (VND, để trống = không yêu cầu)">
            <Input
              type="number"
              min={0}
              value={form.min_amount_vnd}
              disabled={mode === "edit"}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  min_amount_vnd: numericOrEmpty(e.target.value),
                }))
              }
            />
          </Field>
          <Field label="Tổng lượt redeem (để trống = không giới hạn)">
            <Input
              type="number"
              min={1}
              value={form.max_redemptions}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  max_redemptions: numericOrEmpty(e.target.value),
                }))
              }
            />
          </Field>
          <Field label="Lượt mỗi user">
            <Input
              type="number"
              min={1}
              max={100}
              value={form.max_per_user}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  max_per_user: Math.max(1, Number(e.target.value || 1)),
                }))
              }
            />
          </Field>
          <Field label="Hiệu lực từ">
            <Input
              type="datetime-local"
              value={form.valid_from}
              onChange={(e) => setForm((f) => ({ ...f, valid_from: e.target.value }))}
            />
          </Field>
          <Field label="Hiệu lực đến">
            <Input
              type="datetime-local"
              value={form.valid_until}
              onChange={(e) =>
                setForm((f) => ({ ...f, valid_until: e.target.value }))
              }
            />
          </Field>
          <Field label="Active">
            <Switch
              checked={form.active}
              onCheckedChange={(v) => setForm((f) => ({ ...f, active: v }))}
            />
          </Field>
          <Field label="Mô tả ngắn" colSpan={2}>
            <Input
              value={form.description}
              onChange={(e) =>
                setForm((f) => ({ ...f, description: e.target.value }))
              }
              placeholder="Hiển thị nội bộ — user không thấy."
            />
          </Field>
          <Field label="Áp dụng cho plan (rỗng = mọi plan)" colSpan={2}>
            <PlanCheckboxes
              plans={plans}
              value={form.plan_codes}
              onChange={(codes) => setForm((f) => ({ ...f, plan_codes: codes }))}
            />
          </Field>
        </div>
        <DialogFooter className="gap-2">
          {mode === "edit" ? (
            <Button
              variant="ghost"
              onClick={async () => {
                const ok = await confirm({
                  title: "Xoá mã giảm giá",
                  description: `Mã ${coupon!.code} sẽ bị xoá vĩnh viễn. Nếu đã có người dùng, hãy chọn “tắt” thay vì xoá.`,
                  confirmText: "Xoá",
                  variant: "destructive",
                });
                if (ok) remove.mutate();
              }}
              disabled={remove.isPending}
            >
              Xoá
            </Button>
          ) : null}
          <Button onClick={() => save.mutate()} loading={save.isPending}>
            Lưu
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PlanCheckboxes({
  plans,
  value,
  onChange,
}: {
  plans: AdminPlan[];
  value: string[];
  onChange: (codes: string[]) => void;
}) {
  if (plans.length === 0) {
    return <p className="text-xs text-muted-foreground">Chưa có plan nào.</p>;
  }
  return (
    <div className="flex flex-wrap gap-3">
      {plans.map((p) => {
        const checked = value.includes(p.code);
        return (
          <label
            key={p.code}
            className="flex items-center gap-2 rounded-md border border-input px-3 py-1.5 text-sm"
          >
            <input
              type="checkbox"
              className="h-4 w-4"
              checked={checked}
              onChange={(e) => {
                if (e.target.checked) {
                  onChange([...value, p.code]);
                } else {
                  onChange(value.filter((c) => c !== p.code));
                }
              }}
            />
            <span className="font-mono text-xs">{p.code}</span>
            <span className="text-muted-foreground">{p.name}</span>
          </label>
        );
      })}
    </div>
  );
}

function RedemptionsDialog({
  coupon,
  onClose,
}: {
  coupon: AdminCoupon;
  onClose: () => void;
}) {
  const list = useQuery({
    queryKey: ["admin", "coupons", coupon.id, "redemptions"],
    queryFn: async () =>
      (await adminEndpoints.listCouponRedemptions(coupon.id, { limit: 200 })).data,
  });

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Lượt dùng — {coupon.code}</DialogTitle>
          <DialogDescription>
            Lịch sử user áp mã. Tối đa 200 dòng gần nhất.
          </DialogDescription>
        </DialogHeader>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Tổng quan</CardTitle>
            <CardDescription>
              Đã redeem {coupon.redeemed_count}
              {coupon.max_redemptions != null ? `/${coupon.max_redemptions}` : ""}
            </CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Thời gian</TableHead>
                  <TableHead>User</TableHead>
                  <TableHead>Plan</TableHead>
                  <TableHead className="text-right">Trước</TableHead>
                  <TableHead className="text-right">Discount</TableHead>
                  <TableHead className="text-right">Sau</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.isLoading ? (
                  <TableRow>
                    <TableCell colSpan={6}>
                      <Skeleton className="h-6 w-full" />
                    </TableCell>
                  </TableRow>
                ) : (list.data?.length ?? 0) === 0 ? (
                  <TableEmpty colSpan={6}>Chưa có ai dùng mã này.</TableEmpty>
                ) : (
                  list.data?.map((r) => (
                    <TableRow key={r.id}>
                      <TableCell className="text-xs text-muted-foreground">
                        <span title={formatDateTime(r.created_at)}>
                          {relativeTime(r.created_at)}
                        </span>
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {r.user_id.slice(0, 16)}…
                      </TableCell>
                      <TableCell className="text-xs">
                        {r.plan_code ?? "—"}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {formatVnd(r.amount_before_vnd)}
                      </TableCell>
                      <TableCell className="text-right font-mono text-emerald-600 dark:text-emerald-400">
                        −{formatVnd(r.discount_vnd)}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {formatVnd(r.amount_after_vnd)}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Đóng
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  label,
  children,
  colSpan,
}: {
  label: string;
  children: React.ReactNode;
  colSpan?: 1 | 2;
}) {
  return (
    <div className={`space-y-1.5 ${colSpan === 2 ? "md:col-span-2" : ""}`}>
      <Label>{label}</Label>
      {children}
    </div>
  );
}

function numericOrEmpty(raw: string): number | "" {
  if (raw === "") return "";
  const n = Number(raw);
  return Number.isFinite(n) ? n : "";
}

function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  // Convert ISO → "YYYY-MM-DDTHH:mm" theo timezone local cho <input type=datetime-local>.
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
