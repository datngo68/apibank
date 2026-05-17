/**
 * NotificationsPage — trang xem toàn bộ thông báo của user.
 *
 * Filter: tất cả / chưa đọc.
 * Pagination: tăng `limit` (API hiện chỉ hỗ trợ limit, chưa có cursor).
 */

import { useMemo, useState } from "react";
import { Helmet } from "react-helmet-async";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CheckCheck } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState } from "@/components/ui/empty-state";
import { endpoints, toApiError, type NotificationItem } from "@/lib/api";
import { cn, relativeTime, formatDateTime } from "@/lib/utils";

const KIND_LABELS: Record<string, string> = {
  topup_credited: "Nạp ví",
  subscription_purchased: "Mua gói",
  subscription_expiring: "Sắp hết hạn",
  subscription_expired: "Hết hạn",
  webhook_failing: "Webhook lỗi",
  bank_login_failed: "Login bank lỗi",
};

const PAGE_SIZE = 20;

export function NotificationsPage() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<"all" | "unread">("all");
  const [limit, setLimit] = useState(PAGE_SIZE);

  const list = useQuery({
    queryKey: ["notifications", "page", filter, limit],
    queryFn: async () =>
      (
        await endpoints.notifications({
          limit,
          unread_only: filter === "unread" ? true : undefined,
        })
      ).data,
  });

  const markRead = useMutation({
    mutationFn: (id: string) => endpoints.markNotificationRead(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  const markAll = useMutation({
    mutationFn: () => endpoints.markAllNotificationsRead(),
    onSuccess: () => {
      toast.success("Đã đánh dấu tất cả là đã đọc");
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  const items = useMemo<NotificationItem[]>(() => list.data ?? [], [list.data]);
  const reachedEnd = items.length < limit;
  const hasUnread = items.some((it) => !it.read_at);

  return (
    <div className="space-y-6">
      <Helmet>
        <title>Thông báo · APIBank</title>
      </Helmet>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Thông báo</h1>
          <p className="text-sm text-muted-foreground">
            Sự kiện hệ thống, kết quả nạp ví, gói cước và webhook.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Tabs value={filter} onValueChange={(v) => setFilter(v as "all" | "unread")}>
            <TabsList>
              <TabsTrigger value="all">Tất cả</TabsTrigger>
              <TabsTrigger value="unread">Chưa đọc</TabsTrigger>
            </TabsList>
          </Tabs>
          <Button
            variant="ghost"
            size="sm"
            disabled={!hasUnread || markAll.isPending}
            loading={markAll.isPending}
            onClick={() => markAll.mutate()}
          >
            <CheckCheck aria-hidden /> Đánh dấu tất cả
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Lịch sử thông báo</CardTitle>
          <CardDescription>
            Click vào mục chưa đọc để đánh dấu đã đọc. Bật/tắt kênh nhận thông báo trong{" "}
            <span className="text-foreground">Cài đặt → Tuỳ chọn thông báo</span>.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {list.isLoading ? (
            <div className="space-y-2 p-4">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : items.length === 0 ? (
            <EmptyState
              title={filter === "unread" ? "Không có thông báo chưa đọc" : "Chưa có thông báo nào"}
              description="Khi có sự kiện liên quan tới tài khoản, hệ thống sẽ ghi vào đây."
            />
          ) : (
            <ul className="divide-y">
              {items.map((it) => (
                <li
                  key={it.id}
                  className={cn(
                    "flex cursor-pointer items-start gap-3 px-4 py-3 transition-colors hover:bg-muted/30",
                    !it.read_at && "bg-primary/5",
                  )}
                  onClick={() => {
                    if (!it.read_at) markRead.mutate(it.id);
                  }}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if ((e.key === "Enter" || e.key === " ") && !it.read_at) {
                      e.preventDefault();
                      markRead.mutate(it.id);
                    }
                  }}
                >
                  <div className="mt-1 size-2 shrink-0 rounded-full bg-primary"
                    style={{ visibility: it.read_at ? "hidden" : "visible" }}
                    aria-hidden
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">{it.title}</span>
                      <Badge variant="muted" className="text-[10px]">
                        {KIND_LABELS[it.kind] ?? it.kind}
                      </Badge>
                    </div>
                    {it.body ? (
                      <p className="mt-0.5 text-sm text-muted-foreground">{it.body}</p>
                    ) : null}
                    <p
                      className="mt-1 text-xs text-muted-foreground"
                      title={formatDateTime(it.created_at)}
                    >
                      {relativeTime(it.created_at)}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {!list.isLoading && items.length > 0 && !reachedEnd ? (
        <div className="flex justify-center">
          <Button
            variant="outline"
            onClick={() => setLimit((l) => l + PAGE_SIZE)}
            loading={list.isFetching}
          >
            Xem thêm
          </Button>
        </div>
      ) : null}
    </div>
  );
}
