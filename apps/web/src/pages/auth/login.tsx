import { useEffect, useState } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { Helmet } from "react-helmet-async";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Card, CardHeader, CardContent, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { endpoints, toApiError } from "@/lib/api";
import { AUTH_QUERY_KEY } from "@/lib/auth";

const schema = z.object({
  email: z.string().email("Email không hợp lệ"),
  password: z.string().min(1, "Vui lòng nhập mật khẩu"),
  code: z.string().optional(),
});

type FormValues = z.infer<typeof schema>;

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const qc = useQueryClient();
  const [requires2fa, setRequires2fa] = useState(false);
  const [googleEnabled, setGoogleEnabled] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await endpoints.googleStatus();
        if (!cancelled) setGoogleEnabled(Boolean(res.data.enabled));
      } catch {
        if (!cancelled) setGoogleEnabled(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const { register, handleSubmit, formState } = useForm<FormValues>({
    resolver: zodResolver(schema),
  });
  const { errors, isSubmitting } = formState;

  const login = useMutation({
    mutationFn: async (values: FormValues) => (await endpoints.login(values)).data,
    onSuccess: async (data) => {
      if (data.requires_2fa) {
        setRequires2fa(true);
        toast.message("Cần mã 2FA để hoàn tất đăng nhập");
        return;
      }
      qc.setQueryData(AUTH_QUERY_KEY, { user: data.user, requires_2fa: false });
      const next = (location.state as { from?: string } | null)?.from ?? "/app";
      navigate(next, { replace: true });
    },
    onError: (err) => {
      const e = toApiError(err);
      toast.error(e.detail);
    },
  });

  return (
    <Card>
      <Helmet>
        <title>Đăng nhập · APIBank</title>
      </Helmet>
      <CardHeader>
        <CardTitle>Đăng nhập</CardTitle>
        <CardDescription>Vào dashboard quản lý cổng thanh toán của bạn.</CardDescription>
      </CardHeader>
      <CardContent>
        {requires2fa ? (
          <Alert variant="info" className="mb-4">
            <AlertTitle>Cần mã 2FA</AlertTitle>
            <AlertDescription>Mở app Authenticator và nhập mã 6 số.</AlertDescription>
          </Alert>
        ) : null}
        <form
          onSubmit={handleSubmit((v) => login.mutate(v))}
          className="space-y-4"
          noValidate
        >
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" autoComplete="email" {...register("email")} invalid={!!errors.email} />
            {errors.email ? <p className="text-xs text-destructive">{errors.email.message}</p> : null}
          </div>
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label htmlFor="password">Mật khẩu</Label>
              <Link to="/forgot" className="text-xs text-primary hover:underline">
                Quên mật khẩu?
              </Link>
            </div>
            <Input id="password" type="password" autoComplete="current-password" {...register("password")} invalid={!!errors.password} />
            {errors.password ? <p className="text-xs text-destructive">{errors.password.message}</p> : null}
          </div>
          {requires2fa ? (
            <div className="space-y-1.5">
              <Label htmlFor="code">Mã 2FA</Label>
              <Input id="code" inputMode="numeric" maxLength={6} {...register("code")} placeholder="123456" />
            </div>
          ) : null}
          <Button type="submit" className="w-full" loading={isSubmitting || login.isPending}>
            Đăng nhập
          </Button>
        </form>
        {googleEnabled ? (
          <>
            <div className="my-4 flex items-center gap-3 text-xs text-muted-foreground">
              <div className="h-px flex-1 bg-border" />
              hoặc
              <div className="h-px flex-1 bg-border" />
            </div>
            <Button
              type="button"
              variant="outline"
              className="w-full"
              onClick={() => {
                window.location.href = "/api/v1/auth/google/login";
              }}
            >
              Đăng nhập với Google
            </Button>
          </>
        ) : null}
        <p className="mt-4 text-center text-sm text-muted-foreground">
          Chưa có tài khoản?{" "}
          <Link to="/register" className="text-primary hover:underline">
            Đăng ký miễn phí
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}
