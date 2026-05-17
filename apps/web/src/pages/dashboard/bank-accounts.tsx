import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, RefreshCw, Trash2, AlertTriangle } from "lucide-react";
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
import { endpoints, toApiError, type BankAccount } from "@/lib/api";
import { useConfirm } from "@/components/ui/confirm-dialog";
import { formatDateTime, relativeTime } from "@/lib/utils";

const BANK_OPTIONS = [
  { code: "MB", name: "Quân Đội (MB)", supported: true },
  { code: "VTB", name: "Vietinbank", supported: true },
  { code: "BIDV", name: "BIDV — sắp ra mắt", supported: false },
  { code: "ACB", name: "ACB — sắp ra mắt", supported: false },
  { code: "VCB", name: "Vietcombank — sắp ra mắt", supported: false },
];

const createSchema = z.object({
  bank_code: z.string().min(2),
  account_no: z.string().min(6),
  account_holder: z.string().min(1),
  username: z.string().min(1),
  password: z.string().min(1),
});

type CreateValues = z.infer<typeof createSchema>;

const rotateSchema = z.object({
  username: z.string().min(1),
  password: z.string().min(1),
});

type RotateValues = z.infer<typeof rotateSchema>;

export function BankAccountsPage() {
  const qc = useQueryClient();
  const banks = useQuery({
    queryKey: ["banks"],
    queryFn: async () => (await endpoints.bankAccounts()).data,
    refetchInterval: 30_000,
  });

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Tài khoản ngân hàng</h1>
          <p className="text-sm text-muted-foreground">
            Thêm tài khoản để hệ thống tự động kiểm tra biến động số dư.
          </p>
        </div>
        <CreateDialog onCreated={() => qc.invalidateQueries({ queryKey: ["banks"] })} />
      </div>

      {banks.isLoading ? (
        <Skeleton className="h-40" />
      ) : (banks.data?.length ?? 0) === 0 ? (
        <EmptyState
          title="Chưa có tài khoản nào"
          description="Thêm tài khoản đầu tiên để bắt đầu nhận giao dịch."
          action={<CreateDialog onCreated={() => qc.invalidateQueries({ queryKey: ["banks"] })} />}
        />
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {banks.data?.map((b) => <BankCard key={b.id} bank={b} />)}
        </div>
      )}
    </div>
  );
}

function BankCard({ bank }: { bank: BankAccount }) {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const remove = useMutation({
    mutationFn: () => endpoints.deleteBank(bank.id),
    onSuccess: () => {
      toast.success("Đã xoá tài khoản");
      qc.invalidateQueries({ queryKey: ["banks"] });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              {bank.bank_code}
              <Badge variant="muted">{bank.status}</Badge>
            </CardTitle>
            <CardDescription className="font-mono">{bank.account_no}</CardDescription>
          </div>
          <RotateDialog bank={bank} />
        </div>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        <div>
          <span className="text-muted-foreground">Chủ: </span>
          {bank.account_holder}
        </div>
        <div>
          <span className="text-muted-foreground">Polling: </span>
          <Badge variant={bank.polling_status === "error" ? "destructive" : "muted"}>
            {bank.polling_status}
          </Badge>
        </div>
        <div className="text-xs text-muted-foreground">
          Lần poll cuối: {bank.last_poll_at ? relativeTime(bank.last_poll_at) : "—"}
        </div>
        {bank.verified_at ? (
          <div className="text-xs text-success">Đã verify · {formatDateTime(bank.verified_at)}</div>
        ) : null}
        {bank.last_error ? (
          <Alert variant="destructive">
            <AlertTitle>Có lỗi</AlertTitle>
            <AlertDescription>{bank.last_error}</AlertDescription>
          </Alert>
        ) : null}
        <div className="flex justify-end pt-2">
          <Button
            variant="ghost"
            size="sm"
            loading={remove.isPending}
            onClick={async () => {
              const ok = await confirm({
                title: "Xoá tài khoản ngân hàng",
                description: `Tài khoản ${bank.bank_code} · ${bank.account_no} sẽ bị xoá. Worker sẽ ngừng polling và mọi đơn hàng đang chờ sẽ không match được nữa.`,
                confirmText: "Xoá",
                variant: "destructive",
              });
              if (ok) remove.mutate();
            }}
          >
            <Trash2 aria-hidden /> Xoá
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function CreateDialog({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const { register, handleSubmit, reset, formState } = useForm<CreateValues>({
    resolver: zodResolver(createSchema),
    defaultValues: { bank_code: "MB" },
  });
  const create = useMutation({
    mutationFn: async (values: CreateValues) => (await endpoints.createBank(values)).data,
    onSuccess: () => {
      toast.success("Đã thêm tài khoản");
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
          <Plus aria-hidden /> Thêm tài khoản
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Thêm tài khoản ngân hàng</DialogTitle>
          <DialogDescription>
            Credential sẽ được mã hoá Fernet trước khi lưu DB.
          </DialogDescription>
        </DialogHeader>
        <form
          id="create-bank-form"
          onSubmit={handleSubmit((v) => create.mutate(v))}
          className="space-y-4"
        >
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="bank_code">Ngân hàng</Label>
              <select
                id="bank_code"
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                {...register("bank_code")}
              >
                {BANK_OPTIONS.map((b) => (
                  <option key={b.code} value={b.code} disabled={!b.supported}>
                    {b.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="account_no">Số tài khoản</Label>
              <Input id="account_no" {...register("account_no")} invalid={!!formState.errors.account_no} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="account_holder">Chủ tài khoản</Label>
            <Input id="account_holder" {...register("account_holder")} invalid={!!formState.errors.account_holder} />
          </div>
          <Alert variant="warning">
            <AlertTitle className="flex items-center gap-2">
              <AlertTriangle className="size-4" aria-hidden /> Lưu ý bảo mật
            </AlertTitle>
            <AlertDescription>
              Sử dụng tài khoản phụ riêng cho APIBank. Adapter ngân hàng có thể bị nhà phát hành tạm
              khoá nếu phát hiện auto.
            </AlertDescription>
          </Alert>
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="username">Username login</Label>
              <Input id="username" {...register("username")} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Mật khẩu</Label>
              <Input id="password" type="password" {...register("password")} />
            </div>
          </div>
        </form>
        <DialogFooter>
          <Button type="submit" form="create-bank-form" loading={create.isPending}>
            Thêm
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RotateDialog({ bank }: { bank: BankAccount }) {
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const { register, handleSubmit, reset, formState } = useForm<RotateValues>({
    resolver: zodResolver(rotateSchema),
  });
  const rotate = useMutation({
    mutationFn: async (values: RotateValues) =>
      (await endpoints.rotateBank(bank.id, values)).data,
    onSuccess: () => {
      toast.success("Đã cập nhật credential");
      reset();
      setOpen(false);
      qc.invalidateQueries({ queryKey: ["banks"] });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="icon" variant="ghost" aria-label="Đổi credential">
          <RefreshCw aria-hidden />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Đổi credential</DialogTitle>
          <DialogDescription>Áp dụng cho {bank.account_no}.</DialogDescription>
        </DialogHeader>
        <form id="rotate-form" onSubmit={handleSubmit((v) => rotate.mutate(v))} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="r-username">Username</Label>
            <Input id="r-username" {...register("username")} invalid={!!formState.errors.username} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="r-password">Mật khẩu</Label>
            <Input
              id="r-password"
              type="password"
              {...register("password")}
              invalid={!!formState.errors.password}
            />
          </div>
        </form>
        <DialogFooter>
          <Button type="submit" form="rotate-form" loading={rotate.isPending}>
            Cập nhật
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
