/**
 * NotificationBell — chuông thông báo trong header dashboard.
 *
 * - Polls `/api/v1/me/notifications/unread-count` mỗi 15s.
 * - Khi unread tăng so với lần fetch trước → toast info báo có thông báo mới.
 * - Khi click, mở dropdown 10 noti gần nhất, mark-read khi user click vào item.
 * - Có nút "Đánh dấu tất cả đã đọc" và link "Xem tất cả" sang trang /app/notifications.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Bell } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { endpoints, type NotificationItem } from "@/lib/api";
import { cn, relativeTime } from "@/lib/utils";

const KIND_LABELS: Record<string, string> = {
  topup_credited: "Nạp ví thành công",
  subscription_purchased: "Đã mua gói",
  subscription_expiring: "Gói sắp hết hạn",
  subscription_expired: "Gói đã hết hạn",
  webhook_failing: "Webhook lỗi",
  bank_login_failed: "Đăng nhập ngân hàng lỗi",
};

export function NotificationBell() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const previousUnread = useRef<number | null>(null);

  const countQuery = useQuery({
    queryKey: ["notifications", "unread-count"],
    queryFn: async () => (await endpoints.notificationsUnreadCount()).data,
    refetchInterval: 15_000,
    staleTime: 5_000,
  });

  const listQuery = useQuery({
    queryKey: ["notifications", "list"],
    queryFn: async () => (await endpoints.notifications({ limit: 10 })).data,
    enabled: open,
  });

  const markRead = useMutation({
    mutationFn: (id: string) => endpoints.markNotificationRead(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });

  const markAll = useMutation({
    mutationFn: () => endpoints.markAllNotificationsRead(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });

  const unread = countQuery.data?.unread ?? 0;
  const items: NotificationItem[] = useMemo(() => listQuery.data ?? [], [listQuery.data]);

  // Refresh list khi dropdown mở.
  useEffect(() => {
    if (open) {
      void listQuery.refetch();
    }
  }, [open, listQuery]);

  // Toast khi unread tăng so với lần check trước. Lần đầu chỉ ghi nhớ giá trị,
  // không toast (tránh nháy khi vừa mở app).
  useEffect(() => {
    if (countQuery.data === undefined) return;
    const current = countQuery.data.unread;
    const prev = previousUnread.current;
    previousUnread.current = current;
    if (prev === null || current <= prev) return;

    const delta = current - prev;
    void (async () => {
      try {
        const latest = (await endpoints.notifications({ limit: 1, unread_only: true })).data;
        const top = latest[0];
        const title =
          delta === 1
            ? top?.title ?? "Bạn có thông báo mới"
            : `${delta} thông báo mới`;
        const description =
          delta === 1
            ? top?.body ?? KIND_LABELS[top?.kind ?? ""] ?? undefined
            : undefined;
        toast.info(title, {
          description,
          action: {
            label: "Xem",
            onClick: () => navigate("/app/notifications"),
          },
        });
      } catch {
        toast.info(`${delta} thông báo mới`, {
          action: {
            label: "Xem",
            onClick: () => navigate("/app/notifications"),
          },
        });
      }
    })();
  }, [countQuery.data, navigate]);

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label={`Thông báo${unread > 0 ? ` (${unread} chưa đọc)` : ""}`}
          className="relative"
        >
          <Bell className="size-4" aria-hidden />
          {unread > 0 ? (
            <span
              className="absolute -right-0.5 -top-0.5 inline-flex min-w-[1rem] items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold text-destructive-foreground"
              aria-hidden
            >
              {unread > 9 ? "9+" : unread}
            </span>
          ) : null}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel className="flex items-center justify-between">
          <span>Thông báo</span>
          {unread > 0 ? (
            <button
              type="button"
              onClick={() => markAll.mutate()}
              className="text-xs text-primary hover:underline disabled:opacity-50"
              disabled={markAll.isPending}
            >
              Đánh dấu đã đọc
            </button>
          ) : null}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {listQuery.isLoading ? (
          <div className="px-3 py-4 text-sm text-muted-foreground">Đang tải…</div>
        ) : items.length === 0 ? (
          <div className="px-3 py-4 text-sm text-muted-foreground">
            Bạn chưa có thông báo nào.
          </div>
        ) : (
          items.map((it) => (
            <DropdownMenuItem
              key={it.id}
              onSelect={(e) => {
                e.preventDefault();
                if (!it.read_at) {
                  markRead.mutate(it.id);
                }
              }}
              className={cn(
                "flex flex-col items-start gap-0.5 whitespace-normal py-2",
                !it.read_at && "bg-primary/5",
              )}
            >
              <div className="flex w-full items-center justify-between gap-2">
                <span className="text-sm font-medium">{it.title}</span>
                <span className="text-[10px] text-muted-foreground">
                  {relativeTime(it.created_at)}
                </span>
              </div>
              <span className="text-xs text-muted-foreground line-clamp-2">
                {it.body ?? KIND_LABELS[it.kind] ?? it.kind}
              </span>
            </DropdownMenuItem>
          ))
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link to="/app/notifications" className="w-full text-center text-xs text-primary">
            Xem tất cả
          </Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
