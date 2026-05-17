#!/usr/bin/env bash
# =============================================================================
# APIBank — one-liner install cho VPS Ubuntu/Debian
# =============================================================================
#
# Cách dùng (chạy bằng user thường có sudo):
#   curl -fsSL https://raw.githubusercontent.com/datngo68/apibank/main/scripts/install.sh | bash
#
# Hoặc clone trước rồi chạy:
#   git clone https://github.com/datngo68/apibank.git /opt/apibank
#   cd /opt/apibank && bash scripts/install.sh
#
# Việc:
#   1. Cài docker + docker compose plugin (nếu chưa có).
#   2. Clone repo vào /opt/apibank (nếu chạy qua curl).
#   3. Gọi infra/docker/bootstrap.sh để sinh secret + migrate + seed.
#   4. Khởi động stack.
#
# Idempotent: chạy lại không phá secret/cấu hình cũ.

set -euo pipefail

REPO_URL="${APIBANK_REPO_URL:-https://github.com/datngo68/apibank.git}"
INSTALL_DIR="${APIBANK_INSTALL_DIR:-/opt/apibank}"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
green() { printf '\033[32m%s\033[0m\n' "$1"; }
red() { printf '\033[31m%s\033[0m\n' "$1"; }
yellow() { printf '\033[33m%s\033[0m\n' "$1"; }

# -----------------------------------------------------------------------------
# Step 1: docker + compose plugin
# -----------------------------------------------------------------------------
ensure_docker() {
    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        green "→ Docker + compose plugin đã có"
        return
    fi
    bold "→ Cài Docker từ get.docker.com..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER" || true
    yellow "  Lưu ý: bạn cần logout/login lại để dùng docker không cần sudo."
}

# -----------------------------------------------------------------------------
# Step 2: clone hoặc cập nhật repo
# -----------------------------------------------------------------------------
ensure_repo() {
    if [[ -d "$INSTALL_DIR/.git" ]]; then
        bold "→ Repo đã có ở $INSTALL_DIR, pull bản mới..."
        sudo git -C "$INSTALL_DIR" pull --ff-only
    else
        bold "→ Clone repo về $INSTALL_DIR..."
        sudo mkdir -p "$(dirname "$INSTALL_DIR")"
        sudo git clone "$REPO_URL" "$INSTALL_DIR"
    fi
    sudo chown -R "$USER:$USER" "$INSTALL_DIR"
}

# -----------------------------------------------------------------------------
# Step 3: bootstrap (sinh secret + migrate + seed + tạo admin)
# -----------------------------------------------------------------------------
run_bootstrap() {
    bold "→ Chạy bootstrap..."
    bash "$INSTALL_DIR/infra/docker/bootstrap.sh"
}

# -----------------------------------------------------------------------------
# Step 4: start stack
# -----------------------------------------------------------------------------
start_stack() {
    bold "→ Khởi động stack..."
    docker compose -f "$INSTALL_DIR/infra/docker/docker-compose.yml" up -d
    green ""
    green "Stack đang chạy. Kiểm tra:"
    green "  docker compose -f $INSTALL_DIR/infra/docker/docker-compose.yml ps"
    green "  docker compose -f $INSTALL_DIR/infra/docker/docker-compose.yml logs -f api"
}

main() {
    if [[ $EUID -eq 0 ]]; then
        red "Đừng chạy install.sh dưới root. Dùng user thường có sudo."
        exit 1
    fi
    ensure_docker
    ensure_repo
    run_bootstrap
    start_stack
}

main "$@"
