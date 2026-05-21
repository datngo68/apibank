import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Ban, Plus } from "lucide-react";
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
import { CopyButton } from "@/components/ui/copy-button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import {
  adminEndpoints,
  toApiError,
  type AdminApiKeyCreated,
  type AdminApiKeyRead,
} from "@/lib/api";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { formatDateTime, relativeTime } from "@/lib/utils";

const SCOPES = [
  "orders:write",
  "orders:read",
  "transactions:read",
  "bank_accounts:read",
  "webhooks:read",
];

export function AdminApiKeysPage() {
  const [q, setQ] = useState("");
  const [revoked, setRevoked] = useState<"all" | "active" | "revoked">("active");

  const list = useQuery({
    queryKey: ["admin", "api-keys", { q, revoked }],
    queryFn: async () =>
      (
        await adminEndpoints.listApiKeys({
          q: q || undefined,
          revoked:
            revoked === "all" ? undefined : revoked === "revoked",
          limit: 200,
        })
      ).data,
  });

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">API keys</h1>
        <p className="text-sm text-muted-foreground">
          Toàn bộ API key trong hệ thống. Có thể thu hồi ngay khi nghi rò rỉ.
        </p>
      </div>

      <Card>
        <CardContent className="grid gap-3 pt-6 md:grid-cols-[1fr_auto]">
          <Input
            placeholder="Tìm theo email user hoặc tên key"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <select
            className="flex h-9 rounded-md border border-input bg-background px-3 text-sm"
            value={revoked}
            onChange={(e) =>
              setRevoked(e.target.value as "all" | "active" | "revoked")
            }
          >
            <option value="active">Đang hoạt động</option>
            <option value="revoked">Đã thu hồi</option>
            <option value="all">Tất cả</option>
          </select>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{list.data?.total ?? 0} API key</CardTitle>
          <CardDescription>
            Sắp theo thời gian tạo mới nhất.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>User</TableHead>
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
                  <TableCell colSpan={7}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              ) : (list.data?.items?.length ?? 0) === 0 ? (
                <TableEmpty colSpan={7}>Không có key nào.</TableEmpty>
              ) : (
                list.data?.items.map((k) => (
                  <ApiKeyRow key={k.id} keyData={k} />
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function ApiKeyRow({ keyData: k }: { keyData: AdminApiKeyRead }) {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const revoke = useMutation({
    mutationFn: () => adminEndpoints.revokeApiKey(k.id),
    onSuccess: () => {
      toast.success("Đã thu hồi");
      qc.invalidateQueries({ queryKey: ["admin", "api-keys"] });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });
  return (
    <TableRow>
      <TableCell className="font-mono text-xs">
        {k.user_email ?? k.user_id ?? "—"}
      </TableCell>
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
          loading={revoke.isPending}
          onClick={async () => {
            const ok = await confirm({
              title: "Thu hồi API key",
              description: `Mọi request dùng key "${k.name ?? k.id}" sẽ trả 401 ngay lập tức.`,
              confirmText: "Thu hồi",
              variant: "destructive",
            });
            if (ok) revoke.mutate();
          }}
        >
          <Ban aria-hidden /> {k.revoked_at ? "Đã thu hồi" : "Thu hồi"}
        </Button>
      </TableCell>
    </TableRow>
  );
}

/** Dialog tạo key hộ user (export để UserDrawer dùng lại). */
export function AdminCreateApiKeyDialog({
  userId,
  userEmail,
  open,
  onOpenChange,
  onCreated,
}: {
  userId: string;
  userEmail: string;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onCreated: (k: AdminApiKeyCreated) => void;
}) {
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>([
    "orders:write",
    "orders:read",
  ]);

  const create = useMutation({
    mutationFn: async () =>
      (
        await adminEndpoints.createUserApiKey(userId, { name, scopes })
      ).data,
    onSuccess: (data) => {
      toast.success("Đã tạo API key");
      onCreated(data);
      setName("");
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Tạo API key cho {userEmail}</DialogTitle>
          <DialogDescription>
            Key chỉ hiện 1 lần — copy và gửi cho user qua kênh bảo mật.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="admin-key-name">Tên key</Label>
            <Input
              id="admin-key-name"
              placeholder="VD: Restored after rotation"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label>Scopes</Label>
            <div className="grid grid-cols-2 gap-2">
              {SCOPES.map((s) => (
                <label key={s} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={scopes.includes(s)}
                    onChange={(e) => {
                      const set = new Set(scopes);
                      if (e.target.checked) set.add(s);
                      else set.delete(s);
                      setScopes(Array.from(set));
                    }}
                  />
                  <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
                    {s}
                  </code>
                </label>
              ))}
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button
            type="button"
            loading={create.isPending}
            disabled={!name || scopes.length === 0}
            onClick={() => create.mutate()}
          >
            <Plus aria-hidden /> Tạo
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Alert hiện raw key sau khi tạo. Dùng chung cho admin pages + UserDrawer. */
export function AdminRawKeyReveal({
  keyData,
  onClose,
}: {
  keyData: AdminApiKeyCreated;
  onClose: () => void;
}) {
  return (
    <Alert variant="success">
      <AlertTitle className="flex items-center justify-between">
        <span>API key (chỉ hiện 1 lần)</span>
        <Button size="sm" variant="ghost" onClick={onClose}>
          Đã lưu
        </Button>
      </AlertTitle>
      <AlertDescription>
        <div className="mt-2 flex items-center gap-2 rounded-md border bg-background p-2 font-mono text-xs">
          <code className="flex-1 break-all">{keyData.raw_key}</code>
          <CopyButton value={keyData.raw_key} label="Copy key" />
        </div>
      </AlertDescription>
    </Alert>
  );
}
