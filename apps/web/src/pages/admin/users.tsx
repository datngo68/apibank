import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Ban } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableEmpty,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  adminEndpoints,
  toApiError,
  type AdminApiKeyCreated,
  type AdminApiKeyRead,
  type AdminUserListItem,
  type AdminUserDetail as AdminUserDetailType,
} from "@/lib/api";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { formatVnd, formatDateTime, relativeTime } from "@/lib/utils";
import {
  AdminCreateApiKeyDialog,
  AdminRawKeyReveal,
} from "./api-keys";
import { UsageBarChart } from "./usage";

export function AdminUsersPage() {
  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<AdminUserListItem | null>(null);

  const list = useQuery({
    queryKey: ["admin", "users", { q, role, status }],
    queryFn: async () =>
      (
        await adminEndpoints.listUsers({
          q: q || undefined,
          role: role || undefined,
          status: status || undefined,
          limit: 100,
        })
      ).data,
  });

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Người dùng</h1>
        <p className="text-sm text-muted-foreground">
          Tìm kiếm, đổi role/status, nạp tiền vào ví, reset mật khẩu, tắt 2FA.
        </p>
      </div>

      <Card>
        <CardContent className="grid gap-3 pt-6 md:grid-cols-[1fr_auto_auto_auto]">
          <Input
            placeholder="Tìm theo email hoặc tên"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <select
            className="flex h-9 rounded-md border border-input bg-background px-3 text-sm"
            value={role}
            onChange={(e) => setRole(e.target.value)}
          >
            <option value="">Mọi role</option>
            <option value="user">user</option>
            <option value="admin">admin</option>
            <option value="owner">owner</option>
          </select>
          <select
            className="flex h-9 rounded-md border border-input bg-background px-3 text-sm"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="">Mọi status</option>
            <option value="active">active</option>
            <option value="suspended">suspended</option>
            <option value="banned">banned</option>
          </select>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{list.data?.total ?? 0} người dùng</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Email</TableHead>
                <TableHead>Tên</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Số dư</TableHead>
                <TableHead>Tạo</TableHead>
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
              ) : (list.data?.items?.length ?? 0) === 0 ? (
                <TableEmpty colSpan={7}>Không có user.</TableEmpty>
              ) : (
                list.data?.items.map((u) => (
                  <TableRow key={u.id}>
                    <TableCell className="font-mono text-xs">{u.email}</TableCell>
                    <TableCell>{u.full_name ?? "—"}</TableCell>
                    <TableCell>
                      <Badge variant={u.role === "admin" || u.role === "owner" ? "primary" : "muted"}>
                        {u.role}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={u.status === "active" ? "success" : "warning"}>
                        {u.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      {formatVnd(u.balance_vnd)}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDateTime(u.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" variant="ghost" onClick={() => setSelected(u)}>
                        Mở
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {selected ? (
        <UserDrawer userId={selected.id} onClose={() => setSelected(null)} />
      ) : null}
    </div>
  );
}

function UserDrawer({ userId, onClose }: { userId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const detail = useQuery({
    queryKey: ["admin", "users", userId],
    queryFn: async () => (await adminEndpoints.getUser(userId)).data,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["admin", "users"] });
  };

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{detail.data?.email ?? "Đang tải…"}</DialogTitle>
          <DialogDescription>
            ID: <code className="font-mono">{userId}</code>
          </DialogDescription>
        </DialogHeader>
        {detail.isLoading || !detail.data ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          <Tabs defaultValue="overview">
            <TabsList>
              <TabsTrigger value="overview">Tổng quan</TabsTrigger>
              <TabsTrigger value="wallet">Ví</TabsTrigger>
              <TabsTrigger value="api-keys">API keys</TabsTrigger>
              <TabsTrigger value="usage">Lượt request</TabsTrigger>
              <TabsTrigger value="security">Bảo mật</TabsTrigger>
            </TabsList>
            <TabsContent value="overview">
              <OverviewTab detail={detail.data} onChanged={() => { detail.refetch(); refresh(); }} />
            </TabsContent>
            <TabsContent value="wallet">
              <WalletTab userId={userId} detail={detail.data} onChanged={() => { detail.refetch(); refresh(); }} />
            </TabsContent>
            <TabsContent value="api-keys">
              <ApiKeysTab userId={userId} userEmail={detail.data.email} />
            </TabsContent>
            <TabsContent value="usage">
              <UsageTab userId={userId} />
            </TabsContent>
            <TabsContent value="security">
              <SecurityTab userId={userId} detail={detail.data} onChanged={() => detail.refetch()} />
            </TabsContent>
          </Tabs>
        )}
      </DialogContent>
    </Dialog>
  );
}

function OverviewTab({
  detail,
  onChanged,
}: {
  detail: AdminUserDetailType;
  onChanged: () => void;
}) {
  const update = useMutation({
    mutationFn: async (body: { role?: string; status?: string; full_name?: string }) =>
      (await adminEndpoints.updateUser(detail.id, body)).data,
    onSuccess: () => {
      toast.success("Đã cập nhật");
      onChanged();
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Stat label="Số dư ví" value={formatVnd(detail.balance_vnd)} mono />
      <Stat
        label="Subscription"
        value={detail.subscription?.plan_code ?? "—"}
        hint={detail.subscription ? `Hết hạn ${formatDateTime(detail.subscription.expires_at)}` : ""}
      />
      <Stat label="Đăng nhập gần nhất" value={detail.last_login_at ? formatDateTime(detail.last_login_at) : "—"} />
      <Stat label="2FA" value={detail.has_2fa ? "Đang bật" : "Tắt"} />
      <Stat label="Bank accounts" value={String(detail.bank_accounts_count)} />
      <Stat label="Sessions" value={String(detail.sessions_count)} />

      <div className="md:col-span-2 space-y-3 rounded-md border p-3">
        <div className="text-sm font-semibold">Thay đổi role / status</div>
        <div className="grid gap-3 md:grid-cols-3">
          <select
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
            defaultValue={detail.role}
            onChange={(e) => update.mutate({ role: e.target.value })}
          >
            <option value="user">user</option>
            <option value="admin">admin</option>
            <option value="owner">owner</option>
          </select>
          <select
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
            defaultValue={detail.status}
            onChange={(e) => update.mutate({ status: e.target.value })}
          >
            <option value="active">active</option>
            <option value="suspended">suspended</option>
            <option value="banned">banned</option>
          </select>
        </div>
      </div>
    </div>
  );
}

function WalletTab({
  userId,
  detail,
  onChanged,
}: {
  userId: string;
  detail: { recent_wallet_tx: Array<{ id: string; type: string; amount_vnd: string; balance_after: string; note: string | null; created_at: string }>; balance_vnd: string };
  onChanged: () => void;
}) {
  const qc = useQueryClient();
  const reload = () => {
    qc.invalidateQueries({ queryKey: ["admin", "users", userId] });
    onChanged();
  };

  return (
    <div className="space-y-4">
      <div className="rounded-md border bg-muted/30 px-3 py-2">
        <div className="text-xs uppercase text-muted-foreground">Số dư hiện tại</div>
        <div className="text-2xl font-semibold tabular-nums">{formatVnd(detail.balance_vnd)}</div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <WalletForm
          title="Credit (nạp tay)"
          description="Cộng tiền vào ví, type=topup"
          buttonLabel="Cộng vào ví"
          op={(amount, note) => adminEndpoints.walletCredit(userId, { amount_vnd: amount, note })}
          onDone={reload}
        />
        <WalletForm
          title="Refund"
          description="Hoàn tiền"
          buttonLabel="Hoàn tiền"
          op={(amount, note) => adminEndpoints.walletRefund(userId, { amount_vnd: amount, note })}
          onDone={reload}
        />
        <WalletForm
          title="Adjust (+/-)"
          description="Cho phép số âm (trừ tay)"
          buttonLabel="Điều chỉnh"
          allowNegative
          op={(amount, note) => adminEndpoints.walletAdjust(userId, { amount_vnd: amount, note })}
          onDone={reload}
        />
      </div>

      <div>
        <div className="mb-2 text-sm font-semibold">10 giao dịch ví gần nhất</div>
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Type</TableHead>
                <TableHead className="text-right">Amount</TableHead>
                <TableHead className="text-right">Sau</TableHead>
                <TableHead>Note</TableHead>
                <TableHead>Thời gian</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {detail.recent_wallet_tx.length === 0 ? (
                <TableEmpty colSpan={5}>Chưa có giao dịch.</TableEmpty>
              ) : (
                detail.recent_wallet_tx.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell>
                      <Badge variant="muted">{t.type}</Badge>
                    </TableCell>
                    <TableCell
                      className={`text-right font-mono ${
                        Number(t.amount_vnd) >= 0 ? "text-success" : "text-destructive"
                      }`}
                    >
                      {Number(t.amount_vnd) >= 0 ? "+" : ""}
                      {formatVnd(t.amount_vnd)}
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      {formatVnd(t.balance_after)}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {t.note ?? "—"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDateTime(t.created_at)}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  );
}

function WalletForm({
  title,
  description,
  buttonLabel,
  allowNegative,
  op,
  onDone,
}: {
  title: string;
  description: string;
  buttonLabel: string;
  allowNegative?: boolean;
  op: (amount: number, note: string) => Promise<unknown>;
  onDone: () => void;
}) {
  const [amount, setAmount] = useState<number>(50_000);
  const [note, setNote] = useState("");
  const m = useMutation({
    mutationFn: async () => op(amount, note),
    onSuccess: () => {
      toast.success(`${title}: thành công`);
      setAmount(50_000);
      setNote("");
      onDone();
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  return (
    <div className="space-y-2 rounded-md border p-3">
      <div className="text-sm font-semibold">{title}</div>
      <p className="text-xs text-muted-foreground">{description}</p>
      <div className="space-y-1.5">
        <Label htmlFor={`amount-${title}`}>Số tiền (VND)</Label>
        <Input
          id={`amount-${title}`}
          type="number"
          min={allowNegative ? undefined : 1}
          value={amount}
          onChange={(e) => setAmount(Number(e.target.value))}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor={`note-${title}`}>Ghi chú</Label>
        <Input
          id={`note-${title}`}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="VD: nạp tay theo chuyển khoản #..."
        />
      </div>
      <Button size="sm" className="w-full" loading={m.isPending} onClick={() => m.mutate()}>
        {buttonLabel}
      </Button>
    </div>
  );
}

function SecurityTab({
  userId,
  detail,
  onChanged,
}: {
  userId: string;
  detail: { has_2fa: boolean; email: string };
  onChanged: () => void;
}) {
  const confirm = useConfirm();
  const reset = useMutation({
    mutationFn: async () => (await adminEndpoints.resetPassword(userId)).data,
    onSuccess: () => toast.success("Đã gửi email reset mật khẩu"),
    onError: (err) => toast.error(toApiError(err).detail),
  });
  const disable2fa = useMutation({
    mutationFn: async () => (await adminEndpoints.disable2fa(userId)).data,
    onSuccess: () => {
      toast.success("Đã tắt 2FA");
      onChanged();
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  return (
    <div className="space-y-3">
      <div className="rounded-md border p-3">
        <div className="text-sm font-semibold">Đặt lại mật khẩu</div>
        <p className="text-xs text-muted-foreground">
          Gửi email kèm token reset (1h) tới {detail.email}.
        </p>
        <Button
          size="sm"
          className="mt-2"
          loading={reset.isPending}
          onClick={() => reset.mutate()}
        >
          Gửi email reset
        </Button>
      </div>
      <div className="rounded-md border p-3">
        <div className="text-sm font-semibold">2FA</div>
        <p className="text-xs text-muted-foreground">
          {detail.has_2fa
            ? "User đang dùng 2FA. Tắt khi user mất authenticator (cẩn trọng)."
            : "User chưa bật 2FA."}
        </p>
        <Button
          size="sm"
          variant="destructive"
          className="mt-2"
          disabled={!detail.has_2fa}
          loading={disable2fa.isPending}
          onClick={async () => {
            const ok = await confirm({
              title: "Tắt 2FA",
              description: `Tắt 2FA cho ${detail.email}. Chỉ làm khi user mất authenticator. User cần bật lại 2FA sau khi đăng nhập.`,
              confirmText: "Tắt 2FA",
              variant: "destructive",
            });
            if (ok) disable2fa.mutate();
          }}
        >
          Tắt 2FA
        </Button>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
  mono,
}: {
  label: string;
  value: string;
  hint?: string;
  mono?: boolean;
}) {
  return (
    <div className="rounded-md border bg-muted/30 px-3 py-2">
      <div className="text-xs uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className={`text-base ${mono ? "font-mono" : ""}`}>{value}</div>
      {hint ? <div className="text-xs text-muted-foreground">{hint}</div> : null}
    </div>
  );
}

function ApiKeysTab({
  userId,
  userEmail,
}: {
  userId: string;
  userEmail: string;
}) {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const [open, setOpen] = useState(false);
  const [created, setCreated] = useState<AdminApiKeyCreated | null>(null);

  const list = useQuery({
    queryKey: ["admin", "users", userId, "api-keys"],
    queryFn: async () =>
      (await adminEndpoints.listUserApiKeys(userId)).data,
  });
  const revoke = useMutation({
    mutationFn: (id: string) => adminEndpoints.revokeApiKey(id),
    onSuccess: () => {
      toast.success("Đã thu hồi");
      qc.invalidateQueries({ queryKey: ["admin", "users", userId, "api-keys"] });
      qc.invalidateQueries({ queryKey: ["admin", "api-keys"] });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          API key user dùng để gọi /v1/*. Tạo hộ chỉ khi user mất key gốc.
        </p>
        <Button size="sm" onClick={() => setOpen(true)}>
          <Plus aria-hidden /> Tạo key
        </Button>
      </div>

      {created ? (
        <AdminRawKeyReveal
          keyData={created}
          onClose={() => setCreated(null)}
        />
      ) : null}

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Tên</TableHead>
              <TableHead>Scopes</TableHead>
              <TableHead>Last used</TableHead>
              <TableHead>Trạng thái</TableHead>
              <TableHead>Tạo</TableHead>
              <TableHead className="text-right">Thao tác</TableHead>
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
              <TableEmpty colSpan={6}>User chưa có API key.</TableEmpty>
            ) : (
              list.data?.map((k: AdminApiKeyRead) => (
                <TableRow key={k.id}>
                  <TableCell>{k.name ?? "(không tên)"}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {k.scopes.map((s) => (
                        <Badge key={s} variant="muted">
                          {s}
                        </Badge>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {k.last_used_at ? relativeTime(k.last_used_at) : "Chưa dùng"}
                  </TableCell>
                  <TableCell>
                    {k.revoked_at ? (
                      <Badge variant="warning">đã thu hồi</Badge>
                    ) : (
                      <Badge variant="success">active</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {formatDateTime(k.created_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={!!k.revoked_at}
                      loading={revoke.isPending && revoke.variables === k.id}
                      onClick={async () => {
                        const ok = await confirm({
                          title: "Thu hồi API key",
                          description: `Mọi request dùng "${k.name ?? k.id}" sẽ bị 401.`,
                          confirmText: "Thu hồi",
                          variant: "destructive",
                        });
                        if (ok) revoke.mutate(k.id);
                      }}
                    >
                      <Ban aria-hidden /> Thu hồi
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <AdminCreateApiKeyDialog
        userId={userId}
        userEmail={userEmail}
        open={open}
        onOpenChange={setOpen}
        onCreated={(c) => {
          setCreated(c);
          setOpen(false);
          qc.invalidateQueries({
            queryKey: ["admin", "users", userId, "api-keys"],
          });
          qc.invalidateQueries({ queryKey: ["admin", "api-keys"] });
        }}
      />
    </div>
  );
}

function UsageTab({ userId }: { userId: string }) {
  const usage = useQuery({
    queryKey: ["admin", "users", userId, "usage"],
    queryFn: async () => (await adminEndpoints.userUsage(userId, 30)).data,
  });

  if (usage.isLoading) {
    return <Skeleton className="h-40 w-full" />;
  }
  if (!usage.data) {
    return <p className="text-sm text-muted-foreground">Chưa có dữ liệu.</p>;
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-3">
        <Stat
          label="Tổng request 30d"
          value={usage.data.total_count.toLocaleString("vi-VN")}
          mono
        />
        <Stat
          label="Lỗi 30d"
          value={usage.data.total_errors.toLocaleString("vi-VN")}
          mono
        />
        <Stat
          label="Số API key đã dùng"
          value={String(usage.data.by_api_key.length)}
        />
      </div>
      <div className="rounded-md border p-3">
        <div className="mb-2 text-sm font-semibold">Request theo ngày</div>
        <UsageBarChart points={usage.data.points} />
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-md border">
          <div className="border-b px-3 py-2 text-sm font-semibold">
            Theo API key
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Key</TableHead>
                <TableHead className="text-right">Request</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {usage.data.by_api_key.length === 0 ? (
                <TableEmpty colSpan={2}>Không có dữ liệu.</TableEmpty>
              ) : (
                usage.data.by_api_key.map((r) => (
                  <TableRow key={r.api_key_id}>
                    <TableCell className="text-xs">
                      {r.name ?? r.api_key_id}
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      {r.count.toLocaleString("vi-VN")}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
        <div className="rounded-md border">
          <div className="border-b px-3 py-2 text-sm font-semibold">
            Theo endpoint
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Endpoint</TableHead>
                <TableHead className="text-right">Request</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {usage.data.by_endpoint.length === 0 ? (
                <TableEmpty colSpan={2}>Không có dữ liệu.</TableEmpty>
              ) : (
                usage.data.by_endpoint.map((r) => (
                  <TableRow key={r.endpoint_group}>
                    <TableCell>
                      <code className="text-xs">{r.endpoint_group}</code>
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      {r.count.toLocaleString("vi-VN")}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  );
}
