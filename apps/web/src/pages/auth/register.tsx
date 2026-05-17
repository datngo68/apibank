import { Link, useNavigate } from "react-router-dom";
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

const schema = z
  .object({
    email: z.string().email("Email không hợp lệ"),
    full_name: z.string().min(1, "Vui lòng nhập tên").max(255).optional().or(z.literal("")),
    password: z
      .string()
      .min(8, "Mật khẩu tối thiểu 8 ký tự")
      .max(128, "Mật khẩu quá dài")
      .regex(/[A-Z]/, "Cần ít nhất 1 chữ in hoa")
      .regex(/[0-9]/, "Cần ít nhất 1 chữ số"),
    confirm_password: z.string().min(1, "Vui lòng nhập lại mật khẩu"),
  })
  .refine((data) => data.password === data.confirm_password, {
    path: ["confirm_password"],
    message: "Mật khẩu xác nhận không khớp",
  });

type FormValues = z.infer<typeof schema>;

export function RegisterPage() {
  const navigate = useNavigate();
  const { register, handleSubmit, formState, watch } = useForm<FormValues>({
    resolver: zodResolver(schema),
  });
  const password = watch("password") ?? "";
  const strength = passwordStrength(password);

  const submit = useMutation({
    mutationFn: async (values: FormValues) => {
      const { confirm_password: _confirm, ...payload } = values;
      void _confirm;
      return (await endpoints.register(payload)).data;
    },
    onSuccess: () => {
      toast.success("Đăng ký thành công, kiểm tra email để xác minh.");
      navigate("/login", { replace: true });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  return (
    <Card>
      <Helmet>
        <title>Đăng ký · APIBank</title>
      </Helmet>
      <CardHeader>
        <CardTitle>Tạo tài khoản</CardTitle>
        <CardDescription>Miễn phí, không cần thẻ thanh toán.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit((v) => submit.mutate(v))} className="space-y-4" noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="full_name">Tên hiển thị (tuỳ chọn)</Label>
            <Input id="full_name" autoComplete="name" {...register("full_name")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" autoComplete="email" {...register("email")} invalid={!!formState.errors.email} />
            {formState.errors.email ? (
              <p className="text-xs text-destructive">{formState.errors.email.message}</p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">Mật khẩu</Label>
            <Input id="password" type="password" autoComplete="new-password" {...register("password")} invalid={!!formState.errors.password} />
            <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
              <div
                className={`h-full transition-all ${strength.color}`}
                style={{ width: `${strength.percent}%` }}
              />
            </div>
            <p className="text-xs text-muted-foreground">
              Tối thiểu 8 ký tự, có chữ in hoa và chữ số. Độ mạnh: {strength.label}
            </p>
            {formState.errors.password ? (
              <p className="text-xs text-destructive">{formState.errors.password.message}</p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="confirm_password">Nhập lại mật khẩu</Label>
            <Input
              id="confirm_password"
              type="password"
              autoComplete="new-password"
              {...register("confirm_password")}
              invalid={!!formState.errors.confirm_password}
            />
            {formState.errors.confirm_password ? (
              <p className="text-xs text-destructive">{formState.errors.confirm_password.message}</p>
            ) : null}
          </div>
          <Button type="submit" className="w-full" loading={submit.isPending}>
            Tạo tài khoản
          </Button>
        </form>
        <p className="mt-4 text-center text-sm text-muted-foreground">
          Đã có tài khoản?{" "}
          <Link to="/login" className="text-primary hover:underline">
            Đăng nhập
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}

function passwordStrength(pwd: string): { percent: number; label: string; color: string } {
  let score = 0;
  if (pwd.length >= 8) score++;
  if (/[A-Z]/.test(pwd)) score++;
  if (/[0-9]/.test(pwd)) score++;
  if (/[^A-Za-z0-9]/.test(pwd)) score++;
  if (pwd.length >= 12) score++;
  const map = [
    { percent: 0, label: "—", color: "bg-muted" },
    { percent: 25, label: "Yếu", color: "bg-destructive" },
    { percent: 45, label: "Trung bình", color: "bg-warning" },
    { percent: 65, label: "Khá", color: "bg-warning" },
    { percent: 85, label: "Mạnh", color: "bg-success" },
    { percent: 100, label: "Rất mạnh", color: "bg-success" },
  ];
  return map[Math.min(score, map.length - 1)];
}
