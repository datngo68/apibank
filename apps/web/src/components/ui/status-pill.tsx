import * as React from "react";
import { CheckCircle2, AlertTriangle, AlertCircle, Clock, Pause, Ban } from "lucide-react";
import { Badge } from "@/components/ui/badge";

export type OrderStatus = "pending" | "paid" | "expired" | "canceled" | "review";
export type TxState = "new" | "matched" | "ignored" | "review";

const orderConfig: Record<OrderStatus, { label: string; variant: "muted" | "warning" | "success" | "destructive" | "primary"; icon: React.ComponentType<{ className?: string }> }> = {
  pending: { label: "Đang chờ", variant: "warning", icon: Clock },
  paid: { label: "Đã thanh toán", variant: "success", icon: CheckCircle2 },
  expired: { label: "Hết hạn", variant: "muted", icon: Pause },
  canceled: { label: "Đã hủy", variant: "muted", icon: Ban },
  review: { label: "Cần kiểm tra", variant: "destructive", icon: AlertTriangle },
};

const txConfig: Record<TxState, { label: string; variant: "muted" | "warning" | "success" | "destructive" | "primary" }> = {
  new: { label: "Mới", variant: "primary" },
  matched: { label: "Khớp đơn", variant: "success" },
  ignored: { label: "Bỏ qua", variant: "muted" },
  review: { label: "Cần kiểm tra", variant: "destructive" },
};

export function OrderStatusPill({ status }: { status: OrderStatus | string }) {
  const cfg = (orderConfig as Record<string, typeof orderConfig.pending>)[status] ?? {
    label: status,
    variant: "muted" as const,
    icon: AlertCircle,
  };
  const Icon = cfg.icon;
  return (
    <Badge variant={cfg.variant}>
      <Icon className="size-3" aria-hidden /> {cfg.label}
    </Badge>
  );
}

export function TxStatePill({ state }: { state: TxState | string }) {
  const cfg = (txConfig as Record<string, typeof txConfig.new>)[state] ?? {
    label: state,
    variant: "muted" as const,
  };
  return <Badge variant={cfg.variant}>{cfg.label}</Badge>;
}
