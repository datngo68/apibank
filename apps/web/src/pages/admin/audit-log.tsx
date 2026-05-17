import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableEmpty,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { adminEndpoints } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";

export function AdminAuditLogPage() {
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const [page, setPage] = useState(0);
  const limit = 50;

  const list = useQuery({
    queryKey: ["admin", "audit", { action, actor, page }],
    queryFn: async () =>
      (
        await adminEndpoints.listAudit({
          action: action || undefined,
          actor: actor || undefined,
          limit,
          offset: page * limit,
        })
      ).data,
  });

  const total = list.data?.total ?? 0;
  const hasNext = (page + 1) * limit < total;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Audit log</h1>
        <p className="text-sm text-muted-foreground">
          Tra cứu mọi thao tác có audit trail. Filter prefix theo `action` (vd `admin.user`).
        </p>
      </div>

      <Card>
        <CardContent className="grid gap-3 pt-6 md:grid-cols-[1fr_1fr_auto]">
          <Input
            placeholder="Action prefix, vd admin.wallet"
            value={action}
            onChange={(e) => setAction(e.target.value)}
          />
          <Input
            placeholder="Actor ID"
            value={actor}
            onChange={(e) => setActor(e.target.value)}
          />
          <Button variant="outline" onClick={() => setPage(0)}>
            Áp dụng
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div>
            <CardTitle>{total} bản ghi</CardTitle>
            <CardDescription>
              Trang {page + 1}/{Math.max(1, Math.ceil(total / limit))}
            </CardDescription>
          </div>
          <Link to="/app/admin" className="text-sm text-primary hover:underline">
            Về dashboard
          </Link>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Thời gian</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Actor</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>IP</TableHead>
                <TableHead>After</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.isLoading ? (
                <TableRow>
                  <TableCell colSpan={6}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              ) : (list.data?.items?.length ?? 0) === 0 ? (
                <TableEmpty colSpan={6}>Không có bản ghi nào.</TableEmpty>
              ) : (
                list.data?.items.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDateTime(a.created_at)}
                    </TableCell>
                    <TableCell>
                      <Badge variant="muted">{a.action}</Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs">{a.actor}</TableCell>
                    <TableCell className="text-xs">
                      {a.target_type}/{a.target_id.slice(0, 16)}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {a.ip ?? "—"}
                    </TableCell>
                    <TableCell className="max-w-[28ch] truncate text-xs text-muted-foreground">
                      {a.after_json ? JSON.stringify(a.after_json) : "—"}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <div className="flex items-center justify-between">
        <Button
          variant="ghost"
          disabled={page === 0}
          onClick={() => setPage((p) => Math.max(0, p - 1))}
        >
          ← Trước
        </Button>
        <Button
          variant="ghost"
          disabled={!hasNext}
          onClick={() => setPage((p) => p + 1)}
        >
          Sau →
        </Button>
      </div>
    </div>
  );
}
