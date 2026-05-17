import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, RefreshCw, Send, Trash2 } from "lucide-react";
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
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
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
import { endpoints, toApiError, type Webhook as WH } from "@/lib/api";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { formatDateTime, relativeTime } from "@/lib/utils";

const schema = z.object({
  name: z.string().max(255).optional().or(z.literal("")),
  url: z.string().url(),
  secret: z.string().min(16).max(128),
  events: z.string().optional().or(z.literal("")),
});

type FormValues = z.infer<typeof schema>;

export function WebhooksPage() {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["webhooks"],
    queryFn: async () => (await endpoints.webhooks()).data,
  });

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Webhooks</h1>
          <p className="text-sm text-muted-foreground">
            URL nhận sự kiện thanh toán. Mỗi request được ký HMAC SHA-256 với secret riêng.{" "}
            <Link to="/app/docs#webhooks" className="text-primary hover:underline">
              Xem hướng dẫn verify chữ ký →
            </Link>
          </p>
        </div>
        <CreateDialog onCreated={() => qc.invalidateQueries({ queryKey: ["webhooks"] })} />
      </div>
      <Alert variant="info">
        <AlertTitle>Cách hoạt động</AlertTitle>
        <AlertDescription className="text-sm">
          Khi tiền về và match đơn, hệ thống POST event{" "}
          <code className="font-mono">payment.succeeded</code> tới URL bên dưới với header{" "}
          <code className="font-mono">APIBank-Signature</code>. Endpoint của bạn cần verify
          HMAC trước khi tin payload và phản hồi 2xx trong 10 giây.{" "}
          <Link to="/app/docs#webhooks" className="text-primary hover:underline">
            Code mẫu Node/Python/PHP
          </Link>
          .
        </AlertDescription>
      </Alert>
      {list.isLoading ? (
        <Skeleton className="h-40" />
      ) : (list.data?.length ?? 0) === 0 ? (
        <EmptyState title="Chưa có webhook nào" description="Đăng ký URL để nhận sự kiện." />
      ) : (
        <div className="space-y-4">
          {list.data?.map((wh) => <WebhookRow key={wh.id} webhook={wh} />)}
        </div>
      )}
    </div>
  );
}

function WebhookRow({ webhook }: { webhook: WH }) {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const remove = useMutation({
    mutationFn: () => endpoints.deleteWebhook(webhook.id),
    onSuccess: () => {
      toast.success("Đã xoá webhook");
      qc.invalidateQueries({ queryKey: ["webhooks"] });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });
  const toggle = useMutation({
    mutationFn: () => endpoints.updateWebhook(webhook.id, { active: !webhook.active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["webhooks"] }),
    onError: (err) => toast.error(toApiError(err).detail),
  });
  const testPing = useMutation({
    mutationFn: async () => (await endpoints.webhookTest(webhook.id)).data,
    onSuccess: (res) => {
      if (res.delivered) {
        toast.success(`Test ping OK · HTTP ${res.status_code}`);
      } else {
        toast.error(
          `Test ping fail · ${res.status_code ?? res.error ?? "không phản hồi"}`,
        );
      }
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });
  const attempts = useQuery({
    queryKey: ["webhook-attempts", webhook.id],
    queryFn: async () => (await endpoints.webhookAttempts(webhook.id)).data,
  });
  const replay = useMutation({
    mutationFn: (attemptId: string) =>
      endpoints.replayWebhookAttempt(webhook.id, attemptId),
    onSuccess: () => {
      toast.success("Đã đưa vào hàng đợi gửi lại. Hệ thống sẽ retry trong vài giây.");
      qc.invalidateQueries({ queryKey: ["webhook-attempts", webhook.id] });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  const events = webhook.events_json?.events ?? [];

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="break-all text-base">
              {webhook.name || webhook.url}
            </CardTitle>
            <CardDescription className="break-all font-mono">{webhook.url}</CardDescription>
          </div>
          <div className="flex items-center gap-3">
            <Switch checked={webhook.active} onCheckedChange={() => toggle.mutate()} />
            <Button
              variant="ghost"
              size="sm"
              loading={testPing.isPending}
              onClick={() => testPing.mutate()}
            >
              <Send aria-hidden /> Gửi ping thử
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Xoá"
              onClick={async () => {
                const ok = await confirm({
                  title: "Xoá webhook",
                  description: `${webhook.name || webhook.url} sẽ bị xoá khỏi hệ thống. Hành động này không thể hoàn tác.`,
                  confirmText: "Xoá webhook",
                  variant: "destructive",
                });
                if (ok) remove.mutate();
              }}
            >
              <Trash2 aria-hidden />
            </Button>
          </div>
        </div>
        <div className="flex flex-wrap gap-2 pt-2 text-xs">
          {events.length === 0 ? (
            <Badge variant="muted">Tất cả sự kiện</Badge>
          ) : (
            events.map((e) => (
              <Badge key={e} variant="primary">
                {e}
              </Badge>
            ))
          )}
          <span className="ml-auto text-muted-foreground">
            Tạo {formatDateTime(webhook.created_at)}
          </span>
        </div>
      </CardHeader>
      <CardContent>
        <h4 className="text-sm font-semibold">Lần gửi gần đây</h4>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Thời gian</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>HTTP</TableHead>
              <TableHead>Lỗi</TableHead>
              <TableHead className="text-right">Hành động</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {attempts.isLoading ? (
              <TableRow>
                <TableCell colSpan={5}>
                  <Skeleton className="h-6 w-full" />
                </TableCell>
              </TableRow>
            ) : (attempts.data ?? []).length === 0 ? (
              <TableEmpty colSpan={5}>Chưa có lần gửi nào.</TableEmpty>
            ) : (
              attempts.data?.slice(0, 5).map((a: any) => (
                <TableRow key={a.id}>
                  <TableCell className="text-muted-foreground">
                    {a.sent_at ? relativeTime(a.sent_at) : relativeTime(a.next_run_at)}
                  </TableCell>
                  <TableCell>
                    <Badge variant={a.status === "delivered" ? "success" : a.status === "failed" ? "destructive" : "muted"}>
                      {a.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{a.last_status_code ?? "—"}</TableCell>
                  <TableCell className="max-w-[20ch] truncate text-xs text-muted-foreground">
                    {a.last_error ?? "—"}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      loading={replay.isPending && replay.variables === a.id}
                      disabled={a.status === "pending" || a.status === "dispatching"}
                      onClick={() => replay.mutate(a.id)}
                      title={
                        a.status === "pending" || a.status === "dispatching"
                          ? "Đang trong hàng đợi"
                          : "Gửi lại event này"
                      }
                    >
                      <RefreshCw aria-hidden /> Gửi lại
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function CreateDialog({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const { register, handleSubmit, reset, formState } = useForm<FormValues>({
    resolver: zodResolver(schema),
  });
  const create = useMutation({
    mutationFn: async (values: FormValues) => {
      const events = (values.events ?? "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      return (
        await endpoints.createWebhook({
          name: values.name || undefined,
          url: values.url,
          secret: values.secret,
          events,
        })
      ).data;
    },
    onSuccess: () => {
      toast.success("Đã thêm webhook");
      reset();
      setOpen(false);
      onCreated();
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus aria-hidden /> Thêm webhook
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Thêm webhook</DialogTitle>
          <DialogDescription>Sự kiện sẽ được ký HMAC SHA-256.</DialogDescription>
        </DialogHeader>
        <form id="webhook-form" onSubmit={handleSubmit((v) => create.mutate(v))} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="wh-name">Tên (tuỳ chọn)</Label>
            <Input id="wh-name" {...register("name")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="wh-url">URL</Label>
            <Input id="wh-url" placeholder="https://shop.example.com/hooks/apibank" {...register("url")} invalid={!!formState.errors.url} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="wh-secret">Secret (≥16 ký tự)</Label>
            <Input id="wh-secret" {...register("secret")} invalid={!!formState.errors.secret} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="wh-events">Events (cách nhau bởi dấu phẩy, để trống = tất cả)</Label>
            <Input id="wh-events" placeholder="order.paid, order.expired" {...register("events")} />
          </div>
        </form>
        <DialogFooter>
          <Button type="submit" form="webhook-form" loading={create.isPending}>
            Tạo
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
