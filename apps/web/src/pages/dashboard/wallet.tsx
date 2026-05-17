import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { motion } from "framer-motion";
import { Plus, QrCode, X } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { CopyButton } from "@/components/ui/copy-button";
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
import {
  endpoints,
  toApiError,
  type TopupListItem,
  type TopupResponse,
} from "@/lib/api";
import { formatVnd, formatDateTime } from "@/lib/utils";
import { AUTH_QUERY_KEY } from "@/lib/auth";

const PRESETS = [50_000, 100_000, 200_000, 500_000];
const PENDING_TOPUPS_KEY = ["pending-topups"] as const;

/** Subset chung dùng để render QR view (cùng TopupResponse và TopupListItem). */
type TopupView = Pick<
  TopupListItem,
  | "code"
  | "amount_vnd"
  | "qr_url"
  | "bank_code"
  | "bank_name"
  | "account_no"
  | "account_holder"
  | "transfer_content"
>;

export function WalletPage() {
  const wallet = useQuery({
    queryKey: ["wallet"],
    queryFn: async () => (await endpoints.wallet()).data,
    refetchInterval: 15_000,
  });
  const txs = useQuery({
    queryKey: ["wallet-tx"],
    queryFn: async () => (await endpoints.walletTransactions()).data,
  });
  const pending = useQuery({
    queryKey: PENDING_TOPUPS_KEY,
    queryFn: async () => (await endpoints.pendingTopups()).data,
    refetchInterval: 30_000,
  });

  const pendingCount = pending.data?.length ?? wallet.data?.pending_topups ?? 0;

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="md:col-span-2">
          <CardHeader>
            <CardDescription className="uppercase tracking-wider">
              Số dư khả dụng
            </CardDescription>
            <CardTitle className="text-4xl tabular-nums">
              {wallet.isLoading ? <Skeleton className="h-10 w-48" /> : formatVnd(wallet.data?.balance_vnd ?? 0)}
            </CardTitle>
          </CardHeader>
          <CardContent className="flex items-center gap-3">
            <TopupDialog />
            <span className="text-sm text-muted-foreground">
              {pendingCount} đơn nạp đang chờ
            </span>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Lịch sử nạp / chi</CardTitle>
            <CardDescription>Xem chi tiết bên dưới.</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Sổ kế toán dùng cộng/trừ ký, đảm bảo tổng giao dịch khớp số dư hiện tại.
            </p>
          </CardContent>
        </Card>
      </div>

      <PendingTopupsCard
        items={pending.data ?? []}
        loading={pending.isLoading}
      />

      <Card>
        <CardHeader>
          <CardTitle>Lịch sử ví</CardTitle>
          <CardDescription>Mỗi dòng là một bút toán có dấu.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Loại</TableHead>
                <TableHead>Số tiền</TableHead>
                <TableHead>Số dư sau</TableHead>
                <TableHead>Ghi chú</TableHead>
                <TableHead>Thời gian</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {txs.isLoading ? (
                <TableRow>
                  <TableCell colSpan={5}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              ) : (txs.data?.length ?? 0) === 0 ? (
                <TableEmpty colSpan={5}>Chưa có giao dịch ví.</TableEmpty>
              ) : (
                txs.data?.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell>
                      <Badge variant={t.type === "topup" || t.type === "refund" ? "success" : "muted"}>
                        {t.type}
                      </Badge>
                    </TableCell>
                    <TableCell
                      className={
                        Number(t.amount_vnd) >= 0
                          ? "font-mono text-success"
                          : "font-mono text-destructive"
                      }
                    >
                      {Number(t.amount_vnd) >= 0 ? "+" : ""}
                      {formatVnd(t.amount_vnd)}
                    </TableCell>
                    <TableCell className="font-mono">{formatVnd(t.balance_after)}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">{t.note ?? "—"}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDateTime(t.created_at)}
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

function PendingTopupsCard({
  items,
  loading,
}: {
  items: TopupListItem[];
  loading: boolean;
}) {
  const qc = useQueryClient();
  const [viewing, setViewing] = useState<TopupListItem | null>(null);

  const cancel = useMutation({
    mutationFn: async (orderId: string) =>
      (await endpoints.cancelTopup(orderId)).data,
    onSuccess: () => {
      toast.success("Đã huỷ đơn nạp");
      qc.invalidateQueries({ queryKey: PENDING_TOPUPS_KEY });
      qc.invalidateQueries({ queryKey: ["wallet"] });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  if (!loading && items.length === 0) return null;

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Đơn nạp đang chờ</CardTitle>
          <CardDescription>
            Bạn có thể mở lại mã QR để chuyển khoản, hoặc huỷ nếu không nạp nữa.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Mã đơn</TableHead>
                <TableHead>Số tiền</TableHead>
                <TableHead>Ngân hàng</TableHead>
                <TableHead>Tạo lúc</TableHead>
                <TableHead>Hết hạn</TableHead>
                <TableHead className="text-right">Thao tác</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={6}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              ) : (
                items.map((t) => (
                  <TableRow key={t.order_id}>
                    <TableCell className="font-mono text-xs">{t.code}</TableCell>
                    <TableCell className="font-mono">{formatVnd(t.amount_vnd)}</TableCell>
                    <TableCell className="text-xs">
                      {t.bank_name} ({t.bank_code})
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDateTime(t.created_at)}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDateTime(t.expired_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setViewing(t)}
                        >
                          <QrCode aria-hidden /> Xem QR
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          loading={
                            cancel.isPending && cancel.variables === t.order_id
                          }
                          onClick={() => cancel.mutate(t.order_id)}
                        >
                          <X aria-hidden /> Huỷ
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog
        open={viewing !== null}
        onOpenChange={(v) => {
          if (!v) setViewing(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Mã QR nạp tiền</DialogTitle>
            <DialogDescription>
              Quét QR hoặc chuyển khoản theo nội dung dưới đây.
            </DialogDescription>
          </DialogHeader>
          {viewing ? (
            <TopupQrView topup={viewing} />
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  );
}

function TopupDialog() {
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState<number>(100_000);
  const [topup, setTopup] = useState<TopupResponse | null>(null);
  const qc = useQueryClient();

  const create = useMutation({
    mutationFn: async (n: number) => (await endpoints.topup(n)).data,
    onSuccess: (data) => {
      setTopup(data);
      qc.invalidateQueries({ queryKey: PENDING_TOPUPS_KEY });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  const stream = useTopupStream(topup?.code ?? null);

  useEffect(() => {
    if (stream.status === "paid") {
      toast.success("Nạp tiền thành công!");
      qc.invalidateQueries({ queryKey: ["wallet"] });
      qc.invalidateQueries({ queryKey: ["wallet-tx"] });
      qc.invalidateQueries({ queryKey: PENDING_TOPUPS_KEY });
      qc.invalidateQueries({ queryKey: AUTH_QUERY_KEY });
    }
  }, [stream.status, qc]);

  const isPaid = stream.status === "paid";
  const isExpired = stream.status === "expired";

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        if (!v) setTopup(null);
      }}
    >
      <DialogTrigger asChild>
        <Button>
          <Plus aria-hidden /> Nạp tiền
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Nạp tiền vào ví</DialogTitle>
          <DialogDescription>
            Nạp vào tài khoản ngân hàng hệ thống, số dư cập nhật trong vòng 5 giây sau khi tiền về.
          </DialogDescription>
        </DialogHeader>
        {topup ? (
          isPaid ? (
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              className="rounded-xl border bg-success/10 p-6 text-center"
            >
              <p className="text-2xl">🎉</p>
              <p className="mt-2 font-semibold">Nạp tiền thành công</p>
              <p className="text-sm text-muted-foreground">
                {formatVnd(topup.amount_vnd)} đã được cộng vào ví.
              </p>
              <Button className="mt-4" onClick={() => setOpen(false)}>
                Đóng
              </Button>
            </motion.div>
          ) : isExpired ? (
            <div className="space-y-2 rounded-xl border bg-muted/20 p-6 text-center">
              <p className="font-semibold">Đơn nạp đã hết hạn</p>
              <p className="text-sm text-muted-foreground">
                Vui lòng tạo đơn mới nếu bạn muốn tiếp tục.
              </p>
              <Button className="mt-2" onClick={() => setTopup(null)}>
                Tạo đơn mới
              </Button>
            </div>
          ) : (
            <TopupQrView topup={topup} />
          )
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-4 gap-2">
              {PRESETS.map((p) => (
                <Button
                  key={p}
                  variant={amount === p ? "primary" : "outline"}
                  onClick={() => setAmount(p)}
                  size="sm"
                >
                  {formatVnd(p)}
                </Button>
              ))}
            </div>
            <input
              type="number"
              min={10_000}
              max={50_000_000}
              step={1_000}
              value={amount}
              onChange={(e) => setAmount(Number(e.target.value))}
              className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm tabular-nums"
            />
            <Button
              className="w-full"
              loading={create.isPending}
              onClick={() => create.mutate(amount)}
            >
              Tạo đơn nạp {formatVnd(amount)}
            </Button>
          </div>
        )}
        {!topup ? (
          <DialogFooter>
            <p className="text-xs text-muted-foreground">
              Số tiền tối thiểu 10.000 đ — tối đa 50.000.000 đ.
            </p>
          </DialogFooter>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function TopupQrView({ topup }: { topup: TopupView }) {
  return (
    <div className="grid gap-4 md:grid-cols-[auto_1fr]">
      <div className="flex flex-col items-center gap-2">
        <img
          src={topup.qr_url}
          alt="VietQR nạp tiền"
          className="size-64 rounded-lg border bg-white p-2 md:size-72"
        />
        <Badge variant="warning">Đang chờ thanh toán…</Badge>
        <p className="max-w-[18rem] text-center text-[11px] leading-relaxed text-muted-foreground">
          Hệ thống tự dò giao dịch ~20s/lần. Sau khi chuyển khoản, vui lòng đợi
          tối đa 1–2 phút để ví được cộng tự động.
        </p>
      </div>
      <div className="space-y-3 text-sm">
        <InfoRow label="Ngân hàng" value={`${topup.bank_name} (${topup.bank_code})`} />
        <InfoRow
          label="Số tài khoản"
          value={topup.account_no}
          copy={topup.account_no}
          mono
        />
        <InfoRow label="Chủ TK" value={topup.account_holder} />
        <InfoRow
          label="Số tiền"
          value={formatVnd(topup.amount_vnd)}
          copy={String(topup.amount_vnd)}
          mono
        />
        <InfoRow
          label="Nội dung CK"
          value={topup.transfer_content}
          copy={topup.transfer_content}
          mono
          highlight
        />
        <p className="text-xs text-warning">
          Bắt buộc nhập đúng nội dung trên — hệ thống dựa vào đó để tự gạch nợ vào ví.
        </p>
      </div>
    </div>
  );
}

function InfoRow({
  label,
  value,
  copy,
  mono,
  highlight,
}: {
  label: string;
  value: string;
  copy?: string;
  mono?: boolean;
  highlight?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-md border bg-muted/30 px-3 py-2">
      <div className="space-y-0.5">
        <div className="text-xs uppercase tracking-wider text-muted-foreground">
          {label}
        </div>
        <div
          className={`${mono ? "font-mono" : ""} ${
            highlight ? "text-base font-semibold text-primary" : "text-sm"
          }`}
        >
          {value}
        </div>
      </div>
      {copy ? <CopyButton value={copy} label="" className="shrink-0 px-2" /> : null}
    </div>
  );
}

interface TopupStreamState {
  status: "idle" | "pending" | "paid" | "expired" | "error";
  balance_vnd: number | null;
}

function useTopupStream(code: string | null): TopupStreamState {
  const [state, setState] = useState<TopupStreamState>({
    status: "idle",
    balance_vnd: null,
  });
  const esRef = useRef<EventSource | null>(null);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    if (!code) {
      setState({ status: "idle", balance_vnd: null });
      return;
    }
    setState({ status: "pending", balance_vnd: null });

    const cleanup = () => {
      esRef.current?.close();
      esRef.current = null;
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };

    if (typeof EventSource !== "undefined") {
      const es = new EventSource(`/api/v1/me/topup/${code}/events`, {
        withCredentials: true,
      });
      esRef.current = es;
      es.addEventListener("paid", (ev) => {
        const data = JSON.parse((ev as MessageEvent).data || "{}") as {
          balance_vnd?: number | null;
        };
        setState({ status: "paid", balance_vnd: data.balance_vnd ?? null });
        cleanup();
      });
      es.addEventListener("expired", () => {
        setState((s) => ({ ...s, status: "expired" }));
        cleanup();
      });
      es.onerror = () => {
        // Đóng SSE; fallback polling
        cleanup();
        startPolling();
      };
    } else {
      startPolling();
    }

    function startPolling() {
      const tick = async () => {
        try {
          const data = (await endpoints.topupStatus(code!)).data as {
            status?: string;
          };
          if (data.status === "paid") {
            setState({ status: "paid", balance_vnd: null });
            cleanup();
          } else if (data.status === "expired" || data.status === "canceled") {
            setState((s) => ({ ...s, status: "expired" }));
            cleanup();
          }
        } catch {
          /* ignore */
        }
      };
      void tick();
      pollRef.current = window.setInterval(tick, 5_000);
    }

    return cleanup;
  }, [code]);

  return state;
}
