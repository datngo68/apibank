import { useEffect, useRef, useState } from "react";
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
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { CopyButton } from "@/components/ui/copy-button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  adminEndpoints,
  toApiError,
  type GoogleConfigUpdate,
  type SmtpConfigUpdate,
  type TelegramConfigUpdate,
} from "@/lib/api";

export function AdminConfigPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Cấu hình hệ thống</h1>
        <p className="text-sm text-muted-foreground">
          Các cấu hình ở đây áp dụng ngay sau khi lưu, không cần restart. Field nhạy cảm để trống = giữ nguyên.
        </p>
      </div>

      <SmtpSection />
      <GoogleSection />
      <TelegramSection />
    </div>
  );
}

// ---------------------------------------------------------------------------
// SMTP
// ---------------------------------------------------------------------------

function SmtpSection() {
  const qc = useQueryClient();
  const data = useQuery({
    queryKey: ["admin", "config", "smtp"],
    queryFn: async () => (await adminEndpoints.getSmtp()).data,
  });
  const [form, setForm] = useState<SmtpConfigUpdate>({
    host: "",
    port: 587,
    user: "",
    from_addr: "",
    use_tls: true,
    enabled: false,
    password: "",
  });

  useEffect(() => {
    if (!data.data) return;
    setForm((f) => ({
      ...f,
      host: data.data!.host,
      port: data.data!.port,
      user: data.data!.user,
      from_addr: data.data!.from_addr,
      use_tls: data.data!.use_tls,
      enabled: data.data!.enabled,
      password: "",
    }));
  }, [data.data]);

  const save = useMutation({
    mutationFn: async () => {
      const body: SmtpConfigUpdate = { ...form };
      if (!body.password) body.password = null;
      return (await adminEndpoints.saveSmtp(body)).data;
    },
    onSuccess: () => {
      toast.success("Đã lưu cấu hình SMTP");
      qc.invalidateQueries({ queryKey: ["admin", "config", "smtp"] });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  const test = useMutation({
    mutationFn: async (to: string) => (await adminEndpoints.testSmtp(to)).data,
    onSuccess: (res) => {
      if (res.ok) toast.success("Đã gửi email test thành công");
      else toast.error(`Gửi thất bại: ${res.error ?? "unknown"}`);
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>SMTP (gửi email)</CardTitle>
        <CardDescription>
          Gmail: bật 2FA → tạo App password 16 ký tự. Hoặc dùng SES/Mailgun/Resend.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {data.isLoading ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          <>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="SMTP host">
                <Input
                  value={form.host}
                  onChange={(e) => setForm((f) => ({ ...f, host: e.target.value }))}
                  placeholder="smtp.gmail.com"
                />
              </Field>
              <Field label="Port">
                <Input
                  type="number"
                  value={form.port}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, port: Number(e.target.value) || 587 }))
                  }
                />
              </Field>
              <Field label="User">
                <Input
                  value={form.user}
                  onChange={(e) => setForm((f) => ({ ...f, user: e.target.value }))}
                  placeholder="you@gmail.com"
                />
              </Field>
              <Field label="Pass / App password">
                <Input
                  type="password"
                  value={form.password ?? ""}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, password: e.target.value }))
                  }
                  placeholder={data.data?.password_set ? "Đã lưu (để trống nếu giữ nguyên)" : "16 ký tự"}
                />
              </Field>
              <Field label="From">
                <Input
                  value={form.from_addr}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, from_addr: e.target.value }))
                  }
                  placeholder="apibank@yourdomain.com"
                />
              </Field>
              <div className="flex items-end gap-3">
                <div className="flex items-center gap-2">
                  <Switch
                    checked={form.use_tls}
                    onCheckedChange={(v) => setForm((f) => ({ ...f, use_tls: v }))}
                  />
                  <span className="text-sm">Secure (TLS — bật khi port 465/587)</span>
                </div>
              </div>
              <div className="flex items-end gap-3">
                <div className="flex items-center gap-2">
                  <Switch
                    checked={form.enabled}
                    onCheckedChange={(v) => setForm((f) => ({ ...f, enabled: v }))}
                  />
                  <span className="text-sm">Bật gửi qua SMTP</span>
                </div>
              </div>
            </div>
            <div className="flex gap-2">
              <Button onClick={() => save.mutate()} loading={save.isPending}>
                Lưu SMTP
              </Button>
              <Button
                variant="outline"
                disabled={!data.data?.password_set && !form.password}
                onClick={() => {
                  const to = window.prompt("Gửi email test tới:");
                  if (to) test.mutate(to);
                }}
              >
                Gửi email test
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// GOOGLE OAUTH
// ---------------------------------------------------------------------------

function GoogleSection() {
  const qc = useQueryClient();
  const data = useQuery({
    queryKey: ["admin", "config", "google"],
    queryFn: async () => (await adminEndpoints.getGoogle()).data,
  });
  const [form, setForm] = useState<GoogleConfigUpdate>({
    client_id: "",
    redirect_uri: "",
    enabled: false,
    client_secret: "",
  });

  useEffect(() => {
    if (!data.data) return;
    const defaultRedirect =
      data.data.redirect_uri ||
      `${window.location.origin}/api/v1/auth/google/callback`;
    setForm({
      client_id: data.data.client_id,
      redirect_uri: defaultRedirect,
      enabled: data.data.enabled,
      client_secret: "",
    });
  }, [data.data]);

  const save = useMutation({
    mutationFn: async () => {
      const body: GoogleConfigUpdate = { ...form };
      if (!body.client_secret) body.client_secret = null;
      return (await adminEndpoints.saveGoogle(body)).data;
    },
    onSuccess: () => {
      toast.success("Đã lưu cấu hình Google OAuth");
      qc.invalidateQueries({ queryKey: ["admin", "config", "google"] });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Google đăng nhập khách hàng</CardTitle>
        <CardDescription>
          Tạo OAuth Client trên Google Cloud Console, thêm redirect URI trùng cấu hình bên dưới.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {data.isLoading ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          <>
            <div className="flex items-center gap-2">
              <Switch
                checked={form.enabled}
                onCheckedChange={(v) => setForm((f) => ({ ...f, enabled: v }))}
              />
              <span className="text-sm font-medium">Bật đăng nhập bằng Google</span>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Google Client ID" colSpan={2}>
                <Input
                  value={form.client_id}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, client_id: e.target.value }))
                  }
                  placeholder="xxxxx.apps.googleusercontent.com"
                />
              </Field>
              <Field label="Google Client Secret">
                <Input
                  type="password"
                  value={form.client_secret ?? ""}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, client_secret: e.target.value }))
                  }
                  placeholder={
                    data.data?.client_secret_set
                      ? "Đã lưu (để trống nếu giữ nguyên)"
                      : "GOCSPX-..."
                  }
                />
              </Field>
              <Field label="Redirect URI">
                <Input
                  value={form.redirect_uri}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, redirect_uri: e.target.value }))
                  }
                />
              </Field>
            </div>
            <div className="flex items-center gap-2">
              <CopyButton value={form.redirect_uri} label="Copy redirect URI" />
              <Button onClick={() => save.mutate()} loading={save.isPending}>
                Lưu Google OAuth
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// TELEGRAM
// ---------------------------------------------------------------------------

function TelegramSection() {
  const qc = useQueryClient();
  const data = useQuery({
    queryKey: ["admin", "config", "telegram"],
    queryFn: async () => (await adminEndpoints.getTelegram()).data,
    refetchInterval: ({ state }) =>
      state.data && (state.data as { admin_chat_id?: string }).admin_chat_id ? false : 0,
  });
  const [form, setForm] = useState<TelegramConfigUpdate>({
    bot_token: "",
    enabled: false,
  });

  useEffect(() => {
    if (!data.data) return;
    setForm((f) => ({ ...f, enabled: data.data!.enabled, bot_token: "" }));
  }, [data.data]);

  const save = useMutation({
    mutationFn: async () => {
      const body: TelegramConfigUpdate = {
        enabled: form.enabled,
        bot_token: form.bot_token || null,
      };
      return (await adminEndpoints.saveTelegram(body)).data;
    },
    onSuccess: () => {
      toast.success("Đã lưu cấu hình Telegram");
      qc.invalidateQueries({ queryKey: ["admin", "config", "telegram"] });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  const registerHook = useMutation({
    mutationFn: async () =>
      (
        await adminEndpoints.registerTelegramWebhook(window.location.origin)
      ).data,
    onSuccess: (res) => {
      if (res.ok) toast.success("Đăng ký webhook thành công");
      else toast.error(`Webhook lỗi: ${res.description ?? "unknown"}`);
      qc.invalidateQueries({ queryKey: ["admin", "config", "telegram"] });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  const deleteHook = useMutation({
    mutationFn: async () => (await adminEndpoints.deleteTelegramWebhook()).data,
    onSuccess: () => {
      toast.success("Đã xóa webhook");
      qc.invalidateQueries({ queryKey: ["admin", "config", "telegram"] });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  const unlink = useMutation({
    mutationFn: async () => (await adminEndpoints.unlinkTelegramChat()).data,
    onSuccess: () => {
      toast.success("Đã hủy liên kết");
      qc.invalidateQueries({ queryKey: ["admin", "config", "telegram"] });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  const linker = useTelegramAutoLink(() =>
    qc.invalidateQueries({ queryKey: ["admin", "config", "telegram"] }),
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>Telegram bot</CardTitle>
        <CardDescription>
          Tạo bot qua @BotFather để lấy token. Sau đó đăng ký webhook và liên kết admin
          chat — bot sẽ gửi notify topup và confirm/cancel đơn ngay trong chat.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {data.isLoading ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          <>
            <div className="grid gap-3 md:grid-cols-[1fr_auto]">
              <Field label="Bot token">
                <Input
                  value={form.bot_token ?? ""}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, bot_token: e.target.value }))
                  }
                  placeholder={
                    data.data?.bot_token_set
                      ? "Đã lưu (để trống nếu giữ nguyên)"
                      : "123456:ABC-DEF..."
                  }
                />
              </Field>
              <div className="flex items-end gap-2">
                <div className="flex items-center gap-2">
                  <Switch
                    checked={form.enabled}
                    onCheckedChange={(v) => setForm((f) => ({ ...f, enabled: v }))}
                  />
                  <span className="text-sm">Bật</span>
                </div>
              </div>
            </div>
            <Button onClick={() => save.mutate()} loading={save.isPending}>
              Lưu token
            </Button>

            <div className="rounded-md border p-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold">Webhook</div>
                  <div className="text-xs text-muted-foreground">
                    {data.data?.webhook_url || "Chưa đăng ký"}
                  </div>
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    onClick={() => registerHook.mutate()}
                    loading={registerHook.isPending}
                    disabled={!data.data?.bot_token_set}
                  >
                    {data.data?.webhook_url ? "Đăng ký lại" : "Đăng ký"}
                  </Button>
                  {data.data?.webhook_url ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => deleteHook.mutate()}
                    >
                      Xóa
                    </Button>
                  ) : null}
                </div>
              </div>
            </div>

            <div className="rounded-md border p-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold">Admin chat</div>
                  <div className="text-xs text-muted-foreground">
                    {data.data?.admin_chat_id ? (
                      <>
                        Đã liên kết · chat ID:{" "}
                        <span className="font-mono">{data.data.admin_chat_id}</span>
                      </>
                    ) : (
                      "Chưa liên kết"
                    )}
                  </div>
                  {linker.deepLink ? (
                    <div className="mt-2 flex items-center gap-2">
                      <code className="break-all rounded bg-muted px-1.5 py-0.5 text-xs">
                        {linker.deepLink}
                      </code>
                      <CopyButton value={linker.deepLink} label="Copy link" />
                    </div>
                  ) : null}
                  {linker.waiting ? (
                    <Badge variant="warning" className="mt-2">
                      Đang chờ bạn bấm Start trong Telegram… ({linker.timeoutLeft}s)
                    </Badge>
                  ) : null}
                </div>
                <div className="flex gap-2">
                  {data.data?.admin_chat_id ? (
                    <>
                      <Button size="sm" onClick={() => linker.start()}>
                        Liên kết lại
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => unlink.mutate()}
                      >
                        Hủy
                      </Button>
                    </>
                  ) : (
                    <Button
                      size="sm"
                      onClick={() => linker.start()}
                      disabled={!data.data?.bot_token_set}
                    >
                      Liên kết tự động
                    </Button>
                  )}
                </div>
              </div>
            </div>

            {!data.data?.bot_token_set ? (
              <Alert variant="info">
                <AlertTitle>Cần lưu bot token trước</AlertTitle>
                <AlertDescription>
                  Sau khi lưu token, bạn mới đăng ký webhook và liên kết admin chat được.
                </AlertDescription>
              </Alert>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function useTelegramAutoLink(onLinked: () => void) {
  const [deepLink, setDeepLink] = useState<string | null>(null);
  const [waiting, setWaiting] = useState(false);
  const [timeoutLeft, setTimeoutLeft] = useState(0);
  const stopRef = useRef<{ cancel: () => void } | null>(null);

  const start = async () => {
    try {
      setDeepLink(null);
      setWaiting(false);
      const res = (await adminEndpoints.linkTelegramChat()).data;
      setDeepLink(res.deep_link_url);
      window.open(res.deep_link_url, "_blank", "noopener");
      setWaiting(true);
      setTimeoutLeft(60);

      let cancelled = false;
      stopRef.current?.cancel();
      stopRef.current = {
        cancel: () => {
          cancelled = true;
        },
      };

      const tickStart = Date.now();
      const poll = async () => {
        while (!cancelled) {
          const elapsed = Math.floor((Date.now() - tickStart) / 1000);
          setTimeoutLeft(Math.max(0, 60 - elapsed));
          if (elapsed >= 60) break;
          try {
            const cur = (await adminEndpoints.getTelegram()).data;
            if (cur.admin_chat_id) {
              toast.success(`Đã liên kết chat ID ${cur.admin_chat_id}`);
              setWaiting(false);
              setDeepLink(null);
              onLinked();
              return;
            }
          } catch {
            /* ignore */
          }
          await new Promise((r) => setTimeout(r, 2000));
        }
        setWaiting(false);
      };
      void poll();
    } catch (err) {
      toast.error(toApiError(err).detail);
    }
  };

  return { deepLink, waiting, timeoutLeft, start };
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
