import { Helmet } from "react-helmet-async";
import { Banknote, Sparkles, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  CardFooter,
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState } from "@/components/ui/empty-state";
import { CopyButton } from "@/components/ui/copy-button";
import { OrderStatusPill, TxStatePill } from "@/components/ui/status-pill";
import { Separator } from "@/components/ui/separator";

function Section({
  id,
  title,
  description,
  children,
}: {
  id: string;
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="scroll-mt-20 space-y-4">
      <header className="space-y-1">
        <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
        {description ? <p className="text-sm text-muted-foreground">{description}</p> : null}
      </header>
      <div className="rounded-xl border bg-card p-6">{children}</div>
    </section>
  );
}

function Swatch({ name, varName }: { name: string; varName: string }) {
  return (
    <div className="flex flex-col gap-2">
      <div
        className="h-14 w-full rounded-lg border"
        style={{ backgroundColor: `hsl(var(${varName}))` }}
        aria-hidden
      />
      <div className="text-xs">
        <div className="font-medium">{name}</div>
        <code className="text-muted-foreground">{varName}</code>
      </div>
    </div>
  );
}

export function StyleGuidePage() {
  return (
    <>
      <Helmet>
        <title>Style Guide · APIBank</title>
        <meta name="robots" content="noindex" />
      </Helmet>
      <div className="container space-y-12 py-10">
        <header className="space-y-2">
          <Badge variant="primary">Phase 0 · Design system</Badge>
          <h1 className="text-3xl font-semibold tracking-tight text-balance">
            APIBank Style Guide
          </h1>
          <p className="max-w-2xl text-muted-foreground">
            Bộ token và component nền tảng dùng xuyên suốt sản phẩm. Mọi page tiếp theo phải dùng
            các primitive ở đây để giữ tính nhất quán; nếu cần biến thể mới, bổ sung tại{" "}
            <code className="rounded bg-muted px-1.5 py-0.5">src/components/ui</code> rồi cập nhật
            trang này.
          </p>
        </header>

        <Section id="colors" title="Màu" description="HSL token, đổi theo chế độ light/dark.">
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <Swatch name="Background" varName="--background" />
            <Swatch name="Foreground" varName="--foreground" />
            <Swatch name="Primary" varName="--primary" />
            <Swatch name="Accent" varName="--accent" />
            <Swatch name="Muted" varName="--muted" />
            <Swatch name="Border" varName="--border" />
            <Swatch name="Success" varName="--success" />
            <Swatch name="Warning" varName="--warning" />
            <Swatch name="Destructive" varName="--destructive" />
          </div>
        </Section>

        <Section id="typography" title="Typography" description="Inter cho UI, JetBrains Mono cho code.">
          <div className="space-y-4">
            <div>
              <p className="text-xs uppercase tracking-wider text-muted-foreground">Display</p>
              <p className="text-4xl font-semibold tracking-tight">Nhận biến động số dư realtime</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wider text-muted-foreground">Heading 2</p>
              <p className="text-2xl font-semibold tracking-tight">Tích hợp trong 5 phút</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wider text-muted-foreground">Body</p>
              <p className="text-base text-muted-foreground">
                APIBank xác thực giao dịch tự động, gửi webhook đến shop của bạn ngay khi tiền về.
              </p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wider text-muted-foreground">Mono</p>
              <code className="block rounded-md bg-muted p-3 font-mono text-sm">
                {"POST /api/v1/orders\\nIdempotency-Key: ord_xxx"}
              </code>
            </div>
          </div>
        </Section>

        <Section id="buttons" title="Button">
          <div className="flex flex-wrap gap-3">
            <Button>
              <Sparkles aria-hidden /> Bắt đầu
            </Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="outline">Outline</Button>
            <Button variant="ghost">Ghost</Button>
            <Button variant="destructive">Xóa</Button>
            <Button variant="link">Link</Button>
            <Button loading>Loading</Button>
            <Button size="sm">Small</Button>
            <Button size="lg">Large</Button>
            <Button size="icon" aria-label="Icon only">
              <Banknote aria-hidden />
            </Button>
          </div>
        </Section>

        <Section id="forms" title="Form controls">
          <div className="grid gap-6 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" placeholder="ban@vidu.com" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="apikey">API key</Label>
              <Input id="apikey" placeholder="sk_live_..." invalid />
              <p className="text-xs text-destructive">Khóa không hợp lệ.</p>
            </div>
            <div className="flex items-center gap-3">
              <Switch id="auto-renew" defaultChecked />
              <Label htmlFor="auto-renew">Tự gia hạn</Label>
            </div>
            <div className="flex items-center gap-3">
              <CopyButton value="sk_live_demo_1234" label="Sao chép key" />
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button variant="outline">Tooltip</Button>
                </TooltipTrigger>
                <TooltipContent>Hiện chỉ một lần — hãy lưu lại.</TooltipContent>
              </Tooltip>
            </div>
          </div>
        </Section>

        <Section id="feedback" title="Feedback">
          <div className="grid gap-4 md:grid-cols-2">
            <Alert variant="info">
              <AlertTitle>Bạn có biết?</AlertTitle>
              <AlertDescription>Mỗi gói cước đều miễn phí giải captcha.</AlertDescription>
            </Alert>
            <Alert variant="success">
              <AlertTitle>Thành công</AlertTitle>
              <AlertDescription>Đã tạo API key mới.</AlertDescription>
            </Alert>
            <Alert variant="warning">
              <AlertTitle>Sắp hết hạn</AlertTitle>
              <AlertDescription>Gói của bạn còn 3 ngày — gia hạn để tránh gián đoạn.</AlertDescription>
            </Alert>
            <Alert variant="destructive">
              <AlertTitle>Có lỗi</AlertTitle>
              <AlertDescription>Không kết nối được Redis. Vui lòng thử lại.</AlertDescription>
            </Alert>
          </div>
          <Separator className="my-6" />
          <div className="grid gap-4 md:grid-cols-2">
            <Skeleton className="h-24 w-full" />
            <EmptyState
              title="Chưa có giao dịch"
              description="Khi có giao dịch về tài khoản, bạn sẽ thấy ngay tại đây."
              action={<Button>Thêm tài khoản ngân hàng</Button>}
            />
          </div>
        </Section>

        <Section id="badges" title="Badge & Status pill">
          <div className="flex flex-wrap gap-2">
            <Badge>default</Badge>
            <Badge variant="primary">primary</Badge>
            <Badge variant="success">success</Badge>
            <Badge variant="warning">warning</Badge>
            <Badge variant="destructive">destructive</Badge>
            <Badge variant="muted">muted</Badge>
            <Badge variant="outline">outline</Badge>
          </div>
          <Separator className="my-6" />
          <div className="flex flex-wrap gap-2">
            <OrderStatusPill status="pending" />
            <OrderStatusPill status="paid" />
            <OrderStatusPill status="expired" />
            <OrderStatusPill status="canceled" />
            <OrderStatusPill status="review" />
            <TxStatePill state="new" />
            <TxStatePill state="matched" />
            <TxStatePill state="ignored" />
          </div>
        </Section>

        <Section id="card-tabs" title="Card · Tabs · Dialog">
          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Số dư khả dụng</CardTitle>
                <CardDescription>Cập nhật theo thời gian thực</CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-3xl font-semibold tabular-nums">325.000 ₫</p>
              </CardContent>
              <CardFooter>
                <Button size="sm">Nạp tiền</Button>
                <Button size="sm" variant="outline">
                  Xem lịch sử
                </Button>
              </CardFooter>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Tích hợp nhanh</CardTitle>
                <CardDescription>Chọn ngôn ngữ phù hợp.</CardDescription>
              </CardHeader>
              <CardContent>
                <Tabs defaultValue="curl">
                  <TabsList>
                    <TabsTrigger value="curl">cURL</TabsTrigger>
                    <TabsTrigger value="node">Node</TabsTrigger>
                    <TabsTrigger value="python">Python</TabsTrigger>
                  </TabsList>
                  <TabsContent value="curl">
                    <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">
                      {`curl -X POST https://api.example.com/v1/orders \\\n  -H "Authorization: Bearer $TOKEN" \\\n  -d '{"amount_vnd": 50000}'`}
                    </pre>
                  </TabsContent>
                  <TabsContent value="node">
                    <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">
                      {`await fetch("/v1/orders", { method: "POST", body: JSON.stringify({ amount_vnd: 50000 }) });`}
                    </pre>
                  </TabsContent>
                  <TabsContent value="python">
                    <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">
                      {`httpx.post("/v1/orders", json={"amount_vnd": 50000})`}
                    </pre>
                  </TabsContent>
                </Tabs>
              </CardContent>
            </Card>
          </div>
          <Separator className="my-6" />
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="outline">
                <ShieldCheck aria-hidden /> Mở dialog mẫu
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Xác nhận thao tác</DialogTitle>
                <DialogDescription>
                  Hành động này không thể hoàn tác. Bạn có chắc chắn muốn tiếp tục?
                </DialogDescription>
              </DialogHeader>
              <div className="flex justify-end gap-2">
                <Button variant="outline">Hủy</Button>
                <Button variant="destructive">Tiếp tục</Button>
              </div>
            </DialogContent>
          </Dialog>
        </Section>

        <Section id="table" title="Table">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Mã đơn</TableHead>
                <TableHead>Số tiền</TableHead>
                <TableHead>Trạng thái</TableHead>
                <TableHead>Tạo lúc</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow>
                <TableCell className="font-mono">DH7QW2NX</TableCell>
                <TableCell>50.000 ₫</TableCell>
                <TableCell>
                  <OrderStatusPill status="paid" />
                </TableCell>
                <TableCell className="text-muted-foreground">2 phút trước</TableCell>
              </TableRow>
              <TableRow>
                <TableCell className="font-mono">DH9ABC12</TableCell>
                <TableCell>120.000 ₫</TableCell>
                <TableCell>
                  <OrderStatusPill status="pending" />
                </TableCell>
                <TableCell className="text-muted-foreground">5 phút trước</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </Section>
      </div>
    </>
  );
}
