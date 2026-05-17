import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
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
import {
  Table,
  TableBody,
  TableCell,
  TableEmpty,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { adminEndpoints, toApiError } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";

export function AdminBankAccountsPage() {
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ["admin", "bank-accounts"],
    queryFn: async () => (await adminEndpoints.listBankAccounts()).data,
  });
  const sysBank = useQuery({
    queryKey: ["admin", "system-bank"],
    queryFn: async () => (await adminEndpoints.getSystemBank()).data,
  });

  const setSystem = useMutation({
    mutationFn: async (id: string) =>
      (await adminEndpoints.setSystemBank(id)).data,
    onSuccess: () => {
      toast.success("Đã đặt làm system bank");
      qc.invalidateQueries({ queryKey: ["admin", "bank-accounts"] });
      qc.invalidateQueries({ queryKey: ["admin", "system-bank"] });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });
  const unsetSystem = useMutation({
    mutationFn: async () => (await adminEndpoints.unsetSystemBank()).data,
    onSuccess: () => {
      toast.success("Đã bỏ system bank");
      qc.invalidateQueries({ queryKey: ["admin", "bank-accounts"] });
      qc.invalidateQueries({ queryKey: ["admin", "system-bank"] });
    },
    onError: (err) => toast.error(toApiError(err).detail),
  });

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Ngân hàng hệ thống</h1>
        <p className="text-sm text-muted-foreground">
          Bank account dùng để nhận topup ví được đánh dấu "System bank". Chỉ 1 bank được active làm system tại 1 thời điểm.
        </p>
      </div>

      {sysBank.data ? (
        <Alert variant="success">
          <AlertTitle>System bank đang dùng</AlertTitle>
          <AlertDescription className="flex items-center justify-between gap-3">
            <div>
              {sysBank.data.bank_code} · <span className="font-mono">{sysBank.data.account_no}</span> · {sysBank.data.account_holder}
            </div>
            <Button size="sm" variant="ghost" onClick={() => unsetSystem.mutate()}>
              Bỏ system bank
            </Button>
          </AlertDescription>
        </Alert>
      ) : (
        <Alert variant="warning">
          <AlertTitle>Chưa cấu hình system bank</AlertTitle>
          <AlertDescription>
            User không thể nạp tiền vào ví cho tới khi bạn đặt 1 bank account làm system bank.
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>{list.data?.length ?? 0} bank account trong hệ thống</CardTitle>
          <CardDescription>
            Bao gồm bank do user thêm. Admin có thể chọn bất kỳ bank "active" nào làm system bank.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Bank</TableHead>
                <TableHead>Số TK</TableHead>
                <TableHead>Chủ TK</TableHead>
                <TableHead>User</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Polling</TableHead>
                <TableHead>System</TableHead>
                <TableHead>Last poll</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.isLoading ? (
                <TableRow>
                  <TableCell colSpan={9}>
                    <Skeleton className="h-6 w-full" />
                  </TableCell>
                </TableRow>
              ) : (list.data?.length ?? 0) === 0 ? (
                <TableEmpty colSpan={9}>Chưa có bank account.</TableEmpty>
              ) : (
                list.data?.map((b) => (
                  <TableRow key={b.id}>
                    <TableCell className="font-mono text-xs">{b.bank_code}</TableCell>
                    <TableCell className="font-mono">{b.account_no}</TableCell>
                    <TableCell>{b.account_holder}</TableCell>
                    <TableCell className="text-xs">{b.user_email ?? "—"}</TableCell>
                    <TableCell>
                      <Badge variant={b.status === "active" ? "success" : "muted"}>
                        {b.status}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={b.polling_status === "ok" ? "success" : "muted"}>
                        {b.polling_status}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {b.is_system_account ? (
                        <Badge variant="primary">System</Badge>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {b.last_poll_at ? formatDateTime(b.last_poll_at) : "—"}
                    </TableCell>
                    <TableCell className="text-right">
                      {b.is_system_account ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => unsetSystem.mutate()}
                        >
                          Bỏ
                        </Button>
                      ) : b.status === "active" ? (
                        <Button
                          size="sm"
                          onClick={() => setSystem.mutate(b.id)}
                        >
                          Đặt làm system
                        </Button>
                      ) : null}
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
