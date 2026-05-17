import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Card,
  CardContent,
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
import { adminEndpoints, toApiError, type AdminPlan, type AdminPlanCreateInput } from "@/lib/api";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { formatVnd } from "@/lib/utils";

export function AdminPlansPage() {
  const [editing, setEditing] = useState<AdminPlan | null>(null);
  const [creating, setCreating] = useState(false);

  const list = useQuery({
    queryKey: ["admin", "plans"],
    queryFn: async () => (await adminEndpoints.listPlans()).data,
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Plans</h1>
          <p className="text-sm text-muted-foreground">
            Quản lý gói cước. Plan có user đang dùng nên dùng "deactivate" thay vì xóa cứng.
          </p>
        </div>
        <Button onClick={() => setCreating(true)}>+ Tạo plan</Button>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Code</TableHead>
                <TableHead>Tên</TableHead>
                <TableHead className="text-right">Giá</TableHead>
                <TableHead className="text-right">Days</TableHead>
                <TableHead className="text-right">Daily quota</TableHead>
                <TableHead>Active</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.isLoading ? (
                <TableRow>
                  <TableCell colSpan={7}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              ) : (list.data?.length ?? 0) === 0 ? (
                <TableEmpty colSpan={7}>Chưa có plan nào.</TableEmpty>
              ) : (
                list.data?.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-mono text-xs">{p.code}</TableCell>
                    <TableCell>{p.name}</TableCell>
                    <TableCell className="text-right font-mono">{formatVnd(p.price_vnd)}</TableCell>
                    <TableCell className="text-right">{p.duration_days}</TableCell>
                    <TableCell className="text-right">{p.daily_quota}</TableCell>
                    <TableCell>
                      <Badge variant={p.active ? "success" : "muted"}>
                        {p.active ? "active" : "off"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" variant="ghost" onClick={() => setEditing(p)}>
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
        <PlanFormDialog mode="create" onClose={() => setCreating(false)} />
      ) : null}
      {editing ? (
        <PlanFormDialog mode="edit" plan={editing} onClose={() => setEditing(null)} />
      ) : null}
    </div>
  );
}

function PlanFormDialog({
  mode,
  plan,
  onClose,
}: {
  mode: "create" | "edit";
  plan?: AdminPlan;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const [form, setForm] = useState<AdminPlanCreateInput>({
    code: plan?.code ?? "",
    name: plan?.name ?? "",
    description: plan?.description ?? "",
    price_vnd: plan ? Number(plan.price_vnd) : 0,
    duration_days: plan?.duration_days ?? 30,
    daily_quota: plan?.daily_quota ?? 0,
    monthly_quota: plan?.monthly_quota ?? 0,
    sort_order: plan?.sort_order ?? 0,
    active: plan?.active ?? true,
    features_json: plan?.features_json ?? {},
  });
  const [highlightsText, setHighlightsText] = useState(
    (plan?.features_json?.highlights ?? []).join("\n"),
  );

  const save = useMutation({
    mutationFn: async () => {
      const features_json = {
        ...(form.features_json ?? {}),
        highlights: highlightsText
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean),
      };
      const body = { ...form, features_json };
      if (mode === "create") {
        return (await adminEndpoints.createPlan(body)).data;
      }
      return (await adminEndpoints.updatePlan(plan!.id, body)).data;
    },
    onSuccess: () => {
      toast.success(mode === "create" ? "Đã tạo plan" : "Đã cập nhật plan");
      qc.invalidateQueries({ queryKey: ["admin", "plans"] });
      onClose();
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  const remove = useMutation({
    mutationFn: async () => (await adminEndpoints.deletePlan(plan!.id)).data,
    onSuccess: () => {
      toast.success("Đã deactivate plan");
      qc.invalidateQueries({ queryKey: ["admin", "plans"] });
      onClose();
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{mode === "create" ? "Tạo plan mới" : `Sửa plan ${plan?.code}`}</DialogTitle>
          <DialogDescription>Thay đổi áp dụng ngay khi lưu.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Code (a-z0-9-)" disabled={mode === "edit"}>
            <Input
              value={form.code}
              disabled={mode === "edit"}
              onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))}
            />
          </Field>
          <Field label="Tên hiển thị">
            <Input
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
          </Field>
          <Field label="Giá (VND)">
            <Input
              type="number"
              value={form.price_vnd}
              onChange={(e) => setForm((f) => ({ ...f, price_vnd: Number(e.target.value) }))}
            />
          </Field>
          <Field label="Thời hạn (ngày)">
            <Input
              type="number"
              min={1}
              value={form.duration_days}
              onChange={(e) => setForm((f) => ({ ...f, duration_days: Number(e.target.value) }))}
            />
          </Field>
          <Field label="Daily quota">
            <Input
              type="number"
              min={0}
              value={form.daily_quota ?? 0}
              onChange={(e) => setForm((f) => ({ ...f, daily_quota: Number(e.target.value) }))}
            />
          </Field>
          <Field label="Monthly quota">
            <Input
              type="number"
              min={0}
              value={form.monthly_quota ?? 0}
              onChange={(e) => setForm((f) => ({ ...f, monthly_quota: Number(e.target.value) }))}
            />
          </Field>
          <Field label="Sort order">
            <Input
              type="number"
              value={form.sort_order ?? 0}
              onChange={(e) => setForm((f) => ({ ...f, sort_order: Number(e.target.value) }))}
            />
          </Field>
          <Field label="Active">
            <Switch
              checked={form.active ?? true}
              onCheckedChange={(v) => setForm((f) => ({ ...f, active: v }))}
            />
          </Field>
          <Field label="Mô tả ngắn" colSpan={2}>
            <Input
              value={form.description ?? ""}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            />
          </Field>
          <Field label="Highlights (mỗi dòng 1 mục)" colSpan={2}>
            <textarea
              className="min-h-[100px] w-full rounded-md border border-input bg-background px-3 py-1 text-sm"
              value={highlightsText}
              onChange={(e) => setHighlightsText(e.target.value)}
            />
          </Field>
        </div>
        <DialogFooter className="gap-2">
          {mode === "edit" ? (
            <Button
              variant="ghost"
              onClick={async () => {
                const ok = await confirm({
                  title: "Deactivate plan",
                  description: `Plan ${plan!.name} sẽ bị ẩn khỏi danh sách mua. User đang dùng vẫn giữ subscription cho đến khi hết hạn.`,
                  confirmText: "Deactivate",
                  variant: "destructive",
                });
                if (ok) remove.mutate();
              }}
              disabled={remove.isPending}
            >
              Deactivate
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

function Field({
  label,
  children,
  colSpan,
  disabled,
}: {
  label: string;
  children: React.ReactNode;
  colSpan?: 1 | 2;
  disabled?: boolean;
}) {
  return (
    <div className={`space-y-1.5 ${colSpan === 2 ? "md:col-span-2" : ""}`}>
      <Label className={disabled ? "text-muted-foreground" : ""}>{label}</Label>
      {children}
    </div>
  );
}
