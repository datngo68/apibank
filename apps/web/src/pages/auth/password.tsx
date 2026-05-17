import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Helmet } from "react-helmet-async";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { Card, CardHeader, CardContent, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { endpoints, toApiError } from "@/lib/api";

const forgotSchema = z.object({ email: z.string().email() });
const resetSchema = z.object({
  token: z.string().min(10),
  password: z.string().min(8).max(128).regex(/[A-Z]/).regex(/[0-9]/),
});

export function ForgotPasswordPage() {
  const { register, handleSubmit, formState } = useForm<z.infer<typeof forgotSchema>>({
    resolver: zodResolver(forgotSchema),
  });
  const submit = useMutation({
    mutationFn: async (v: z.infer<typeof forgotSchema>) =>
      (await endpoints.forgot(v.email)).data,
    onSuccess: () => toast.success("Nếu email tồn tại, link đặt lại đã được gửi."),
    onError: (err) => toast.error(toApiError(err).detail),
  });

  return (
    <Card>
      <Helmet>
        <title>Quên mật khẩu · APIBank</title>
      </Helmet>
      <CardHeader>
        <CardTitle>Quên mật khẩu</CardTitle>
        <CardDescription>Nhập email để nhận link đặt lại mật khẩu.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit((v) => submit.mutate(v))} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" {...register("email")} invalid={!!formState.errors.email} />
          </div>
          <Button type="submit" className="w-full" loading={submit.isPending}>
            Gửi link
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const initialToken = params.get("token") ?? "";
  const [token] = useState(initialToken);
  const { register, handleSubmit, formState } = useForm<z.infer<typeof resetSchema>>({
    resolver: zodResolver(resetSchema),
    defaultValues: { token: initialToken },
  });
  const submit = useMutation({
    mutationFn: async (v: z.infer<typeof resetSchema>) =>
      (await endpoints.reset(v.token, v.password)).data,
    onSuccess: () => toast.success("Đã đặt lại mật khẩu, vui lòng đăng nhập."),
    onError: (err) => toast.error(toApiError(err).detail),
  });

  return (
    <Card>
      <Helmet>
        <title>Đặt lại mật khẩu · APIBank</title>
      </Helmet>
      <CardHeader>
        <CardTitle>Đặt lại mật khẩu</CardTitle>
        <CardDescription>Dán token nhận từ email và nhập mật khẩu mới.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit((v) => submit.mutate(v))} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="token">Token</Label>
            <Input
              id="token"
              defaultValue={token}
              {...register("token")}
              invalid={!!formState.errors.token}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">Mật khẩu mới</Label>
            <Input id="password" type="password" {...register("password")} invalid={!!formState.errors.password} />
          </div>
          <Button type="submit" className="w-full" loading={submit.isPending}>
            Đặt lại
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const submit = useMutation({
    mutationFn: async (t: string) => (await endpoints.verifyEmail(t)).data,
    onSuccess: () => toast.success("Đã xác minh email."),
    onError: (err) => toast.error(toApiError(err).detail),
  });
  return (
    <Card>
      <Helmet>
        <title>Xác minh email · APIBank</title>
      </Helmet>
      <CardHeader>
        <CardTitle>Xác minh email</CardTitle>
        <CardDescription>Bấm nút bên dưới để hoàn tất xác minh.</CardDescription>
      </CardHeader>
      <CardContent>
        <Button
          className="w-full"
          loading={submit.isPending}
          disabled={!token}
          onClick={() => submit.mutate(token)}
        >
          Xác minh
        </Button>
        {!token ? (
          <p className="mt-3 text-xs text-muted-foreground">Thiếu token trong URL.</p>
        ) : null}
      </CardContent>
    </Card>
  );
}
