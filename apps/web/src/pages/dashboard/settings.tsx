import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { CopyButton } from "@/components/ui/copy-button";
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
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  TableEmpty,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { endpoints, toApiError, type NotificationPreferenceItem } from "@/lib/api";
import { useAuth, AUTH_QUERY_KEY } from "@/lib/auth";
import { formatDateTime } from "@/lib/utils";

const profileSchema = z.object({
  full_name: z.string().max(255).optional(),
  locale: z.enum(["vi", "en"]).optional(),
});

const passwordSchema = z.object({
  current_password: z.string().min(1),
  new_password: z.string().min(8).max(128).regex(/[A-Z]/).regex(/[0-9]/),
});

export function SettingsPage() {
  const { data: auth } = useAuth();
  const qc = useQueryClient();
  const sessions = useQuery({
    queryKey: ["sessions"],
    queryFn: async () => (await endpoints.listSessions()).data,
  });
  const profileForm = useForm<z.infer<typeof profileSchema>>({
    resolver: zodResolver(profileSchema),
    defaultValues: {
      full_name: auth?.user.full_name ?? "",
      locale: (auth?.user.locale as "vi" | "en") ?? "vi",
    },
  });
  const updateProfile = useMutation({
    mutationFn: async (v: z.infer<typeof profileSchema>) => (await endpoints.updateProfile(v)).data,
    onSuccess: () => {
      toast.success("Đã cập nhật hồ sơ");
      qc.invalidateQueries({ queryKey: AUTH_QUERY_KEY });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  const passwordForm = useForm<z.infer<typeof passwordSchema>>({
    resolver: zodResolver(passwordSchema),
  });
  const changePassword = useMutation({
    mutationFn: async (v: z.infer<typeof passwordSchema>) =>
      (await endpoints.changePassword(v.current_password, v.new_password)).data,
    onSuccess: () => {
      toast.success("Đã đổi mật khẩu");
      passwordForm.reset();
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Cài đặt</h1>
        <p className="text-sm text-muted-foreground">
          Cập nhật hồ sơ, mật khẩu, 2FA và phiên đăng nhập.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Hồ sơ</CardTitle>
          <CardDescription>Tên hiển thị và ngôn ngữ.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={profileForm.handleSubmit((v) => updateProfile.mutate(v))}
            className="grid gap-4 md:grid-cols-2"
          >
            <div className="space-y-1.5">
              <Label htmlFor="full_name">Tên hiển thị</Label>
              <Input id="full_name" {...profileForm.register("full_name")} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="locale">Ngôn ngữ</Label>
              <select
                id="locale"
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                {...profileForm.register("locale")}
              >
                <option value="vi">Tiếng Việt</option>
                <option value="en">English</option>
              </select>
            </div>
            <div className="md:col-span-2">
              <Button type="submit" loading={updateProfile.isPending}>
                Lưu
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <TelegramLinkSection />

      <NotificationPreferencesSection />

      <Card>
        <CardHeader>
          <CardTitle>Đổi mật khẩu</CardTitle>
          <CardDescription>
            Sau khi đổi, các phiên khác sẽ bị thu hồi tự động.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={passwordForm.handleSubmit((v) => changePassword.mutate(v))}
            className="grid gap-4 md:grid-cols-2"
          >
            <div className="space-y-1.5">
              <Label htmlFor="current_password">Mật khẩu hiện tại</Label>
              <Input id="current_password" type="password" {...passwordForm.register("current_password")} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="new_password">Mật khẩu mới</Label>
              <Input id="new_password" type="password" {...passwordForm.register("new_password")} />
            </div>
            <div className="md:col-span-2">
              <Button type="submit" loading={changePassword.isPending}>
                Đổi mật khẩu
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <TwoFactorSection />

      <Card>
        <CardHeader>
          <CardTitle>Phiên đăng nhập</CardTitle>
          <CardDescription>
            Thiết bị đang đăng nhập tài khoản của bạn. Có thể thu hồi từ xa.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>IP</TableHead>
                <TableHead>User agent</TableHead>
                <TableHead>Đăng nhập</TableHead>
                <TableHead>Hết hạn</TableHead>
                <TableHead className="text-right">Thao tác</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sessions.isLoading ? (
                <TableRow>
                  <TableCell colSpan={5}>Đang tải…</TableCell>
                </TableRow>
              ) : (sessions.data?.length ?? 0) === 0 ? (
                <TableEmpty colSpan={5}>Không có phiên nào.</TableEmpty>
              ) : (
                sessions.data?.map((s: any) => (
                  <TableRow key={s.id}>
                    <TableCell className="font-mono text-xs">{s.ip ?? "—"}</TableCell>
                    <TableCell className="max-w-[28ch] truncate text-xs">{s.user_agent}</TableCell>
                    <TableCell className="text-xs">{formatDateTime(s.created_at)}</TableCell>
                    <TableCell className="text-xs">{formatDateTime(s.expires_at)}</TableCell>
                    <TableCell className="text-right">
                      {s.current ? (
                        <span className="text-xs text-muted-foreground">Hiện tại</span>
                      ) : (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={async () => {
                            await endpoints.revokeSession(s.id);
                            toast.success("Đã thu hồi");
                            qc.invalidateQueries({ queryKey: ["sessions"] });
                          }}
                        >
                          Thu hồi
                        </Button>
                      )}
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

function TwoFactorSection() {
  const { data: auth } = useAuth();
  const qc = useQueryClient();
  const [enrollSecret, setEnrollSecret] = useState<string | null>(null);
  const [otpUri, setOtpUri] = useState<string | null>(null);
  const [qrDataUri, setQrDataUri] = useState<string | null>(null);
  const [showManual, setShowManual] = useState(false);
  const [code, setCode] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);

  const enroll = useMutation({
    mutationFn: async () => (await endpoints.enroll2fa()).data,
    onSuccess: (data: any) => {
      setEnrollSecret(data.secret);
      setOtpUri(data.otpauth_uri);
      setQrDataUri(data.qr_data_uri ?? null);
      setShowManual(false);
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  const verify = useMutation({
    mutationFn: async () => (await endpoints.verify2fa(code)).data,
    onSuccess: (data: any) => {
      setRecoveryCodes(data.recovery_codes);
      setEnrollSecret(null);
      setOtpUri(null);
      setQrDataUri(null);
      setCode("");
      qc.invalidateQueries({ queryKey: AUTH_QUERY_KEY });
      toast.success("Đã bật 2FA");
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  const disable = useMutation({
    mutationFn: async () => {
      const password = window.prompt("Nhập mật khẩu để tắt 2FA:");
      if (!password) throw new Error("Cần mật khẩu");
      return (await endpoints.disable2fa(password)).data;
    },
    onSuccess: () => {
      toast.success("Đã tắt 2FA");
      qc.invalidateQueries({ queryKey: AUTH_QUERY_KEY });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  const has2fa = auth?.user.has_2fa;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Xác thực 2 yếu tố</CardTitle>
        <CardDescription>
          Yêu cầu mã TOTP mỗi khi đăng nhập, tăng độ an toàn cho tài khoản.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {has2fa ? (
          <Alert variant="success">
            <AlertTitle>2FA đang bật</AlertTitle>
            <AlertDescription>
              Bạn cần nhập mã 6 số mỗi lần đăng nhập.{" "}
              <Button size="sm" variant="ghost" onClick={() => disable.mutate()}>
                Tắt 2FA
              </Button>
            </AlertDescription>
          </Alert>
        ) : enrollSecret ? (
          <div className="space-y-3">
            <Alert variant="info">
              <AlertTitle>Bước 1: quét QR bằng ứng dụng Authenticator</AlertTitle>
              <AlertDescription>
                Mở Google Authenticator / Microsoft Authenticator / Authy → "Thêm
                tài khoản" → chọn "Quét mã QR" → hướng camera vào hình bên dưới.
              </AlertDescription>
            </Alert>

            <div className="flex flex-col items-center gap-3 rounded-md border bg-background p-4 sm:flex-row sm:items-start sm:gap-4">
              {qrDataUri ? (
                <img
                  src={qrDataUri}
                  alt="QR code 2FA APIBank"
                  className="size-48 rounded border bg-white p-2"
                />
              ) : (
                <div className="flex size-48 items-center justify-center rounded border bg-muted text-xs text-muted-foreground">
                  Đang tạo QR…
                </div>
              )}
              <div className="flex-1 space-y-2 text-sm">
                <p className="font-medium">Sau khi quét, nhập mã 6 số mà ứng dụng hiển thị:</p>
                <div className="flex items-center gap-2">
                  <Input
                    placeholder="123456"
                    inputMode="numeric"
                    maxLength={6}
                    value={code}
                    onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                    className="max-w-[10rem] tracking-[0.4em]"
                  />
                  <Button loading={verify.isPending} onClick={() => verify.mutate()}>
                    Xác nhận
                  </Button>
                </div>
                <button
                  type="button"
                  className="text-xs text-muted-foreground underline-offset-2 hover:underline"
                  onClick={() => setShowManual((v) => !v)}
                >
                  {showManual ? "Ẩn" : "Không quét được? Nhập tay"}
                </button>
              </div>
            </div>

            {showManual ? (
              <div className="space-y-2 rounded-md border bg-muted/30 p-3 text-xs">
                <p className="text-muted-foreground">
                  Nếu app không quét được QR, mở app → "Thêm tài khoản" → "Nhập
                  khoá thủ công" và dán secret bên dưới (loại "Theo thời gian").
                </p>
                <div className="flex items-center gap-2 rounded bg-background p-2 font-mono">
                  <span className="flex-1 break-all">{enrollSecret}</span>
                  <CopyButton value={enrollSecret} label="Copy secret" />
                </div>
                <details className="text-muted-foreground">
                  <summary className="cursor-pointer select-none">
                    Hiện URI otpauth (cho password manager hỗ trợ TOTP)
                  </summary>
                  <div className="mt-2 flex items-center gap-2 rounded bg-background p-2 font-mono">
                    <code className="flex-1 break-all">{otpUri}</code>
                    <CopyButton value={otpUri ?? ""} label="Copy URI" />
                  </div>
                </details>
              </div>
            ) : null}
          </div>
        ) : recoveryCodes ? (
          <Alert variant="warning">
            <AlertTitle>Lưu mã khôi phục</AlertTitle>
            <AlertDescription>
              Mã chỉ hiện 1 lần. Lưu lại để dùng khi mất Authenticator.
              <ul className="mt-2 grid grid-cols-2 gap-1 font-mono text-xs">
                {recoveryCodes.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        ) : (
          <Button loading={enroll.isPending} onClick={() => enroll.mutate()}>
            Bật 2FA
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function TelegramLinkSection() {
  const { data: auth } = useAuth();
  const qc = useQueryClient();
  const [deepLink, setDeepLink] = useState<string | null>(null);
  const [waiting, setWaiting] = useState(false);
  const [timeoutLeft, setTimeoutLeft] = useState(0);
  const stopRef = useRef<{ cancel: () => void } | null>(null);

  const linked = Boolean(auth?.user.telegram_chat_id);

  const link = useMutation({
    mutationFn: async () => (await endpoints.linkUserTelegram()).data,
    onSuccess: (data) => {
      setDeepLink(data.deep_link_url);
      window.open(data.deep_link_url, "_blank", "noopener");
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
      void (async () => {
        while (!cancelled) {
          const elapsed = Math.floor((Date.now() - tickStart) / 1000);
          setTimeoutLeft(Math.max(0, 60 - elapsed));
          if (elapsed >= 60) break;
          try {
            const me = (await endpoints.me()).data;
            if (me.user.telegram_chat_id) {
              toast.success("Đã liên kết Telegram thành công");
              setWaiting(false);
              setDeepLink(null);
              qc.invalidateQueries({ queryKey: AUTH_QUERY_KEY });
              return;
            }
          } catch {
            /* ignore */
          }
          await new Promise((r) => setTimeout(r, 2000));
        }
        setWaiting(false);
      })();
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  const unlink = useMutation({
    mutationFn: async () => (await endpoints.unlinkUserTelegram()).data,
    onSuccess: () => {
      toast.success("Đã hủy liên kết Telegram");
      qc.invalidateQueries({ queryKey: AUTH_QUERY_KEY });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Liên kết Telegram</CardTitle>
        <CardDescription>
          Nhận thông báo topup ví, hết hạn gói, webhook lỗi qua Telegram cá nhân.
          Bấm 1 nút để liên kết, không cần nhập chat ID.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {linked ? (
          <Alert variant="success">
            <AlertTitle className="flex items-center justify-between gap-3">
              <span>Đã liên kết</span>
              <Badge variant="success">
                Chat ID: {auth?.user.telegram_chat_id}
              </Badge>
            </AlertTitle>
            <AlertDescription className="flex items-center justify-between gap-3">
              <span>Bot sẽ gửi thông báo về chat này.</span>
              <Button size="sm" variant="ghost" onClick={() => unlink.mutate()}>
                Hủy liên kết
              </Button>
            </AlertDescription>
          </Alert>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                onClick={() => link.mutate()}
                loading={link.isPending}
                disabled={waiting}
              >
                Liên kết tự động qua Telegram
              </Button>
              {deepLink ? (
                <CopyButton value={deepLink} label="Copy link nếu popup bị chặn" />
              ) : null}
            </div>
            {waiting ? (
              <Alert variant="info">
                <AlertTitle>Đang chờ bạn bấm Start trong Telegram…</AlertTitle>
                <AlertDescription>
                  Còn {timeoutLeft}s. Mình sẽ phát hiện ngay sau khi bạn bấm Start trong cuộc trò chuyện vừa mở.
                </AlertDescription>
              </Alert>
            ) : null}
            {!waiting && deepLink ? (
              <p className="text-xs text-muted-foreground">
                Hết hạn chờ. Bấm "Liên kết tự động" để thử lại.
              </p>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Notification preferences section — matrix kind x channel.
// ---------------------------------------------------------------------------

const KIND_LABELS: Record<string, { title: string; description: string }> = {
  topup_credited: {
    title: "Nạp ví thành công",
    description: "Khi giao dịch chuyển khoản match đơn topup ví.",
  },
  subscription_purchased: {
    title: "Đã mua/gia hạn gói",
    description: "Sau khi trừ ví và kích hoạt subscription.",
  },
  subscription_expiring: {
    title: "Gói sắp hết hạn",
    description: "Nhắc trước 3 ngày khi gói sắp hết hạn.",
  },
  subscription_expired: {
    title: "Gói đã hết hạn",
    description: "Khi subscription hiện tại đã hết hạn.",
  },
  webhook_failing: {
    title: "Webhook lỗi liên tục",
    description: "Khi webhook fail nhiều lần liên tiếp.",
  },
  bank_login_failed: {
    title: "Đăng nhập ngân hàng lỗi",
    description: "Khi worker không đăng nhập được vào tài khoản ngân hàng.",
  },
};

const CHANNEL_LABELS: Record<NotificationPreferenceItem["channel"], string> = {
  in_app: "Trong app",
  email: "Email",
  telegram: "Telegram",
};

const CHANNELS: NotificationPreferenceItem["channel"][] = ["in_app", "email", "telegram"];

function NotificationPreferencesSection() {
  const qc = useQueryClient();
  const { data: auth } = useAuth();
  const prefs = useQuery({
    queryKey: ["notification-preferences"],
    queryFn: async () => (await endpoints.notificationPreferences()).data,
  });

  const update = useMutation({
    mutationFn: async (items: NotificationPreferenceItem[]) =>
      (await endpoints.updateNotificationPreferences(items)).data,
    onMutate: async (items) => {
      await qc.cancelQueries({ queryKey: ["notification-preferences"] });
      const prev = qc.getQueryData<{ items: NotificationPreferenceItem[] }>([
        "notification-preferences",
      ]);
      if (prev) {
        const map = new Map(items.map((it) => [`${it.kind}:${it.channel}`, it.enabled]));
        const next = prev.items.map((it) => {
          const k = `${it.kind}:${it.channel}`;
          return map.has(k) ? { ...it, enabled: map.get(k)! } : it;
        });
        qc.setQueryData(["notification-preferences"], { items: next });
      }
      return { prev };
    },
    onError: (err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(["notification-preferences"], ctx.prev);
      toast.error(toApiError(err).detail);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notification-preferences"] });
    },
  });

  const items = prefs.data?.items ?? [];
  const telegramLinked = Boolean(auth?.user.telegram_chat_id);

  // Group theo kind để render từng dòng.
  const byKind = new Map<string, Map<string, boolean>>();
  for (const it of items) {
    if (!byKind.has(it.kind)) byKind.set(it.kind, new Map());
    byKind.get(it.kind)!.set(it.channel, it.enabled);
  }

  const toggle = (kind: string, channel: NotificationPreferenceItem["channel"], enabled: boolean) => {
    update.mutate([{ kind, channel, enabled }]);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Tuỳ chọn thông báo</CardTitle>
        <CardDescription>
          Bật/tắt từng kênh cho từng loại sự kiện. Telegram chỉ chạy nếu bạn đã liên kết.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {prefs.isLoading ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Sự kiện</TableHead>
                {CHANNELS.map((ch) => (
                  <TableHead key={ch} className="text-center">
                    {CHANNEL_LABELS[ch]}
                    {ch === "telegram" && !telegramLinked ? (
                      <Badge variant="muted" className="ml-1 text-[10px]">
                        chưa liên kết
                      </Badge>
                    ) : null}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {[...byKind.entries()].map(([kind, channels]) => {
                const meta = KIND_LABELS[kind] ?? { title: kind, description: "" };
                return (
                  <TableRow key={kind}>
                    <TableCell>
                      <div className="text-sm font-medium">{meta.title}</div>
                      {meta.description ? (
                        <div className="text-xs text-muted-foreground">{meta.description}</div>
                      ) : null}
                    </TableCell>
                    {CHANNELS.map((ch) => {
                      const enabled = channels.get(ch) ?? false;
                      const disabled =
                        update.isPending || (ch === "telegram" && !telegramLinked);
                      return (
                        <TableCell key={ch} className="text-center">
                          <Switch
                            checked={enabled}
                            disabled={disabled}
                            onCheckedChange={(v) => toggle(kind, ch, v)}
                            aria-label={`${meta.title} qua ${CHANNEL_LABELS[ch]}`}
                          />
                        </TableCell>
                      );
                    })}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
