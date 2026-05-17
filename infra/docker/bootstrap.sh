#!/usr/bin/env bash
# =============================================================================
# APIBank bootstrap — chạy 1 lần trên VPS sau khi clone repo
# =============================================================================
#
# Việc:
#   1. Sinh secrets ngẫu nhiên (Fernet, api_key_salt, session_secret_key)
#      và inject vào .env nếu vẫn còn placeholder CHANGE_ME.
#   2. Build image apibank:latest.
#   3. Chạy migration (service `migrate` của compose).
#   4. Seed plans mặc định + tạo admin user (tương tác).
#
# Idempotent: chạy lại không phá secret đã sinh.
#
# Cách dùng:
#   bash infra/docker/bootstrap.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/infra/docker/docker-compose.yml"
ENV_FILE="$REPO_ROOT/.env"
ENV_TEMPLATE="$REPO_ROOT/infra/docker/.env.production.example"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
green() { printf '\033[32m%s\033[0m\n' "$1"; }
red() { printf '\033[31m%s\033[0m\n' "$1"; }
yellow() { printf '\033[33m%s\033[0m\n' "$1"; }

require() {
    if ! command -v "$1" >/dev/null 2>&1; then
        red "Thiếu binary '$1'. Hãy cài đặt trước khi chạy bootstrap."
        exit 1
    fi
}

require docker
require openssl
require python3

# -----------------------------------------------------------------------------
# Step 1: tạo .env nếu chưa có
# -----------------------------------------------------------------------------
if [[ ! -f "$ENV_FILE" ]]; then
    bold "→ Tạo .env từ template..."
    cp "$ENV_TEMPLATE" "$ENV_FILE"
    green "  Đã copy .env.production.example → .env"
fi

# -----------------------------------------------------------------------------
# Step 2: sinh secrets
# -----------------------------------------------------------------------------
gen_token() {
    python3 -c "import secrets; print(secrets.token_urlsafe(48))"
}

gen_fernet() {
    python3 -c "from cryptography.fernet import Fernet; print(f'primary:{Fernet.generate_key().decode()}')" 2>/dev/null || {
        # cryptography chưa cài — dùng base64 raw 32 bytes (Fernet key format).
        python3 -c "import base64,os; print('primary:' + base64.urlsafe_b64encode(os.urandom(32)).decode())"
    }
}

# Replace giá trị "CHANGE_ME_*" trong .env bằng giá trị mới.
# Chỉ thay nếu placeholder vẫn còn — idempotent.
update_secret() {
    local key="$1"
    local value="$2"
    if grep -E "^${key}=.*CHANGE_ME" "$ENV_FILE" >/dev/null 2>&1; then
        # escape '/' và '&' cho sed
        local escaped
        escaped=$(printf '%s' "$value" | sed 's/[\/&]/\\&/g')
        sed -i.bak "s|^${key}=.*|${key}=${escaped}|" "$ENV_FILE"
        rm -f "${ENV_FILE}.bak"
        green "  Đã sinh ${key}"
    fi
}

bold "→ Sinh secrets..."
update_secret "APIBANK_FERNET_KEYS" "$(gen_fernet)"
update_secret "APIBANK_API_KEY_SALT" "$(gen_token)"
update_secret "APIBANK_SESSION_SECRET_KEY" "$(gen_token)"

# Postgres password: nếu vẫn placeholder thì sinh + đồng bộ DB_URL.
if grep -E "^POSTGRES_PASSWORD=.*CHANGE_ME" "$ENV_FILE" >/dev/null 2>&1; then
    PG_PASS=$(openssl rand -base64 32 | tr -d '\n=+/' | head -c 32)
    update_secret "POSTGRES_PASSWORD" "$PG_PASS"
    # Cập nhật DB_URL theo password mới (đảm bảo khớp).
    sed -i.bak "s|^APIBANK_DB_URL=.*|APIBANK_DB_URL=postgresql+asyncpg://apibank:${PG_PASS}@postgres:5432/apibank|" "$ENV_FILE"
    rm -f "${ENV_FILE}.bak"
    green "  Đã sinh POSTGRES_PASSWORD và đồng bộ APIBANK_DB_URL"
fi

# -----------------------------------------------------------------------------
# Step 3: kiểm tra biến bắt buộc do user phải tự điền
# -----------------------------------------------------------------------------
check_required() {
    local key="$1"
    local hint="$2"
    if grep -E "^${key}=.*CHANGE_ME|^${key}=$" "$ENV_FILE" >/dev/null 2>&1 \
        || ! grep -E "^${key}=" "$ENV_FILE" >/dev/null 2>&1; then
        red "  Thiếu biến: ${key}"
        yellow "    ${hint}"
        return 1
    fi
}

bold "→ Kiểm tra biến do user phải điền..."
MISSING=0
check_required "APIBANK_DOMAIN" "Domain thật, ví dụ apibank.example.com" || MISSING=1
check_required "APIBANK_ACME_EMAIL" "Email cho Let's Encrypt" || MISSING=1
check_required "CLOUDFLARE_API_TOKEN" "Token Cloudflare có quyền Zone:DNS:Edit" || MISSING=1

if [[ $MISSING -eq 1 ]]; then
    yellow ""
    yellow "Hãy mở .env, điền các biến trên, rồi chạy lại bootstrap."
    exit 1
fi

# -----------------------------------------------------------------------------
# Step 4: build + migrate
# -----------------------------------------------------------------------------
bold "→ Build image apibank:latest (có thể mất vài phút lần đầu)..."
docker compose -f "$COMPOSE_FILE" build api caddy

bold "→ Khởi động postgres + redis..."
docker compose -f "$COMPOSE_FILE" up -d postgres redis

bold "→ Chạy migration..."
docker compose -f "$COMPOSE_FILE" run --rm migrate

# -----------------------------------------------------------------------------
# Step 5: seed plan + tạo admin
# -----------------------------------------------------------------------------
bold "→ Seed gói cước mặc định..."
docker compose -f "$COMPOSE_FILE" run --rm \
    --entrypoint apimb api plan seed || yellow "  (đã seed trước đó, bỏ qua)"

bold "→ Tạo admin user..."
read -rp "  Email admin: " ADMIN_EMAIL
read -rsp "  Password admin (≥ 8 ký tự): " ADMIN_PASS
echo
if [[ ${#ADMIN_PASS} -lt 8 ]]; then
    red "Password phải ≥ 8 ký tự"
    exit 1
fi

# `apimb user create` đã có flag --password → non-interactive được.
docker compose -f "$COMPOSE_FILE" run --rm \
    --entrypoint apimb api user create \
    --email "$ADMIN_EMAIL" \
    --password "$ADMIN_PASS" \
    --admin \
    || yellow "  (admin đã tồn tại, bỏ qua — dùng 'apimb user reset-password' nếu cần đổi)"

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------
green ""
green "============================================================"
green "  Bootstrap hoàn tất."
green "============================================================"
green ""
green "Bước tiếp theo:"
green "  docker compose -f $COMPOSE_FILE up -d"
green ""
green "Sau đó truy cập https://\$APIBANK_DOMAIN với email admin vừa tạo."
green "Trong dashboard: Bank accounts → thêm tài khoản MB → System bank set."
