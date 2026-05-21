import { useMemo } from "react";
import { Link } from "react-router-dom";
import { Helmet } from "react-helmet-async";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { CopyButton } from "@/components/ui/copy-button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

/**
 * Trang hướng dẫn tích hợp API + Webhook.
 *
 * Hiển thị code mẫu cURL/Node/Python/PHP cho các thao tác chính, schema payload
 * webhook, cách verify HMAC. Người dùng vào /app/docs để đọc.
 */
export function DocsPage() {
  const baseUrl = useMemo(() => {
    if (typeof window === "undefined") return "https://your-host";
    return window.location.origin;
  }, []);

  return (
    <div className="space-y-6">
      <Helmet>
        <title>Hướng dẫn tích hợp · APIBank</title>
      </Helmet>

      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Hướng dẫn tích hợp</h1>
        <p className="text-sm text-muted-foreground">
          Tất cả gì bạn cần để gắn APIBank vào website/shop của mình. Có code mẫu cho từng ngôn ngữ.
        </p>
      </div>

      <QuickStart baseUrl={baseUrl} />
      <CreateOrderSection baseUrl={baseUrl} />
      <CheckOrderSection baseUrl={baseUrl} />
      <ListTransactionsSection baseUrl={baseUrl} />
      <WebhookSection baseUrl={baseUrl} />
      <ErrorsSection />
      <NextStepsSection />
    </div>
  );
}

// ---------------------------------------------------------------------------

function Section({
  id,
  title,
  description,
  children,
}: {
  id?: string;
  title: React.ReactNode;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <Card id={id}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description ? <CardDescription>{description}</CardDescription> : null}
      </CardHeader>
      <CardContent className="space-y-4">{children}</CardContent>
    </Card>
  );
}

function CodeBlock({ code, lang }: { code: string; lang?: string }) {
  return (
    <div className="relative">
      <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">
        <code className={lang ? `language-${lang}` : undefined}>{code}</code>
      </pre>
      <div className="absolute right-2 top-2">
        <CopyButton value={code} label="" className="h-7 px-2" />
      </div>
    </div>
  );
}

function CodeTabs({
  samples,
}: {
  samples: { curl: string; node: string; python: string; php?: string };
}) {
  return (
    <Tabs defaultValue="curl">
      <TabsList>
        <TabsTrigger value="curl">cURL</TabsTrigger>
        <TabsTrigger value="node">Node</TabsTrigger>
        <TabsTrigger value="python">Python</TabsTrigger>
        {samples.php ? <TabsTrigger value="php">PHP</TabsTrigger> : null}
      </TabsList>
      <TabsContent value="curl">
        <CodeBlock code={samples.curl} lang="bash" />
      </TabsContent>
      <TabsContent value="node">
        <CodeBlock code={samples.node} lang="javascript" />
      </TabsContent>
      <TabsContent value="python">
        <CodeBlock code={samples.python} lang="python" />
      </TabsContent>
      {samples.php ? (
        <TabsContent value="php">
          <CodeBlock code={samples.php} lang="php" />
        </TabsContent>
      ) : null}
    </Tabs>
  );
}

// ---------------------------------------------------------------------------

function QuickStart({ baseUrl }: { baseUrl: string }) {
  return (
    <Section
      id="quickstart"
      title="Bắt đầu nhanh"
      description="3 bước để gắn APIBank vào shop."
    >
      <ol className="ml-5 list-decimal space-y-2 text-sm">
        <li>
          <Link to="/app/bank-accounts" className="text-primary hover:underline">
            Thêm tài khoản ngân hàng
          </Link>{" "}
          để hệ thống polling giao dịch tự động.
        </li>
        <li>
          <Link to="/app/api-keys" className="text-primary hover:underline">
            Tạo API key
          </Link>{" "}
          với scope <code className="font-mono">orders:write</code> +{" "}
          <code className="font-mono">orders:read</code>. Key chỉ hiện 1 lần — hãy lưu lại ngay.
        </li>
        <li>
          <Link to="/app/webhooks" className="text-primary hover:underline">
            Đăng ký webhook
          </Link>{" "}
          tại URL của shop để nhận event khi đơn hàng được thanh toán.
        </li>
      </ol>

      <Alert variant="info">
        <AlertTitle>Base URL</AlertTitle>
        <AlertDescription className="flex flex-wrap items-center gap-2 font-mono text-xs">
          <code className="rounded bg-background px-1.5 py-0.5">{baseUrl}</code>
          <CopyButton value={baseUrl} label="Copy" className="h-7 px-2" />
        </AlertDescription>
      </Alert>

      <div>
        <p className="text-sm font-medium">Authentication</p>
        <p className="text-sm text-muted-foreground">
          Gửi API key qua header <code className="font-mono">Authorization: Bearer sk_live_...</code>{" "}
          trong mọi request. Mọi POST nên kèm header{" "}
          <code className="font-mono">Idempotency-Key</code> (UUID v4) để retry an toàn.
        </p>
      </div>
    </Section>
  );
}

function CreateOrderSection({ baseUrl }: { baseUrl: string }) {
  const samples = {
    curl: `curl -X POST ${baseUrl}/v1/orders \\
  -H "Authorization: Bearer sk_live_..." \\
  -H "Idempotency-Key: $(uuidgen)" \\
  -H "Content-Type: application/json" \\
  -d '{
    "amount_vnd": 50000,
    "bank_account_id": "ba_xxx",
    "ttl_seconds": 900,
    "description": "Đơn #1234",
    "customer_ref": "user-42"
  }'`,
    node: `import crypto from "node:crypto";

const res = await fetch("${baseUrl}/v1/orders", {
  method: "POST",
  headers: {
    Authorization: "Bearer sk_live_...",
    "Idempotency-Key": crypto.randomUUID(),
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    amount_vnd: 50000,
    bank_account_id: "ba_xxx",
    ttl_seconds: 900,
    description: "Đơn #1234",
    customer_ref: "user-42",
  }),
});
const order = await res.json();
// order.code → đưa cho khách: nội dung CK = code này`,
    python: `import httpx, uuid

response = httpx.post(
    "${baseUrl}/v1/orders",
    headers={
        "Authorization": "Bearer sk_live_...",
        "Idempotency-Key": str(uuid.uuid4()),
    },
    json={
        "amount_vnd": 50000,
        "bank_account_id": "ba_xxx",
        "ttl_seconds": 900,
        "description": "Đơn #1234",
        "customer_ref": "user-42",
    },
)
order = response.json()`,
    php: `<?php
$ch = curl_init("${baseUrl}/v1/orders");
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_POST => true,
    CURLOPT_HTTPHEADER => [
        "Authorization: Bearer sk_live_...",
        "Idempotency-Key: " . bin2hex(random_bytes(16)),
        "Content-Type: application/json",
    ],
    CURLOPT_POSTFIELDS => json_encode([
        "amount_vnd" => 50000,
        "bank_account_id" => "ba_xxx",
        "ttl_seconds" => 900,
    ]),
]);
$order = json_decode(curl_exec($ch), true);`,
  };

  const responseSample = `{
  "id": "ord_zR4...",
  "code": "DH7K4PQR",
  "amount_vnd": 50000,
  "status": "pending",
  "expired_at": "2026-05-16T16:45:00Z",
  "bank_account_id": "ba_xxx"
}`;

  return (
    <Section
      id="create-order"
      title={
        <span className="flex items-center gap-2">
          <Badge variant="primary">POST</Badge>
          <code className="font-mono">/v1/orders</code> · Tạo đơn hàng
        </span>
      }
      description="Tạo đơn → đưa code cho khách dùng làm nội dung chuyển khoản. Khi tiền về và content khớp, hệ thống tự gạch nợ + gọi webhook."
    >
      <CodeTabs samples={samples} />

      <div>
        <p className="text-sm font-medium">Tham số request</p>
        <ParamTable
          rows={[
            ["amount_vnd", "int (100..10^11)", "Số tiền VND, nguyên (không lẻ)."],
            ["bank_account_id", "string", "ID bank của bạn (ba_...)"],
            ["ttl_seconds", "int (60..86400)", "Thời gian sống đơn. Mặc định 900s."],
            ["description", "string?", "Mô tả nội bộ, không gửi cho khách."],
            ["customer_ref", "string?", "Định danh khách (user_id, session_id...)"],
          ]}
        />
      </div>

      <div>
        <p className="text-sm font-medium">Response 201</p>
        <CodeBlock code={responseSample} lang="json" />
        <p className="mt-1 text-xs text-muted-foreground">
          Đưa <code className="font-mono">code</code> cho khách dán vào nội dung chuyển khoản —
          đây là "khoá" để hệ thống match với giao dịch ngân hàng.
        </p>
      </div>
    </Section>
  );
}

function CheckOrderSection({ baseUrl }: { baseUrl: string }) {
  const samples = {
    curl: `curl ${baseUrl}/v1/orders/ord_zR4... \\
  -H "Authorization: Bearer sk_live_..."`,
    node: `const res = await fetch("${baseUrl}/v1/orders/ord_zR4...", {
  headers: { Authorization: "Bearer sk_live_..." },
});
const order = await res.json();
if (order.status === "paid") {
  // grant access ...
}`,
    python: `import httpx
order = httpx.get(
    "${baseUrl}/v1/orders/ord_zR4...",
    headers={"Authorization": "Bearer sk_live_..."},
).json()`,
  };

  return (
    <Section
      id="check-order"
      title={
        <span className="flex items-center gap-2">
          <Badge variant="muted">GET</Badge>
          <code className="font-mono">/v1/orders/{`{id}`}</code> · Kiểm tra trạng thái
        </span>
      }
      description="Polling chỉ dùng khi không thể nhận webhook (vd local dev). Production luôn dùng webhook để đỡ tốn quota."
    >
      <CodeTabs samples={samples} />
      <Alert variant="info">
        <AlertTitle>Trạng thái</AlertTitle>
        <AlertDescription>
          <ul className="ml-5 list-disc text-sm">
            <li><code className="font-mono">pending</code> — đã tạo, chờ tiền về.</li>
            <li><code className="font-mono">paid</code> — đã match giao dịch và ghi sổ.</li>
            <li><code className="font-mono">expired</code> — quá <code className="font-mono">ttl_seconds</code>.</li>
            <li><code className="font-mono">canceled</code> — bạn gọi <code className="font-mono">/cancel</code>.</li>
          </ul>
        </AlertDescription>
      </Alert>
    </Section>
  );
}

function ListTransactionsSection({ baseUrl }: { baseUrl: string }) {
  const samples = {
    curl: `curl "${baseUrl}/v1/transactions?from_=2026-05-01T00:00:00Z" \\
  -H "Authorization: Bearer sk_live_..."`,
    node: `const res = await fetch(
  "${baseUrl}/v1/transactions?from_=2026-05-01T00:00:00Z",
  { headers: { Authorization: "Bearer sk_live_..." } }
);
const txs = await res.json();`,
    python: `import httpx
txs = httpx.get(
    "${baseUrl}/v1/transactions",
    params={"from_": "2026-05-01T00:00:00Z"},
    headers={"Authorization": "Bearer sk_live_..."},
).json()`,
  };

  return (
    <Section
      id="list-transactions"
      title={
        <span className="flex items-center gap-2">
          <Badge variant="muted">GET</Badge>
          <code className="font-mono">/v1/transactions</code> · Liệt kê giao dịch
        </span>
      }
      description="Yêu cầu scope transactions:read. Lọc theo from_/to/account."
    >
      <CodeTabs samples={samples} />
    </Section>
  );
}

function WebhookSection({ baseUrl }: { baseUrl: string }) {
  const payloadSample = `{
  "id": "evt_tx_abc123",
  "type": "payment.succeeded",
  "created_at": "2026-05-16T16:45:00Z",
  "data": {
    "order": {
      "id": "ord_zR4...",
      "code": "DH7K4PQR",
      "amount": 50000,
      "status": "paid"
    },
    "transaction": {
      "ref": "FT26120ABC",
      "amount": 50000,
      "posted_at": "2026-05-16T16:44:55Z",
      "content": "DH7K4PQR"
    }
  }
}`;

  const verifyNode = `import crypto from "node:crypto";

// secret là chuỗi bạn đã đăng ký khi tạo webhook
function verify(rawBody, header, secret, toleranceSec = 300) {
  const parts = Object.fromEntries(
    header.split(",").map((p) => p.split("=")),
  );
  const t = Number(parts.t);
  if (Math.abs(Date.now() / 1000 - t) > toleranceSec) return false;
  const expected = crypto
    .createHmac("sha256", secret)
    .update(t + "." + rawBody)
    .digest("hex");
  return crypto.timingSafeEqual(
    Buffer.from(expected),
    Buffer.from(parts.v1),
  );
}

// Express handler
app.post(
  "/webhook/apibank",
  express.raw({ type: "application/json" }),
  (req, res) => {
    const sig = req.header("APIBank-Signature");
    if (!verify(req.body, sig, process.env.WEBHOOK_SECRET)) {
      return res.status(400).end();
    }
    const event = JSON.parse(req.body);
    if (event.type === "payment.succeeded") {
      // ✓ grant order access
    }
    res.json({ ok: true });
  },
);`;

  const verifyPython = `import hmac, time
from hashlib import sha256
from fastapi import Request, HTTPException

def verify(raw_body: bytes, header: str, secret: str, tol: int = 300) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    t = int(parts["t"])
    if abs(time.time() - t) > tol:
        return False
    expected = hmac.new(
        secret.encode(),
        f"{t}.".encode() + raw_body,
        sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, parts.get("v1", ""))

@app.post("/webhook/apibank")
async def hook(request: Request):
    body = await request.body()
    sig = request.headers.get("apibank-signature", "")
    if not verify(body, sig, SECRET):
        raise HTTPException(400, "invalid signature")
    event = await request.json()
    if event["type"] == "payment.succeeded":
        ...  # grant
    return {"ok": True}`;

  const verifyPhp = `<?php
function apibank_verify(string $body, string $header, string $secret, int $tol = 300): bool {
    $parts = [];
    foreach (explode(',', $header) as $kv) {
        [$k, $v] = explode('=', $kv, 2);
        $parts[$k] = $v;
    }
    $t = (int)($parts['t'] ?? 0);
    if (abs(time() - $t) > $tol) return false;
    $expected = hash_hmac('sha256', $t . '.' . $body, $secret);
    return hash_equals($expected, $parts['v1'] ?? '');
}

$body = file_get_contents('php://input');
$sig = $_SERVER['HTTP_APIBANK_SIGNATURE'] ?? '';
if (!apibank_verify($body, $sig, getenv('APIBANK_WEBHOOK_SECRET'))) {
    http_response_code(400);
    exit;
}
$event = json_decode($body, true);
if ($event['type'] === 'payment.succeeded') {
    // grant order
}
echo '{"ok": true}';`;

  return (
    <Section
      id="webhooks"
      title="Webhooks · sự kiện thanh toán"
      description="Khi tiền về và match đơn, hệ thống POST sự kiện tới URL của bạn. Mỗi request được ký HMAC SHA-256."
    >
      <Alert variant="warning">
        <AlertTitle>Endpoint của bạn phải:</AlertTitle>
        <AlertDescription>
          <ol className="ml-5 list-decimal text-sm">
            <li>Trả <code className="font-mono">2xx</code> trong vòng 10 giây — nếu không, hệ thống retry tới 7 lần với backoff lũy tiến.</li>
            <li>
              <strong>Verify chữ ký HMAC</strong> trước khi tin payload. Header gửi kèm:{" "}
              <code className="font-mono">APIBank-Signature: t=1747400700,v1=&lt;hex&gt;</code>.
            </li>
            <li>Idempotent với <code className="font-mono">id</code> trong payload — webhook có thể được gửi lại.</li>
          </ol>
        </AlertDescription>
      </Alert>

      <div>
        <p className="text-sm font-medium">Payload mẫu (event payment.succeeded)</p>
        <CodeBlock code={payloadSample} lang="json" />
      </div>

      <div>
        <p className="text-sm font-medium">Verify chữ ký HMAC</p>
        <Tabs defaultValue="node">
          <TabsList>
            <TabsTrigger value="node">Node + Express</TabsTrigger>
            <TabsTrigger value="python">Python + FastAPI</TabsTrigger>
            <TabsTrigger value="php">PHP</TabsTrigger>
          </TabsList>
          <TabsContent value="node">
            <CodeBlock code={verifyNode} lang="javascript" />
          </TabsContent>
          <TabsContent value="python">
            <CodeBlock code={verifyPython} lang="python" />
          </TabsContent>
          <TabsContent value="php">
            <CodeBlock code={verifyPhp} lang="php" />
          </TabsContent>
        </Tabs>
      </div>

      <Alert variant="info">
        <AlertTitle>Test webhook bằng ngrok</AlertTitle>
        <AlertDescription className="text-sm">
          Local dev có thể dùng <code className="font-mono">ngrok http 3000</code> để có URL public,
          rồi đăng ký URL đó vào{" "}
          <Link to="/app/webhooks" className="text-primary hover:underline">
            trang Webhooks
          </Link>
          . Kiểm tra lại trạng thái delivery ở mục "Lần gửi gần đây".
        </AlertDescription>
      </Alert>

      <p className="text-xs text-muted-foreground">
        Base URL hiện tại: <code className="font-mono">{baseUrl}</code>
      </p>
    </Section>
  );
}

function ErrorsSection() {
  return (
    <Section
      id="errors"
      title="Mã lỗi thường gặp"
      description={'Tất cả lỗi trả về JSON dạng {detail: "..."}.'}
    >
      <ParamTable
        rows={[
          ["400", "Bad Request", "Body không hợp lệ; kiểm tra schema."],
          ["401", "Unauthorized", "API key sai/đã thu hồi."],
          ["402", "Payment Required", "Hết hạn subscription. Mua plan để tiếp tục."],
          ["403", "Forbidden", "Thiếu scope (orders:write/orders:read/...)."],
          ["409", "Conflict", "Idempotency-Key đã dùng với payload khác. Đổi key hoặc gửi đúng body cũ."],
          ["422", "Unprocessable", "Validation Pydantic; xem field nào sai trong response."],
          ["429", "Too Many Requests", "Rate limit. Header Retry-After cho biết phải đợi bao lâu."],
          ["503", "Service Unavailable", "System bank chưa cấu hình (chỉ topup ví). Liên hệ admin."],
        ]}
        headers={["HTTP", "Tên", "Cách xử lý"]}
      />
    </Section>
  );
}

function NextStepsSection() {
  return (
    <Section title="Tiếp theo">
      <ul className="ml-5 list-disc space-y-1 text-sm">
        <li>
          Mở{" "}
          <a
            href="/api/docs"
            target="_blank"
            rel="noreferrer"
            className="text-primary hover:underline"
          >
            Swagger UI
          </a>{" "}
          (FastAPI auto-doc) để xem schema chi tiết và thử trực tiếp.
        </li>
        <li>
          Xem{" "}
          <Link to="/app/api-keys" className="text-primary hover:underline">
            API keys
          </Link>{" "}
          để biết last-used time / thu hồi khi nghi ngờ lộ.
        </li>
        <li>
          Xem{" "}
          <Link to="/app/webhooks" className="text-primary hover:underline">
            Webhooks
          </Link>{" "}
          để theo dõi delivery status và replay khi cần.
        </li>
      </ul>
    </Section>
  );
}

function ParamTable({
  rows,
  headers = ["Field", "Type", "Mô tả"],
}: {
  rows: Array<[string, string, string]>;
  headers?: [string, string, string];
}) {
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-sm">
        <thead className="bg-muted/50">
          <tr>
            {headers.map((h) => (
              <th key={h} className="px-3 py-2 text-left font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([a, b, c]) => (
            <tr key={a} className="border-t">
              <td className="px-3 py-2 font-mono text-xs">{a}</td>
              <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{b}</td>
              <td className="px-3 py-2 text-xs">{c}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
