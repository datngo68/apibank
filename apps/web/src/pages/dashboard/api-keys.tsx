import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Ban } from "lucide-react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
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
  DialogTrigger,
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { endpoints, toApiError, type MeApiKeyCreated } from "@/lib/api";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { formatDateTime, relativeTime } from "@/lib/utils";

const SCOPES = [
  "orders:write",
  "orders:read",
  "transactions:read",
  "webhooks:read",
];

const schema = z.object({
  name: z.string().min(1).max(255),
  scopes: z.array(z.string()).min(1, "Chọn ít nhất 1 scope"),
});

type FormValues = z.infer<typeof schema>;

export function ApiKeysPage() {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["api-keys"],
    queryFn: async () => (await endpoints.apiKeys()).data,
  });
  const [created, setCreated] = useState<MeApiKeyCreated | null>(null);

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">API keys</h1>
          <p className="text-sm text-muted-foreground">
            Sinh key để tích hợp shop của bạn. Key chỉ hiện 1 lần — hãy lưu lại ngay.{" "}
            <Link to="/app/docs#create-order" className="text-primary hover:underline">
              Xem hướng dẫn dùng API →
            </Link>
          </p>
        </div>
        <CreateDialog onCreated={(c) => {
          setCreated(c);
          qc.invalidateQueries({ queryKey: ["api-keys"] });
        }} />
      </div>

      {created ? <RevealOnce keyData={created} onClose={() => setCreated(null)} /> : null}

      <Card>
        <CardHeader>
          <CardTitle>Danh sách API key</CardTitle>
          <CardDescription>Last-used cập nhật khi key được dùng.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Tên</TableHead>
                <TableHead>Scopes</TableHead>
                <TableHead>Last used</TableHead>
                <TableHead>Tạo</TableHead>
                <TableHead className="text-right">Thao tác</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.isLoading ? (
                <TableRow>
                  <TableCell colSpan={5}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              ) : (list.data ?? []).length === 0 ? (
                <TableEmpty colSpan={5}>Chưa có key nào.</TableEmpty>
              ) : (
                list.data?.map((k) => (
                  <TableRow key={k.id}>
                    <TableCell className="font-medium">{k.name ?? "(không tên)"}</TableCell>
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
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDateTime(k.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <RevokeButton id={k.id} disabled={!!k.revoked_at} />
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

function RevokeButton({ id, disabled }: { id: string; disabled: boolean }) {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const revoke = useMutation({
    mutationFn: () => endpoints.revokeApiKey(id),
    onSuccess: () => {
      toast.success("Đã thu hồi");
      qc.invalidateQueries({ queryKey: ["api-keys"] });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });
  return (
    <Button
      size="sm"
      variant="ghost"
      disabled={disabled}
      loading={revoke.isPending}
      onClick={async () => {
        const ok = await confirm({
          title: "Thu hồi API key",
          description: "Mọi request dùng key này sẽ trả 401 ngay lập tức. Hành động không thể hoàn tác.",
          confirmText: "Thu hồi",
          variant: "destructive",
        });
        if (ok) revoke.mutate();
      }}
    >
      <Ban aria-hidden /> {disabled ? "Đã thu hồi" : "Thu hồi"}
    </Button>
  );
}

function CreateDialog({
  onCreated,
}: {
  onCreated: (k: MeApiKeyCreated) => void;
}) {
  const [open, setOpen] = useState(false);
  const { register, handleSubmit, reset, formState, setValue, watch } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { scopes: ["orders:write", "orders:read"] },
  });
  const scopes = watch("scopes");

  const create = useMutation({
    mutationFn: async (v: FormValues) =>
      (await endpoints.createApiKey({ name: v.name, scopes: v.scopes })).data,
    onSuccess: (data) => {
      toast.success("Đã tạo API key");
      reset();
      setOpen(false);
      onCreated(data);
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus aria-hidden /> Tạo API key
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Tạo API key</DialogTitle>
          <DialogDescription>Chọn scope phù hợp; tránh cấp quá rộng.</DialogDescription>
        </DialogHeader>
        <form id="apikey-form" onSubmit={handleSubmit((v) => create.mutate(v))} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="name">Tên</Label>
            <Input id="name" placeholder="Shop A" {...register("name")} invalid={!!formState.errors.name} />
          </div>
          <div className="space-y-2">
            <Label>Scopes</Label>
            <div className="grid grid-cols-2 gap-2">
              {SCOPES.map((s) => (
                <label key={s} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={scopes?.includes(s)}
                    onChange={(e) => {
                      const set = new Set(scopes ?? []);
                      if (e.target.checked) set.add(s);
                      else set.delete(s);
                      setValue("scopes", Array.from(set), { shouldValidate: true });
                    }}
                  />
                  <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{s}</code>
                </label>
              ))}
            </div>
            {formState.errors.scopes ? (
              <p className="text-xs text-destructive">{formState.errors.scopes.message as string}</p>
            ) : null}
          </div>
        </form>
        <DialogFooter>
          <Button type="submit" form="apikey-form" loading={create.isPending}>
            Tạo
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RevealOnce({ keyData, onClose }: { keyData: MeApiKeyCreated; onClose: () => void }) {
  const samples = {
    curl: `curl -X POST https://your-host/v1/orders \\
  -H "Authorization: Bearer ${keyData.raw_key}" \\
  -H "Idempotency-Key: $(uuidgen)" \\
  -H "Content-Type: application/json" \\
  -d '{"amount_vnd": 50000, "bank_account_id": "ba_xxx"}'`,
    node: `await fetch("https://your-host/v1/orders", {
  method: "POST",
  headers: {
    "Authorization": "Bearer ${keyData.raw_key}",
    "Idempotency-Key": crypto.randomUUID(),
    "Content-Type": "application/json"
  },
  body: JSON.stringify({ amount_vnd: 50000, bank_account_id: "ba_xxx" })
});`,
    python: `import httpx, uuid
httpx.post(
    "https://your-host/v1/orders",
    headers={
        "Authorization": "Bearer ${keyData.raw_key}",
        "Idempotency-Key": str(uuid.uuid4()),
    },
    json={"amount_vnd": 50000, "bank_account_id": "ba_xxx"},
)`,
  };
  return (
    <Alert variant="success">
      <AlertTitle className="flex items-center justify-between">
        <span>API key của bạn (chỉ hiện 1 lần)</span>
        <Button size="sm" variant="ghost" onClick={onClose}>
          Đã lưu
        </Button>
      </AlertTitle>
      <AlertDescription className="space-y-3">
        <div className="flex items-center gap-2 rounded-md border bg-background p-2 font-mono text-xs">
          <code className="flex-1 break-all">{keyData.raw_key}</code>
          <CopyButton value={keyData.raw_key} label="Copy key" />
        </div>
        <Tabs defaultValue="curl">
          <TabsList>
            <TabsTrigger value="curl">cURL</TabsTrigger>
            <TabsTrigger value="node">Node</TabsTrigger>
            <TabsTrigger value="python">Python</TabsTrigger>
          </TabsList>
          <TabsContent value="curl">
            <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">{samples.curl}</pre>
          </TabsContent>
          <TabsContent value="node">
            <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">{samples.node}</pre>
          </TabsContent>
          <TabsContent value="python">
            <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">{samples.python}</pre>
          </TabsContent>
        </Tabs>
      </AlertDescription>
    </Alert>
  );
}
